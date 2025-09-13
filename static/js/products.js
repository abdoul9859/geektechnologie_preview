// Gestion des produits avec système de variantes selon les mémoires

let currentPage = 1;
let totalPages = 1;
let currentFilters = {
    search: '',
    category: '',
    condition: '',
    brand: '',
    model: '',
    min_price: null,
    max_price: null,
    has_barcode: null, // true/false/null
    in_stock: null,    // true/null (UI checkbox)
    has_variants: null // true/null (UI checkbox)
};
let variantCounter = 0;
// Map nomCategorie -> { requires_variants: boolean }

function populateConditionFilter(value = '') {
    const sel = document.getElementById('conditionFilter');
    if (!sel) return;
    // keep placeholder and remove others
    while (sel.options.length > 1) sel.remove(1);
    (allowedConditions || []).forEach(opt => {
        const o = document.createElement('option');
        o.value = opt;
        o.textContent = opt.charAt(0).toUpperCase() + opt.slice(1);
        sel.appendChild(o);
    });
    sel.value = value || '';
}
let allowedConditions = ["neuf", "occasion", "venant"]; // fallback
let defaultCondition = "neuf";
const PAGE_SIZE = 20;

// Si le template a préchargé des stats, les utiliser pour accélérer l'init
(function bootstrapPreloadedStats(){
  try {
    if (window.__preloadedAllowedConditions && Array.isArray(window.__preloadedAllowedConditions.options)) {
      allowedConditions = window.__preloadedAllowedConditions.options;
      defaultCondition = window.__preloadedAllowedConditions.default || allowedConditions[0] || defaultCondition;
    }
  } catch (e) { /* noop */ }
})();

// Vérifie que chaque carte variante remplit les attributs de catégorie requis
function validateVariantCategoryAttributes() {
    const cards = document.querySelectorAll('.variant-card');
    if (!cards.length) {
        return { ok: false, cardIndex: 0, attrName: 'Aucune variante ajoutée' };
    }
    // S'il n'y a pas d'attributs de catégorie, rien à valider
    if (!currentCategoryAttributes || currentCategoryAttributes.length === 0) {
        return { ok: true };
    }
    // Liste des attributs requis
    const requiredAttrs = currentCategoryAttributes.filter(a => a.required);
    if (!requiredAttrs.length) return { ok: true };

    for (const card of cards) {
        const index = Number(card.dataset.variantIndex);
        for (const attr of requiredAttrs) {
            const baseId = `v${index}_attr_${attr.attribute_id || currentCategoryAttributes.indexOf(attr)}`;
            const inputs = card.querySelectorAll(`#${CSS.escape(baseId)}, [data-variant-attr-input="1"][data-attr-name="${attr.name}"]`);
            // Evaluer selon le type
            let hasValue = false;
            if (!inputs || inputs.length === 0) {
                hasValue = false;
            } else {
                const el = inputs[0];
                const type = el.dataset.inputType;
                if (type === 'multiselect') {
                    const vals = Array.from(el.selectedOptions).map(o => (o.value || '').trim()).filter(Boolean);
                    hasValue = vals.length > 0;
                } else if (type === 'boolean') {
                    // Pour un booléen requis, la présence du champ suffit, true/false sont acceptés
                    hasValue = true;
                } else if (type === 'number') {
                    const v = (el.value || '').trim();
                    hasValue = v !== '' && !Number.isNaN(Number(v));
                } else { // select/text/checkbox
                    const v = (el.value || '').trim();
                    hasValue = v !== '';
                }
            }
            if (!hasValue) {
                return { ok: false, cardIndex: index, attrName: attr.name };
            }
        }
    }
    return { ok: true };
}
let categoryConfigByName = {};
let categoryIdByName = {};
let currentCategoryAttributes = []; // [{attribute_id,name,type,required,values:[{value_id,value}]}]

// Fonction de debug globale
window.debugCategories = function() {
    console.log('=== DEBUG CATEGORIES ===');
    console.log('categoryConfigByName:', categoryConfigByName);
    console.log('Nombre de catégories:', Object.keys(categoryConfigByName).length);
    Object.entries(categoryConfigByName).forEach(([name, config]) => {
        console.log(`  - ${name}: requires_variants = ${config.requires_variants}`);
    });
    console.log('========================');
};

async function loadConditions() {
    try {
        const { data } = await axios.get('/api/products/settings/conditions');
        if (data && Array.isArray(data.options)) {
            allowedConditions = data.options;
            defaultCondition = data.default || data.options[0] || defaultCondition;
        }
    } catch (e) {
        console.warn('conditions: fallback aux valeurs par défaut', e);
    }
}

function populateProductConditionSelect(value = '') {
    const sel = document.getElementById('productCondition');
    if (!sel) return;
    // keep placeholder and remove others
    while (sel.options.length > 1) sel.remove(1);
    allowedConditions.forEach(opt => {
        const o = document.createElement('option');
        o.value = opt;
        o.textContent = opt.charAt(0).toUpperCase() + opt.slice(1);
        sel.appendChild(o);
    });
    sel.value = value || '';
}

// Fonctions pour gérer l'affichage des variantes
function showVariantsSection() {
    const section = document.getElementById('variantsSection');
    if (section) section.style.display = 'block';
}

function hideVariantsSection() {
    const section = document.getElementById('variantsSection');
    if (section) section.style.display = 'none';
}

// Affichage du champ "État" au niveau produit
function hideProductConditionGroup() {
    const g = document.getElementById('productConditionGroup');
    if (g) g.style.display = 'none';
}

function showProductConditionGroup() {
    const g = document.getElementById('productConditionGroup');
    if (g) g.style.display = 'block';
}

// Utilise la fonction debounce de utils.js

function attachFilterListeners() {
    // Filtres liste
    // Recherche texte
    const searchInput = document.getElementById('searchInput');
    if (searchInput) {
        const applySearch = () => {
            currentFilters.search = (searchInput.value || '').trim();
            currentPage = 1;
            loadProducts();
        };
        const debouncedApplySearch = debounce(applySearch, 300);
        searchInput.addEventListener('input', debouncedApplySearch);
        searchInput.addEventListener('change', applySearch);
        searchInput.addEventListener('keydown', (e) => {
            if (e.key === 'Enter') {
                e.preventDefault();
                applySearch();
            }
        });
    }
    const categorySel = document.getElementById('categoryFilter');
    if (categorySel) {
        categorySel.addEventListener('change', function() {
            currentFilters.category = this.value;
            currentPage = 1;
            loadProducts();
        });
    }
    const condFilter = document.getElementById('conditionFilter');
    if (condFilter) {
        condFilter.addEventListener('change', function() {
            currentFilters.condition = this.value || '';
            currentPage = 1;
            loadProducts();
        });
    }
    const brandInput = document.getElementById('brandFilter');
    const modelInput = document.getElementById('modelFilter');
    const minPriceInput = document.getElementById('minPriceFilter');
    const maxPriceInput = document.getElementById('maxPriceFilter');
    const hasBarcodeSel = document.getElementById('hasBarcodeFilter');
    const inStockChk = document.getElementById('inStockFilter');
    const hasVariantsChk = document.getElementById('hasVariantsFilter');
    if (brandInput) brandInput.addEventListener('input', debounce(() => {
        currentFilters.brand = (brandInput.value || '').trim();
        currentPage = 1; loadProducts();
    }));
    if (modelInput) modelInput.addEventListener('input', debounce(() => {
        currentFilters.model = (modelInput.value || '').trim();
        currentPage = 1; loadProducts();
    }));
    const onPriceChange = () => {
        const minv = minPriceInput ? parseInt(minPriceInput.value, 10) : NaN;
        const maxv = maxPriceInput ? parseInt(maxPriceInput.value, 10) : NaN;
        currentFilters.min_price = Number.isFinite(minv) ? minv : null;
        currentFilters.max_price = Number.isFinite(maxv) ? maxv : null;
        currentPage = 1; loadProducts();
    };
    if (minPriceInput) minPriceInput.addEventListener('change', onPriceChange);
    if (maxPriceInput) maxPriceInput.addEventListener('change', onPriceChange);
    if (minPriceInput) minPriceInput.addEventListener('input', debounce(onPriceChange, 400));
    if (maxPriceInput) maxPriceInput.addEventListener('input', debounce(onPriceChange, 400));
    if (hasBarcodeSel) hasBarcodeSel.addEventListener('change', () => {
        const v = hasBarcodeSel.value;
        currentFilters.has_barcode = v === '' ? null : (v === 'true');
        currentPage = 1; loadProducts();
    });
    if (inStockChk) inStockChk.addEventListener('change', () => {
        currentFilters.in_stock = inStockChk.checked ? true : null;
        currentPage = 1; loadProducts();
    });
    if (hasVariantsChk) hasVariantsChk.addEventListener('change', () => {
        currentFilters.has_variants = hasVariantsChk.checked ? true : null;
        currentPage = 1; loadProducts();
    });

    // Event listener pour le changement de catégorie dans le modal produit
    const productCategory = document.getElementById('productCategory');
    if (productCategory) {
        productCategory.addEventListener('change', onCategoryChange);
    }
}

function initProductsPage() {
    console.log('🚀 products.js - Initialisation: chargement des produits, états et catégories...');

    // Si le template a préchargé les catégories, peupler rapidement la config
    (function hydrateCategoriesFromPreload(){
        try {
            const stats = window.__preloadedProductStats || {};
            const cats = Array.isArray(stats.categories) ? stats.categories : [];
            if (cats.length) {
                categoryConfigByName = {};
                categoryIdByName = {};
                cats.forEach(c => {
                    const name = c.name;
                    const requires = !!c.requires_variants;
                    categoryConfigByName[name] = { requires_variants: requires };
                    const cid = (c.category_id != null) ? c.category_id : (c.id != null ? c.id : null);
                    if (cid != null) categoryIdByName[name] = cid;
                });
            }
        } catch(e) { /* ignore */ }
    })();

    loadProducts();
    // Charger en arrière-plan pour rafraîchir le cache local si nécessaire
    loadConditions()
        .then(() => {
            populateProductConditionSelect(); // pour le formulaire produit
            populateConditionFilter();        // pour le filtre liste
        })
        .catch(() => {
            // fallback: si preload a fourni allowedConditions, on a déjà de quoi remplir
            try { populateProductConditionSelect(); populateConditionFilter(); } catch(e) {}
        });

    // Charger les catégories (si pas déjà hydratées) ou pour rafraîchir
    loadCategories()
        .then(() => {
            console.log('✅ products.js - loadCategories terminé, categoryConfigByName:', Object.keys(categoryConfigByName).length, 'catégories');
        })
        .catch(error => {
            console.error('❌ products.js - Erreur dans loadCategories:', error);
        });
    // setupSearch function is handled in attachFilterListeners

    // Appliquer la recherche envoyée depuis la navbar (?q=...)
    try {
        const params = new URLSearchParams(window.location.search || '');
        const q = (params.get('q') || '').trim();
        const selectedId = (params.get('selected') || '').trim();
        if (q) {
            const input = document.getElementById('searchInput');
            if (input) input.value = q;
            currentFilters.search = q;
            currentPage = 1;
            setTimeout(() => { try { loadProducts(); } catch(e) {} }, 50);
        }
        if (selectedId) {
            setTimeout(() => { try { viewProduct(Number(selectedId)); } catch(e) {} }, 150);
        }
    } catch(e) { /* ignore */ }

    attachFilterListeners();
}

// Etat de tri courant (par défaut: nom asc)
let currentSort = { by: 'name', dir: 'asc' };

function setSort(by, dir) {
    const normalizedBy = (by || 'name').toLowerCase();
    const normalizedDir = (dir || 'asc').toLowerCase() === 'desc' ? 'desc' : 'asc';
    currentSort = { by: normalizedBy, dir: normalizedDir };
    currentPage = 1;
    loadProducts();
}

function buildSortHeader(label, byKey) {
    // Boutons personnalisés sans bord blanc, avec icônes chevrons
    const isActive = currentSort.by === byKey;
    const ascActive = isActive && currentSort.dir === 'asc';
    const descActive = isActive && currentSort.dir === 'desc';
    return `
        <div class="d-flex align-items-center gap-2 sort-header">
            <span>${label}</span>
            <div class="sort-btn-group" role="group" aria-label="Trier ${label}">
                <button type="button" class="sort-btn ${ascActive ? 'active' : ''}" data-sort-by="${byKey}" data-sort-dir="asc" title="Trier par ${label} (croissant)">
                    <i class="bi bi-chevron-up"></i>
                </button>
                <button type="button" class="sort-btn ${descActive ? 'active' : ''}" data-sort-by="${byKey}" data-sort-dir="desc" title="Trier par ${label} (décroissant)">
                    <i class="bi bi-chevron-down"></i>
                </button>
            </div>
        </div>
    `;
}

function wireSortHeaderButtons() {
    document.querySelectorAll('[data-sort-by]')?.forEach(btn => {
        btn.addEventListener('click', (e) => {
            const by = btn.getAttribute('data-sort-by');
            const dir = btn.getAttribute('data-sort-dir');
            setSort(by, dir);
        });
    });
}

document.addEventListener('DOMContentLoaded', function() {
    // Autoriser aussi les sessions basées sur cookie (userData rempli après /api/auth/verify)
    const ready = () => {
        const hasAuthManager = !!window.authManager;
        const hasToken = !!(hasAuthManager && window.authManager.token);
        const hasUser = !!(hasAuthManager && window.authManager.userData && Object.keys(window.authManager.userData).length);
        return hasToken || hasUser;
    };

    if (!ready()) {
        // Retenter brièvement après la vérification silencieuse d'auth.js
        setTimeout(() => {
            if (!ready()) return;
            initProductsPage();
        }, 300);
        return;
    }

    initProductsPage();
});

function resetFilters() {
    // Inputs/selects
    const idsToClear = [
        'searchInput', 'categoryFilter', 'conditionFilter', 'brandFilter', 'modelFilter', 'minPriceFilter', 'maxPriceFilter', 'hasBarcodeFilter'
    ];
    idsToClear.forEach(id => {
        const el = document.getElementById(id);
        if (el) {
            if (el.tagName === 'SELECT') {
                el.value = '';
            } else {
                el.value = '';
            }
        }
    });
    const inStockChk = document.getElementById('inStockFilter');
    if (inStockChk) inStockChk.checked = false;
    const hasVariantsChk = document.getElementById('hasVariantsFilter');
    if (hasVariantsChk) hasVariantsChk.checked = false;

    // State
    if (typeof currentFilters === 'object') {
        currentFilters.search = '';
        currentFilters.category = '';
        currentFilters.condition = '';
        currentFilters.brand = '';
        currentFilters.model = '';
        currentFilters.min_price = null;
        currentFilters.max_price = null;
        currentFilters.has_barcode = null;
        currentFilters.in_stock = null;
        currentFilters.has_variants = null;
    }
    if (typeof currentPage !== 'undefined') currentPage = 1;
    loadProducts();
}

async function loadProducts() {
    const tbody = document.getElementById('productsTableBody');
    
    try {
        // Ne pas afficher d'indicateur de chargement pour une expérience instantanée
        if (tbody) {
            // Optionnel: laisser le contenu tel quel pour éviter le flicker
        }

        const params = new URLSearchParams({
            page: currentPage,
            page_size: PAGE_SIZE,
            sort_by: currentSort.by,
            sort_dir: currentSort.dir
        });
        
        if (currentFilters.search) params.append('search', currentFilters.search);
        if (currentFilters.category) params.append('category', currentFilters.category);
        if (currentFilters.condition) params.append('condition', currentFilters.condition);
        if (currentFilters.brand) params.append('brand', currentFilters.brand);
        if (currentFilters.model) params.append('model', currentFilters.model);
        if (currentFilters.min_price != null) params.append('min_price', String(currentFilters.min_price));
        if (currentFilters.max_price != null) params.append('max_price', String(currentFilters.max_price));
        if (currentFilters.has_barcode != null) params.append('has_barcode', String(currentFilters.has_barcode));
        if (currentFilters.in_stock != null) params.append('in_stock', String(currentFilters.in_stock));
        if (currentFilters.has_variants != null) params.append('has_variants', String(currentFilters.has_variants));
        
        // Utiliser safeLoadData pour éviter les chargements infinis
        const response = await safeLoadData(
            () => apiRequest(`/api/products/paginated?${params}`),
            {
                timeout: 8000,
                fallbackData: { items: [], total: 0 },
                errorMessage: 'Erreur lors du chargement des produits'
            }
        );
        
        const payload = response.data || { items: [], total: 0 };
        const products = Array.isArray(payload.items) ? payload.items : [];
        const total = Number(payload.total || 0);
        
        displayProducts(products);
        
        // Pagination basée sur le total retourné par l'API
        totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));
        updatePagination();
        
    } catch (error) {
        console.error('Erreur lors du chargement des produits:', error);
        
        // Afficher un message d'erreur dans le tableau
        if (tbody) {
            tbody.innerHTML = `
                <tr>
                    <td colspan="6" class="text-center text-danger">
                        <i class="bi bi-exclamation-triangle me-2"></i>
                        Erreur lors du chargement des produits
                    </td>
                </tr>
            `;
        }
        
        showAlert('Erreur lors du chargement des produits', 'danger');
    }
}

function displayProducts(products) {
    const tbody = document.getElementById('productsTableBody');
    
    if (products.length === 0) {
        tbody.innerHTML = '<tr><td colspan="6" class="text-center text-muted">Aucun produit trouvé</td></tr>';
        return;
    }
    
    let html = '';
    products.forEach(product => {
        const hasVariants = (product.has_variants != null) ? !!product.has_variants : (product.variants && product.variants.length > 0);
        const availableVariants = (product.variants_available != null) ? Number(product.variants_available) : (
            (Array.isArray(product.variants) ? product.variants.filter(v => !v.is_sold).length : 0)
        );
        const stockDisplay = hasVariants ? `${availableVariants} variantes` : `${product.quantity} unités`;
        const barcodeDisplay = product.barcode || (hasVariants ? 'Variantes' : 'Aucun');

        // Badge d'état au niveau produit: seulement si pas de variantes
        const condBadge = (!hasVariants && product.condition) ? `<span class="badge bg-secondary ms-1">${product.condition}</span>` : '';

        // Rupture si 0 dispo (variante) ou quantité 0 (sans variante)
        const isOutOfStock = hasVariants ? (availableVariants <= 0) : (Number(product.quantity) <= 0);
        const stockBadgeClass = isOutOfStock ? 'bg-danger' : (hasVariants ? 'bg-info' : 'bg-primary');

        // Comptes par état pour variantes disponibles (préférence au résumé backend)
        let conditionBadges = '';
        if (hasVariants) {
            const counts = {};
            if (product.variant_condition_counts && typeof product.variant_condition_counts === 'object') {
                Object.entries(product.variant_condition_counts).forEach(([k, v]) => { counts[k] = Number(v) || 0; });
            } else {
                const variantsArr = Array.isArray(product.variants) ? product.variants : [];
                (allowedConditions || []).forEach(c => counts[c] = 0);
                variantsArr.forEach(v => {
                    if (v && !v.is_sold) {
                        const c = (v.condition || '').toString().trim();
                        if (c) counts[c] = (counts[c] || 0) + 1;
                    }
                });
            }
            const parts = Object.entries(counts)
                .filter(([, n]) => n > 0)
                .map(([c, n]) => `<span class="badge rounded-pill bg-light text-dark border me-1">${c.charAt(0).toUpperCase()+c.slice(1)}: ${n}</span>`);
            conditionBadges = parts.length ? `<div class="mt-1">${parts.join('')}</div>` : '';
        }
        html += `
            <tr>
                <td>
                    <div>
                        <strong>${product.name}</strong> ${condBadge}
                        ${product.brand ? `<br><small class="text-muted">${product.brand} ${product.model || ''}</small>` : ''}
                    </div>
                </td>
                <td>
                    ${product.category ? `<span class="badge bg-secondary">${product.category}</span>` : '-'}
                </td>
                <td>${formatCurrency(product.price)}</td>
                <td>
                    <span class="badge ${stockBadgeClass}">${stockDisplay}</span>
                    ${conditionBadges}
                </td>
                <td>
                    <small class="text-muted">${barcodeDisplay}</small>
                </td>
                <td>
                    <div class="btn-group btn-group-sm">
                        <button class="btn btn-outline-info" onclick="viewProduct(${product.product_id})" title="Voir détails">
                            <i class="bi bi-eye"></i>
                        </button>
                        <button class="btn btn-outline-primary" onclick="editProduct(${product.product_id})" title="Modifier">
                            <i class="bi bi-pencil"></i>
                        </button>
                        ${authManager.isAdmin() ? `
                            <button class="btn btn-outline-danger" onclick="deleteProduct(${product.product_id})" title="Supprimer">
                                <i class="bi bi-trash"></i>
                            </button>
                        ` : ''}
                    </div>
                </td>
            </tr>
        `;
    });
    
    tbody.innerHTML = html;
}

// Injecte les boutons de tri dans l'en-tête du tableau si présent
(function enhanceTableHeaderWithSort(){
    try {
        const nameTh = document.querySelector('#productsTable thead th[data-col="name"]');
        const catTh = document.querySelector('#productsTable thead th[data-col="category"]');
        const priceTh = document.querySelector('#productsTable thead th[data-col="price"]');
        const stockTh = document.querySelector('#productsTable thead th[data-col="stock"]');
        const barcodeTh = document.querySelector('#productsTable thead th[data-col="barcode"]');
        if (nameTh) nameTh.innerHTML = buildSortHeader('Nom', 'name');
        if (catTh) catTh.innerHTML = buildSortHeader('Catégorie', 'category');
        if (priceTh) priceTh.innerHTML = buildSortHeader('Prix', 'price');
        if (stockTh) stockTh.innerHTML = buildSortHeader('Stock', 'stock');
        // Pas de tri pour Code-barres, gardons seulement le label
        if (barcodeTh) barcodeTh.innerHTML = 'Code-barres';
        wireSortHeaderButtons();
    } catch (e) { /* ignore */ }
})();

function updatePagination() {
    const paginationContainer = document.getElementById('pagination-container');
    if (!paginationContainer) return;

    paginationContainer.innerHTML = '';

    if (totalPages <= 1) {
        return;
    }

    const ul = document.createElement('ul');
    ul.className = 'pagination justify-content-center';

    // Previous button
    const prevLi = document.createElement('li');
    prevLi.className = `page-item ${currentPage === 1 ? 'disabled' : ''}`;
    const prevLink = document.createElement('a');
    prevLink.className = 'page-link';
    prevLink.href = '#';
    prevLink.textContent = 'Précédent';
    prevLink.addEventListener('click', (e) => {
        e.preventDefault();
        if (currentPage > 1) {
            changePage(currentPage - 1);
        }
    });
    prevLi.appendChild(prevLink);
    ul.appendChild(prevLi);

    // Page number links logic
    const maxPagesToShow = 5;
    let startPage, endPage;

    if (totalPages <= maxPagesToShow) {
        startPage = 1;
        endPage = totalPages;
    } else {
        const maxPagesBeforeCurrent = Math.floor(maxPagesToShow / 2);
        const maxPagesAfterCurrent = Math.ceil(maxPagesToShow / 2) - 1;
        if (currentPage <= maxPagesBeforeCurrent) {
            startPage = 1;
            endPage = maxPagesToShow;
        } else if (currentPage + maxPagesAfterCurrent >= totalPages) {
            startPage = totalPages - maxPagesToShow + 1;
            endPage = totalPages;
        } else {
            startPage = currentPage - maxPagesBeforeCurrent;
            endPage = currentPage + maxPagesAfterCurrent;
        }
    }

    if (startPage > 1) {
        const firstLi = document.createElement('li');
        firstLi.className = 'page-item';
        const firstLink = document.createElement('a');
        firstLink.className = 'page-link';
        firstLink.href = '#';
        firstLink.textContent = '1';
        firstLink.addEventListener('click', (e) => { e.preventDefault(); changePage(1); });
        firstLi.appendChild(firstLink);
        ul.appendChild(firstLi);
        if (startPage > 2) {
            const dotsLi = document.createElement('li');
            dotsLi.className = 'page-item disabled';
            dotsLi.innerHTML = `<span class="page-link">...</span>`;
            ul.appendChild(dotsLi);
        }
    }

    for (let i = startPage; i <= endPage; i++) {
        const pageLi = document.createElement('li');
        pageLi.className = `page-item ${i === currentPage ? 'active' : ''}`;
        const pageLink = document.createElement('a');
        pageLink.className = 'page-link';
        pageLink.href = '#';
        pageLink.textContent = i;
        pageLink.addEventListener('click', (e) => { e.preventDefault(); changePage(i); });
        pageLi.appendChild(pageLink);
        ul.appendChild(pageLi);
    }

    if (endPage < totalPages) {
        if (endPage < totalPages - 1) {
            const dotsLi = document.createElement('li');
            dotsLi.className = 'page-item disabled';
            dotsLi.innerHTML = `<span class="page-link">...</span>`;
            ul.appendChild(dotsLi);
        }
        const lastLi = document.createElement('li');
        lastLi.className = 'page-item';
        const lastLink = document.createElement('a');
        lastLink.className = 'page-link';
        lastLink.href = '#';
        lastLink.textContent = totalPages;
        lastLink.addEventListener('click', (e) => { e.preventDefault(); changePage(totalPages); });
        lastLi.appendChild(lastLink);
        ul.appendChild(lastLi);
    }

    // Next button
    const nextLi = document.createElement('li');
    nextLi.className = `page-item ${currentPage === totalPages ? 'disabled' : ''}`;
    const nextLink = document.createElement('a');
    nextLink.className = 'page-link';
    nextLink.href = '#';
    nextLink.textContent = 'Suivant';
    nextLink.addEventListener('click', (e) => {
        e.preventDefault();
        if (currentPage < totalPages) {
            changePage(currentPage + 1);
        }
    });
    nextLi.appendChild(nextLink);
    ul.appendChild(nextLi);

    paginationContainer.appendChild(ul);
}

function changePage(page) {
    if (page < 1 || page > totalPages || page === currentPage) {
        return;
    }
    currentPage = page;
    window.scrollTo(0, 0);
    loadProducts();
}

async function loadCategories() {
    console.log('🔄 loadCategories - DÉBUT DE LA FONCTION');
    try {
        // Utiliser axios directement pour éviter les problèmes avec apiRequest
        console.log('📡 loadCategories - Appel API /api/products/categories...');
        const response = await axios.get('/api/products/categories');
        let categories = [];
        const data = response.data;

        console.log('✅ loadCategories - Raw API response:', response);
        console.log('📋 loadCategories - Data:', data);
        console.log('🔍 loadCategories - Type de data:', typeof data);
        console.log('📊 loadCategories - Array.isArray(data):', Array.isArray(data));

        // Support multiple shapes: [{id,name,...}], {categories:[...]}, ["name1","name2"], {data:[...]}
        if (Array.isArray(data)) {
            console.log('🎯 loadCategories - Data est un array direct');
            categories = data;
        } else if (data && Array.isArray(data.categories)) {
            console.log('🎯 loadCategories - Data contient data.categories');
            categories = data.categories;
        } else if (data && Array.isArray(data.data)) {
            console.log('🎯 loadCategories - Data contient data.data');
            categories = data.data;
        } else {
            console.log('⚠️ loadCategories - Aucun format reconnu, categories = []');
            categories = [];
        }
        
        console.log('📝 loadCategories - Processed categories:', categories);
        console.log('📏 loadCategories - categories.length:', categories.length);
        
        // Build config map and names list
        categoryConfigByName = {};
        categoryIdByName = {};
        const categoryNames = [];
        
        if (categories.length === 0) {
            console.warn('loadCategories - Aucune catégorie trouvée, ajout de catégories par défaut');
            // Ajouter quelques catégories par défaut si l'API ne retourne rien
            const defaultCategories = [
                { name: 'Smartphones', requires_variants: true },
                { name: 'Ordinateurs portables', requires_variants: true },
                { name: 'Tablettes', requires_variants: true },
                { name: 'Accessoires', requires_variants: false },
                { name: 'Téléphones fixes', requires_variants: false },
                { name: 'Montres connectées', requires_variants: true }
            ];
            categories = defaultCategories;
        }
        
        categories.forEach(c => {
            if (typeof c === 'string') {
                categoryConfigByName[c] = { requires_variants: false };
                categoryNames.push(c);
                console.log(`loadCategories - Added string category: ${c}, requires_variants: false`);
            } else if (c && c.name) {
                const name = c.name;
                const requires = !!c.requires_variants;
                categoryConfigByName[name] = { requires_variants: requires };
                const cid = (c.category_id != null) ? c.category_id : (c.id != null ? c.id : (c.categoryId != null ? c.categoryId : null));
                if (cid != null) categoryIdByName[name] = cid;
                categoryNames.push(name);
                console.log(`loadCategories - Added object category: ${name}, requires_variants: ${requires}`);
            } else {
                console.log('loadCategories - Skipped invalid category:', c);
            }
        });

        console.log('loadCategories - Final categoryConfigByName:', categoryConfigByName);
        console.log('loadCategories - categoryNames:', categoryNames);

        // Validation finale
        if (Object.keys(categoryConfigByName).length === 0) {
            console.error('loadCategories - ERREUR: categoryConfigByName est toujours vide après le traitement !');
        } else {
            console.log('loadCategories - SUCCESS: categoryConfigByName peuplé avec', Object.keys(categoryConfigByName).length, 'catégories');
        }

        const categoryFilter = document.getElementById('categoryFilter');
        const productCategory = document.getElementById('productCategory');

        if (categoryFilter) {
            // keep the first option (placeholder) and remove others
            while (categoryFilter.options.length > 1) categoryFilter.remove(1);
        }
        if (productCategory) {
            while (productCategory.options.length > 1) productCategory.remove(1);
        }

        categoryNames.forEach(name => {
            if (categoryFilter) {
                const opt1 = document.createElement('option');
                opt1.value = name;
                opt1.textContent = name;
                categoryFilter.appendChild(opt1);
            }
            if (productCategory) {
                const opt2 = document.createElement('option');
                opt2.value = name;
                opt2.textContent = name;
                productCategory.appendChild(opt2);
            }
        });
        // Note: L'event listener pour onCategoryChange est déjà configuré dans l'initialisation DOMContentLoaded
    } catch (error) {
        console.error('Erreur lors du chargement des catégories:', error);
    }
}

function openProductModal(productId = null) {
    const modal = document.getElementById('productModal');
    const title = document.getElementById('productModalTitle');
    // Ouvrir/afficher le modal même si déclenché par un bouton sans data-bs-toggle
    try {
        const instance = bootstrap.Modal.getOrCreateInstance(modal);
        instance.show();
    } catch (e) {
        // ignore si Bootstrap non chargé (cas improbable)
    }
    
    if (productId) {
        title.innerHTML = '<i class="bi bi-pencil me-2"></i>Modifier le Produit';
        loadProductForEdit(productId);
    } else {
        title.innerHTML = '<i class="bi bi-plus-circle me-2"></i>Nouveau Produit';
        clearProductForm();
        // Appliquer la logique de catégorie après le reset du formulaire
        setTimeout(() => {
            onCategoryChange();
        }, 50);
        // Charger les états et remplir le select
        populateProductConditionSelect('');
    }
}

function clearProductForm() {
    document.getElementById('productForm').reset();
    document.getElementById('productId').value = '';
    document.getElementById('variantsList').innerHTML = '<p class="text-muted text-center">Aucune variante ajoutée</p>';
    variantCounter = 0;
    
    // Réinitialiser la visibilité des champs
    showProductBarcodeField();
    showQuantityField();
    hideVariantsSection();
}

async function loadProductForEdit(productId) {
    try {
        const response = await apiRequest(`/api/products/id/${productId}`);
        const product = response.data;
        
        // Remplir le formulaire
        document.getElementById('productId').value = product.product_id;
        document.getElementById('productName').value = product.name;
        document.getElementById('productCategory').value = product.category || '';
        document.getElementById('productBrand').value = product.brand || '';
        document.getElementById('productModel').value = product.model || '';
        document.getElementById('productPrice').value = Math.round(product.price || 0);
        document.getElementById('productPurchasePrice').value = Math.round(product.purchase_price || 0);
        document.getElementById('productBarcode').value = product.barcode || '';
        document.getElementById('productQuantity').value = product.quantity;
        document.getElementById('productDescription').value = product.description || '';
        document.getElementById('productNotes').value = product.notes || '';
        populateProductConditionSelect(product.condition || '');
        
        // Charger les variantes
        loadVariants(product.variants || []);
        
        // Appliquer la logique de visibilité selon la catégorie
        onCategoryChange();

        // S'assurer que le modal est visible
        try { bootstrap.Modal.getOrCreateInstance(document.getElementById('productModal')).show(); } catch(e) {}
        
    } catch (error) {
        console.error('Erreur lors du chargement du produit:', error);
        showAlert('Erreur lors du chargement du produit', 'danger');
    }
}

function loadVariants(variants) {
    const variantsList = document.getElementById('variantsList');
    variantCounter = 0;
    
    if (variants.length === 0) {
        variantsList.innerHTML = '<p class="text-muted text-center">Aucune variante ajoutée</p>';
        return;
    }
    
    let html = '';
    variants.forEach(variant => {
        html += createVariantForm(variant, variantCounter++);
    });
    
    variantsList.innerHTML = html;
    // Injecter les attributs de catégorie dans chaque carte déjà rendue
    for (let i = 0; i < variantCounter; i++) {
        renderVariantCategoryAttributes(i);
    }
}

// Fonction appelée lors du changement de catégorie (selon les mémoires)
function onCategoryChange() {
    const category = document.getElementById('productCategory').value;
    console.log('onCategoryChange - Catégorie:', `"${category}"`, 'Config:', categoryConfigByName[category]);
    
    // Si aucune catégorie sélectionnée, afficher le mode produit simple par défaut
    if (!category || category === '') {
        console.log('onCategoryChange - Aucune catégorie sélectionnée, mode produit simple par défaut');
        showProductBarcodeField();
        showQuantityField();
        hideVariantsSection();
        showProductConditionGroup();
        renderCategoryAttributesPreview([]);
        return;
    }
    
    // Vérification de sécurité : si la config n'est pas encore chargée, utiliser un comportement par défaut
    if (Object.keys(categoryConfigByName).length === 0) {
        console.log('onCategoryChange - Config vide, utilisation du comportement par défaut (pas de variantes)');
        // Comportement par défaut : pas de variantes
        showProductBarcodeField();
        showQuantityField();
        hideVariantsSection();
        showProductConditionGroup();
        renderCategoryAttributesPreview([]);
        return;
    }
    
    const requiresVariants = !!(categoryConfigByName[category] && categoryConfigByName[category].requires_variants);
    
    if (requiresVariants) {
        // Masquer le champ code-barres produit et afficher le message d'aide
        hideProductBarcodeField();
        hideQuantityField();
        document.getElementById('productBarcode').value = ''; // Effacer la valeur
        showVariantsSection();
        hideProductConditionGroup();
    } else {
        // Afficher le champ code-barres produit
        showProductBarcodeField();
        showQuantityField();
        // Cacher les variantes et réinitialiser la liste
        hideVariantsSection();
        const variantsList = document.getElementById('variantsList');
        if (variantsList) variantsList.innerHTML = '<p class="text-muted text-center">Aucune variante ajoutée</p>';
        variantCounter = 0;
        showProductConditionGroup();
    }

    // Charger et afficher les attributs de la catégorie
    fetchAndRenderCategoryAttributes(category).catch(err => {
        console.error('Erreur fetch attributs catégorie:', err);
        renderCategoryAttributesPreview([]);
    });
}

function hideProductBarcodeField() {
    const barcodeGroup = document.getElementById('productBarcodeGroup');
    const barcodeInput = document.getElementById('productBarcode');
    const helpText = document.getElementById('barcodeHelpText');
    const genBtn = document.getElementById('productBarcodeGenBtn');
    
    barcodeInput.disabled = true;
    barcodeInput.style.display = 'none';
    if (genBtn) genBtn.style.display = 'none';
    helpText.style.display = 'block';
}

function showProductBarcodeField() {
    const barcodeGroup = document.getElementById('productBarcodeGroup');
    const barcodeInput = document.getElementById('productBarcode');
    const helpText = document.getElementById('barcodeHelpText');
    const genBtn = document.getElementById('productBarcodeGenBtn');
    
    barcodeInput.disabled = false;
    barcodeInput.style.display = 'block';
    if (genBtn) genBtn.style.display = 'inline-block';
    helpText.style.display = 'none';
}

function hideQuantityField() {
    document.getElementById('productQuantityGroup').style.display = 'none';
}

function showQuantityField() {
    document.getElementById('productQuantityGroup').style.display = 'block';
}

// === Helpers génération de codes-barres ===
function generateRandomBarcode(length = 12) {
    // Génère une chaîne numérique de longueur donnée
    const now = Date.now().toString();
    let base = now + Math.floor(Math.random() * 1e9).toString().padStart(9, '0');
    let out = '';
    for (let i = 0; i < length; i++) {
        out += base[i % base.length];
    }
    return out;
}

function generateNewProductBarcode() {
    try {
        const input = document.getElementById('productBarcode');
        if (!input) return;
        // Utilise 12 chiffres (compatibles EAN-13 si on ajoute une clé plus tard)
        const code = generateRandomBarcode(12);
        input.value = code;
    } catch (e) { /* noop */ }
}

function generateVariantBarcode(index) {
    try {
        const card = document.querySelector(`.variant-card[data-variant-index="${index}"]`);
        if (!card) return;
        const input = card.querySelector(`input[name="variant_${index}_barcode"]`);
        if (!input) return;
        input.value = generateRandomBarcode(12);
    } catch (e) { /* noop */ }
}

function addVariant() {
    const variantsList = document.getElementById('variantsList');
    
    if (variantsList.innerHTML.includes('Aucune variante')) {
        variantsList.innerHTML = '';
    }
    
    const variantHtml = createVariantForm(null, variantCounter++);
    variantsList.insertAdjacentHTML('beforeend', variantHtml);
    // Après insertion, injecter les attributs de catégorie pour cette variante
    renderVariantCategoryAttributes(variantCounter - 1);
}

function createVariantForm(variant = null, index) {
    const variantData = variant || {
        imei_serial: '',
        barcode: '',
        condition: '',
        attributes: []
    };
    const sold = !!variantData.is_sold;
    const disabled = sold ? 'disabled' : '';
    const soldBadge = sold ? '<span class="badge bg-danger ms-2">Vendu</span>' : '';
    
    let attributesHtml = '';
    if (variantData.attributes && variantData.attributes.length > 0) {
        variantData.attributes.forEach((attr, attrIndex) => {
            attributesHtml += `
                <div class="row mb-2">
                    <div class="col-md-6">
                        <input type="text" class="form-control form-control-sm" 
                               name="variant_${index}_attr_name_${attrIndex}" 
                               placeholder="Nom attribut (ex: Couleur)" 
                               value="${attr.attribute_name}" ${disabled}>
                    </div>
                    <div class="col-md-6">
                        <div class="input-group">
                            <input type="text" class="form-control form-control-sm" 
                                   name="variant_${index}_attr_value_${attrIndex}" 
                                   placeholder="Valeur (ex: Noir)" 
                                   value="${attr.attribute_value}" ${disabled}>
                            ${sold ? '' : `
                            <button type="button" class="btn btn-outline-danger btn-sm" 
                                    onclick="removeAttribute(this)">
                                <i class="bi bi-trash"></i>
                            </button>`}
                        </div>
                    </div>
                </div>
            `;
        });
    }
    
    return `
        <div class="card mb-3 variant-card" data-variant-index="${index}" data-variant-id="${variantData.variant_id || ''}" data-variant-sold="${sold ? '1' : '0'}">
            <div class="card-header d-flex justify-content-between align-items-center">
                <h6 class="mb-0">Variante #${index + 1} ${soldBadge}</h6>
                ${sold ? '' : `
                <button type="button" class="btn btn-sm btn-outline-danger" onclick="removeVariant(this)">
                    <i class="bi bi-trash"></i>
                </button>`}
            </div>
            <div class="card-body ${sold ? 'bg-light' : ''}">
                <div class="row">
                    <div class="col-md-6">
                        <label class="form-label">IMEI/Numéro de série *</label>
                        <input type="text" class="form-control" 
                               name="variant_${index}_imei" 
                               value="${variantData.imei_serial}" 
                               required ${disabled}>
                    </div>
                    <div class="col-md-6">
                        <label class="form-label">Code-barres variante</label>
                        <div class="input-group">
                            <input type="text" class="form-control" 
                                   name="variant_${index}_barcode" 
                                   value="${variantData.barcode || ''}" ${disabled}>
                            <button type="button" class="btn btn-outline-secondary" onclick="generateVariantBarcode(${index})" title="Générer un code-barres" ${disabled}>
                                <i class="bi bi-upc-scan"></i>
                            </button>
                        </div>
                    </div>
                </div>
                <div class="row mt-2">
                    <div class="col-md-6">
                        <label class="form-label">État de la variante</label>
                        <select class="form-select" name="variant_${index}_condition" data-variant-condition="1" ${disabled}>
                            <option value="">(Hériter du produit)</option>
                            ${allowedConditions.map(c => `<option value="${c}" ${variantData.condition === c ? 'selected' : ''}>${c.charAt(0).toUpperCase()+c.slice(1)}</option>`).join('')}
                        </select>
                    </div>
                </div>
                
                <!-- Attributs de la catégorie (dynamiques) -->
                <div class="mt-3">
                    <label class="form-label mb-2">Attributs de la catégorie</label>
                    <div id="cat_attributes_${index}">
                        <p class="text-muted small mb-0">Aucun attribut pour cette catégorie</p>
                    </div>
                </div>

                <div class="mt-3">
                    <div class="d-flex justify-content-between align-items-center mb-2">
                        <label class="form-label mb-0">Attributs spécifiques</label>
                        <button type="button" class="btn btn-sm btn-outline-secondary" 
                                onclick="addAttribute(${index})" ${disabled}>
                            <i class="bi bi-plus me-1"></i>Ajouter attribut
                        </button>
                    </div>
                    <div id="attributes_${index}">
                        ${attributesHtml || '<p class="text-muted small">Aucun attribut spécifique</p>'}
                    </div>
                </div>
            </div>
        </div>
    `;
}

function removeVariant(button) {
    const variantCard = button.closest('.variant-card');
    if (!variantCard) return;
    
    // Récupérer l'index de la variante
    const variantIndex = variantCard.dataset.variantIndex;
    
    // Créer un champ caché pour indiquer que cette variante doit être supprimée
    const deleteInput = document.createElement('input');
    deleteInput.type = 'hidden';
    deleteInput.name = `delete_variant_${variantIndex}`;
    deleteInput.value = 'true';
    variantCard.appendChild(deleteInput);
    
    // Masquer la carte de variante
    variantCard.style.display = 'none';
    variantCard.setAttribute('data-removed', 'true');
    
    // Désactiver les champs pour qu'ils ne soient pas inclus dans la soumission
    const inputs = variantCard.querySelectorAll('input:not([type="hidden"]), select, textarea');
    inputs.forEach(input => {
        input.disabled = true;
    });
    
    // Vérifier s'il reste des variantes visibles
    const variantsList = document.getElementById('variantsList');
    const visibleVariants = variantsList.querySelectorAll('.variant-card:not([data-removed="true"])');
    
    if (visibleVariants.length === 0) {
        const emptyMessage = document.createElement('p');
        emptyMessage.className = 'text-muted text-center';
        emptyMessage.textContent = 'Aucune variante ajoutée';
        variantsList.appendChild(emptyMessage);
    }
}

function addAttribute(variantIndex) {
    const attributesContainer = document.getElementById(`attributes_${variantIndex}`);
    
    if (attributesContainer.innerHTML.includes('Aucun attribut')) {
        attributesContainer.innerHTML = '';
    }
    
    const attrIndex = attributesContainer.children.length;
    const attributeHtml = `
        <div class="row mb-2">
            <div class="col-md-6">
                <input type="text" class="form-control form-control-sm" 
                       name="variant_${variantIndex}_attr_name_${attrIndex}" 
                       placeholder="Nom attribut (ex: Couleur)">
            </div>
            <div class="col-md-6">
                <div class="input-group">
                    <input type="text" class="form-control form-control-sm" 
                           name="variant_${variantIndex}_attr_value_${attrIndex}" 
                           placeholder="Valeur (ex: Noir)">
                    <button type="button" class="btn btn-outline-danger btn-sm" 
                            onclick="removeAttribute(this)">
                        <i class="bi bi-trash"></i>
                    </button>
                </div>
            </div>
        </div>
    `;
    
    attributesContainer.insertAdjacentHTML('beforeend', attributeHtml);
}

function removeAttribute(button) {
    const attributeRow = button.closest('.row');
    const container = attributeRow.parentElement;
    attributeRow.remove();
    
    if (container.children.length === 0) {
        container.innerHTML = '<p class="text-muted small">Aucun attribut spécifique</p>';
    }
}

function serializeVariants() {
    const variants = [];
    const variantCards = document.querySelectorAll('.variant-card');
    
    variantCards.forEach(card => {
        // Ignorer les variantes marquées comme supprimées
        if (card.getAttribute('data-removed') === 'true') {
            return; // Passer à la variante suivante
        }
        
        const index = card.dataset.variantIndex;
        const imeiInput = card.querySelector(`input[name="variant_${index}_imei"]`);
        const barcodeInput = card.querySelector(`input[name="variant_${index}_barcode"]`);
        const condSelect = card.querySelector(`select[name="variant_${index}_condition"]`);
        
        // Vérifier si c'est une variante à supprimer
        const isDeleted = card.querySelector(`input[name="delete_variant_${index}"]`)?.value === 'true';
        
        if (imeiInput && imeiInput.value.trim() && !isDeleted) {
            const variant = {
                imei_serial: imeiInput.value.trim(),
                barcode: barcodeInput ? barcodeInput.value.trim() : '',
                condition: condSelect ? (condSelect.value || '') : '',
                attributes: []
            };
            
            // Ajouter l'ID de la variante si elle existe (pour les mises à jour)
            const variantId = card.dataset.variantId;
            if (variantId) {
                variant.id = parseInt(variantId);
            }
            
            // Sérialiser les attributs de catégorie
            const catAttrInputs = card.querySelectorAll('[data-variant-attr-input="1"]');
            const grouped = {};
            catAttrInputs.forEach(el => {
                const type = el.dataset.inputType;
                const attrName = el.dataset.attrName;
                if (!attrName) return;
                if (type === 'checkbox') {
                    if (!grouped[attrName]) grouped[attrName] = [];
                    if (el.checked) grouped[attrName].push(el.value);
                } else if (type === 'multiselect') {
                    const vals = Array.from(el.selectedOptions).map(o => o.value).filter(Boolean);
                    if (vals.length) grouped[attrName] = vals;
                } else if (type === 'boolean') {
                    grouped[attrName] = [el.checked ? 'true' : 'false'];
                } else {
                    const val = (el.value || '').trim();
                    if (val) grouped[attrName] = [val];
                }
            });
            
            Object.entries(grouped).forEach(([name, values]) => {
                values.forEach(val => {
                    variant.attributes.push({ attribute_name: name, attribute_value: val });
                });
            });
            
            variants.push(variant);
        }
    });
    
    // Ajouter les variantes à supprimer
    const deletedVariants = [];
    document.querySelectorAll('input[name^="delete_variant_"]').forEach(input => {
        if (input.value === 'true') {
            const variantIndex = input.name.replace('delete_variant_', '');
            // Trouver la carte de variante correspondante pour obtenir son ID
            const card = document.querySelector(`.variant-card[data-variant-index="${variantIndex}"]`);
            if (card && card.dataset.variantId) {
                deletedVariants.push(parseInt(card.dataset.variantId));
            }
        }
    });
    
    return {
        variants: variants,
        deleted_variants: deletedVariants
    };
}

async function saveProduct() {
    try {
        if (!validateForm('productForm')) {
            showAlert('Veuillez remplir tous les champs obligatoires', 'warning');
            return;
        }
        
        const productId = document.getElementById('productId').value;
        const selectedCategory = document.getElementById('productCategory').value;
        const requiresVariants = !!(categoryConfigByName[selectedCategory] && categoryConfigByName[selectedCategory].requires_variants);
        
        // Validation stricte des attributs requis par variante si la catégorie l'exige
        if (requiresVariants) {
            const validation = validateVariantCategoryAttributes();
            if (!validation.ok) {
                showAlert(`Variante #${validation.cardIndex + 1}: l'attribut « ${validation.attrName} » est requis`, 'warning');
                // Scroll vers la carte fautive
                const badCard = document.querySelector(`.variant-card[data-variant-index="${validation.cardIndex}"]`);
                if (badCard && badCard.scrollIntoView) badCard.scrollIntoView({ behavior: 'smooth', block: 'center' });
                return;
            }
        }
        let variantsData = { variants: [], deleted_variants: [] };
        if (requiresVariants) {
            variantsData = serializeVariants();
        }
        
        const productData = {
            name: document.getElementById('productName').value.trim(),
            category: document.getElementById('productCategory').value,
            brand: document.getElementById('productBrand').value.trim(),
            model: document.getElementById('productModel').value.trim(),
            price: parseInt(document.getElementById('productPrice').value, 10) || 0,
            purchase_price: parseInt(document.getElementById('productPurchasePrice').value, 10) || 0,
            barcode: document.getElementById('productBarcode').value.trim(),
            quantity: parseInt(document.getElementById('productQuantity').value) || 0,
            description: document.getElementById('productDescription').value.trim(),
            notes: document.getElementById('productNotes').value.trim(),
            condition: requiresVariants ? undefined : (document.getElementById('productCondition').value || ''),
            variants: variantsData.variants,
            deleted_variants: variantsData.deleted_variants || []
        };

        // Si variantes requises, ne pas conserver visuellement une valeur de condition produit
        if (requiresVariants) {
            const sel = document.getElementById('productCondition');
            if (sel) sel.value = '';
            // Supprimer complètement la clé pour éviter la validation côté backend
            delete productData.condition;
        }
        
        let response;
        if (productId) {
            response = await apiRequest(`/api/products/id/${productId}`, {
                method: 'PUT',
                data: productData
            });
        } else {
            response = await apiRequest('/api/products', {
                method: 'POST',
                data: productData
            });
        }
        
        showAlert(
            productId ? 'Produit modifié avec succès' : 'Produit créé avec succès',
            'success'
        );
        
        // Fermer le modal et recharger la liste
        const modal = bootstrap.Modal.getInstance(document.getElementById('productModal'));
        modal.hide();
        loadProducts();
        
    } catch (error) {
        console.error('Erreur lors de la sauvegarde:', error);
        let errorMessage = 'Erreur lors de la sauvegarde du produit';
        
        if (error.response && error.response.data && error.response.data.detail) {
            errorMessage = error.response.data.detail;
        }
        
        showAlert(errorMessage, 'danger');
    }
}

async function viewProduct(productId) {
    try {
        const response = await apiRequest(`/api/products/id/${productId}`);
        const product = response.data;
        
        let html = `
            <div class="row">
                <div class="col-md-6">
                    <h6>Informations générales</h6>
                    <table class="table table-sm">
                        <tr><td><strong>Nom:</strong></td><td>${product.name}</td></tr>
                        <tr><td><strong>Catégorie:</strong></td><td>${product.category || '-'}</td></tr>
                        <tr><td><strong>Marque:</strong></td><td>${product.brand || '-'}</td></tr>
                        <tr><td><strong>Modèle:</strong></td><td>${product.model || '-'}</td></tr>
                        <tr><td><strong>Prix:</strong></td><td>${formatCurrency(product.price)}</td></tr>
                        <tr><td><strong>Prix d'achat:</strong></td><td>${formatCurrency(product.purchase_price)}</td></tr>
                        <tr><td><strong>État:</strong></td><td>${product.condition || '-'}</td></tr>
                        <tr><td><strong>Stock:</strong></td><td>${product.quantity} unités</td></tr>
                        <tr><td><strong>Code-barres:</strong></td><td>${product.barcode || '-'}</td></tr>
                    </table>
                </div>
                <div class="col-md-6">
                    <h6>Description</h6>
                    <p>${product.description || 'Aucune description'}</p>
                    <h6>Notes</h6>
                    <p>${product.notes || 'Aucune note'}</p>
                </div>
            </div>
        `;
        
        if (product.variants && product.variants.length > 0) {
            const availableCount = (product.variants || []).filter(v => !v.is_sold).length;
            html += `
                <hr>
                <h6>Variantes (${availableCount})</h6>
                <div class="table-responsive">
                    <table class="table table-sm">
                        <thead>
                            <tr>
                                <th>IMEI/Série</th>
                                <th>Code-barres</th>
                                <th>État</th>
                                <th>Attributs</th>
                                <th>Statut</th>
                            </tr>
                        </thead>
                        <tbody>
            `;
            
            product.variants.forEach(variant => {
                let attributesText = '';
                if (variant.attributes && variant.attributes.length > 0) {
                    attributesText = variant.attributes.map(attr => 
                        `${attr.attribute_name}: ${attr.attribute_value}`
                    ).join(', ');
                }
                
                html += `
                    <tr>
                        <td><code>${variant.imei_serial}</code></td>
                        <td>
                            <div class="d-flex align-items-center gap-3">
                                <div>
                                    ${variant.barcode ? `<code class="text-primary">${variant.barcode}</code>` : '-'}
                                    <div class="mt-1">
                                        <svg id="variant-barcode-${variant.variant_id || variant.imei_serial}"></svg>
                                    </div>
                                </div>
                                ${variant.barcode ? `
                                <button class="btn btn-sm btn-outline-secondary" onclick="printVariantBarcode('${variant.barcode}', '${product.name.replace(/'/g, "&#39;")}')">
                                    <i class="bi bi-printer"></i>
                                </button>` : ''}
                            </div>
                        </td>
                        <td>${variant.condition || product.condition || '-'}</td>
                        <td><small>${attributesText || '-'}</small></td>
                        <td>
                            <span class="badge ${variant.is_sold ? 'bg-danger' : 'bg-success'}">
                                ${variant.is_sold ? 'Vendu' : 'Disponible'}
                            </span>
                        </td>
                    </tr>
                `;
            });
            
            html += '</tbody></table></div>';
        }
        
        document.getElementById('productDetailsContent').innerHTML = html;
        
        const modal = new bootstrap.Modal(document.getElementById('productDetailsModal'));
        modal.show();

        // Générer les rendus de codes-barres pour chaque variante affichée
        setTimeout(() => {
            try {
                (product.variants || []).forEach(v => {
                    if (!v.barcode) return;
                    const elId = `#variant-barcode-${v.variant_id || v.imei_serial}`;
                    const svgEl = document.querySelector(elId);
                    if (!svgEl) return;
                    JsBarcode(elId, v.barcode, {
                        format: "CODE128",
                        width: 2,
                        height: 40,
                        displayValue: true,
                        fontSize: 10,
                        margin: 2
                    });
                });
            } catch (e) {
                console.warn('Erreur rendu codes-barres variantes:', e);
            }
        }, 50);
        
    } catch (error) {
        console.error('Erreur lors du chargement des détails:', error);
        showAlert('Erreur lors du chargement des détails du produit', 'danger');
    }
}

function editProduct(productId) {
    openProductModal(productId);
}

// Impression individuelle d'un code-barres de variante
function printVariantBarcode(barcodeValue, productName) {
    if (!barcodeValue) return;
    const w = window.open('', '_blank');
    w.document.write(`<!DOCTYPE html><html><head><meta charset="utf-8"><title>Impression Code-barres</title>
        <style>
            body{font-family: Arial, sans-serif; padding: 12px}
            .barcode-container{width:220px; height:120px; border:1px solid #000; display:flex; flex-direction:column; align-items:center; justify-content:center}
            .label{font-size:12px; font-weight:bold; margin-bottom:6px; text-align:center}
        </style>
    </head><body>
        <div class="barcode-container">
            <div class="label">${(productName || '').replace(/</g,'&lt;')}</div>
            <svg id="to-print"></svg>
        </div>
        <script src="https://cdn.jsdelivr.net/npm/jsbarcode@3.11.5/dist/JsBarcode.all.min.js"></script>
        <script>
            try { JsBarcode('#to-print', '${barcodeValue.replace(/'/g, "\'")}', { format: 'CODE128', width: 2, height: 60, displayValue: true, fontSize: 12, margin: 0 });
                setTimeout(() => { window.print(); setTimeout(() => window.close(), 300); }, 200);
            } catch(e) { document.body.innerHTML = '<p>Erreur impression code-barres</p>'; }
        <\/script>
    </body></html>`);
    w.document.close();
}

async function deleteProduct(productId) {
    if (!confirm('Êtes-vous sûr de vouloir supprimer ce produit ? Cette action est irréversible.')) {
        return;
    }
    
    try {
        await apiRequest(`/api/products/id/${productId}`, { method: 'DELETE' });
        showAlert('Produit supprimé avec succès', 'success');
        loadProducts();
    } catch (error) {
        console.error('Erreur lors de la suppression:', error);
        showAlert('Erreur lors de la suppression du produit', 'danger');
    }
}

function resetFilters() {
    const searchEl = document.getElementById('searchInput');
    const categoryEl = document.getElementById('categoryFilter');
    const condEl = document.getElementById('conditionFilter');
    const brandEl = document.getElementById('brandFilter');
    const modelEl = document.getElementById('modelFilter');
    const minEl = document.getElementById('minPriceFilter');
    const maxEl = document.getElementById('maxPriceFilter');
    const barcodeEl = document.getElementById('hasBarcodeFilter');
    const inStockEl = document.getElementById('inStockFilter');
    const hasVarEl = document.getElementById('hasVariantsFilter');

    if (searchEl) searchEl.value = '';
    if (categoryEl) categoryEl.value = '';
    if (condEl) condEl.value = '';
    if (brandEl) brandEl.value = '';
    if (modelEl) modelEl.value = '';
    if (minEl) minEl.value = '';
    if (maxEl) maxEl.value = '';
    if (barcodeEl) barcodeEl.value = '';
    if (inStockEl) inStockEl.checked = false;
    if (hasVarEl) hasVarEl.checked = false;

    currentFilters = {
        search: '', category: '', condition: '', brand: '', model: '',
        min_price: null, max_price: null, has_barcode: null, in_stock: null, has_variants: null
    };
    currentPage = 1;
    loadProducts();
}

function updatePagination() {
    const container = document.getElementById('pagination-container');
    if (!container) return;
    if (!totalPages || totalPages <= 1) {
        container.innerHTML = '';
        return;
    }

    const makePageItem = (label, page, disabled = false, active = false) => {
        return `
            <li class="page-item ${disabled ? 'disabled' : ''} ${active ? 'active' : ''}">
                <a class="page-link" href="#" data-page="${page}">${label}</a>
            </li>
        `;
    };

    // Fenêtre de pagination (max 5 numéros)
    const windowSize = 5;
    let start = Math.max(1, currentPage - Math.floor(windowSize / 2));
    let end = start + windowSize - 1;
    if (end > totalPages) {
        end = totalPages;
        start = Math.max(1, end - windowSize + 1);
    }

    let itemsHtml = '';
    // First/Prev
    itemsHtml += makePageItem('«', 1, currentPage === 1);
    itemsHtml += makePageItem('‹', currentPage - 1, currentPage === 1);
    // Numbers
    for (let p = start; p <= end; p++) {
        itemsHtml += makePageItem(String(p), p, false, p === currentPage);
    }
    // Next/Last
    itemsHtml += makePageItem('›', currentPage + 1, currentPage === totalPages);
    itemsHtml += makePageItem('»', totalPages, currentPage === totalPages);

    container.innerHTML = `
        <nav aria-label="Pagination produits">
            <ul class="pagination justify-content-center mb-0">
                ${itemsHtml}
            </ul>
        </nav>
        <div class="text-center text-muted small mt-2">
            Page ${currentPage} / ${totalPages}
        </div>
    `;

    // Wire click handlers
    container.querySelectorAll('a.page-link').forEach(a => {
        a.addEventListener('click', (e) => {
            e.preventDefault();
            const target = Number(a.getAttribute('data-page'));
            if (!target || target === currentPage || target < 1 || target > totalPages) return;
            currentPage = target;
            loadProducts();
        });
    });
}

// ====== Attributs de catégorie: chargement et rendu ======

async function fetchAndRenderCategoryAttributes(categoryName) {
    const hint = document.getElementById('categoryAttributesHint');
    const container = document.getElementById('categoryAttributesContainer');
    if (!hint || !container) return;

    const catId = categoryIdByName[categoryName];
    if (!catId) {
        console.warn('[products] fetchAndRenderCategoryAttributes: catId introuvable pour', categoryName, 'mapping:', categoryIdByName);
        currentCategoryAttributes = [];
        renderCategoryAttributesPreview([]);
        return;
    }

    container.innerHTML = '<div class="text-center"><div class="spinner-border" role="status"><span class="visually-hidden">Chargement...</span></div></div>';
    try {
        const { data } = await axios.get(`/api/products/categories/${catId}/attributes`);
        currentCategoryAttributes = Array.isArray(data) ? data : [];
        renderCategoryAttributesPreview(currentCategoryAttributes);
        // Mettre à jour les cartes variantes existantes
        document.querySelectorAll('.variant-card').forEach(card => {
            const idx = Number(card.dataset.variantIndex);
            renderVariantCategoryAttributes(idx);
        });
    } catch (e) {
        console.error('fetchAndRenderCategoryAttributes error:', e);
        currentCategoryAttributes = [];
        renderCategoryAttributesPreview([]);
    }
}

function renderCategoryAttributesPreview(attrs) {
    const hint = document.getElementById('categoryAttributesHint');
    const container = document.getElementById('categoryAttributesContainer');
    if (!hint || !container) return;
    if (!attrs || attrs.length === 0) {
        hint.textContent = 'Aucun attribut pour cette catégorie';
        container.innerHTML = '<p class="text-muted mb-0">Aucun attribut à afficher</p>';
        return;
    }
    hint.textContent = `${attrs.length} attribut(s)`;
    container.innerHTML = attrs.map(a => {
        const req = a.required ? '<span class="badge bg-danger ms-1">Obligatoire</span>' : '';
        const type = `<span class=\"badge bg-light text-dark ms-1\">${a.type}</span>`;
        const values = (a.values || []).map(v => `<span class=\"badge rounded-pill bg-info text-dark me-1\">${escapeHtml(v.value)}</span>`).join(' ');
        return `<div class=\"mb-1\"><strong>${escapeHtml(a.name)}</strong> ${type} ${req}<div class=\"small text-muted\">${values || '—'}</div></div>`;
    }).join('');
}

function renderVariantCategoryAttributes(index) {
    const host = document.getElementById(`cat_attributes_${index}`);
    if (!host) return;
    if (!currentCategoryAttributes || currentCategoryAttributes.length === 0) {
        host.innerHTML = '<p class="text-muted small mb-0">Aucun attribut pour cette catégorie</p>';
        return;
    }
    const fields = currentCategoryAttributes.map((a, i) => renderAttrInput(index, a, i)).join('');
    host.innerHTML = fields;
    // Si la variante est vendue, désactiver tous les champs dans la carte
    try {
        const card = document.querySelector(`.variant-card[data-variant-index="${index}"]`);
        const isSold = card && String(card.dataset.variantSold) === '1';
        if (isSold) {
            card.querySelectorAll('input, select, textarea, button').forEach(el => {
                // Ne pas désactiver le bouton d'entête inexistant; ici on applique partout
                el.disabled = true;
            });
        }
    } catch (e) { /* noop */ }
    // Après rendu, tenter de pré-remplir à partir des "Attributs spécifiques"
    try { prefillVariantCategoryAttrValues(index); } catch(e) { console.warn('prefillVariantCategoryAttrValues error:', e); }
}

// Construit une map des attributs spécifiques saisis pour une variante: name(normalisé) -> [valeurs]
function buildVariantSpecificAttrMap(index) {
    const container = document.getElementById(`attributes_${index}`);
    const map = {};
    if (!container) return map;
    const nameInputs = container.querySelectorAll(`[name^="variant_${index}_attr_name_"]`);
    nameInputs.forEach(nameInput => {
        const name = (nameInput.value || '').trim();
        if (!name) return;
        const suffix = nameInput.name.split(`variant_${index}_attr_name_`)[1];
        const valInput = container.querySelector(`[name="variant_${index}_attr_value_${suffix}"]`);
        const val = (valInput && valInput.value != null) ? String(valInput.value).trim() : '';
        const key = name.toLowerCase();
        if (!map[key]) map[key] = [];
        if (val) map[key].push(val);
    });
    return map;
}

// Pré-remplit les inputs d'attributs de catégorie d'une carte variante à partir de la map spécifique
function prefillVariantCategoryAttrValues(index) {
    const card = document.querySelector(`.variant-card[data-variant-index="${index}"]`);
    if (!card) return;
    const specificMap = buildVariantSpecificAttrMap(index);
    if (!specificMap || Object.keys(specificMap).length === 0) return;
    const inputs = card.querySelectorAll('[data-variant-attr-input="1"]');
    inputs.forEach(input => {
        const attrName = (input.dataset.attrName || '').toLowerCase().trim();
        if (!attrName || !(attrName in specificMap)) return;
        const values = specificMap[attrName];
        const type = input.dataset.inputType;
        if (type === 'select') {
            // Choisir la première valeur correspondante disponible dans la liste
            const options = Array.from(input.options).map(o => o.value.toLowerCase());
            const match = values.find(v => options.includes(String(v).toLowerCase()));
            if (match) input.value = match;
        } else if (type === 'checkbox') {
            // Coche si la valeur 'true'/'1' est trouvée
            const match = values.find(v => ['true','1','oui','yes'].includes(String(v).toLowerCase()));
            input.checked = !!match;
        } else if (type === 'number') {
            const v = values[0];
            if (v != null && v !== '') input.value = v;
        } else { // text
            const v = values[0];
            if (v != null && v !== '') input.value = v;
        }
    });
}

function renderAttrInput(index, attr, order) {
    const baseId = `v${index}_attr_${attr.attribute_id || order}`;
    const name = attr.name;
    const values = attr.values || [];
    switch (attr.type) {
        case 'select': {
            const options = ['<option value="">Sélectionner...</option>']
                .concat(values.map(v => `<option value="${escapeHtml(v.value)}">${escapeHtml(v.value)}</option>`)).join('');
            return `
            <div class="mb-2">
                <label class="form-label small">${escapeHtml(name)}${attr.required ? ' *' : ''}</label>
                <select class="form-select form-select-sm" id="${baseId}" data-variant-attr-input="1" data-input-type="select" data-attr-name="${escapeHtml(name)}">
                    ${options}
                </select>
            </div>`;
        }
        case 'multiselect': {
            const options = values.map(v => `<option value="${escapeHtml(v.value)}">${escapeHtml(v.value)}</option>`).join('');
            return `
            <div class="mb-2">
                <label class="form-label small">${escapeHtml(name)}${attr.required ? ' *' : ''}</label>
                <select multiple class="form-select form-select-sm" id="${baseId}" data-variant-attr-input="1" data-input-type="multiselect" data-attr-name="${escapeHtml(name)}">
                    ${options}
                </select>
            </div>`;
        }
        case 'boolean': {
            return `
            <div class="form-check form-switch mb-2">
                <input class="form-check-input" type="checkbox" id="${baseId}" data-variant-attr-input="1" data-input-type="boolean" data-attr-name="${escapeHtml(name)}">
                <label class="form-check-label small" for="${baseId}">${escapeHtml(name)}${attr.required ? ' *' : ''}</label>
            </div>`;
        }
        case 'number': {
            return `
            <div class="mb-2">
                <label class="form-label small">${escapeHtml(name)}${attr.required ? ' *' : ''}</label>
                <input type="number" step="any" class="form-control form-control-sm" id="${baseId}" data-variant-attr-input="1" data-input-type="number" data-attr-name="${escapeHtml(name)}">
            </div>`;
        }
        case 'text':
        default: {
            return `
            <div class="mb-2">
                <label class="form-label small">${escapeHtml(name)}${attr.required ? ' *' : ''}</label>
                <input type="text" class="form-control form-control-sm" id="${baseId}" data-variant-attr-input="1" data-input-type="text" data-attr-name="${escapeHtml(name)}">
            </div>`;
        }
    }
}
