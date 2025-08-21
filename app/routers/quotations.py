from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy import desc, func
from typing import List, Optional
from datetime import datetime, date
from ..database import get_db, Quotation, QuotationItem, Client, Product, Invoice
from ..schemas import QuotationCreate, QuotationResponse
from ..auth import get_current_user
import logging

router = APIRouter(prefix="/api/quotations", tags=["quotations"])

@router.get("/", response_model=List[QuotationResponse])
async def list_quotations(
    skip: int = 0,
    limit: int = 100,
    status_filter: Optional[str] = None,
    client_id: Optional[int] = None,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """Lister les devis avec filtres"""
    query = db.query(Quotation).order_by(desc(Quotation.created_at))
    
    if status_filter:
        query = query.filter(Quotation.status == status_filter)
    
    if client_id:
        query = query.filter(Quotation.client_id == client_id)
    
    if start_date:
        query = query.filter(func.date(Quotation.date) >= start_date)
    
    if end_date:
        query = query.filter(func.date(Quotation.date) <= end_date)
    
    quotations = query.offset(skip).limit(limit).all()
    # Attacher l'ID de la facture liée (s'il existe) pour chaque devis
    try:
        qids = [int(q.quotation_id) for q in quotations]
        if qids:
            rows = (
                db.query(Invoice.quotation_id, Invoice.invoice_id)
                .filter(Invoice.quotation_id.in_(qids))
                .all()
            )
            qid_to_invoice = {int(r[0]): int(r[1]) for r in rows if r[0] is not None and r[1] is not None}
            for q in quotations:
                try:
                    setattr(q, "invoice_id", qid_to_invoice.get(int(q.quotation_id)))
                except Exception:
                    pass
    except Exception:
        pass
    return quotations

@router.get("/{quotation_id}", response_model=QuotationResponse)
async def get_quotation(
    quotation_id: int,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """Obtenir un devis par ID"""
    quotation = db.query(Quotation).filter(Quotation.quotation_id == quotation_id).first()
    if not quotation:
        raise HTTPException(status_code=404, detail="Devis non trouvé")
    # Attacher l'ID de facture liée si présent
    try:
        inv = db.query(Invoice).filter(Invoice.quotation_id == quotation.quotation_id).first()
        if inv:
            setattr(quotation, "invoice_id", inv.invoice_id)
    except Exception:
        pass
    return quotation

@router.post("/", response_model=QuotationResponse)
async def create_quotation(
    quotation_data: QuotationCreate,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """Créer un nouveau devis"""
    try:
        # Vérifier que le client existe
        client = db.query(Client).filter(Client.client_id == quotation_data.client_id).first()
        if not client:
            raise HTTPException(status_code=404, detail="Client non trouvé")
        
        # Vérifier l'unicité du numéro de devis
        existing_quotation = db.query(Quotation).filter(Quotation.quotation_number == quotation_data.quotation_number).first()
        if existing_quotation:
            raise HTTPException(status_code=400, detail="Ce numéro de devis existe déjà")
        
        # Créer le devis
        db_quotation = Quotation(
            quotation_number=quotation_data.quotation_number,
            client_id=quotation_data.client_id,
            date=quotation_data.date,
            expiry_date=quotation_data.expiry_date,
            subtotal=quotation_data.subtotal,
            tax_rate=quotation_data.tax_rate,
            tax_amount=quotation_data.tax_amount,
            total=quotation_data.total,
            notes=quotation_data.notes
        )
        
        db.add(db_quotation)
        db.flush()  # Pour obtenir l'ID du devis
        
        # Créer les éléments du devis (supporte lignes personnalisées sans produit)
        for item_data in quotation_data.items:
            pid = getattr(item_data, 'product_id', None)
            if pid is not None:
                # Vérifier l'existence uniquement si un product_id est fourni
                product = db.query(Product).filter(Product.product_id == pid).first()
                if not product:
                    raise HTTPException(status_code=404, detail=f"Produit {pid} non trouvé")
            db_item = QuotationItem(
                quotation_id=db_quotation.quotation_id,
                product_id=pid,
                product_name=item_data.product_name,
                quantity=item_data.quantity,
                price=item_data.price,
                total=item_data.total
            )
            db.add(db_item)
        
        db.commit()
        db.refresh(db_quotation)
        
        return db_quotation
        
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logging.error(f"Erreur lors de la création du devis: {e}")
        raise HTTPException(status_code=500, detail="Erreur serveur")

@router.put("/{quotation_id}", response_model=QuotationResponse)
async def update_quotation(
    quotation_id: int,
    quotation_data: QuotationCreate,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """Mettre à jour un devis existant et ses lignes."""
    try:
        quotation = db.query(Quotation).filter(Quotation.quotation_id == quotation_id).first()
        if not quotation:
            raise HTTPException(status_code=404, detail="Devis non trouvé")

        # Unicité du numéro si modifié
        if quotation.quotation_number != quotation_data.quotation_number:
            existing = db.query(Quotation).filter(Quotation.quotation_number == quotation_data.quotation_number).first()
            if existing and int(existing.quotation_id) != int(quotation_id):
                raise HTTPException(status_code=400, detail="Ce numéro de devis existe déjà")

        # Vérifier client
        client = db.query(Client).filter(Client.client_id == quotation_data.client_id).first()
        if not client:
            raise HTTPException(status_code=404, detail="Client non trouvé")

        # Mettre à jour les champs principaux
        quotation.quotation_number = quotation_data.quotation_number
        quotation.client_id = quotation_data.client_id
        quotation.date = quotation_data.date
        quotation.expiry_date = quotation_data.expiry_date
        quotation.subtotal = quotation_data.subtotal
        quotation.tax_rate = quotation_data.tax_rate
        quotation.tax_amount = quotation_data.tax_amount
        quotation.total = quotation_data.total
        quotation.notes = quotation_data.notes

        # Normaliser un statut éventuel reçu
        try:
            raw_status = getattr(quotation_data, 'status', None)
            if raw_status:
                s = str(raw_status).strip().lower()
                if s in ["draft", "sent", "en attente", "en_attente", "brouillon", "envoyé", "envoye"]:
                    quotation.status = "en attente"
                elif s in ["accepté", "accepte", "accepted"]:
                    quotation.status = "accepté"
                elif s in ["refusé", "refuse", "rejected"]:
                    quotation.status = "refusé"
                elif s in ["expiré", "expire", "expired"]:
                    quotation.status = "expiré"
        except Exception:
            pass

        # Remplacer les lignes (delete-orphan actif)
        for old in list(quotation.items or []):
            try:
                db.delete(old)
            except Exception:
                pass
        db.flush()

        for item_data in (quotation_data.items or []):
            pid = getattr(item_data, 'product_id', None)
            if pid is not None:
                product = db.query(Product).filter(Product.product_id == pid).first()
                if not product:
                    raise HTTPException(status_code=404, detail=f"Produit {pid} non trouvé")
            db_item = QuotationItem(
                quotation_id=quotation.quotation_id,
                product_id=pid,
                product_name=item_data.product_name,
                quantity=item_data.quantity,
                price=item_data.price,
                total=item_data.total
            )
            db.add(db_item)

        db.commit()
        db.refresh(quotation)
        return quotation

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logging.error(f"Erreur lors de la mise à jour du devis: {e}")
        raise HTTPException(status_code=500, detail="Erreur serveur")

@router.put("/{quotation_id}/status")
async def update_quotation_status(
    quotation_id: int,
    payload: dict,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """Mettre à jour le statut d'un devis"""
    try:
        quotation = db.query(Quotation).filter(Quotation.quotation_id == quotation_id).first()
        if not quotation:
            raise HTTPException(status_code=404, detail="Devis non trouvé")
        
        new_status = str(payload.get("status", "")).lower()
        valid_statuses = ["en attente", "accepté", "refusé", "expiré"]
        if new_status not in valid_statuses:
            raise HTTPException(status_code=400, detail="Statut invalide")
        
        quotation.status = new_status
        db.commit()
        
        return {"message": "Statut mis à jour avec succès"}
        
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logging.error(f"Erreur lors de la mise à jour du statut: {e}")
        raise HTTPException(status_code=500, detail="Erreur serveur")

@router.delete("/{quotation_id}")
async def delete_quotation(
    quotation_id: int,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """Supprimer un devis"""
    try:
        quotation = db.query(Quotation).filter(Quotation.quotation_id == quotation_id).first()
        if not quotation:
            raise HTTPException(status_code=404, detail="Devis non trouvé")
        
        db.delete(quotation)
        db.commit()
        
        return {"message": "Devis supprimé avec succès"}
        
    except Exception as e:
        db.rollback()
        logging.error(f"Erreur lors de la suppression du devis: {e}")
        raise HTTPException(status_code=500, detail="Erreur serveur")

@router.post("/{quotation_id}/convert-to-invoice")
async def convert_to_invoice(
    quotation_id: int,
    payload: dict = None,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """Convertir un devis en facture"""
    try:
        from ..database import Invoice, InvoiceItem, InvoicePayment
        
        quotation = db.query(Quotation).filter(Quotation.quotation_id == quotation_id).first()
        if not quotation:
            raise HTTPException(status_code=404, detail="Devis non trouvé")
        
        if quotation.status != "accepté":
            raise HTTPException(status_code=400, detail="Seuls les devis acceptés peuvent être convertis")
        
        # Éviter la double conversion
        existing_invoice_for_quote = db.query(Invoice).filter(Invoice.quotation_id == quotation.quotation_id).first()
        if existing_invoice_for_quote:
            return {"message": "Déjà converti", "invoice_id": existing_invoice_for_quote.invoice_id, "invoice_number": existing_invoice_for_quote.invoice_number}
        
        # Numéro de facture: à partir du payload ou auto-généré avec incrément basé sur le dernier existant
        req_number = None
        try:
            if payload and isinstance(payload, dict):
                req_number = (payload.get("invoice_number") or "").strip() or None
        except Exception:
            req_number = None

        # Préfixe du jour: FAC-YYYYMMDD-
        from datetime import datetime as _dt
        today_prefix = _dt.now().strftime("FAC-%Y%m%d-")

        def _next_number(prefix: str) -> str:
            # Récupérer la dernière facture du jour par ID décroissant
            last = (
                db.query(Invoice)
                .filter(Invoice.invoice_number.ilike(f"{prefix}%"))
                .order_by(Invoice.invoice_id.desc())
                .first()
            )
            if last and isinstance(last.invoice_number, str) and last.invoice_number.startswith(prefix):
                try:
                    last_seq = int(str(last.invoice_number).split("-")[-1])
                except Exception:
                    last_seq = 0
                next_seq = last_seq + 1
            else:
                next_seq = 1
            # Boucle de sécurité pour garantir l'unicité
            while True:
                candidate = f"{prefix}{next_seq:04d}"
                exists = db.query(Invoice).filter(Invoice.invoice_number == candidate).first()
                if not exists:
                    return candidate
                next_seq += 1

        if req_number:
            # Si le numéro demandé existe déjà, on bascule automatiquement sur le prochain disponible du jour
            existing_invoice = db.query(Invoice).filter(Invoice.invoice_number == req_number).first()
            if existing_invoice:
                invoice_number_final = _next_number(today_prefix)
            else:
                invoice_number_final = req_number
        else:
            invoice_number_final = _next_number(today_prefix)
        
        # Due date + paiement initial éventuel
        from datetime import timedelta
        payment_payload = (payload or {}).get('payment') if isinstance(payload, dict) else None
        term_days = 30
        try:
            term_days = int((payload or {}).get('payment_terms') or 30)
        except Exception:
            term_days = 30
        due_date = datetime.now().date() + timedelta(days=term_days)

        # Créer la facture
        db_invoice = Invoice(
            invoice_number=invoice_number_final,
            client_id=quotation.client_id,
            quotation_id=quotation.quotation_id,
            date=datetime.now().date(),
            due_date=due_date,
            subtotal=quotation.subtotal,
            tax_rate=quotation.tax_rate,
            tax_amount=quotation.tax_amount,
            total=quotation.total,
            remaining_amount=quotation.total,
            notes=f"Convertie du devis {quotation.quotation_number}",
            show_tax=bool(float(quotation.tax_rate or 0) > 0),
            price_display="TTC",
        )
        
        db.add(db_invoice)
        db.flush()
        
        # Copier les éléments
        # Conserver la quantité d'origine par produit dans des métadonnées pour affichage ultérieur
        quote_qty_map = {}
        for item in quotation.items:
            try:
                pid = int(item.product_id) if item.product_id is not None else None
                if pid is not None:
                    quote_qty_map[pid] = (quote_qty_map.get(pid, 0) + int(item.quantity or 0))
            except Exception:
                pass
            db_item = InvoiceItem(
                invoice_id=db_invoice.invoice_id,
                product_id=item.product_id,
                product_name=item.product_name,
                quantity=item.quantity,
                price=item.price,
                total=item.total
            )
            db.add(db_item)
        
        # Paiement initial optionnel
        if payment_payload and isinstance(payment_payload, dict):
            try:
                amt = float(payment_payload.get('amount') or 0)
                method = (payment_payload.get('method') or '').strip() or None
                if amt and amt > 0:
                    pay = InvoicePayment(
                        invoice_id=db_invoice.invoice_id,
                        amount=amt,
                        payment_method=method,
                    )
                    db.add(pay)
                    # MAJ montants payés/restants
                    db_invoice.paid_amount = (db_invoice.paid_amount or 0) + amt
                    db_invoice.remaining_amount = max(0, (db_invoice.total or 0) - (db_invoice.paid_amount or 0))
                    # statut
                    if db_invoice.remaining_amount == 0:
                        db_invoice.status = 'payée'
                    elif db_invoice.paid_amount > 0:
                        db_invoice.status = 'partiellement payée'
            except Exception:
                pass

        # Stocker les quantités du devis dans les notes de la facture sous forme de méta balise
        try:
            import json as _json
            if quote_qty_map:
                serialized = _json.dumps([{"product_id": pid, "qty": qty} for pid, qty in quote_qty_map.items()])
                base_notes = (db_invoice.notes or "").strip()
                # Nettoyer une éventuelle ancienne balise
                import re as _re
                if base_notes and "__QUOTE_QTYS__=" in base_notes:
                    base_notes = _re.sub(r"\n?\n?__QUOTE_QTYS__=.*$", "", base_notes, flags=_re.S)
                meta = f"__QUOTE_QTYS__={serialized}"
                db_invoice.notes = (base_notes + ("\n\n" if base_notes else "") + meta).strip()
        except Exception:
            pass

        db.commit()
        
        # Mettre à jour côté devis: optionnel, mais nous laissons la relation se faire via la clé étrangère sur Invoice
        return {"message": "Devis converti en facture avec succès", "invoice_id": db_invoice.invoice_id, "invoice_number": db_invoice.invoice_number}
        
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logging.error(f"Erreur lors de la conversion: {e}")
        raise HTTPException(status_code=500, detail="Erreur serveur")
