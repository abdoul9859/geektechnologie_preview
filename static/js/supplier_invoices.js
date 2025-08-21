// Variables globales
let currentInvoiceId = null;
let invoices = [];
let suppliers = [];
let products = [];
let currentPage = 1;
let itemsPerPage = 20;
let currentFilters = {
    search: '',
    supplier_id: null,
    status: null
};

// Initialisation
function initializeSupplierInvoices() {
    loadSuppliers();
    loadProducts();
    loadInvoices();
    loadSummaryStats();
    setupEventListeners();
    setupFormValidation();
    
    // Date par défaut à maintenant
    const now = new Date();
    now.setMinutes(now.getMinutes() - now.getTimezoneOffset());
    document.getElementById('invoiceDate').value = now.toISOString().slice(0, 16);
    document.getElementById('paymentDate').value = now.toISOString().slice(0, 16);
}

// Configuration des écouteurs d'événements
function setupEventListeners() {
    // Recherche en temps réel
    document.getElementById('searchInput').addEventListener('input', debounce(handleSearch, 300));
    
    // Filtres
    document.getElementById('supplierFilter').addEventListener('change', handleFilterChange);
    document.getElementById('statusFilter').addEventListener('change', handleFilterChange);
    
    // Formulaire de facture
    document.getElementById('invoiceForm').addEventListener('submit', handleInvoiceFormSubmit);
    document.getElementById('paymentForm').addEventListener('submit', handlePaymentFormSubmit);
    
    // Calculs automatiques
    document.getElementById('taxRate').addEventListener('input', calculateTotals);
    
    // Modal de paiement
    document.getElementById('addPaymentBtn').addEventListener('click', () => {
        if (currentInvoiceId) {
            openPaymentModal(currentInvoiceId);
        }
    });
}

// Validation des formulaires
function setupFormValidation() {
    const invoiceForm = document.getElementById('invoiceForm');
    const paymentForm = document.getElementById('paymentForm');
    
    invoiceForm.addEventListener('input', function(e) {
        const field = e.target;
        if (field.validity.valid) {
            field.classList.remove('is-invalid');
            field.classList.add('is-valid');
        } else {
            field.classList.remove('is-valid');
            field.classList.add('is-invalid');
        }
    });
    
    paymentForm.addEventListener('input', function(e) {
        const field = e.target;
        if (field.validity.valid) {
            field.classList.remove('is-invalid');
            field.classList.add('is-valid');
        } else {
            field.classList.remove('is-valid');
            field.classList.add('is-invalid');
        }
    });
}

// Charger les fournisseurs
async function loadSuppliers() {
    try {
        const response = await axios.get('/api/suppliers');
        suppliers = response.data.suppliers || response.data;
        
        // Remplir les sélecteurs
        const supplierSelect = document.getElementById('supplierId');
        const supplierFilter = document.getElementById('supplierFilter');
        
        supplierSelect.innerHTML = '<option value="">Sélectionner un fournisseur</option>';
        supplierFilter.innerHTML = '<option value="">Tous les fournisseurs</option>';
        
        suppliers.forEach(supplier => {
            const option = new Option(supplier.name, supplier.supplier_id);
            const filterOption = new Option(supplier.name, supplier.supplier_id);
            
            supplierSelect.appendChild(option.cloneNode(true));
            supplierFilter.appendChild(filterOption);
        });
    } catch (error) {
        console.error('Erreur lors du chargement des fournisseurs:', error);
        showError('Erreur lors du chargement des fournisseurs');
    }
}

// Charger les produits
async function loadProducts() {
    try {
        const response = await axios.get('/api/products');
        products = response.data.products || response.data;
    } catch (error) {
        console.error('Erreur lors du chargement des produits:', error);
        products = [];
    }
}

// Charger les factures
async function loadInvoices() {
    try {
        showLoading();
        
        // Construire les paramètres de manière plus simple
        const queryParams = {
            skip: (currentPage - 1) * itemsPerPage,
            limit: itemsPerPage
        };
        
        // Ajouter les filtres seulement s'ils ont une valeur valide
        if (currentFilters.search && currentFilters.search.trim()) {
            queryParams.search = currentFilters.search.trim();
        }
        if (currentFilters.supplier_id && currentFilters.supplier_id !== 'null' && currentFilters.supplier_id !== null) {
            queryParams.supplier_id = currentFilters.supplier_id;
        }
        if (currentFilters.status && currentFilters.status !== 'null' && currentFilters.status !== null) {
            queryParams.status = currentFilters.status;
        }
        
        const response = await axios.get('/api/supplier-invoices/', { params: queryParams });
        invoices = response.data.invoices || [];
        
        displayInvoices();
        updatePagination(response.data.total || 0);
        hideLoading();
        
    } catch (error) {
        console.error('Erreur lors du chargement des factures:', error);
        hideLoading();
        if (error.response && error.response.status === 401) {
            showError('Vous devez être connecté pour accéder à cette page');
            // Redirection gérée automatiquement par http.js
        } else {
            showError('Erreur lors du chargement des factures: ' + (error.response?.data?.detail || error.message));
        }
    }
}

// Charger les statistiques
async function loadSummaryStats() {
    try {
        const response = await axios.get('/api/supplier-invoices/stats/summary');
        const stats = response.data;
        
        document.getElementById('totalInvoices').textContent = stats.total_invoices;
        document.getElementById('pendingInvoices').textContent = stats.pending_invoices;
        document.getElementById('totalAmount').textContent = formatCurrency(stats.total_amount);
        document.getElementById('remainingAmount').textContent = formatCurrency(stats.remaining_amount);
        
    } catch (error) {
        console.error('Erreur lors du chargement des statistiques:', error);
    }
}

// Afficher les factures
function displayInvoices() {
    const tbody = document.getElementById('invoicesTableBody');
    
    if (invoices.length === 0) {
        tbody.innerHTML = `
            <tr>
                <td colspan="9" class="text-center py-4">
                    <i class="bi bi-inbox text-muted" style="font-size: 2rem;"></i>
                    <p class="text-muted mt-2">Aucune facture trouvée</p>
                </td>
            </tr>
        `;
        return;
    }
    
    tbody.innerHTML = invoices.map(invoice => `
        <tr>
            <td>
                <strong>${escapeHtml(invoice.invoice_number)}</strong>
            </td>
            <td>${escapeHtml(invoice.supplier_name || 'N/A')}</td>
            <td>${formatDateTime(invoice.invoice_date)}</td>
            <td>${invoice.due_date ? formatDateTime(invoice.due_date) : '-'}</td>
            <td class="amount-display">${formatCurrency(invoice.total)}</td>
            <td class="amount-display">${formatCurrency(invoice.paid_amount)}</td>
            <td class="amount-display">${formatCurrency(invoice.remaining_amount)}</td>
            <td>
                <span class="badge ${getStatusBadgeClass(invoice.status)}">
                    ${getStatusLabel(invoice.status)}
                </span>
            </td>
            <td>
                <div class="btn-group btn-group-sm">
                    <button class="btn btn-outline-info" onclick="viewInvoice(${invoice.invoice_id})" title="Voir détails">
                        <i class="bi bi-eye"></i>
                    </button>
                    <button class="btn btn-outline-primary" onclick="editInvoice(${invoice.invoice_id})" title="Modifier">
                        <i class="bi bi-pencil"></i>
                    </button>
                    ${invoice.remaining_amount > 0 ? `
                        <button class="btn btn-outline-success" onclick="openPaymentModal(${invoice.invoice_id})" title="Ajouter paiement">
                            <i class="bi bi-credit-card"></i>
                        </button>
                    ` : ''}
                    <button class="btn btn-outline-danger" onclick="deleteInvoice(${invoice.invoice_id})" title="Supprimer">
                        <i class="bi bi-trash"></i>
                    </button>
                </div>
            </td>
        </tr>
    `).join('');
}

// Ouvrir la modal de facture
function openInvoiceModal(invoiceId = null) {
    currentInvoiceId = invoiceId;
    const modal = new bootstrap.Modal(document.getElementById('invoiceModal'));
    const title = document.getElementById('invoiceModalLabel');
    const saveBtn = document.getElementById('saveButtonText');
    
    if (invoiceId) {
        title.textContent = 'Modifier la facture';
        saveBtn.textContent = 'Mettre à jour';
        loadInvoiceForEdit(invoiceId);
    } else {
        title.textContent = 'Nouvelle facture fournisseur';
        saveBtn.textContent = 'Enregistrer';
        resetInvoiceForm();
        addInvoiceItem(); // Ajouter un élément par défaut
    }
    
    modal.show();
}

// Réinitialiser le formulaire de facture
function resetInvoiceForm() {
    document.getElementById('invoiceForm').reset();
    document.getElementById('invoiceItems').innerHTML = '';
    
    // Remettre les valeurs par défaut
    document.getElementById('taxRate').value = '18';
    const now = new Date();
    now.setMinutes(now.getMinutes() - now.getTimezoneOffset());
    document.getElementById('invoiceDate').value = now.toISOString().slice(0, 16);
    
    calculateTotals();
    
    // Supprimer les classes de validation
    document.querySelectorAll('.form-control, .form-select').forEach(field => {
        field.classList.remove('is-valid', 'is-invalid');
    });
}

// Charger une facture pour édition
async function loadInvoiceForEdit(invoiceId) {
    try {
        const response = await axios.get(`/api/supplier-invoices/${invoiceId}`);
        const invoice = response.data;
        
        // Remplir le formulaire
        document.getElementById('supplierId').value = invoice.supplier_id;
        document.getElementById('invoiceNumber').value = invoice.invoice_number;
        document.getElementById('invoiceDate').value = invoice.invoice_date.slice(0, 16);
        document.getElementById('dueDate').value = invoice.due_date ? invoice.due_date.slice(0, 16) : '';
        document.getElementById('paymentMethod').value = invoice.payment_method || '';
        document.getElementById('taxRate').value = invoice.tax_rate;
        document.getElementById('notes').value = invoice.notes || '';
        
        // Charger les éléments
        const itemsContainer = document.getElementById('invoiceItems');
        itemsContainer.innerHTML = '';
        
        invoice.items.forEach(item => {
            addInvoiceItem(item);
        });
        
        calculateTotals();
        
    } catch (error) {
        console.error('Erreur lors du chargement de la facture:', error);
        showError('Erreur lors du chargement de la facture');
    }
}

// Ajouter un élément de facture
function addInvoiceItem(itemData = null) {
    const container = document.getElementById('invoiceItems');
    const itemIndex = container.children.length;
    
    const row = document.createElement('tr');
    row.innerHTML = `
        <td>
            <select class="form-select form-select-sm product-select" name="items[${itemIndex}][product_id]" onchange="handleProductChange(this, ${itemIndex})">
                <option value="">Produit personnalisé</option>
                ${products.map(product => 
                    `<option value="${product.product_id}" ${itemData && itemData.product_id === product.product_id ? 'selected' : ''}>
                        ${escapeHtml(product.name)} (${formatCurrency(product.purchase_price)})
                    </option>`
                ).join('')}
            </select>
            <input type="text" class="form-control form-control-sm mt-1" name="items[${itemIndex}][product_name]" 
                   placeholder="Nom du produit" value="${itemData ? escapeHtml(itemData.product_name) : ''}" required>
        </td>
        <td>
            <input type="number" class="form-control form-control-sm quantity-input" name="items[${itemIndex}][quantity]" 
                   min="1" step="1" value="${itemData ? itemData.quantity : 1}" required onchange="calculateItemTotal(${itemIndex})">
        </td>
        <td>
            <input type="number" class="form-control form-control-sm unit-price-input" name="items[${itemIndex}][unit_price]" 
                   min="0" step="0.01" value="${itemData ? itemData.unit_price : 0}" required onchange="calculateItemTotal(${itemIndex})">
        </td>
        <td>
            <input type="number" class="form-control form-control-sm total-input" name="items[${itemIndex}][total]" 
                   value="${itemData ? itemData.total : 0}" readonly>
        </td>
        <td>
            <button type="button" class="btn btn-sm btn-outline-danger" onclick="removeInvoiceItem(this)">
                <i class="bi bi-trash"></i>
            </button>
        </td>
    `;
    
    container.appendChild(row);
    
    if (itemData) {
        calculateItemTotal(itemIndex);
    }
    
    calculateTotals();
}

// Supprimer un élément de facture
function removeInvoiceItem(button) {
    button.closest('tr').remove();
    calculateTotals();
}

// Gérer le changement de produit
function handleProductChange(select, itemIndex) {
    const productId = parseInt(select.value);
    const product = products.find(p => p.product_id === productId);
    
    if (product) {
        const row = select.closest('tr');
        row.querySelector('input[name*="[product_name]"]').value = product.name;
        row.querySelector('input[name*="[unit_price]"]').value = product.purchase_price;
        calculateItemTotal(itemIndex);
    }
}

// Calculer le total d'un élément
function calculateItemTotal(itemIndex) {
    const container = document.getElementById('invoiceItems');
    const row = container.children[itemIndex];
    
    const quantity = parseFloat(row.querySelector('.quantity-input').value) || 0;
    const unitPrice = parseFloat(row.querySelector('.unit-price-input').value) || 0;
    const total = quantity * unitPrice;
    
    row.querySelector('.total-input').value = total.toFixed(2);
    
    calculateTotals();
}

// Calculer les totaux
function calculateTotals() {
    const container = document.getElementById('invoiceItems');
    const taxRate = parseFloat(document.getElementById('taxRate').value) || 0;
    
    let subtotal = 0;
    
    for (const row of container.children) {
        const total = parseFloat(row.querySelector('.total-input').value) || 0;
        subtotal += total;
    }
    
    const taxAmount = (subtotal * taxRate) / 100;
    const total = subtotal + taxAmount;
    
    document.getElementById('subtotalDisplay').textContent = formatCurrency(subtotal);
    document.getElementById('taxDisplay').textContent = formatCurrency(taxAmount);
    document.getElementById('totalDisplay').textContent = formatCurrency(total);
}

// Gérer la soumission du formulaire de facture
async function handleInvoiceFormSubmit(e) {
    e.preventDefault();
    
    if (!validateInvoiceForm()) {
        return;
    }
    
    try {
        const formData = collectInvoiceFormData();
        
        if (currentInvoiceId) {
            await axios.put(`/api/supplier-invoices/${currentInvoiceId}`, formData);
            showSuccess('Facture mise à jour avec succès');
        } else {
            await axios.post('/api/supplier-invoices', formData);
            showSuccess('Facture créée avec succès');
        }
        
        const modal = bootstrap.Modal.getInstance(document.getElementById('invoiceModal'));
        modal.hide();
        
        loadInvoices();
        loadSummaryStats();
        
    } catch (error) {
        console.error('Erreur lors de la sauvegarde:', error);
        showError(error.response?.data?.detail || 'Erreur lors de la sauvegarde');
    }
}

// Valider le formulaire de facture
function validateInvoiceForm() {
    const requiredFields = [
        'supplierId', 'invoiceNumber', 'invoiceDate'
    ];
    
    let isValid = true;
    
    requiredFields.forEach(fieldId => {
        const field = document.getElementById(fieldId);
        if (!field.value.trim()) {
            field.classList.add('is-invalid');
            isValid = false;
        } else {
            field.classList.remove('is-invalid');
        }
    });
    
    // Vérifier qu'il y a au moins un élément
    const items = document.getElementById('invoiceItems').children;
    if (items.length === 0) {
        showError('Veuillez ajouter au moins un élément à la facture');
        return false;
    }
    
    // Valider les éléments
    for (const row of items) {
        const productName = row.querySelector('input[name*="[product_name]"]');
        const quantity = row.querySelector('.quantity-input');
        const unitPrice = row.querySelector('.unit-price-input');
        
        if (!productName.value.trim() || !quantity.value || !unitPrice.value) {
            showError('Tous les éléments doivent être correctement remplis');
            return false;
        }
    }
    
    return isValid;
}

// Collecter les données du formulaire
function collectInvoiceFormData() {
    const container = document.getElementById('invoiceItems');
    const items = [];
    
    for (const row of container.children) {
        const productSelect = row.querySelector('.product-select');
        const productName = row.querySelector('input[name*="[product_name]"]');
        const quantity = parseInt(row.querySelector('.quantity-input').value);
        const unitPrice = parseFloat(row.querySelector('.unit-price-input').value);
        const total = parseFloat(row.querySelector('.total-input').value);
        
        items.push({
            product_id: productSelect.value ? parseInt(productSelect.value) : null,
            product_name: productName.value,
            quantity: quantity,
            unit_price: unitPrice,
            total: total
        });
    }
    
    const subtotal = items.reduce((sum, item) => sum + item.total, 0);
    const taxRate = parseFloat(document.getElementById('taxRate').value) || 0;
    const taxAmount = (subtotal * taxRate) / 100;
    const total = subtotal + taxAmount;
    
    return {
        supplier_id: parseInt(document.getElementById('supplierId').value),
        invoice_number: document.getElementById('invoiceNumber').value,
        invoice_date: document.getElementById('invoiceDate').value,
        due_date: document.getElementById('dueDate').value || null,
        payment_method: document.getElementById('paymentMethod').value || null,
        subtotal: subtotal,
        tax_rate: taxRate,
        tax_amount: taxAmount,
        total: total,
        notes: document.getElementById('notes').value || null,
        items: items
    };
}

// Voir les détails d'une facture
async function viewInvoice(invoiceId) {
    try {
        const response = await axios.get(`/api/supplier-invoices/${invoiceId}`);
        const invoice = response.data;
        
        currentInvoiceId = invoiceId;
        
        const content = document.getElementById('invoiceDetailsContent');
        content.innerHTML = `
            <div class="row">
                <div class="col-md-6">
                    <h6>Informations générales</h6>
                    <p><strong>N° Facture :</strong> ${escapeHtml(invoice.invoice_number)}</p>
                    <p><strong>Fournisseur :</strong> ${escapeHtml(invoice.supplier_name)}</p>
                    <p><strong>Date facture :</strong> ${formatDateTime(invoice.invoice_date)}</p>
                    <p><strong>Date échéance :</strong> ${invoice.due_date ? formatDateTime(invoice.due_date) : 'Non définie'}</p>
                    <p><strong>Statut :</strong> 
                        <span class="badge ${getStatusBadgeClass(invoice.status)}">
                            ${getStatusLabel(invoice.status)}
                        </span>
                    </p>
                </div>
                <div class="col-md-6">
                    <h6>Montants</h6>
                    <p><strong>Sous-total :</strong> ${formatCurrency(invoice.subtotal)}</p>
                    <p><strong>TVA (${invoice.tax_rate}%) :</strong> ${formatCurrency(invoice.tax_amount)}</p>
                    <p><strong>Total :</strong> ${formatCurrency(invoice.total)}</p>
                    <p><strong>Payé :</strong> ${formatCurrency(invoice.paid_amount)}</p>
                    <p><strong>Restant :</strong> ${formatCurrency(invoice.remaining_amount)}</p>
                </div>
            </div>
            
            ${invoice.notes ? `
                <div class="row mt-3">
                    <div class="col-12">
                        <h6>Notes</h6>
                        <p>${escapeHtml(invoice.notes)}</p>
                    </div>
                </div>
            ` : ''}
            
            <div class="row mt-3">
                <div class="col-12">
                    <h6>Éléments de la facture</h6>
                    <div class="table-responsive">
                        <table class="table table-sm">
                            <thead class="table-light">
                                <tr>
                                    <th>Produit</th>
                                    <th>Quantité</th>
                                    <th>Prix unitaire</th>
                                    <th>Total</th>
                                </tr>
                            </thead>
                            <tbody>
                                ${invoice.items.map(item => `
                                    <tr>
                                        <td>${escapeHtml(item.product_name)}</td>
                                        <td>${item.quantity}</td>
                                        <td>${formatCurrency(item.unit_price)}</td>
                                        <td>${formatCurrency(item.total)}</td>
                                    </tr>
                                `).join('')}
                            </tbody>
                        </table>
                    </div>
                </div>
            </div>
        `;
        
        // Afficher/masquer le bouton de paiement
        const addPaymentBtn = document.getElementById('addPaymentBtn');
        addPaymentBtn.style.display = invoice.remaining_amount > 0 ? 'inline-block' : 'none';
        
        const modal = new bootstrap.Modal(document.getElementById('invoiceDetailsModal'));
        modal.show();
        
    } catch (error) {
        console.error('Erreur lors du chargement des détails:', error);
        showError('Erreur lors du chargement des détails');
    }
}

// Modifier une facture
function editInvoice(invoiceId) {
    openInvoiceModal(invoiceId);
}

// Supprimer une facture
function deleteInvoice(invoiceId) {
    currentInvoiceId = invoiceId;
    const modal = new bootstrap.Modal(document.getElementById('deleteModal'));
    modal.show();
}

// Confirmer la suppression
async function confirmDelete() {
    if (!currentInvoiceId) return;
    
    try {
        await axios.delete(`/api/supplier-invoices/${currentInvoiceId}`);
        
        const modal = bootstrap.Modal.getInstance(document.getElementById('deleteModal'));
        modal.hide();
        
        showSuccess('Facture supprimée avec succès');
        loadInvoices();
        loadSummaryStats();
        
        currentInvoiceId = null;
        
    } catch (error) {
        console.error('Erreur lors de la suppression:', error);
        showError(error.response?.data?.detail || 'Erreur lors de la suppression');
    }
}

// Ouvrir la modal de paiement
async function openPaymentModal(invoiceId) {
    try {
        const response = await axios.get(`/api/supplier-invoices/${invoiceId}`);
        const invoice = response.data;
        
        currentInvoiceId = invoiceId;
        
        // Remplir les informations de la facture
        const infoDiv = document.getElementById('paymentInvoiceInfo');
        infoDiv.innerHTML = `
            <div class="d-flex justify-content-between">
                <span><strong>Facture :</strong> ${escapeHtml(invoice.invoice_number)}</span>
                <span><strong>Fournisseur :</strong> ${escapeHtml(invoice.supplier_name)}</span>
            </div>
            <div class="d-flex justify-content-between mt-2">
                <span><strong>Total facture :</strong> ${formatCurrency(invoice.total)}</span>
                <span><strong>Déjà payé :</strong> ${formatCurrency(invoice.paid_amount)}</span>
            </div>
            <div class="d-flex justify-content-between mt-2">
                <span><strong>Restant à payer :</strong></span>
                <span class="text-danger"><strong>${formatCurrency(invoice.remaining_amount)}</strong></span>
            </div>
        `;
        
        // Préremplir le montant avec le restant dû
        document.getElementById('paymentAmount').value = invoice.remaining_amount;
        document.getElementById('paymentAmount').max = invoice.remaining_amount;
        
        // Réinitialiser le formulaire
        document.getElementById('paymentMethodSelect').value = '';
        document.getElementById('paymentReference').value = '';
        document.getElementById('paymentNotes').value = '';
        
        const modal = new bootstrap.Modal(document.getElementById('paymentModal'));
        modal.show();
        
    } catch (error) {
        console.error('Erreur lors de l\'ouverture de la modal de paiement:', error);
        showError('Erreur lors de l\'ouverture de la modal de paiement');
    }
}

// Gérer la soumission du formulaire de paiement
async function handlePaymentFormSubmit(e) {
    e.preventDefault();
    
    const amount = parseFloat(document.getElementById('paymentAmount').value);
    const paymentDate = document.getElementById('paymentDate').value;
    const paymentMethod = document.getElementById('paymentMethodSelect').value;
    const reference = document.getElementById('paymentReference').value;
    const notes = document.getElementById('paymentNotes').value;
    
    if (!amount || amount <= 0) {
        showError('Veuillez saisir un montant valide');
        return;
    }
    
    if (!paymentDate) {
        showError('Veuillez saisir une date de paiement');
        return;
    }
    
    if (!paymentMethod) {
        showError('Veuillez sélectionner une méthode de paiement');
        return;
    }
    
    try {
        const paymentData = {
            amount: amount,
            payment_date: paymentDate,
            payment_method: paymentMethod,
            reference: reference || null,
            notes: notes || null
        };
        
        await axios.post(`/api/supplier-invoices/${currentInvoiceId}/payments`, paymentData);
        
        const modal = bootstrap.Modal.getInstance(document.getElementById('paymentModal'));
        modal.hide();
        
        showSuccess('Paiement enregistré avec succès');
        
        // Recharger les données
        loadInvoices();
        loadSummaryStats();
        
        // Si la modal de détails est ouverte, la rafraîchir
        const detailsModal = bootstrap.Modal.getInstance(document.getElementById('invoiceDetailsModal'));
        if (detailsModal) {
            viewInvoice(currentInvoiceId);
        }
        
    } catch (error) {
        console.error('Erreur lors de l\'enregistrement du paiement:', error);
        showError(error.response?.data?.detail || 'Erreur lors de l\'enregistrement du paiement');
    }
}

// Gestion des filtres et recherche
function handleSearch() {
    currentFilters.search = document.getElementById('searchInput').value;
    currentPage = 1;
    loadInvoices();
}

function handleFilterChange() {
    currentFilters.supplier_id = document.getElementById('supplierFilter').value || null;
    currentFilters.status = document.getElementById('statusFilter').value || null;
    currentPage = 1;
    loadInvoices();
}

function clearFilters() {
    document.getElementById('searchInput').value = '';
    document.getElementById('supplierFilter').value = '';
    document.getElementById('statusFilter').value = '';
    
    currentFilters = { search: '', supplier_id: null, status: null };
    currentPage = 1;
    loadInvoices();
}

// Pagination
function updatePagination(total) {
    const totalPages = Math.ceil(total / itemsPerPage);
    const paginationContainer = document.getElementById('pagination');
    
    paginationContainer.innerHTML = '';
    
    if (totalPages <= 1) return;
    
    // Bouton précédent
    const prevLi = document.createElement('li');
    prevLi.className = `page-item ${currentPage === 1 ? 'disabled' : ''}`;
    prevLi.innerHTML = `<a class="page-link" href="#" onclick="changePage(${currentPage - 1})">Précédent</a>`;
    paginationContainer.appendChild(prevLi);
    
    // Pages
    const startPage = Math.max(1, currentPage - 2);
    const endPage = Math.min(totalPages, currentPage + 2);
    
    for (let i = startPage; i <= endPage; i++) {
        const li = document.createElement('li');
        li.className = `page-item ${i === currentPage ? 'active' : ''}`;
        li.innerHTML = `<a class="page-link" href="#" onclick="changePage(${i})">${i}</a>`;
        paginationContainer.appendChild(li);
    }
    
    // Bouton suivant
    const nextLi = document.createElement('li');
    nextLi.className = `page-item ${currentPage === totalPages ? 'disabled' : ''}`;
    nextLi.innerHTML = `<a class="page-link" href="#" onclick="changePage(${currentPage + 1})">Suivant</a>`;
    paginationContainer.appendChild(nextLi);
}

function changePage(page) {
    if (page < 1) return;
    currentPage = page;
    loadInvoices();
}

// Fonctions utilitaires
function getStatusBadgeClass(status) {
    const classes = {
        pending: 'bg-warning text-dark',
        partial: 'bg-info',
        paid: 'bg-success',
        overdue: 'bg-danger'
    };
    return classes[status] || 'bg-secondary';
}

function getStatusLabel(status) {
    const labels = {
        pending: 'En attente',
        partial: 'Partiellement payé',
        paid: 'Payé',
        overdue: 'En retard'
    };
    return labels[status] || status;
}

function formatCurrency(amount) {
    return new Intl.NumberFormat('fr-FR', {
        style: 'currency',
        currency: 'XOF',
        minimumFractionDigits: 0,
        maximumFractionDigits: 0
    }).format(Math.round(amount || 0));
}

function formatDateTime(dateString) {
    if (!dateString) return '-';
    const date = new Date(dateString);
    return date.toLocaleDateString('fr-FR', {
        year: 'numeric',
        month: 'short',
        day: 'numeric',
        hour: '2-digit',
        minute: '2-digit'
    });
}

function escapeHtml(text) {
    const map = {
        '&': '&amp;',
        '<': '&lt;',
        '>': '&gt;',
        '"': '&quot;',
        "'": '&#039;'
    };
    return String(text || '').replace(/[&<>"']/g, m => map[m]);
}

function showLoading() {
    document.getElementById('invoicesTableBody').innerHTML = `
        <tr>
            <td colspan="9" class="text-center py-4">
                <div class="spinner-border" role="status">
                    <span class="visually-hidden">Chargement...</span>
                </div>
            </td>
        </tr>
    `;
}

function hideLoading() {
    // Le loading sera masqué par displayInvoices()
}

function showError(message) {
    // Utiliser le système de notification existant
    if (typeof showNotification === 'function') {
        showNotification(message, 'error');
    } else {
        alert('Erreur: ' + message);
    }
}

function showSuccess(message) {
    // Utiliser le système de notification existant
    if (typeof showNotification === 'function') {
        showNotification(message, 'success');
    } else {
        alert('Succès: ' + message);
    }
}

function debounce(func, wait) {
    let timeout;
    return function executedFunction(...args) {
        const later = () => {
            clearTimeout(timeout);
            func(...args);
        };
        clearTimeout(timeout);
        timeout = setTimeout(later, wait);
    };
}
