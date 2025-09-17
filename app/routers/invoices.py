from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session
from sqlalchemy import desc, func, and_, or_
from typing import List, Optional
from datetime import datetime, date
from ..database import (
    get_db,
    Invoice,
    InvoiceItem,
    InvoicePayment,
    Client,
    Product,
    ProductVariant,
    DeliveryNote,
    DeliveryNoteItem,
    SupplierInvoice,
    SupplierInvoicePayment,
)
from ..database import DailyPurchase
from ..schemas import InvoiceCreate, InvoiceResponse, InvoiceItemResponse
from ..auth import get_current_user
from ..routers.stock_movements import create_stock_movement
from ..services.stats_manager import recompute_invoices_stats
import logging
import os
import re
import json

router = APIRouter(prefix="/api/invoices", tags=["invoices"]) 

# Helpers de numérotation
from datetime import datetime as _dt

def extract_signature_from_notes(notes: str) -> str:
    """
    Extrait la signature depuis les notes d'une facture.
    Cherche le pattern __SIGNATURE__=<data_url> dans les notes.
    
    Args:
        notes: Le texte des notes de la facture
        
    Returns:
        str: L'URL de la signature ou None si non trouvée
    """
    if not notes:
        return None
        
    try:
        # Chercher le pattern __SIGNATURE__=<data_url>
        pattern = r"__SIGNATURE__=(.*?)(?:\n|$)"
        match = re.search(pattern, notes, re.MULTILINE | re.DOTALL)
        
        if match:
            signature_url = match.group(1).strip()
            # Vérifier que c'est bien une data URL ou une URL valide
            if signature_url and (signature_url.startswith('data:') or signature_url.startswith('http')):
                return signature_url
    except Exception as e:
        logging.warning(f"Erreur lors de l'extraction de la signature: {e}")
    
    return None

def _next_invoice_number(db: Session, prefix: Optional[str] = None) -> str:
    """Génère le prochain numéro de facture séquentiel sous la forme PREFIX-####.
    Par défaut, PREFIX = 'FAC'. L'algorithme recherche d'abord les numéros
    existants au format exact PREFIX-<digits> et incrémente le plus grand.
    S'il n'en trouve pas, il tente un fallback sur le plus grand suffixe
    numérique présent et repart ensuite proprement.
    """
    import re
    pf = (prefix or 'FAC').strip('-')
    base_prefix = f"{pf}-"

    # Récupérer tous les numéros existants qui commencent par PREFIX-
    try:
        rows = db.query(Invoice.invoice_number).filter(Invoice.invoice_number.ilike(f"{base_prefix}%")).all()
    except Exception:
        rows = []

    last_seq = 0
    # 1) Chercher le max parmi les numéros au format exact PREFIX-####
    for (num,) in (rows or []):
        if not isinstance(num, str):
            continue
        m = re.fullmatch(rf"{re.escape(pf)}-(\\d+)", num.strip())
        if m:
            val = int(m.group(1))
            if val > last_seq:
                last_seq = val

    # 2) Fallback: si aucun au format exact, prendre le plus grand suffixe numérique
    if last_seq == 0:
        for (num,) in (rows or []):
            if not isinstance(num, str):
                continue
            matches = re.findall(r'(\\d+)', num.strip())
            if matches:
                val = int(matches[-1])  # dernier groupe de chiffres
                if val > last_seq:
                    last_seq = val

    next_seq = last_seq + 1

    # Garantir l'unicité (en cas de race, trous, etc.)
    while True:
        candidate = f"{base_prefix}{next_seq:04d}"
        exists = db.query(Invoice).filter(Invoice.invoice_number == candidate).first()
        if not exists:
            return candidate
        next_seq += 1

@router.get("/", response_model=List[InvoiceResponse])
async def list_invoices(
    skip: int = 0,
    limit: int = 100,
    status_filter: Optional[str] = None,
    client_id: Optional[int] = None,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """Lister les factures avec filtres"""
    # Utiliser un JOIN avec la table des clients pour récupérer le nom du client
    query = db.query(Invoice, Client.name.label('client_name')).join(Client, Invoice.client_id == Client.client_id).order_by(desc(Invoice.created_at))
    
    if status_filter:
        query = query.filter(Invoice.status == status_filter)
    
    if client_id:
        query = query.filter(Invoice.client_id == client_id)
    
    if start_date:
        query = query.filter(func.date(Invoice.date) >= start_date)
    
    if end_date:
        query = query.filter(func.date(Invoice.date) <= end_date)
    
    results = query.offset(skip).limit(limit).all()
    
    # Construire la réponse avec le nom du client
    invoices = []
    for invoice, client_name in results:
        invoice_dict = {
            "invoice_id": invoice.invoice_id,
            "invoice_number": invoice.invoice_number,
            "client_id": invoice.client_id,
            "client_name": client_name,  # Ajouter le nom du client
            "quotation_id": invoice.quotation_id,
            "date": invoice.date,
            "due_date": invoice.due_date,
            "status": invoice.status,
            "payment_method": invoice.payment_method,
            "subtotal": float(invoice.subtotal or 0),
            "tax_rate": float(invoice.tax_rate or 0),
            "tax_amount": float(invoice.tax_amount or 0),
            "total": float(invoice.total or 0),
            "paid_amount": float(invoice.paid_amount or 0),
            "remaining_amount": float(invoice.remaining_amount or 0),
            "notes": invoice.notes,
            "show_tax": bool(invoice.show_tax),
            "price_display": invoice.price_display or "FCFA",
            "created_at": invoice.created_at,
            "items": []
        }
        invoices.append(invoice_dict)
    
    return invoices

# Simple in-process cache for list responses
_invoices_cache = {}
_CACHE_TTL_SECONDS = 30

@router.get("/paginated")
async def list_invoices_paginated(
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=200),
    status_filter: Optional[str] = None,
    client_search: Optional[str] = None,
    search: Optional[str] = None,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    sort_by: Optional[str] = Query("created_at"),  # created_at | date | number | total | status | client
    sort_dir: Optional[str] = Query("desc"),       # asc | desc
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """Lister les factures avec pagination, filtres et tri pour la liste principale."""
    # Cache key
    try:
        import time, hashlib
        key_raw = f"p={page}|s={page_size}|sf={status_filter}|cs={client_search}|q={search}|sd={start_date}|ed={end_date}|ob={sort_by}|od={sort_dir}"
        key = hashlib.md5(key_raw.encode()).hexdigest()
        entry = _invoices_cache.get(key)
        if entry and (time.time() - entry['ts']) < _CACHE_TTL_SECONDS:
            return entry['data']
    except Exception:
        key = None
    # Base avec JOIN client pour récupérer le nom
    base = db.query(
        Invoice,
        Client.name.label('client_name')
    ).join(Client, Client.client_id == Invoice.client_id, isouter=True)

    # Filtres
    if status_filter:
        base = base.filter(Invoice.status == status_filter)
    if client_search:
        like = f"%{client_search.strip()}%"
        base = base.filter(Client.name.ilike(like))
    if start_date:
        base = base.filter(func.date(Invoice.date) >= start_date)
    if end_date:
        base = base.filter(func.date(Invoice.date) <= end_date)
    if search:
        s = search.strip()
        if s.isdigit():
            try:
                base = base.filter(Invoice.invoice_id == int(s))
            except Exception:
                base = base.filter(Invoice.invoice_number.ilike(f"%{s}%"))
        else:
            base = base.filter(Invoice.invoice_number.ilike(f"%{s}%"))

    # Total avant pagination
    total = base.count()

    # Tri
    sort_col = Invoice.created_at
    if sort_by == "date":
        sort_col = Invoice.date
    elif sort_by == "number":
        sort_col = Invoice.invoice_number
    elif sort_by == "total":
        sort_col = Invoice.total
    elif sort_by == "status":
        sort_col = Invoice.status
    elif sort_by == "client":
        sort_col = Client.name

    if (sort_dir or "").lower() == "asc":
        base = base.order_by(sort_col.asc())
    else:
        base = base.order_by(sort_col.desc())

    # Pagination
    skip = (page - 1) * page_size
    rows = base.offset(skip).limit(page_size).all()

    # Façonner la réponse légère (pas d'items/payments pour la liste)
    result_invoices = []
    for inv, client_name in rows:
        result_invoices.append({
            "invoice_id": inv.invoice_id,
            "invoice_number": inv.invoice_number,
            "client_id": inv.client_id,
            "client_name": client_name or "",
            "quotation_id": inv.quotation_id,
            "date": inv.date,
            "due_date": inv.due_date,
            "status": inv.status,
            "payment_method": inv.payment_method,
            "subtotal": float(inv.subtotal or 0),
            "tax_rate": float(inv.tax_rate or 0),
            "tax_amount": float(inv.tax_amount or 0),
            "total": float(inv.total or 0),
            "paid_amount": float(inv.paid_amount or 0),
            "remaining_amount": float(inv.remaining_amount or 0),
            "notes": inv.notes,
            "show_tax": bool(inv.show_tax),
            "price_display": inv.price_display or "FCFA",
            "created_at": inv.created_at,
        })

    result = {
        "invoices": result_invoices,
        "total": total,
        "page": page,
        "pages": (total + page_size - 1) // page_size if total > 0 else 1,
    }

    # Store in cache
    try:
        if key:
            import time
            _invoices_cache[key] = { 'ts': time.time(), 'data': result }
    except Exception:
        pass

    return result

@router.get("/next-number")
async def get_next_invoice_number(
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """Retourne le prochain numéro de facture disponible (FAC-####)."""
    try:
        return {"invoice_number": _next_invoice_number(db)}
    except Exception as e:
        logging.error(f"Erreur get_next_invoice_number: {e}")
        raise HTTPException(status_code=500, detail="Erreur serveur")

@router.get("/{invoice_id}")
async def get_invoice(
    invoice_id: int,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """Obtenir une facture par ID avec items et paiements"""
    invoice = db.query(Invoice).filter(Invoice.invoice_id == invoice_id).first()
    if not invoice:
        raise HTTPException(status_code=404, detail="Facture non trouvée")

    # Forcer chargement relations
    _ = invoice.items
    _ = invoice.payments

    return {
        "invoice_id": invoice.invoice_id,
        "invoice_number": invoice.invoice_number,
        "client_id": invoice.client_id,
        "date": invoice.date,
        "due_date": invoice.due_date,
        "status": invoice.status,
        "payment_method": invoice.payment_method,
        "subtotal": float(invoice.subtotal or 0),
        "tax_rate": float(invoice.tax_rate or 0),
        "tax_amount": float(invoice.tax_amount or 0),
        "total": float(invoice.total or 0),
        "paid_amount": float(invoice.paid_amount or 0),
        "remaining_amount": float(invoice.remaining_amount or 0),
        "show_tax": bool(invoice.show_tax),
        "notes": invoice.notes,
        "items": [
            {
                "item_id": it.item_id,
                "product_id": it.product_id,
                "product_name": it.product_name,
                "quantity": it.quantity,
                "price": float(it.price or 0),
                "total": float(it.total or 0)
            } for it in (invoice.items or [])
        ],
        "payments": [
            {
                "payment_id": p.payment_id,
                "amount": float(p.amount or 0),
                "payment_date": p.payment_date,
                "payment_method": p.payment_method,
                "reference": p.reference
            } for p in (invoice.payments or [])
        ]
    }

@router.post("/", response_model=InvoiceResponse)
async def create_invoice(
    invoice_data: InvoiceCreate,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """Créer une nouvelle facture.
    - Si le numéro est vide ou déjà utilisé, génère automatiquement le prochain numéro disponible (FAC-####).
    """
    try:
        # Vérifier que le client existe
        client = db.query(Client).filter(Client.client_id == invoice_data.client_id).first()
        if not client:
            raise HTTPException(status_code=404, detail="Client non trouvé")
        
        # Déterminer le numéro final (tolère vide/auto/duplicate)
        requested_number = (str(invoice_data.invoice_number or '').strip())
        final_number = None
        if not requested_number or requested_number.upper() in {"AUTO", "AUTOMATIC"}:
            final_number = _next_invoice_number(db)
        else:
            # Si déjà existant, basculer sur le prochain disponible
            exists = db.query(Invoice).filter(Invoice.invoice_number == requested_number).first()
            final_number = requested_number if not exists else _next_invoice_number(db)
        
        # Calculer le montant restant
        remaining_amount = invoice_data.total
        
        # Créer la facture
        db_invoice = Invoice(
            invoice_number=final_number,
            client_id=invoice_data.client_id,
            quotation_id=invoice_data.quotation_id,
            date=invoice_data.date,
            due_date=invoice_data.due_date,
            payment_method=invoice_data.payment_method,
            subtotal=invoice_data.subtotal,
            tax_rate=invoice_data.tax_rate,
            tax_amount=invoice_data.tax_amount,
            total=invoice_data.total,
            remaining_amount=remaining_amount,
            notes=invoice_data.notes,
            show_tax=invoice_data.show_tax,
            price_display=invoice_data.price_display
        )
        
        db.add(db_invoice)
        db.flush()  # Pour obtenir l'ID de la facture
        
        # Créer les éléments de facture et gérer le stock
        for item_data in invoice_data.items:
            # Lignes personnalisées sans produit: pas d'impact stock
            if not getattr(item_data, 'product_id', None):
                # Ensure custom line name respects DB length
                safe_custom_name = (item_data.product_name or 'Service')[:100]
                db_item = InvoiceItem(
                    invoice_id=db_invoice.invoice_id,
                    product_id=None,
                    product_name=safe_custom_name,
                    quantity=item_data.quantity,
                    price=item_data.price,
                    total=item_data.total
                )
                db.add(db_item)
                continue

            # Vérifier que le produit existe
            product = db.query(Product).filter(Product.product_id == item_data.product_id).first()
            if not product:
                raise HTTPException(status_code=404, detail=f"Produit {item_data.product_id} non trouvé")
            
            # Vérifier stock disponible
            if (product.quantity or 0) < item_data.quantity:
                raise HTTPException(status_code=400, detail=f"Stock insuffisant pour le produit {product.name}")
            
            # Si une variante est indiquée, vérifier et la marquer comme vendue
            if getattr(item_data, 'variant_id', None):
                variant = db.query(ProductVariant).filter(ProductVariant.variant_id == item_data.variant_id).first()
                if not variant:
                    raise HTTPException(status_code=404, detail=f"Variante {item_data.variant_id} introuvable")
                if variant.product_id != product.product_id:
                    raise HTTPException(status_code=400, detail="Variante n'appartient pas au produit")
                if bool(variant.is_sold):
                    raise HTTPException(status_code=400, detail=f"La variante {variant.imei_serial} est déjà vendue")
                variant.is_sold = True
            
            # Créer l'élément de facture
            # Ensure product_name respects DB length (String(100))
            safe_name = (item_data.product_name or product.name)[:100]
            db_item = InvoiceItem(
                invoice_id=db_invoice.invoice_id,
                product_id=item_data.product_id,
                product_name=safe_name,
                quantity=item_data.quantity,
                price=item_data.price,
                total=item_data.total
            )
            db.add(db_item)
            
            # Mettre à jour le stock et créer un mouvement
            product.quantity = (product.quantity or 0) - item_data.quantity
            try:
                create_stock_movement(
                    db=db,
                    product_id=item_data.product_id,
                    quantity=item_data.quantity,
                    movement_type="OUT",
                    reference_type="INVOICE",
                    reference_id=db_invoice.invoice_id,
                    notes=f"Vente - Facture {final_number}",
                    unit_price=float(item_data.price)
                )
            except Exception:
                # Ne pas bloquer la création de facture si l'enregistrement du mouvement échoue
                pass
        
        db.commit()
        db.refresh(db_invoice)
        
        # Clear invoices cache after creation to ensure fresh data on next load
        _invoices_cache.clear()
        
        try:
            # Mettre à jour les stats persistées
            recompute_invoices_stats(db)
        except Exception:
            pass

        # Façonner et retourner la réponse complète avec client_name
        try:
            client_name = db.query(Client.name).filter(Client.client_id == db_invoice.client_id).scalar() or ""
        except Exception:
            client_name = ""
        try:
            _ = db_invoice.items
        except Exception:
            pass
        return {
            "invoice_id": db_invoice.invoice_id,
            "invoice_number": db_invoice.invoice_number,
            "client_id": db_invoice.client_id,
            "client_name": client_name,
            "quotation_id": db_invoice.quotation_id,
            "date": db_invoice.date,
            "due_date": db_invoice.due_date,
            "status": db_invoice.status,
            "payment_method": db_invoice.payment_method,
            "subtotal": float(db_invoice.subtotal or 0),
            "tax_rate": float(db_invoice.tax_rate or 0),
            "tax_amount": float(db_invoice.tax_amount or 0),
            "total": float(db_invoice.total or 0),
            "paid_amount": float(db_invoice.paid_amount or 0),
            "remaining_amount": float(db_invoice.remaining_amount or 0),
            "notes": db_invoice.notes,
            "show_tax": bool(db_invoice.show_tax),
            "price_display": db_invoice.price_display or "FCFA",
            "created_at": db_invoice.created_at,
            "items": [
                {
                    "item_id": it.item_id,
                    "product_id": it.product_id,
                    "product_name": it.product_name,
                    "quantity": it.quantity,
                    "price": float(it.price or 0),
                    "total": float(it.total or 0),
                }
                for it in (db_invoice.items or [])
            ],
        }
        
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logging.exception(f"Erreur lors de la création de la facture")
        if str(os.getenv("DEBUG_ERRORS", "")).lower() == "true":
            raise HTTPException(status_code=500, detail=f"Erreur serveur: {e}")
        raise HTTPException(status_code=500, detail="Erreur serveur")

@router.put("/{invoice_id}", response_model=InvoiceResponse)
async def update_invoice(
    invoice_id: int,
    invoice_data: InvoiceCreate,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """Mettre à jour une facture existante avec réconciliation du stock et des variantes.

    Stratégie:
    - Restaurer le stock des anciens items (IN) et tenter de réactiver les variantes vendues
      en se basant sur les métadonnées de notes (__SERIALS__) ou, à défaut, sur le libellé (IMEI: ...).
      En dernier recours, désactiver l'état vendu de n variantes correspondant à la quantité.
    - Remplacer les items par ceux du payload et appliquer le nouveau stock (OUT) + variantes vendues.
    - Mettre à jour les montants et le statut en cohérence avec le montant payé actuel.
    """
    try:
        # Charger la facture existante
        invoice = db.query(Invoice).filter(Invoice.invoice_id == invoice_id).first()
        if not invoice:
            raise HTTPException(status_code=404, detail="Facture non trouvée")

        # Vérifier l'unicité du numéro si modifié
        if invoice.invoice_number != invoice_data.invoice_number:
            existing = db.query(Invoice).filter(Invoice.invoice_number == invoice_data.invoice_number).first()
            if existing and int(existing.invoice_id) != int(invoice_id):
                raise HTTPException(status_code=400, detail="Ce numéro de facture existe déjà")

        # Vérifier que le client existe
        client = db.query(Client).filter(Client.client_id == invoice_data.client_id).first()
        if not client:
            raise HTTPException(status_code=404, detail="Client non trouvé")

        # 1) REVERT: restaurer le stock des anciens items et réactiver variantes
        #   a) Restaurer le stock pour chaque item produit
        old_items = list(invoice.items or [])
        for it in old_items:
            if it.product_id is None:
                continue
            product = db.query(Product).filter(Product.product_id == it.product_id).first()
            if product:
                try:
                    product.quantity = (product.quantity or 0) + int(it.quantity or 0)
                except Exception:
                    product.quantity = (product.quantity or 0)
                # Mouvement IN pour revert
                try:
                    create_stock_movement(
                        db=db,
                        product_id=it.product_id,
                        quantity=int(it.quantity or 0),
                        movement_type="IN",
                        reference_type="INV_UPDATE_REVERT",  # Shortened to fit VARCHAR(20)
                        reference_id=invoice_id,
                        notes=f"Revert mise à jour facture {invoice.invoice_number}",
                        unit_price=float(it.price or 0),
                    )
                except Exception:
                    pass

        #   b) Tenter de réactiver les variantes vendues pour les anciens items
        try:
            serials_meta = []
            if invoice.notes:
                import re, json
                txt = str(invoice.notes)
                if "__SERIALS__=" in txt:
                    sub = txt.split("__SERIALS__=", 1)[1]
                    cut_idx = sub.find("\n__")
                    if cut_idx != -1:
                        sub = sub[:cut_idx].strip()
                    sub = sub.strip()
                    try:
                        serials_meta = json.loads(sub)
                    except Exception:
                        m = re.search(r"__SERIALS__=(\[.*?\])", txt, flags=re.S)
                        if m:
                            serials_meta = json.loads(m.group(1))

            processed_products = set()
            # 1) Depuis meta notes
            for entry in (serials_meta or []):
                pid = entry.get("product_id")
                if pid is not None:
                    processed_products.add(int(pid))
                for imei in (entry.get("imeis") or []):
                    variant = db.query(ProductVariant).filter(func.trim(ProductVariant.imei_serial) == str(imei).strip()).first()
                    if variant and bool(variant.is_sold):
                        variant.is_sold = False

            # 2) Fallback: IMEI dans le libellé de ligne
            import re as _re
            for it in (old_items or []):
                if it.product_id is None:
                    continue
                name = it.product_name or ""
                m2 = _re.search(r"\(IMEI:\s*([^)]+)\)", name, flags=_re.I)
                if not m2:
                    continue
                imei = (m2.group(1) or '').strip()
                if not imei:
                    continue
                try:
                    processed_products.add(int(it.product_id))
                except Exception:
                    pass
                variant = db.query(ProductVariant).filter(func.trim(ProductVariant.imei_serial) == imei).first()
                if variant and bool(variant.is_sold):
                    variant.is_sold = False

            # 3) Ultime fallback: désactiver l'état vendu pour autant de variantes que la quantité (par produit)
            for it in (old_items or []):
                pid = int(it.product_id) if it.product_id is not None else None
                if pid is None:
                    continue
                if pid in processed_products:
                    continue
                try:
                    qty = int(it.quantity or 0)
                except Exception:
                    qty = 0
                if qty <= 0:
                    continue
                sold_variants = (
                    db.query(ProductVariant)
                    .filter(ProductVariant.product_id == pid, ProductVariant.is_sold == True)
                    .limit(qty)
                    .all()
                )
                for v in sold_variants:
                    v.is_sold = False
        except Exception:
            # Ne pas bloquer la mise à jour si la réactivation des variantes échoue
            pass

        # Supprimer les anciens items
        for it in old_items:
            try:
                db.delete(it)
            except Exception:
                pass
        db.flush()

        # 2) APPLY: mettre à jour la facture et recréer les items avec nouveaux impacts stock/variants
        invoice.invoice_number = invoice_data.invoice_number
        invoice.client_id = invoice_data.client_id
        invoice.quotation_id = invoice_data.quotation_id
        invoice.date = invoice_data.date
        invoice.due_date = invoice_data.due_date
        invoice.payment_method = invoice_data.payment_method
        invoice.subtotal = invoice_data.subtotal
        invoice.tax_rate = invoice_data.tax_rate
        invoice.tax_amount = invoice_data.tax_amount
        invoice.total = invoice_data.total
        invoice.notes = invoice_data.notes
        invoice.show_tax = bool(invoice_data.show_tax)
        invoice.price_display = invoice_data.price_display

        # Recalculer remaining_amount en fonction du payé existant
        try:
            paid = float(invoice.paid_amount or 0)
            total_val = float(invoice.total or 0)
            invoice.remaining_amount = max(0, total_val - paid)
            # Ajuster le statut si nécessaire
            if invoice.remaining_amount == 0:
                invoice.status = "payée"
            elif paid > 0:
                invoice.status = "partiellement payée"
            else:
                invoice.status = "en attente"
        except Exception:
            pass

        # Créer les nouveaux items et appliquer le stock
        for item_data in (invoice_data.items or []):
            # Lignes personnalisées sans produit: pas d'impact stock
            if not getattr(item_data, 'product_id', None):
                # Ensure custom line name respects DB length
                safe_custom_name = (item_data.product_name or 'Service')[:100]
                db_item = InvoiceItem(
                    invoice_id=invoice.invoice_id,
                    product_id=None,
                    product_name=safe_custom_name,
                    quantity=item_data.quantity,
                    price=item_data.price,
                    total=item_data.total,
                )
                db.add(db_item)
                continue

            # Vérifier produit
            product = db.query(Product).filter(Product.product_id == item_data.product_id).first()
            if not product:
                raise HTTPException(status_code=404, detail=f"Produit {item_data.product_id} non trouvé")

            # Vérifier stock suffisant
            if (product.quantity or 0) < int(item_data.quantity or 0):
                raise HTTPException(status_code=400, detail=f"Stock insuffisant pour le produit {product.name}")

            # Gérer une éventuelle variante (si fournie)
            if getattr(item_data, 'variant_id', None):
                variant = db.query(ProductVariant).filter(ProductVariant.variant_id == item_data.variant_id).first()
                if not variant:
                    raise HTTPException(status_code=404, detail=f"Variante {item_data.variant_id} introuvable")
                if variant.product_id != product.product_id:
                    raise HTTPException(status_code=400, detail="Variante n'appartient pas au produit")
                if bool(variant.is_sold):
                    raise HTTPException(status_code=400, detail=f"La variante {variant.imei_serial} est déjà vendue")
                variant.is_sold = True

            # Créer l'item
            # Ensure product_name respects DB length (String(100))
            safe_name = (item_data.product_name or product.name)[:100]
            db_item = InvoiceItem(
                invoice_id=invoice.invoice_id,
                product_id=item_data.product_id,
                product_name=safe_name,
                quantity=item_data.quantity,
                price=item_data.price,
                total=item_data.total,
            )
            db.add(db_item)

            # Appliquer le stock et enregistrer le mouvement OUT
            product.quantity = (product.quantity or 0) - int(item_data.quantity or 0)
            try:
                create_stock_movement(
                    db=db,
                    product_id=item_data.product_id,
                    quantity=int(item_data.quantity or 0),
                    movement_type="OUT",
                    reference_type="INVOICE_UPDATE",
                    reference_id=invoice.invoice_id,
                    notes=f"Mise à jour - Facture {invoice.invoice_number}",
                    unit_price=float(item_data.price or 0),
                )
            except Exception:
                pass

        db.commit()
        db.refresh(invoice)
        
        # Clear invoices cache after update to ensure fresh data on next load
        _invoices_cache.clear()
        
        try:
            recompute_invoices_stats(db)
        except Exception:
            pass
        # Façonner et retourner la réponse complète avec client_name (aligné sur create_invoice)
        try:
            client_name = db.query(Client.name).filter(Client.client_id == invoice.client_id).scalar() or ""
        except Exception:
            client_name = ""
        try:
            _ = invoice.items
        except Exception:
            pass
        return {
            "invoice_id": invoice.invoice_id,
            "invoice_number": invoice.invoice_number,
            "client_id": invoice.client_id,
            "client_name": client_name,
            "quotation_id": invoice.quotation_id,
            "date": invoice.date,
            "due_date": invoice.due_date,
            "status": invoice.status,
            "payment_method": invoice.payment_method,
            "subtotal": float(invoice.subtotal or 0),
            "tax_rate": float(invoice.tax_rate or 0),
            "tax_amount": float(invoice.tax_amount or 0),
            "total": float(invoice.total or 0),
            "paid_amount": float(invoice.paid_amount or 0),
            "remaining_amount": float(invoice.remaining_amount or 0),
            "notes": invoice.notes,
            "show_tax": bool(invoice.show_tax),
            "price_display": invoice.price_display or "FCFA",
            "created_at": invoice.created_at,
            "items": [
                {
                    "item_id": it.item_id,
                    "product_id": it.product_id,
                    "product_name": it.product_name,
                    "quantity": it.quantity,
                    "price": float(it.price or 0),
                    "total": float(it.total or 0),
                }
                for it in (invoice.items or [])
            ],
        }

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logging.exception(f"Erreur lors de la mise à jour de la facture")
        if str(os.getenv("DEBUG_ERRORS", "")).lower() == "true":
            raise HTTPException(status_code=500, detail=f"Erreur serveur: {e}")
        raise HTTPException(status_code=500, detail="Erreur serveur")

@router.put("/{invoice_id}/status")
async def update_invoice_status(
    invoice_id: int,
    status: str,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """Mettre à jour le statut d'une facture"""
    try:
        invoice = db.query(Invoice).filter(Invoice.invoice_id == invoice_id).first()
        if not invoice:
            raise HTTPException(status_code=404, detail="Facture non trouvée")
        
        valid_statuses = ["en attente", "payée", "partiellement payée", "en retard", "annulée"]
        if status not in valid_statuses:
            raise HTTPException(status_code=400, detail="Statut invalide")
        
        invoice.status = status
        db.commit()
        
        # Clear invoices cache after status update to ensure fresh data on next load
        _invoices_cache.clear()
        
        return {"message": "Statut mis à jour avec succès"}
        
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logging.error(f"Erreur lors de la mise à jour du statut: {e}")
        raise HTTPException(status_code=500, detail="Erreur serveur")

from pydantic import BaseModel
from decimal import Decimal
from datetime import datetime

class PaymentCreate(BaseModel):
    amount: float
    payment_method: str
    payment_date: Optional[datetime] = None
    reference: Optional[str] = None
    notes: Optional[str] = None


@router.post("/{invoice_id}/payments")
async def add_payment(
    invoice_id: int,
    payload: PaymentCreate,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """Ajouter un paiement à une facture (JSON body)"""
    try:
        invoice = db.query(Invoice).filter(Invoice.invoice_id == invoice_id).first()
        if not invoice:
            raise HTTPException(status_code=404, detail="Facture non trouvée")
        
        if payload.amount <= 0:
            raise HTTPException(status_code=400, detail="Le montant doit être positif")
        
        # Convertir en Decimal et forcer un montant entier
        amount_dec = Decimal(str(payload.amount)).quantize(Decimal('1'))
        remaining = Decimal(str(invoice.remaining_amount or 0)).quantize(Decimal('1'))
        if amount_dec > remaining:
            raise HTTPException(status_code=400, detail="Le montant dépasse le solde restant")
        
        # Créer le paiement
        payment = InvoicePayment(
            invoice_id=invoice_id,
            amount=amount_dec,
            payment_method=payload.payment_method,
            payment_date=(payload.payment_date or datetime.now()),
            reference=payload.reference,
            notes=payload.notes
        )
        db.add(payment)
        
        # Mettre à jour les montants de la facture
        invoice.paid_amount = Decimal(str(invoice.paid_amount or 0)) + amount_dec
        invoice.remaining_amount = remaining - amount_dec
        
        # Mettre à jour le statut
        if invoice.remaining_amount == 0:
            invoice.status = "payée"
        elif invoice.paid_amount > 0:
            invoice.status = "partiellement payée"
        
        db.commit()
        db.refresh(payment)
        
        # Clear invoices cache after payment to ensure fresh data on next load
        _invoices_cache.clear()
        
        return {"message": "Paiement ajouté avec succès", "payment_id": payment.payment_id}
        
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logging.error(f"Erreur lors de l'ajout du paiement: {e}")
        raise HTTPException(status_code=500, detail="Erreur serveur")

@router.delete("/{invoice_id}")
async def delete_invoice(
    invoice_id: int,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """Supprimer une facture (admin seulement)"""
    try:
        invoice = db.query(Invoice).filter(Invoice.invoice_id == invoice_id).first()
        if not invoice:
            raise HTTPException(status_code=404, detail="Facture non trouvée")
        
        if current_user.role not in ["admin"]:
            raise HTTPException(status_code=403, detail="Permissions insuffisantes")
        
        # Restaurer le stock des produits
        for item in invoice.items:
            product = db.query(Product).filter(Product.product_id == item.product_id).first()
            if product:
                product.quantity += item.quantity
                create_stock_movement(
                    db=db,
                    product_id=item.product_id,
                    quantity=item.quantity,
                    movement_type="IN",
                    reference_type="INVOICE_CANCELLATION",
                    reference_id=invoice_id,
                    notes=f"Annulation facture {invoice.invoice_number}",
                    unit_price=float(item.price)
                )
        
        # Réactiver les variantes vendues
        try:
            serials_meta = []
            if invoice.notes:
                import re, json
                txt = str(invoice.notes)
                if "__SERIALS__=" in txt:
                    sub = txt.split("__SERIALS__=", 1)[1]
                    # Couper avant une autre balise meta commençant par __ ou fin de texte
                    cut_idx = sub.find("\n__")
                    if cut_idx != -1:
                        sub = sub[:cut_idx].strip()
                    # Nettoyer d'éventuels sauts de lignes/trailing
                    sub = sub.strip()
                    try:
                        serials_meta = json.loads(sub)
                    except Exception:
                        # Ultime tentative: regex non-gourmande entre crochets
                        m = re.search(r"__SERIALS__=(\[.*?\])", txt, flags=re.S)
                        if m:
                            serials_meta = json.loads(m.group(1))
            # 1) Depuis meta notes (le plus fiable)
            processed_products = set()
            if serials_meta:
                for entry in (serials_meta or []):
                    pid = entry.get('product_id')
                    if pid is not None:
                        processed_products.add(int(pid))
                    for imei in (entry.get('imeis') or []):
                        variant = db.query(ProductVariant).filter(func.trim(ProductVariant.imei_serial) == str(imei).strip()).first()
                        if variant and bool(variant.is_sold):
                            variant.is_sold = False
            else:
                # 2) Fallback: extraire IMEI depuis le libellé de chaque ligne: "(IMEI: XXXXX)"
                import re
                for it in (invoice.items or []):
                    name = it.product_name or ""
                    m2 = re.search(r"\(IMEI:\s*([^)]+)\)", name, flags=re.I)
                    if not m2:
                        continue
                    imei = (m2.group(1) or '').strip()
                    if not imei:
                        continue
                    if it.product_id is not None:
                        processed_products.add(int(it.product_id))
                    variant = db.query(ProductVariant).filter(func.trim(ProductVariant.imei_serial) == imei).first()
                    if variant and bool(variant.is_sold):
                        variant.is_sold = False

            # 3) Ultime fallback: pour les produits concernés mais sans IMEI détecté,
            # désactiver l'état "vendu" pour autant de variantes que la quantité des lignes
            # (utile pour anciennes factures sans meta ni IMEI dans le libellé)
            for it in (invoice.items or []):
                pid = int(it.product_id) if it.product_id is not None else None
                if pid is None:
                    continue
                # Si déjà traité via IMEI, sauter
                if pid in processed_products:
                    continue
                try:
                    qty = int(it.quantity or 0)
                except Exception:
                    qty = 0
                if qty <= 0:
                    continue
                sold_variants = (
                    db.query(ProductVariant)
                    .filter(ProductVariant.product_id == pid, ProductVariant.is_sold == True)
                    .limit(qty)
                    .all()
                )
                for v in sold_variants:
                    v.is_sold = False
                # Mettre à jour la quantité disponible du produit si incohérente
                try:
                    product = db.query(Product).filter(Product.product_id == pid).first()
                    if product:
                        product.quantity = (product.quantity or 0) + len(sold_variants)
                except Exception:
                    pass
        except Exception:
            # ne pas bloquer la suppression de la facture si parsing échoue
            pass
        
        # Supprimer d'éventuels bons de livraison liés à cette facture (et leurs items)
        try:
            linked_notes = db.query(DeliveryNote).filter(DeliveryNote.invoice_id == invoice_id).all()
            for note in (linked_notes or []):
                try:
                    for it in list(note.items or []):
                        try:
                            db.delete(it)
                        except Exception:
                            pass
                except Exception:
                    pass
                try:
                    db.delete(note)
                except Exception:
                    pass
        except Exception:
            # Si la suppression échoue, l'exception globale sera gérée ci-dessous
            pass
        
        db.delete(invoice)
        db.commit()
        
        # Clear invoices cache after deletion to ensure fresh data on next load
        _invoices_cache.clear()
        
        try:
            recompute_invoices_stats(db)
        except Exception:
            pass
        
        return {"message": "Facture supprimée avec succès"}
        
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logging.error(f"Erreur lors de la suppression de la facture: {e}")
        raise HTTPException(status_code=500, detail="Erreur serveur")

@router.get("/stats/dashboard")
async def get_invoice_stats(
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """Obtenir les statistiques des factures pour le tableau de bord"""
    try:
        today = date.today()
        
        # Total des factures
        total_invoices = db.query(Invoice).count()
        
        # Comptages par statut (support FR/EN)
        pending_invoices = db.query(Invoice).filter(Invoice.status.in_(["en attente", "SENT", "DRAFT", "OVERDUE", "partiellement payée"]) ).count()
        paid_invoices = db.query(Invoice).filter(Invoice.status.in_(["payée", "PAID"]) ).count()
        
        # Chiffre d'affaires brut du mois
        monthly_revenue_gross = db.query(func.sum(Invoice.total)).filter(
            func.extract('month', Invoice.date) == today.month,
            func.extract('year', Invoice.date) == today.year,
            Invoice.status.in_(["payée", "PAID"])
        ).scalar() or 0

        # Achats quotidiens du mois (par date ou created_at)
        monthly_daily_purchases = db.query(func.coalesce(func.sum(DailyPurchase.amount), 0)).filter(
            or_(
                and_(func.extract('month', DailyPurchase.date) == today.month, func.extract('year', DailyPurchase.date) == today.year),
                and_(func.extract('month', DailyPurchase.created_at) == today.month, func.extract('year', DailyPurchase.created_at) == today.year),
            )
        ).scalar() or 0
        
        # Paiements aux fournisseurs du mois
        monthly_supplier_payments = db.query(func.sum(SupplierInvoice.paid_amount)).filter(
            func.extract('month', SupplierInvoice.invoice_date) == today.month,
            func.extract('year', SupplierInvoice.invoice_date) == today.year
        ).scalar() or 0
        
        # Chiffre d'affaires net du mois (déduction achats quotidiens)
        monthly_revenue = float(monthly_revenue_gross or 0) - float(monthly_supplier_payments or 0) - float(monthly_daily_purchases or 0)
        
        # Chiffre d'affaires total brut (toutes factures payées)
        total_revenue_gross = db.query(func.sum(Invoice.total)).filter(Invoice.status.in_(["payée", "PAID"])).scalar() or 0
        
        # Total des paiements aux fournisseurs
        total_supplier_payments = db.query(func.sum(SupplierInvoice.paid_amount)).scalar() or 0
        
        # Total des achats quotidiens (toute période)
        total_daily_purchases = db.query(func.coalesce(func.sum(DailyPurchase.amount), 0)).scalar() or 0
        
        # Chiffre d'affaires total net (déduction achats quotidiens)
        total_revenue = float(total_revenue_gross or 0) - float(total_supplier_payments or 0) - float(total_daily_purchases or 0)
        
        # Montant impayé (restant)
        unpaid_amount = db.query(func.sum(Invoice.remaining_amount)).filter(Invoice.status.in_(["en attente", "partiellement payée", "OVERDUE"])) .scalar() or 0
        
        # Toujours recalculer à la demande pour refléter immédiatement les derniers changements
        try:
            from ..services.stats_manager import recompute_invoices_stats
            return recompute_invoices_stats(db)
        except Exception:
            return {
                "total_invoices": total_invoices,
                "pending_invoices": pending_invoices,
                "paid_invoices": paid_invoices,
                "monthly_revenue": float(monthly_revenue),
                "monthly_revenue_gross": float(monthly_revenue_gross),
                "monthly_supplier_payments": float(monthly_supplier_payments),
                "monthly_daily_purchases": float(monthly_daily_purchases),
                "total_revenue": float(total_revenue),
                "total_revenue_gross": float(total_revenue_gross),
                "total_supplier_payments": float(total_supplier_payments),
                "total_daily_purchases": float(total_daily_purchases),
                "unpaid_amount": float(unpaid_amount)
            }
        
    except Exception as e:
        logging.error(f"Erreur lors du calcul des stats factures: {e}")
        raise HTTPException(status_code=500, detail="Erreur serveur")

@router.post("/{invoice_id}/delivery-note")
async def create_delivery_note_from_invoice(
    invoice_id: int,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """Générer un bon de livraison à partir d'une facture existante.

    - Copie les lignes produits (ignore les lignes personnalisées sans produit)
    - Calque les montants (HT/TVA/Total) de la facture
    - Tente d'attacher les numéros de série/IMEI depuis les notes de la facture (__SERIALS__=...)
    """
    try:
        # Charger la facture et ses éléments
        invoice = db.query(Invoice).filter(Invoice.invoice_id == invoice_id).first()
        if not invoice:
            raise HTTPException(status_code=404, detail="Facture non trouvée")

        _ = invoice.items  # force load
        _ = invoice.client  # force load

        # Générer un numéro de BL: BL-YYYYMMDD-XXXX
        from datetime import datetime as _dt
        today_prefix = _dt.now().strftime("BL-%Y%m%d-")
        last_note = (
            db.query(DeliveryNote)
            .filter(DeliveryNote.delivery_note_number.ilike(f"{today_prefix}%"))
            .order_by(DeliveryNote.delivery_note_id.desc())
            .first()
        )
        if last_note and last_note.delivery_note_number.startswith(today_prefix):
            try:
                last_seq = int(last_note.delivery_note_number.split("-")[-1])
            except Exception:
                last_seq = 0
            next_seq = last_seq + 1
        else:
            next_seq = 1
        delivery_number = f"{today_prefix}{next_seq:04d}"

        # Parser les IMEIs/séries depuis les notes de facture si présents
        serials_meta = []
        try:
            txt = str(invoice.notes or "")
            if "__SERIALS__=" in txt:
                import re, json
                sub = txt.split("__SERIALS__=", 1)[1]
                cut_idx = sub.find("\n__")
                if cut_idx != -1:
                    sub = sub[:cut_idx].strip()
                sub = sub.strip()
                try:
                    serials_meta = json.loads(sub)
                except Exception:
                    m = re.search(r"__SERIALS__=(\[.*?\])", txt, flags=re.S)
                    if m:
                        serials_meta = json.loads(m.group(1))
        except Exception:
            serials_meta = []

        # Index des séries par produit
        product_id_to_imeis = {}
        try:
            for entry in (serials_meta or []):
                pid = entry.get("product_id")
                if pid is None:
                    continue
                product_id_to_imeis[int(pid)] = list(entry.get("imeis") or [])
        except Exception:
            product_id_to_imeis = {}

        # Extraire la signature de la facture si présente
        signature_data_url = extract_signature_from_notes(invoice.notes or "")
        
        # Créer le BL
        notes = f"Créé depuis facture {invoice.invoice_number}"
        
        dn = DeliveryNote(
            delivery_note_number=delivery_number,
            invoice_id=invoice.invoice_id,
            client_id=invoice.client_id,
            date=_dt.now(),  # BL daté au jour de la génération
            delivery_date=_dt.now(),
            status="en_preparation",
            delivery_address=getattr(invoice.client, "address", None) if invoice.client else None,
            delivery_contact=getattr(invoice.client, "name", None) if invoice.client else None,
            delivery_phone=getattr(invoice.client, "phone", None) if invoice.client else None,
            subtotal=invoice.subtotal,
            tax_rate=invoice.tax_rate,
            tax_amount=invoice.tax_amount,
            total=invoice.total,
            notes=notes,
            signature_data_url=signature_data_url
        )
        db.add(dn)
        db.flush()  # obtenir l'ID

        # Lignes du BL à partir des lignes facture (inclut aussi les lignes personnalisées)
        for it in (invoice.items or []):
            pid = it.product_id  # peut être None pour une ligne personnalisée
            imeis = []
            try:
                if pid is not None:
                    imeis = product_id_to_imeis.get(int(pid), [])
            except Exception:
                imeis = []
            dn_item = DeliveryNoteItem(
                delivery_note_id=dn.delivery_note_id,
                product_id=pid,
                product_name=it.product_name,
                quantity=it.quantity,
                price=it.price,
                delivered_quantity=0,
                serial_numbers=(None if not imeis else __import__("json").dumps(imeis))
            )
            db.add(dn_item)

        db.commit()
        db.refresh(dn)

        return {
            "message": "Bon de livraison créé",
            "delivery_note_id": dn.delivery_note_id,
            "delivery_note_number": dn.delivery_note_number,
        }

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logging.error(f"Erreur lors de la génération du BL depuis facture: {e}")
        raise HTTPException(status_code=500, detail="Erreur serveur")
