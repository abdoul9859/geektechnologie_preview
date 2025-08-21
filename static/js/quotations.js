async function loadQuotationDetail(quotationId) {
    const { data: q } = await axios.get(`/api/quotations/${quotationId}`);
    const cl = (clients || []).find(c => Number(c.client_id) === Number(q.client_id));
    const body = document.getElementById('quotationDetailBody');
    const items = (q.items || []).map(it => `
        <tr>
            <td>
                ${escapeHtml(it.product_name || '')}
                ${(() => { try { const p = (products||[]).find(pp => Number(pp.product_id) === Number(it.product_id)); return (p && p.description) ? `<div class="text-muted small mt-1" style="text-align:justify">${escapeHtml(p.description)}</div>` : ''; } catch(e){ return ''; } })()}
            </td>
            <td class="text-end">${it.quantity}</td>
            <td class="text-end">${formatCurrency(it.price)}</td>
            <td class="text-end">${formatCurrency(it.total)}</td>
        </tr>
    `).join('');
    body.innerHTML = `
        <div class="mb-2"><strong>Numéro:</strong> ${escapeHtml(q.quotation_number)}</div>
        <div class="mb-2"><strong>Client:</strong> ${escapeHtml(cl ? cl.name : (q.client_name || '-'))}</div>
        <div class="mb-2"><strong>Date:</strong> ${q.date ? formatDate(q.date) : '-'}</div>
        <div class="mb-2"><strong>Valide jusqu'au:</strong> ${q.expiry_date ? formatDate(q.expiry_date) : '-'}</div>
        <div class="table-responsive"> 
            <table class="table table-sm"> 
                <thead><tr><th>Article</th><th class="text-end">Qté</th><th class="text-end">PU</th><th class="text-end">Total</th></tr></thead>
                <tbody>${items}</tbody>
            </table>
        </div>
        <div class="text-end">
            <div><strong>Sous-total:</strong> ${formatCurrency(q.subtotal || 0)}</div>
            <div><strong>TVA (${Number(q.tax_rate || 0)}%):</strong> ${formatCurrency(q.tax_amount || 0)}</div>
            <div class="fs-5"><strong>Total:</strong> ${formatCurrency(q.total || 0)}</div>
        </div>
    `;
    const modal = new bootstrap.Modal(document.getElementById('quotationDetailModal'));
    document.getElementById('quotationDetailModal').dataset.quotationId = quotationId;
    modal.show();
}

async function preloadQuotationIntoForm(quotationId) {
    const { data: q } = await axios.get(`/api/quotations/${quotationId}`);
    openQuotationModal();
    document.getElementById('quotationModalTitle').innerHTML = '<i class="bi bi-pencil me-2"></i>Modifier le Devis';
    document.getElementById('quotationId').value = q.quotation_id;
    document.getElementById('quotationNumber').value = q.quotation_number;
    document.getElementById('quotationDate').value = (q.date || '').split('T')[0] || '';
    document.getElementById('validUntil').value = (q.expiry_date || '').split('T')[0] || '';
    const clientSel = document.getElementById('clientSelect');
    if (clientSel) clientSel.value = q.client_id;
    document.getElementById('quotationNotes').value = q.notes || '';
    // TVA
    const taxInput = document.getElementById('taxRateInput');
    if (taxInput) taxInput.value = Number(q.tax_rate || 18);
    const showTaxSwitch = document.getElementById('showTaxSwitch');
    if (showTaxSwitch) showTaxSwitch.checked = (Number(q.tax_rate || 0) > 0);
    // Items
    quotationItems = (q.items || []).map(it => ({
        id: Date.now() + Math.random(),
        product_id: it.product_id,
        product_name: it.product_name,
        is_custom: !it.product_id,
        quantity: it.quantity,
        unit_price: Number(it.price),
        total: Number(it.total)
    }));
    updateQuotationItemsDisplay();
    calculateTotals();
}
// Gestion des devis
let currentPage = 1;
const itemsPerPage = 20;
let quotations = [];
let filteredQuotations = [];
let clients = [];
let products = [];
let quotationItems = [];
let productVariantsByProductId = new Map(); // pour IMEI/variantes comme factures
let productIdToStock = new Map();

// Initialisation (cookie-based auth readiness)
document.addEventListener('DOMContentLoaded', function() {
    const ready = () => {
        const hasAuthManager = !!window.authManager;
        const hasUser = !!(hasAuthManager && window.authManager.userData && Object.keys(window.authManager.userData).length);
        return hasAuthManager && (window.authManager.isAuthenticatedSync() || hasUser);
    };

    const boot = () => {
        loadQuotations();
        loadStats();
        loadClients();
        loadProducts();
        setupEventListeners();
        setDefaultDates();
    };

    if (!ready()) {
        setTimeout(() => {
            if (!ready()) return;
            boot();
        }, 300);
        return;
    }
    boot();
});

function setupEventListeners() {
    // Filtres
    document.getElementById('statusFilter')?.addEventListener('change', filterQuotations);
    document.getElementById('clientFilter')?.addEventListener('input', debounce(filterQuotations, 300));
    document.getElementById('dateFromFilter')?.addEventListener('change', filterQuotations);
    document.getElementById('dateToFilter')?.addEventListener('change', filterQuotations);

    // TVA controls
    const taxSwitch = document.getElementById('showTaxSwitch');
    const taxRateInput = document.getElementById('taxRateInput');
    if (taxSwitch) taxSwitch.addEventListener('change', calculateTotals);
    if (taxRateInput) {
        const handler = () => calculateTotals();
        taxRateInput.addEventListener('input', handler);
        taxRateInput.addEventListener('change', handler);
        taxRateInput.addEventListener('keyup', handler);
        taxRateInput.addEventListener('blur', handler);
    }

    // Recherche produit dans lignes devis
    document.getElementById('quotationItemsBody')?.addEventListener('input', debounce(async (e) => {
        const target = e.target;
        if (!(target && target.classList && target.classList.contains('quotation-search-input'))) return;
        const query = String(target.value || '').trim();
        const row = target.closest('tr');
        if (!row) return;
        const suggestBox = row.querySelector('.quotation-suggestions');
        if (!suggestBox) return;
        if (query.length < 2) { suggestBox.classList.add('d-none'); suggestBox.innerHTML = ''; return; }
        try {
            const res = await axios.get('/api/products/', { params: { search: query, limit: 20 } });
            const list = res.data?.items || res.data || [];
            suggestBox.innerHTML = list.map(p => `
                <div class="list-group-item list-group-item-action d-flex justify-content-between align-items-center" data-product-id="${p.product_id}">
                    <div>
                        <div class="fw-semibold">${escapeHtml(p.name)}</div>
                        <div class="text-muted small">${p.barcode ? 'Code: '+escapeHtml(p.barcode) : ''}</div>
                    </div>
                    <div class="text-nowrap ms-3">${formatCurrency(p.price)}</div>
                </div>
            `).join('');
            suggestBox.classList.toggle('d-none', list.length === 0);
        } catch (err) {
            suggestBox.classList.add('d-none');
            suggestBox.innerHTML = '';
        }
    }, 250));

    // Sélection d'une suggestion
    document.getElementById('quotationItemsBody')?.addEventListener('click', (e) => {
        const item = e.target.closest('.list-group-item[data-product-id]');
        if (!item) return;
        const row = item.closest('tr');
        const productId = item.getAttribute('data-product-id');
        const input = row.querySelector('.quotation-search-input');
        // Récupérer l'id logique de l'item via structure JS
        let idAttr = null;
        try {
            // Trouver l'index de la ligne dans le DOM puis mapper au tableau quotationItems si besoin
            idAttr = row.querySelector('button.btn-outline-danger')?.getAttribute('onclick')?.match(/removeQuotationItem\((\d+)\)/)?.[1] || null;
        } catch (e) {}
        const explicitId = Number(row?.dataset?.itemId || idAttr || 0);
        const realId = explicitId || (quotationItems.find(it => !it.product_id)?.id);
        if (productId && realId) {
            selectProduct(Number(realId), productId);
            const box = row.querySelector('.quotation-suggestions');
            if (box) { box.innerHTML = ''; box.classList.add('d-none'); }
            if (input) input.value = '';
        }
    });

    // Cacher le dropdown si clic en dehors
    document.addEventListener('click', (e) => {
        document.querySelectorAll('.quotation-suggestions').forEach(box => {
            if (!box.contains(e.target) && !box.previousElementSibling?.contains(e.target)) {
                box.classList.add('d-none');
            }
        });
    });
}

function setDefaultDates() {
    const today = new Date().toISOString().split('T')[0];
    const quotationDate = document.getElementById('quotationDate');
    
    if (quotationDate) quotationDate.value = today;
    
    // Date de validité par défaut (30 jours)
    const validUntil = new Date();
    validUntil.setDate(validUntil.getDate() + 30);
    const validUntilInput = document.getElementById('validUntil');
    if (validUntilInput) validUntilInput.value = validUntil.toISOString().split('T')[0];
}

// Statistiques (calculées côté client sur la liste filtrée)
async function loadStats() { updateStats(); }

function updateStats() {
    try {
        const list = Array.isArray(filteredQuotations) && filteredQuotations.length ? filteredQuotations : (Array.isArray(quotations) ? quotations : []);
        const total = list.length;
        // Acceptés (gérer FR/EN)
        const accepted = list.filter(q => {
            const s = String(q.status || '').toUpperCase();
            return s === 'ACCEPTED' || s === 'ACCEPTE' || s === 'ACCEPTÉ';
        }).length;
        // En attente = brouillons + envoyés (gérer FR/EN)
        const pending = list.filter(q => {
            const s = String(q.status || '').toUpperCase();
            return s === 'DRAFT' || s === 'SENT' || s === 'EN ATTENTE' || s === 'EN_ATTENTE' || s === 'BROUILLON' || s === 'ENVOYÉ' || s === 'ENVOYE';
        }).length;
        // Valeur totale
        const totalValue = list.reduce((s, q) => s + (Number(q.total) || 0), 0);
        const elTotal = document.getElementById('totalQuotations');
        const elAccepted = document.getElementById('acceptedQuotations');
        const elPending = document.getElementById('pendingQuotations');
        const elValue = document.getElementById('totalValue');
        if (elTotal) elTotal.textContent = String(total);
        if (elAccepted) elAccepted.textContent = String(accepted);
        if (elPending) elPending.textContent = String(pending);
        if (elValue) elValue.textContent = typeof formatCurrency === 'function' ? formatCurrency(totalValue) : `${(totalValue||0).toLocaleString('fr-FR')} XOF`;
    } catch (e) {
        // silencieux
    }
}

// Charger la liste des devis
async function loadQuotations() {
    try {
        showLoading();
        const response = await safeLoadData(
            () => axios.get('/api/quotations/'),
            {
                timeout: 8000,
                fallbackData: [],
                errorMessage: 'Erreur lors du chargement des devis'
            }
        );
        const payload = response?.data ?? [];
        quotations = Array.isArray(payload) ? payload : (payload.items || []);
        filteredQuotations = [...quotations];

        if (!Array.isArray(filteredQuotations) || filteredQuotations.length === 0) {
            showEmptyState();
            updatePagination();
            updateStats();
            return;
        }

        displayQuotations();
        updatePagination();
        updateStats();
    } catch (error) {
        console.error('Erreur lors du chargement des devis:', error);
        showError(error.response?.data?.detail || 'Erreur lors du chargement des devis');
        showEmptyState();
    }
}

// Charger les clients
async function loadClients() {
    try {
        const { data } = await axios.get('/api/clients/');
        clients = data?.items || data || [];
        populateClientSelect();
        // Re-rendre la liste des devis pour injecter le nom client après chargement
        try { if (Array.isArray(quotations) && quotations.length) displayQuotations(); } catch(e) {}
    } catch (error) {
        console.error('Erreur lors du chargement des clients:', error);
    }
}

// Charger les produits
async function loadProducts() {
    try {
        const { data } = await axios.get('/api/products/?limit=200');
        products = data?.items || data || [];
        // Préparer variations par produit (même logique que factures)
        productVariantsByProductId.clear();
        productIdToStock.clear();
        await Promise.all((products || []).map(async (p) => {
            try {
                const variants = (p.variants && p.variants.length) ? p.variants : [];
                productVariantsByProductId.set(p.product_id, variants);
                // Stock info (non bloquant)
                const available = variants.length ? variants.filter(v => !v.is_sold).length : (p.quantity || 0);
                productIdToStock.set(p.product_id, available);
            } catch (e) {}
        }));
    } catch (error) {
        console.error('Erreur lors du chargement des produits:', error);
    }
}

// Remplir le select des clients
function populateClientSelect() {
    const clientSelect = document.getElementById('clientSelect');
    if (!clientSelect) return;

    clientSelect.innerHTML = '<option value="">Sélectionner un client</option>';
    clients.forEach(client => {
        const option = document.createElement('option');
        option.value = client.client_id;
        option.textContent = client.name;
        clientSelect.appendChild(option);
    });
}

// Afficher les devis
function displayQuotations() {
    const tbody = document.getElementById('quotationsTableBody');
    if (!tbody) return;

    if (filteredQuotations.length === 0) {
        showEmptyState();
        return;
    }

    const startIndex = (currentPage - 1) * itemsPerPage;
    const endIndex = startIndex + itemsPerPage;
    const quotationsToShow = filteredQuotations.slice(startIndex, endIndex);

    tbody.innerHTML = quotationsToShow.map(quotation => {
        const cl = (clients || []).find(c => Number(c.client_id) === Number(quotation.client_id));
        const clientName = cl ? cl.name : (quotation.client_name || quotation.client?.name || '-');
        const currentStatusFr = String(quotation.status || '').toLowerCase();
        const hasInvoice = !!Number(quotation.invoice_id || 0);
        return `
        <tr>
            <td>
                <strong>${escapeHtml(quotation.quotation_number)}</strong>
            </td>
            <td>${escapeHtml(clientName)}</td>
            <td>${quotation.date ? formatDate(quotation.date) : '-'}</td>
            <td>${quotation.expiry_date ? formatDate(quotation.expiry_date) : '-'}</td>
            <td><strong>${formatCurrency(Number(quotation.total || 0))}</strong></td>
            <td>
                <select class="form-select form-select-sm" onchange="changeQuotationStatus(${quotation.quotation_id}, this.value)">
                    <option value="en attente" ${currentStatusFr==='en attente'?'selected':''}>Brouillon/Envoyé</option>
                    <option value="accepté" ${currentStatusFr==='accepté'?'selected':''}>Accepté</option>
                    <option value="refusé" ${currentStatusFr==='refusé'?'selected':''}>Refusé</option>
                    <option value="expiré" ${currentStatusFr==='expiré'?'selected':''}>Expiré</option>
                </select>
            </td>
            <td>
                <div class="btn-group" role="group">
                    <button class="btn btn-sm btn-outline-info" onclick="viewQuotation(${quotation.quotation_id})" title="Voir">
                        <i class="bi bi-eye"></i>
                    </button>
                    <button class="btn btn-sm btn-outline-primary" onclick="editQuotation(${quotation.quotation_id})" title="Modifier">
                        <i class="bi bi-pencil"></i>
                    </button>
                    ${hasInvoice ? `
                        <button class="btn btn-sm btn-success" onclick="goToInvoice(${Number(quotation.invoice_id)})" title="Voir la facture">
                            <i class="bi bi-receipt"></i>
                        </button>
                    ` : ((String(quotation.status||'').toLowerCase()==='accepté') ? `
                        <button class="btn btn-sm btn-outline-success" onclick="convertToInvoice(${quotation.quotation_id})" title="Convertir en facture">
                            <i class="bi bi-receipt"></i>
                        </button>
                    ` : '')}
                    <button class="btn btn-sm btn-outline-secondary" onclick="printQuotation(${quotation.quotation_id})" title="Imprimer">
                        <i class="bi bi-printer"></i>
                    </button>
                    <button class="btn btn-sm btn-outline-danger" onclick="deleteQuotation(${quotation.quotation_id})" title="Supprimer">
                        <i class="bi bi-trash"></i>
                    </button>
                </div>
            </td>
        </tr>
    `}).join('');
}
function goToInvoice(invoiceId) {
    if (!invoiceId) return;
    try {
        sessionStorage.setItem('invoiceSearchQuery', String(invoiceId));
    } catch(e) {}
    window.location.href = '/invoices';
}

// Changer le statut directement depuis la liste
async function changeQuotationStatus(quotationId, newStatus) {
    try {
        const statusFr = String(newStatus || '').toLowerCase();
        await axios.put(`/api/quotations/${quotationId}/status`, { status: statusFr });
        await loadQuotations();
        await loadStats();
        showSuccess('Statut du devis mis à jour');
    } catch (e) {
        showError(e.response?.data?.detail || 'Impossible de mettre à jour le statut');
    }
}

function showEmptyState() {
    const tbody = document.getElementById('quotationsTableBody');
    if (tbody) {
        tbody.innerHTML = `
            <tr>
                <td colspan="7" class="text-center text-muted py-4">
                    <i class="bi bi-inbox fs-1 d-block mb-2"></i>
                    Aucun devis trouvé
                </td>
            </tr>
        `;
    }
}

function showLoading() {
    // Ne pas afficher d'indicateur de chargement pour une expérience instantanée
}

// Utilitaires pour les statuts de devis
function getQuotationStatusBadgeColor(status) {
    switch (status) {
        case 'DRAFT': return 'secondary';
        case 'SENT': return 'primary';
        case 'ACCEPTED': return 'success';
        case 'REJECTED': return 'danger';
        case 'EXPIRED': return 'warning';
        default: return 'secondary';
    }
}

function getQuotationStatusLabel(status) {
    switch (status) {
        case 'DRAFT': return 'Brouillon';
        case 'SENT': return 'Envoyé';
        case 'ACCEPTED': return 'Accepté';
        case 'REJECTED': return 'Refusé';
        case 'EXPIRED': return 'Expiré';
        default: return status;
    }
}

// Filtrer les devis
function filterQuotations() {
    const statusFilter = document.getElementById('statusFilter').value;
    const clientFilter = document.getElementById('clientFilter').value.toLowerCase().trim();
    const dateFromFilter = document.getElementById('dateFromFilter').value;
    const dateToFilter = document.getElementById('dateToFilter').value;

    filteredQuotations = quotations.filter(quotation => {
        // Filtre par statut
        if (statusFilter && quotation.status !== statusFilter) {
            return false;
        }

        // Filtre par client (chercher via tableau clients si nécessaire)
        const clientObj = (clients || []).find(c => Number(c.client_id) === Number(quotation.client_id));
        const clientName = (clientObj && clientObj.name) ? String(clientObj.name) : String(quotation.client_name || '');
        if (clientFilter && !clientName.toLowerCase().includes(clientFilter)) {
            return false;
        }

        // Filtre par date
    const quotationDate = quotation.date ? new Date(quotation.date).toISOString().split('T')[0] : '';
        if (dateFromFilter && quotationDate < dateFromFilter) {
            return false;
        }
        if (dateToFilter && quotationDate > dateToFilter) {
            return false;
        }

        return true;
    });

    currentPage = 1;
    displayQuotations();
    updatePagination();
    updateStats();
}

// Pagination
function updatePagination() {
    const totalPages = Math.ceil(filteredQuotations.length / itemsPerPage);
    const paginationContainer = document.getElementById('pagination-container');
    
    if (!paginationContainer || totalPages <= 1) {
        if (paginationContainer) paginationContainer.innerHTML = '';
        return;
    }

    let paginationHTML = '<nav><ul class="pagination justify-content-center">';
    
    // Bouton précédent
    paginationHTML += `
        <li class="page-item ${currentPage === 1 ? 'disabled' : ''}">
            <a class="page-link" href="#" onclick="changePage(${currentPage - 1})">Précédent</a>
        </li>
    `;
    
    // Numéros de page
    for (let i = 1; i <= totalPages; i++) {
        if (i === 1 || i === totalPages || (i >= currentPage - 2 && i <= currentPage + 2)) {
            paginationHTML += `
                <li class="page-item ${i === currentPage ? 'active' : ''}">
                    <a class="page-link" href="#" onclick="changePage(${i})">${i}</a>
                </li>
            `;
        } else if (i === currentPage - 3 || i === currentPage + 3) {
            paginationHTML += '<li class="page-item disabled"><span class="page-link">...</span></li>';
        }
    }
    
    // Bouton suivant
    paginationHTML += `
        <li class="page-item ${currentPage === totalPages ? 'disabled' : ''}">
            <a class="page-link" href="#" onclick="changePage(${currentPage + 1})">Suivant</a>
        </li>
    `;
    
    paginationHTML += '</ul></nav>';
    paginationContainer.innerHTML = paginationHTML;
}

function changePage(page) {
    const totalPages = Math.ceil(filteredQuotations.length / itemsPerPage);
    if (page >= 1 && page <= totalPages) {
        currentPage = page;
        displayQuotations();
        updatePagination();
    }
}

// Ouvrir le modal pour nouveau devis
function openQuotationModal() {
    document.getElementById('quotationModalTitle').innerHTML = '<i class="bi bi-plus-circle me-2"></i>Nouveau Devis';
    document.getElementById('quotationForm').reset();
    document.getElementById('quotationId').value = '';
    setDefaultDates();
    
    // Générer un numéro de devis automatique
    const nextNumber = generateNumber('DEV-', quotations.length);
    document.getElementById('quotationNumber').value = nextNumber;
    
    // Vider les articles
    quotationItems = [];
    updateQuotationItemsDisplay();
    calculateTotals();

    // Setup signature pad comme facture
    try {
        const canvas = document.getElementById('signatureCanvas');
        if (canvas) {
            const ctx = canvas.getContext('2d');
            let drawing = false; let last = null;
            const getPos = (e) => {
                const rect = canvas.getBoundingClientRect();
                const x = (e.touches ? e.touches[0].clientX : e.clientX) - rect.left;
                const y = (e.touches ? e.touches[0].clientY : e.clientY) - rect.top;
                return { x, y };
            };
            const start = (e) => { drawing = true; last = getPos(e); };
            const move = (e) => {
                if (!drawing) return;
                const pos = getPos(e);
                ctx.beginPath();
                ctx.moveTo(last.x, last.y);
                ctx.lineTo(pos.x, pos.y);
                ctx.strokeStyle = '#111';
                ctx.lineWidth = 2;
                ctx.lineCap = 'round';
                ctx.stroke();
                last = pos;
                e.preventDefault();
            };
            const end = () => { drawing = false; };
            canvas.addEventListener('mousedown', start);
            canvas.addEventListener('mousemove', move);
            window.addEventListener('mouseup', end);
            canvas.addEventListener('touchstart', start, { passive: false });
            canvas.addEventListener('touchmove', move, { passive: false });
            canvas.addEventListener('touchend', end);
            document.getElementById('signatureClearBtn')?.addEventListener('click', () => {
                ctx.clearRect(0, 0, canvas.width, canvas.height);
            });
        }
    } catch (e) { /* ignore */ }

    // Toujours afficher le modal (utile pour l'édition où on ouvre par JS)
    try {
        const modalEl = document.getElementById('quotationModal');
        if (modalEl) bootstrap.Modal.getOrCreateInstance(modalEl).show();
    } catch (e) {}
}

// Gestion des articles de devis
function addQuotationItem() {
    const newItem = {
        id: Date.now(),
        product_id: '',
        product_name: '',
        is_custom: false,
        quantity: 1,
        unit_price: 0,
        total: 0
    };
    
    quotationItems.push(newItem);
    updateQuotationItemsDisplay();
}

// Ajouter une ligne libre/service (sans produit)
function addCustomItem() {
    const newItem = {
        id: Date.now(),
        product_id: null,
        product_name: 'Service personnalisé',
        is_custom: true,
        quantity: 1,
        unit_price: 0,
        total: 0
    };
    quotationItems.push(newItem);
    updateQuotationItemsDisplay();
}

function updateQuotationItemsDisplay() {
    const tbody = document.getElementById('quotationItemsBody');
    if (!tbody) return;

    if (quotationItems.length === 0) {
        tbody.innerHTML = `
            <tr>
                <td colspan="5" class="text-center text-muted py-3">
                    <i class="bi bi-inbox me-2"></i>Aucun article ajouté
                </td>
            </tr>
        `;
        return;
    }

    tbody.innerHTML = quotationItems.map(item => `
        <tr data-item-id="${item.id}">
            <td>
                ${item.is_custom ? `
                <input type="text" class="form-control form-control-sm" value="${escapeHtml(item.product_name || '')}" placeholder="Libellé (ex: Installation Windows)" oninput="updateCustomName(${item.id}, this.value)">
                ` : `
                <div class="input-group input-group-sm">
                    <input type="text" class="form-control form-control-sm quotation-search-input" placeholder="Rechercher un produit..." data-item-id="${item.id}" />
                    <select class="form-select" onchange="selectProduct(${item.id}, this.value)">
                    <option value="">Sélectionner un produit</option>
                        ${products.map(product => {
                            const variants = productVariantsByProductId.get(Number(product.product_id)) || [];
                            const available = variants.filter(v => !v.is_sold).length;
                            const disabled = variants.length > 0 && available === 0;
                            const stock = productIdToStock.get(product.product_id) ?? 0;
                            return `
                            <option value="${product.product_id}" ${product.product_id == item.product_id ? 'selected' : ''} ${disabled ? 'disabled' : ''}>
                                ${escapeHtml(product.name)} - ${formatCurrency(product.price)} ${disabled ? '(épuisé)' : `(stock: ${stock})`}
                            </option>`;
                        }).join('')}
                </select>
                    <span class="input-group-text bg-light text-muted">${item.product_id ? `(stock: ${productIdToStock.get(Number(item.product_id)) ?? 0})` : ''}</span>
                </div>
                <div class="quotation-suggestions d-none" style="position:absolute; z-index:1050; max-height:240px; overflow:auto; width:28rem; box-shadow:0 2px 6px rgba(0,0,0,.15);"></div>`}
            </td>
            <td>
                <input type="number" class="form-control form-control-sm" value="${item.quantity}" min="1" 
                       onchange="updateItemQuantity(${item.id}, this.value)">
            </td>
            <td>
                <input type="number" class="form-control form-control-sm" value="${item.unit_price}" step="0.01" min="0"
                       onchange="updateItemPrice(${item.id}, this.value)">
            </td>
            <td><strong>${formatCurrency(item.total)}</strong></td>
            <td>
                <button class="btn btn-sm btn-outline-danger" onclick="removeQuotationItem(${item.id})">
                    <i class="bi bi-trash"></i>
                </button>
            </td>
        </tr>
    `).join('');
}

function updateCustomName(itemId, name) {
    const item = quotationItems.find(i => i.id === itemId);
    if (!item) return; item.product_name = name || '';
}

function selectProduct(itemId, productId) {
    const item = quotationItems.find(i => i.id === itemId);
    const product = products.find(p => p.product_id == productId);
    
    if (item && product) {
        item.product_id = product.product_id;
        item.product_name = product.name;
        item.unit_price = product.price;
        // Si le produit a des variantes, la quantité suit le nombre d'IMEI sélectionnés (ici, 1 par défaut à la création du devis)
        const hasVariants = (productVariantsByProductId.get(Number(product.product_id)) || []).length > 0;
        if (hasVariants) {
            item.quantity = 1;
        }
        item.total = item.quantity * item.unit_price;
        
        updateQuotationItemsDisplay();
        calculateTotals();
    }
}

function updateItemQuantity(itemId, quantity) {
    const item = quotationItems.find(i => i.id === itemId);
    if (item) {
        item.quantity = parseInt(quantity) || 1;
        item.total = item.quantity * item.unit_price;
        
        updateQuotationItemsDisplay();
        calculateTotals();
    }
}

function updateItemPrice(itemId, price) {
    const item = quotationItems.find(i => i.id === itemId);
    if (item) {
        item.unit_price = parseFloat(price) || 0;
        item.total = item.quantity * item.unit_price;
        
        updateQuotationItemsDisplay();
        calculateTotals();
    }
}

function removeQuotationItem(itemId) {
    quotationItems = quotationItems.filter(i => i.id !== itemId);
    updateQuotationItemsDisplay();
    calculateTotals();
}

// Calculer les totaux
function calculateTotals() {
    const subtotal = quotationItems.reduce((sum, item) => sum + (Number(item.total)||0), 0);
    // Alignement facture: TVA activable, taux dynamique depuis UI
    const showTax = document.getElementById('showTaxSwitch')?.checked ?? true;
    let taxRatePct = parseFloat((document.getElementById('taxRateInput')?.value || '18').toString().replace(',', '.')) || 18;
    const taxRate = showTax ? Math.max(0, taxRatePct) / 100 : 0;
    const taxAmount = subtotal * taxRate;
    const total = subtotal + taxAmount;

    document.getElementById('subtotal').textContent = formatCurrency(subtotal);
    document.getElementById('taxAmount').textContent = formatCurrency(taxAmount);
    const taxLabel = document.getElementById('taxLabel');
    if (taxLabel) taxLabel.textContent = `TVA (${(taxRate * 100).toFixed(2)}%):`;
    document.getElementById('totalAmount').textContent = formatCurrency(total);
}

// Sauvegarder un devis
async function saveQuotation(status) {
    try {
        const quotationData = {
            quotation_number: document.getElementById('quotationNumber')?.value,
            client_id: parseInt(document.getElementById('clientSelect').value),
            date: document.getElementById('quotationDate').value,
            expiry_date: document.getElementById('validUntil').value || null,
            notes: document.getElementById('quotationNotes').value.trim() || null,
            status: status || 'SENT',
            // Inclure aussi les lignes personnalisées (product_id null)
            items: quotationItems.map(item => ({
                product_id: item.product_id ?? null,
                product_name: item.product_name,
                quantity: item.quantity,
                price: item.unit_price,
                total: item.total
            }))
        };

        if (!quotationData.client_id || !quotationData.date || quotationData.items.length === 0) {
            showError('Veuillez remplir tous les champs obligatoires et ajouter au moins un article');
            return;
        }

        // Totaux côté client -> envoyer au backend
        try {
            const subtotal = quotationItems.reduce((s, it) => s + (Number(it.total)||0), 0);
            const showTax = document.getElementById('showTaxSwitch')?.checked ?? true;
            let taxRatePct = parseFloat((document.getElementById('taxRateInput')?.value || '18').toString().replace(',', '.')) || 18;
            const taxRate = showTax ? Math.max(0, taxRatePct) : 0;
            const taxAmount = subtotal * (taxRate/100);
            const total = subtotal + taxAmount;
            quotationData.subtotal = subtotal;
            quotationData.tax_rate = taxRate;
            quotationData.tax_amount = taxAmount;
            quotationData.total = total;
        } catch(e) {}

        // Ajouter signature (fichier PNG ou canvas)
        try {
            const fileInput = document.getElementById('signatureFile');
            const canvas = document.getElementById('signatureCanvas');
            let signatureDataUrl = null;
            if (fileInput && fileInput.files && fileInput.files[0]) {
                const file = fileInput.files[0];
                signatureDataUrl = await new Promise(res => { const r = new FileReader(); r.onload = () => res(String(r.result||'')); r.readAsDataURL(file); });
            } else if (canvas) {
                const tmp = document.createElement('canvas'); tmp.width = canvas.width; tmp.height = canvas.height;
                if (canvas.toDataURL() !== tmp.toDataURL()) signatureDataUrl = canvas.toDataURL('image/png');
            }
            if (signatureDataUrl) {
                quotationData.notes = (quotationData.notes || '') + `\n\n__SIGNATURE__=${signatureDataUrl}`;
            }
        } catch(e) {}

        const quotationId = document.getElementById('quotationId').value;
        const url = quotationId ? `/api/quotations/${quotationId}` : '/api/quotations/';
        if (quotationId) {
            await axios.put(url, quotationData);
        } else {
            await axios.post(url, quotationData);
        }

        // Fermer le modal
        const modal = bootstrap.Modal.getInstance(document.getElementById('quotationModal'));
        modal.hide();

        // Recharger la liste
        await loadQuotations();
        await loadStats();
        
        showSuccess(quotationId ? 'Devis enregistré avec succès' : 'Devis enregistré avec succès');
        
    } catch (error) {
        console.error('Erreur lors de la sauvegarde:', error);
        showError(error.response?.data?.detail || error.message || 'Erreur lors de la sauvegarde du devis');
    }
}

// Actions sur les devis
function viewQuotation(quotationId) {
    loadQuotationDetail(quotationId).catch(() => showError('Impossible de charger le devis'));
}

function editQuotation(quotationId) {
    preloadQuotationIntoForm(quotationId).catch(() => showError('Impossible de charger le devis pour édition'));
}

function convertToInvoice(quotationId) {
    if (!confirm('Convertir ce devis en facture ?')) return;
    (async () => {
        try {
            // Charger le devis pour préremplir le formulaire facture sans créer la facture tout de suite
            const { data: q } = await axios.get(`/api/quotations/${quotationId}`);
            const prefill = {
                fromQuotation: true,
                quotation_id: q.quotation_id,
                quotation_number: q.quotation_number,
                client_id: q.client_id,
                date: q.date,
                items: (q.items || []).map(it => ({
                    // keep null for custom lines; avoid 0/undefined surprises
                    product_id: (it.product_id === null || it.product_id === undefined) ? null : it.product_id,
                    product_name: it.product_name,
                    is_custom: (it.product_id === null || it.product_id === undefined),
                    quantity: Number(it.quantity || 0),
                    price: Number(it.price || 0),
                    total: Number(it.total || 0)
                }))
            };
            try { sessionStorage.setItem('prefill_invoice_from_quotation', JSON.stringify(prefill)); } catch(e) {}
            window.location.href = '/invoices';
        } catch (err) {
            const msg = err?.response?.data?.detail || err?.message || 'Erreur lors de la conversion';
            showError(msg);
        }
    })();
}

function printQuotation(quotationId) {
    // Impression dans une popup contrôlée (même UX que facture)
    const features = ['width=980','height=800','menubar=0','toolbar=0','location=0','status=0','scrollbars=1','resizable=1'].join(',');
    const w = window.open('', 'quotation_print_popup', features);
    if (!w) { showWarning('La fenêtre pop-up a été bloquée par le navigateur'); return; }
    w.document.write('<!DOCTYPE html><html><head><meta charset="utf-8"><title>Impression devis</title></head><body>Chargement...</body></html>');
    w.document.close();
    // Charger le HTML d'impression via fetch pour l'injecter
    fetch(`/quotations/print/${quotationId}`, { credentials: 'include' })
        .then(res => res.text())
        .then(html => { w.document.open(); w.document.write(html); w.document.close(); })
        .catch(() => { try { w.close(); } catch(e) {} showError('Impossible de charger la page d\'impression'); });
}

async function deleteQuotation(quotationId) {
    if (!confirm('Êtes-vous sûr de vouloir supprimer ce devis ?')) {
        return;
    }

    try {
        await axios.delete(`/api/quotations/${quotationId}`);

        await loadQuotations();
        await loadStats();
        showSuccess('Devis supprimé avec succès');
        
    } catch (error) {
        console.error('Erreur lors de la suppression:', error);
        showError(error.response?.data?.detail || error.message || 'Erreur lors de la suppression du devis');
    }
}
