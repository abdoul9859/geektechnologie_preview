// Gestion des dettes
let debts = [];
let clients = [];
let suppliers = [];
let currentDebtId = null;
let currentPage = 1;
const itemsPerPage = 15;

// Initialisation (cookie-based auth readiness)
document.addEventListener('DOMContentLoaded', function() {
    const ready = () => {
        const hasAuthManager = !!window.authManager;
        const hasUser = !!(hasAuthManager && window.authManager.userData && Object.keys(window.authManager.userData).length);
        return hasAuthManager && (window.authManager.isAuthenticatedSync() || hasUser);
    };

    const boot = () => {
        loadDebts();
        loadClients();
        loadSuppliers();
        setupEventListeners();
        setDefaultDate();
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

// Configuration des écouteurs d'événements
function setupEventListeners() {
    // Filtres
    document.getElementById('searchInput').addEventListener('input', debounce(filterDebts, 300));
    document.getElementById('typeFilter').addEventListener('change', filterDebts);
    document.getElementById('statusFilter').addEventListener('change', filterDebts);
    document.getElementById('dateFromFilter').addEventListener('change', filterDebts);
    document.getElementById('dateToFilter').addEventListener('change', filterDebts);

    // Type de dette change
    document.getElementById('debtType').addEventListener('change', handleDebtTypeChange);

    // Modal de suppression
    const confirmDeleteBtn = document.getElementById('confirmDeleteBtn');
    if (confirmDeleteBtn) {
        confirmDeleteBtn.addEventListener('click', confirmDelete);
    }

    // Formulaires
    const debtForm = document.getElementById('debtForm');
    if (debtForm) {
        debtForm.addEventListener('submit', handleDebtFormSubmit);
    }

    const paymentForm = document.getElementById('paymentForm');
    if (paymentForm) {
        paymentForm.addEventListener('submit', handlePaymentFormSubmit);
    }

    // Enforcer des montants entiers dans les champs numériques pertinents
    const amountInput = document.getElementById('amount');
    if (amountInput) enforceIntegerInput(amountInput);
    const paymentAmountInput = document.getElementById('paymentAmount');
    if (paymentAmountInput) enforceIntegerInput(paymentAmountInput);
}

// Définir les dates par défaut
function setDefaultDate() {
    const today = new Date().toISOString().split('T')[0];
    document.getElementById('debtDate').value = today;
    document.getElementById('paymentDate').value = today;
}

// Charger les dettes
async function loadDebts() {
    try {
        showLoading();
        const response = await safeLoadData(
            () => axios.get('/api/debts'),
            {
                timeout: 8000,
                fallbackData: [],
                errorMessage: 'Erreur lors du chargement des dettes'
            }
        );
        const payload = response?.data ?? [];
        if (Array.isArray(payload)) {
            debts = payload;
        } else if (payload && Array.isArray(payload.debts)) {
            debts = payload.debts;
        } else if (payload && Array.isArray(payload.data)) {
            debts = payload.data;
        } else {
            debts = [];
        }

        displayDebts();
        updateStatistics();
    } catch (error) {
        console.error('Erreur:', error);
        showError(error.response?.data?.detail || 'Erreur lors du chargement des dettes');
        // Afficher un état vide pour éviter le spinner infini
        const tbody = document.getElementById('debtsTableBody');
        if (tbody) {
            tbody.innerHTML = `
                <tr>
                    <td colspan="10" class="text-center py-4">
                        <i class="bi bi-credit-card display-4 text-muted"></i>
                        <p class="text-muted mt-2 mb-0">Aucune dette trouvée</p>
                    </td>
                </tr>
            `;
        }
    }
}

// Charger les clients
async function loadClients() {
    try {
        const response = await safeLoadData(
            () => axios.get('/api/clients'),
            { timeout: 8000, fallbackData: [], errorMessage: 'Erreur lors du chargement des clients' }
        );
        const data = response?.data ?? [];
        clients = Array.isArray(data) ? data : (data.items || data.clients || []);
    } catch (error) {
        console.error('Erreur lors du chargement des clients:', error);
    }
}

// Charger les fournisseurs
async function loadSuppliers() {
    try {
        const response = await safeLoadData(
            () => axios.get('/api/suppliers/'),
            { timeout: 8000, fallbackData: [], errorMessage: 'Erreur lors du chargement des fournisseurs' }
        );
        const data = response?.data ?? [];
        suppliers = Array.isArray(data) ? data : (data.items || data.suppliers || []);
    } catch (error) {
        console.error('Erreur lors du chargement des fournisseurs:', error);
    }
}

// Afficher les dettes
function displayDebts() {
    const filteredDebts = getFilteredDebts();
    const startIndex = (currentPage - 1) * itemsPerPage;
    const endIndex = startIndex + itemsPerPage;
    const paginatedDebts = filteredDebts.slice(startIndex, endIndex);

    const tbody = document.getElementById('debtsTableBody');
    tbody.innerHTML = '';

    if (paginatedDebts.length === 0) {
        tbody.innerHTML = `
            <tr>
                <td colspan="10" class="text-center py-4">
                    <i class="bi bi-credit-card display-4 text-muted"></i>
                    <p class="text-muted mt-2 mb-0">Aucune dette trouvée</p>
                </td>
            </tr>
        `;
    } else {
        paginatedDebts.forEach(debt => {
            const row = createDebtRow(debt);
            tbody.appendChild(row);
        });
    }

    updateResultsCount(filteredDebts.length);
    updatePagination(filteredDebts.length);
}

// Créer une ligne de dette
function createDebtRow(debt) {
    const row = document.createElement('tr');
    const entityName = getEntityName(debt);
    const remaining = (debt.amount || 0) - (debt.paid_amount || 0);
    
    row.innerHTML = `
        <td>
            <strong>${escapeHtml(debt.reference)}</strong>
        </td>
        <td>
            <span class="badge ${getTypeBadgeClass(debt.type)}">
                <i class="bi ${getTypeIcon(debt.type)} me-1"></i>
                ${getTypeLabel(debt.type)}
            </span>
        </td>
        <td>${escapeHtml(entityName)}</td>
        <td>${formatDate(debt.date)}</td>
        <td>
            ${debt.due_date ? formatDate(debt.due_date) : '-'}
            ${debt.due_date && isOverdue(debt.due_date, debt.status) ? 
                '<span class="badge bg-danger ms-1">En retard</span>' : ''
            }
        </td>
        <td>
            <strong>${formatCurrency(debt.amount)}</strong>
        </td>
        <td>
            <span class="text-success">${formatCurrency(debt.paid_amount || 0)}</span>
        </td>
        <td>
            <span class="text-${remaining > 0 ? 'danger' : 'success'}">${formatCurrency(remaining)}</span>
        </td>
        <td>
            <span class="badge ${getStatusBadgeClass(debt.status)}">
                ${getStatusLabel(debt.status)}
            </span>
        </td>
        <td>
            <div class="btn-group btn-group-sm">
                <button class="btn btn-outline-primary" onclick="viewDebt(${debt.id})" title="Voir la facture">
                    <i class="bi bi-receipt"></i>
                </button>
            </div>
        </td>
    `;

    return row;
}

// Obtenir les dettes filtrées
function getFilteredDebts() {
    // Vérifier si debts est un tableau valide
    if (!Array.isArray(debts)) {
        console.error('La variable debts n\'est pas un tableau:', debts);
        return [];
    }
    
    let filtered = [...debts];

    const searchTerm = document.getElementById('searchInput').value.toLowerCase();
    const typeFilter = document.getElementById('typeFilter').value;
    const statusFilter = document.getElementById('statusFilter').value;
    const dateFromFilter = document.getElementById('dateFromFilter').value;
    const dateToFilter = document.getElementById('dateToFilter').value;

    if (searchTerm) {
        filtered = filtered.filter(debt => 
            debt.reference.toLowerCase().includes(searchTerm) ||
            debt.description?.toLowerCase().includes(searchTerm) ||
            getEntityName(debt).toLowerCase().includes(searchTerm)
        );
    }

    if (typeFilter) {
        filtered = filtered.filter(debt => debt.type === typeFilter);
    }

    if (statusFilter) {
        filtered = filtered.filter(debt => debt.status === statusFilter);
    }

    if (dateFromFilter) {
        filtered = filtered.filter(debt => debt.date >= dateFromFilter);
    }

    if (dateToFilter) {
        filtered = filtered.filter(debt => debt.date <= dateToFilter);
    }

    // Trier par date (plus récent en premier)
    filtered.sort((a, b) => new Date(b.date) - new Date(a.date));

    return filtered;
}

// Filtrer les dettes
function filterDebts() {
    currentPage = 1;
    displayDebts();
}

// Effacer les filtres
function clearFilters() {
    document.getElementById('searchInput').value = '';
    document.getElementById('typeFilter').value = '';
    document.getElementById('statusFilter').value = '';
    document.getElementById('dateFromFilter').value = '';
    document.getElementById('dateToFilter').value = '';
    filterDebts();
}

// Mettre à jour les statistiques
function updateStatistics() {
    const clientDebts = debts.filter(d => d.type === 'client').reduce((sum, d) => sum + (d.amount || 0), 0);
    const supplierDebts = debts.filter(d => d.type === 'supplier').reduce((sum, d) => sum + (d.amount || 0), 0);
    const totalPaid = debts.reduce((sum, d) => sum + (d.paid_amount || 0), 0);
    const totalRemaining = debts.reduce((sum, d) => sum + ((d.amount || 0) - (d.paid_amount || 0)), 0);

    document.getElementById('totalClientDebts').textContent = formatCurrency(clientDebts);
    document.getElementById('totalSupplierDebts').textContent = formatCurrency(supplierDebts);
    document.getElementById('totalPaidDebts').textContent = formatCurrency(totalPaid);
    document.getElementById('totalRemainingDebts').textContent = formatCurrency(totalRemaining);
}

// Mettre à jour le compteur de résultats
function updateResultsCount(count) {
    const resultsCount = document.getElementById('resultsCount');
    if (resultsCount) {
        resultsCount.textContent = `${count} dette${count !== 1 ? 's' : ''}`;
    }
}

// Créer une nouvelle dette
function createDebt() {
    // Création autorisée uniquement pour les dettes fournisseur
    resetDebtForm();
    document.getElementById('debtType').value = 'supplier';
    handleDebtTypeChange();
    const modal = new bootstrap.Modal(document.getElementById('debtModal'));
    modal.show();
}

// Réinitialiser le formulaire de dette
function resetDebtForm() {
    const form = document.getElementById('debtForm');
    form.reset();
    
    document.getElementById('debtId').value = '';
    setDefaultDate();
    
    const modalTitle = document.getElementById('debtModalTitle');
    modalTitle.innerHTML = '<i class="bi bi-plus-circle me-2"></i>Nouvelle Dette';
    
    currentDebtId = null;
    updateEntitySelect();
}

// Gérer le changement de type de dette
function handleDebtTypeChange() {
    updateEntitySelect();
}

// Mettre à jour le sélecteur d'entité
function updateEntitySelect() {
    const debtType = document.getElementById('debtType').value;
    const entitySelect = document.getElementById('entitySelect');
    const entityLabel = document.getElementById('entityLabel');
    
    entitySelect.innerHTML = '<option value="">Sélectionner...</option>';
    
    if (debtType === 'client') {
        entityLabel.textContent = 'Client';
        clients.forEach(client => {
            const option = new Option(client.name, client.id);
            entitySelect.appendChild(option);
        });
    } else if (debtType === 'supplier') {
        entityLabel.textContent = 'Fournisseur';
        suppliers.forEach(supplier => {
            const option = new Option(supplier.name, supplier.id);
            entitySelect.appendChild(option);
        });
    } else {
        entityLabel.textContent = 'Client/Fournisseur';
    }
}

// Modifier une dette
function editDebt(id) {
    const d = debts.find(x => x.id === id);
    if (!d) return;
    if (d.type !== 'supplier') {
        showInfo('Les créances clients ne sont pas modifiables ici.');
        return;
    }
    document.getElementById('debtId').value = d.id;
    document.getElementById('debtType').value = 'supplier';
    handleDebtTypeChange();
    document.getElementById('reference').value = d.reference || '';
    document.getElementById('amount').value = Math.round(d.amount || 0);
    document.getElementById('debtDate').value = (d.date || '').split('T')[0] || '';
    document.getElementById('dueDate').value = d.due_date ? String(d.due_date).split('T')[0] : '';
    document.getElementById('paidAmount').value = d.paid_amount || 0;
    document.getElementById('debtStatus').value = d.status || 'pending';
    document.getElementById('description').value = d.description || '';
    document.getElementById('notes').value = d.notes || '';
    setTimeout(() => { document.getElementById('entitySelect').value = d.entity_id || ''; }, 50);
    currentDebtId = d.id;
    const modal = new bootstrap.Modal(document.getElementById('debtModal'));
    modal.show();
}

// Gérer la soumission du formulaire de dette
async function handleDebtFormSubmit(e) {
    e.preventDefault();
    await saveDebt();
}

// Enregistrer la dette
async function saveDebt() {
    const debtData = {
        type: document.getElementById('debtType').value,
        reference: document.getElementById('reference').value,
        entity_id: parseInt(document.getElementById('entitySelect').value),
        amount: Math.round(parseFloat(document.getElementById('amount').value)),
        date: document.getElementById('debtDate').value,
        due_date: document.getElementById('dueDate').value || null,
        description: document.getElementById('description').value,
        notes: document.getElementById('notes').value
    };

    if (debtData.type !== 'supplier') {
        showInfo('Les créances clients sont générées automatiquement à partir des factures.');
        return;
    }
    if (!debtData.entity_id) { showError('Veuillez sélectionner un fournisseur'); return; }
    if (!debtData.reference.trim()) { showError('Veuillez saisir une référence'); return; }
    if (!debtData.amount || debtData.amount <= 0) { showError('Veuillez saisir un montant valide'); return; }
    // Création: toujours non payé au départ

    try {
        if (currentDebtId) {
            await axios.put(`/api/debts/${currentDebtId}`, debtData);
        } else {
            await axios.post('/api/debts', debtData);
        }
        showSuccess(currentDebtId ? 'Dette fournisseur modifiée' : 'Dette fournisseur créée');
        const modal = bootstrap.Modal.getInstance(document.getElementById('debtModal'));
        modal.hide();
        loadDebts();
    } catch (error) {
        console.error('Erreur:', error);
        showError(error.response?.data?.detail || 'Erreur lors de l\'enregistrement');
    }
}

// Ajouter un paiement
function addPayment(id) {
    const debt = debts.find(d => d.id === id);
    if (!debt) return;

    const remaining = (debt.amount || 0) - (debt.paid_amount || 0);
    const remainingInt = Math.max(0, Math.floor(remaining));
    
    if (remainingInt <= 0) {
        showInfo('Cette dette est déjà entièrement payée');
        return;
    }

    // Remplir les informations de la dette
    document.getElementById('paymentDebtId').value = debt.id;
    document.getElementById('paymentAmount').value = remainingInt;
    document.getElementById('paymentAmount').max = remainingInt;
    
    const debtInfo = document.getElementById('paymentDebtInfo');
    debtInfo.innerHTML = `
        <div class="d-flex justify-content-between">
            <span><strong>Référence:</strong> ${escapeHtml(debt.reference)}</span>
            <span><strong>Type:</strong> ${getTypeLabel(debt.type)}</span>
        </div>
        <div class="d-flex justify-content-between mt-2">
            <span><strong>Montant total:</strong> ${formatCurrency(debt.amount)}</span>
            <span><strong>Déjà payé:</strong> ${formatCurrency(debt.paid_amount || 0)}</span>
        </div>
        <div class="d-flex justify-content-between mt-2">
            <span><strong>Restant à payer:</strong></span>
            <span class="text-danger"><strong>${formatCurrency(remaining)}</strong></span>
        </div>
    `;

    // Afficher la modal
    const modal = new bootstrap.Modal(document.getElementById('paymentModal'));
    modal.show();
}

// Gérer la soumission du formulaire de paiement
async function handlePaymentFormSubmit(e) {
    e.preventDefault();
    await savePayment();
}

// Enregistrer le paiement
async function savePayment() {
    const debtId = document.getElementById('paymentDebtId').value;
    const paymentData = {
        amount: Math.round(parseFloat(document.getElementById('paymentAmount').value)),
        date: document.getElementById('paymentDate').value,
        method: document.getElementById('paymentMethod').value,
        notes: document.getElementById('paymentNotes').value
    };

    // Validation
    if (!paymentData.amount || paymentData.amount <= 0) {
        showError('Veuillez saisir un montant valide');
        return;
    }

    if (!paymentData.date) {
        showError('Veuillez saisir une date de paiement');
        return;
    }

    try {
        await axios.post(`/api/debts/${debtId}/payments`, paymentData);

        showSuccess('Paiement enregistré avec succès');
        
        // Fermer la modal
        const modal = bootstrap.Modal.getInstance(document.getElementById('paymentModal'));
        modal.hide();
        
        // Recharger les données
        loadDebts();
    } catch (error) {
        console.error('Erreur:', error);
        showError(error.response?.data?.detail || 'Erreur lors de l\'enregistrement du paiement');
    }
}

// Voir une dette
function viewDebt(id) {
    try {
        sessionStorage.setItem('invoiceSearchQuery', String(id));
        sessionStorage.setItem('open_invoice_detail_id', String(id));
    } catch (e) {}
    // Rediriger vers la page des factures (elle ouvrira directement la modale de détail)
    window.location.href = `/invoices`;
}

// Supprimer une dette
function deleteDebt(id) {
    currentDebtId = id;
    const modal = new bootstrap.Modal(document.getElementById('deleteModal'));
    modal.show();
}

// Confirmer la suppression
async function confirmDelete() {
    if (!currentDebtId) return;
    const d = debts.find(x => x.id === currentDebtId);
    if (!d || d.type !== 'supplier') {
        showInfo('Suppression non disponible pour les créances clients.');
        return;
    }
    try {
        await axios.delete(`/api/debts/${currentDebtId}`);
        const modal = bootstrap.Modal.getInstance(document.getElementById('deleteModal'));
        modal.hide();
        showSuccess('Dette fournisseur supprimée');
        loadDebts();
        currentDebtId = null;
    } catch (error) {
        showError(error.response?.data?.detail || 'Erreur lors de la suppression');
    }
}

// Utilitaires
function getEntityName(debt) {
    // Si le backend fournit déjà le nom, l'utiliser en priorité
    if (debt && debt.entity_name) return debt.entity_name;
    if (debt.type === 'client') {
        const client = clients.find(c => (c.client_id ?? c.id) === debt.entity_id);
        return client ? client.name : 'Client inconnu';
    } else if (debt.type === 'supplier') {
        const supplier = suppliers.find(s => (s.supplier_id ?? s.id) === debt.entity_id);
        return supplier ? supplier.name : 'Fournisseur inconnu';
    }
    return 'N/A';
}

function getTypeBadgeClass(type) {
    switch (type) {
        case 'client': return 'bg-primary';
        case 'supplier': return 'bg-warning text-dark';
        case 'invoice': return 'bg-info';
        default: return 'bg-secondary';
    }
}

function getTypeIcon(type) {
    switch (type) {
        case 'client': return 'bi-people';
        case 'supplier': return 'bi-truck';
        case 'invoice': return 'bi-receipt';
        default: return 'bi-tag';
    }
}

function getTypeLabel(type) {
    switch (type) {
        case 'client': return 'Créance client';
        case 'supplier': return 'Dette fournisseur';
        case 'invoice': return 'Facture';
        case 'other': return 'Autre';
        default: return type;
    }
}

function getStatusBadgeClass(status) {
    switch (status) {
        case 'paid': return 'bg-success';
        case 'partial': return 'bg-warning text-dark';
        case 'overdue': return 'bg-danger';
        default: return 'bg-secondary';
    }
}

function getStatusLabel(status) {
    switch (status) {
        case 'pending': return 'En attente';
        case 'partial': return 'Partiel';
        case 'paid': return 'Payé';
        case 'overdue': return 'En retard';
        default: return status;
    }
}

function isOverdue(dueDate, status) {
    if (status === 'paid') return false;
    return new Date(dueDate) < new Date();
}

function formatDate(dateString) {
    if (!dateString) return '-';
    const options = { year: 'numeric', month: 'short', day: 'numeric' };
    const d = new Date(dateString);
    if (isNaN(d.getTime())) return '-';
    return d.toLocaleDateString('fr-FR', options);
}

function formatCurrency(amount) {
    return new Intl.NumberFormat('fr-FR', { 
        style: 'currency', 
        currency: 'XOF',
        minimumFractionDigits: 0,
        maximumFractionDigits: 0
    }).format(Math.round(amount || 0));
}

function updatePagination(totalItems) {
    const totalPages = Math.ceil(totalItems / itemsPerPage);
    const pagination = document.getElementById('pagination');
    
    pagination.innerHTML = '';
    
    if (totalPages <= 1) return;
    
    // Bouton précédent
    const prevLi = document.createElement('li');
    prevLi.className = `page-item ${currentPage === 1 ? 'disabled' : ''}`;
    prevLi.innerHTML = `<a class="page-link" href="#" onclick="changePage(${currentPage - 1})">Précédent</a>`;
    pagination.appendChild(prevLi);
    
    // Pages
    for (let i = 1; i <= totalPages; i++) {
        const li = document.createElement('li');
        li.className = `page-item ${i === currentPage ? 'active' : ''}`;
        li.innerHTML = `<a class="page-link" href="#" onclick="changePage(${i})">${i}</a>`;
        pagination.appendChild(li);
    }
    
    // Bouton suivant
    const nextLi = document.createElement('li');
    nextLi.className = `page-item ${currentPage === totalPages ? 'disabled' : ''}`;
    nextLi.innerHTML = `<a class="page-link" href="#" onclick="changePage(${currentPage + 1})">Suivant</a>`;
    pagination.appendChild(nextLi);
}

// Force un entier dans un input type number (gère aussi la virgule française)
function enforceIntegerInput(input) {
    input.setAttribute('step', '1');
    input.addEventListener('input', () => {
        const raw = String(input.value).replace(',', '.');
        const n = Math.floor(Number(raw));
        if (!Number.isFinite(n) || n < 0) {
            input.value = '';
        } else {
            input.value = String(n);
        }
    });
}

function changePage(page) {
    const totalItems = getFilteredDebts().length;
    const totalPages = Math.ceil(totalItems / itemsPerPage);
    
    if (page < 1 || page > totalPages) return;
    
    currentPage = page;
    displayDebts();
}

function showLoading() {
    // No-op to avoid showing a loading spinner
}

function hideLoading() {
    // Le loading sera masqué par displayDebts()
}
