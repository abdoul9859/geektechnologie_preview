from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import func
from typing import Optional, List
from datetime import datetime, date
from decimal import Decimal

from ..database import (
    get_db, User, Supplier, Product, 
    SupplierInvoice, SupplierInvoiceItem, SupplierInvoicePayment,
    BankTransaction, StockMovement
)
from ..auth import get_current_user
from ..schemas import (
    SupplierInvoiceCreate, SupplierInvoiceResponse, SupplierInvoiceUpdate,
    SupplierInvoicePaymentCreate, SupplierInvoicePaymentResponse
)

router = APIRouter(prefix="/api/supplier-invoices", tags=["supplier-invoices"])

@router.get("/", response_model=dict)
async def get_supplier_invoices(
    skip: int = 0,
    limit: int = 50,
    search: Optional[str] = None,
    supplier_id: Optional[int] = None,
    status: Optional[str] = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Récupérer la liste des factures fournisseur"""
    try:
        query = db.query(SupplierInvoice).join(Supplier, Supplier.supplier_id == SupplierInvoice.supplier_id, isouter=True)
        
        if search:
            search_term = f"%{search.lower()}%"
            query = query.filter(
                func.lower(SupplierInvoice.invoice_number).like(search_term) |
                func.lower(Supplier.name).like(search_term)
            )
        
        if supplier_id:
            query = query.filter(SupplierInvoice.supplier_id == supplier_id)
            
        if status:
            query = query.filter(SupplierInvoice.status == status)
        
        # Mettre à jour les statuts basés sur les dates d'échéance
        today = date.today()
        overdue_invoices = query.filter(
            SupplierInvoice.due_date < datetime.combine(today, datetime.min.time()),
            SupplierInvoice.remaining_amount > 0,
            SupplierInvoice.status != "paid"
        ).all()
        
        for invoice in overdue_invoices:
            invoice.status = "overdue"
        
        db.commit()
        
        total = query.count()
        invoices = query.offset(skip).limit(limit).all()
        
        # Enrichir avec les données des fournisseurs
        result_invoices = []
        for invoice in invoices:
            supplier = db.query(Supplier).filter(Supplier.supplier_id == invoice.supplier_id).first()
            invoice_dict = {
                "invoice_id": invoice.invoice_id,
                "supplier_id": invoice.supplier_id,
                "supplier_name": supplier.name if supplier else "Fournisseur supprimé",
                "invoice_number": invoice.invoice_number,
                "invoice_date": invoice.invoice_date,
                "due_date": invoice.due_date,
                "subtotal": float(invoice.subtotal),
                "tax_rate": float(invoice.tax_rate),
                "tax_amount": float(invoice.tax_amount),
                "total": float(invoice.total),
                "paid_amount": float(invoice.paid_amount),
                "remaining_amount": float(invoice.remaining_amount),
                "status": invoice.status,
                "payment_method": invoice.payment_method,
                "notes": invoice.notes,
                "created_at": invoice.created_at
            }
            result_invoices.append(invoice_dict)
        
        return {
            "invoices": result_invoices,
            "total": total,
            "page": (skip // limit) + 1,
            "pages": (total + limit - 1) // limit if total > 0 else 1
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/{invoice_id}", response_model=SupplierInvoiceResponse)
async def get_supplier_invoice(
    invoice_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Récupérer une facture fournisseur par ID"""
    invoice = db.query(SupplierInvoice).filter(SupplierInvoice.invoice_id == invoice_id).first()
    if not invoice:
        raise HTTPException(status_code=404, detail="Facture non trouvée")
    
    # Enrichir avec les données du fournisseur
    supplier = db.query(Supplier).filter(Supplier.supplier_id == invoice.supplier_id).first()
    
    # Récupérer les éléments de la facture
    items = db.query(SupplierInvoiceItem).filter(SupplierInvoiceItem.invoice_id == invoice_id).all()
    
    return SupplierInvoiceResponse(
        invoice_id=invoice.invoice_id,
        supplier_id=invoice.supplier_id,
        supplier_name=supplier.name if supplier else "Fournisseur supprimé",
        invoice_number=invoice.invoice_number,
        invoice_date=invoice.invoice_date,
        due_date=invoice.due_date,
        subtotal=invoice.subtotal,
        tax_rate=invoice.tax_rate,
        tax_amount=invoice.tax_amount,
        total=invoice.total,
        paid_amount=invoice.paid_amount,
        remaining_amount=invoice.remaining_amount,
        status=invoice.status,
        payment_method=invoice.payment_method,
        notes=invoice.notes,
        created_at=invoice.created_at,
        items=[
            {
                "item_id": item.item_id,
                "product_id": item.product_id,
                "product_name": item.product_name,
                "quantity": item.quantity,
                "unit_price": item.unit_price,
                "total": item.total,
                "description": item.description
            }
            for item in items
        ]
    )

@router.post("/", response_model=SupplierInvoiceResponse)
async def create_supplier_invoice(
    invoice_data: SupplierInvoiceCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Créer une nouvelle facture fournisseur"""
    try:
        # Vérifier que le fournisseur existe
        supplier = db.query(Supplier).filter(Supplier.supplier_id == invoice_data.supplier_id).first()
        if not supplier:
            raise HTTPException(status_code=404, detail="Fournisseur non trouvé")
        
        # Vérifier l'unicité du numéro de facture
        existing = db.query(SupplierInvoice).filter(SupplierInvoice.invoice_number == invoice_data.invoice_number).first()
        if existing:
            raise HTTPException(status_code=400, detail="Ce numéro de facture existe déjà")
        
        # Calculer le remaining_amount
        remaining_amount = invoice_data.total
        
        # Créer la facture
        invoice = SupplierInvoice(
            supplier_id=invoice_data.supplier_id,
            invoice_number=invoice_data.invoice_number,
            invoice_date=invoice_data.invoice_date,
            due_date=invoice_data.due_date,
            subtotal=invoice_data.subtotal,
            tax_rate=invoice_data.tax_rate,
            tax_amount=invoice_data.tax_amount,
            total=invoice_data.total,
            paid_amount=0,
            remaining_amount=remaining_amount,
            status="pending",
            payment_method=invoice_data.payment_method,
            notes=invoice_data.notes
        )
        
        db.add(invoice)
        db.flush()  # Pour obtenir l'ID
        
        # Créer les éléments de la facture
        for item_data in invoice_data.items:
            item = SupplierInvoiceItem(
                invoice_id=invoice.invoice_id,
                product_id=item_data.product_id,
                product_name=item_data.product_name,
                quantity=item_data.quantity,
                unit_price=item_data.unit_price,
                total=item_data.total,
                description=item_data.description
            )
            db.add(item)
            
            # Mettre à jour le stock si un produit est spécifié
            if item_data.product_id:
                product = db.query(Product).filter(Product.product_id == item_data.product_id).first()
                if product:
                    # Augmenter le stock (entrée de marchandises)
                    product.quantity += item_data.quantity
                    
                    # Créer un mouvement de stock
                    movement = StockMovement(
                        product_id=item_data.product_id,
                        quantity=item_data.quantity,
                        movement_type="IN",
                        reference_type="SUPPLIER_INVOICE",
                        reference_id=invoice.invoice_id,
                        unit_price=item_data.unit_price,
                        notes=f"Réception facture fournisseur {invoice.invoice_number}"
                    )
                    db.add(movement)
        
        db.commit()
        db.refresh(invoice)
        
        return await get_supplier_invoice(invoice.invoice_id, current_user, db)
        
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))

@router.put("/{invoice_id}", response_model=SupplierInvoiceResponse)
async def update_supplier_invoice(
    invoice_id: int,
    invoice_data: SupplierInvoiceUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Mettre à jour une facture fournisseur"""
    try:
        invoice = db.query(SupplierInvoice).filter(SupplierInvoice.invoice_id == invoice_id).first()
        if not invoice:
            raise HTTPException(status_code=404, detail="Facture non trouvée")
        
        # Mettre à jour les champs modifiables
        for field, value in invoice_data.dict(exclude_unset=True).items():
            if hasattr(invoice, field):
                setattr(invoice, field, value)
        
        # Recalculer le remaining_amount si nécessaire
        if invoice_data.total is not None:
            invoice.remaining_amount = invoice.total - invoice.paid_amount
        
        # Mettre à jour le statut automatiquement
        if invoice.remaining_amount <= 0:
            invoice.status = "paid"
        elif invoice.paid_amount > 0:
            invoice.status = "partial"
        elif invoice.due_date and invoice.due_date < datetime.now():
            invoice.status = "overdue"
        else:
            invoice.status = "pending"
        
        db.commit()
        db.refresh(invoice)
        
        return await get_supplier_invoice(invoice_id, current_user, db)
        
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))

@router.delete("/{invoice_id}")
async def delete_supplier_invoice(
    invoice_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Supprimer une facture fournisseur"""
    try:
        invoice = db.query(SupplierInvoice).filter(SupplierInvoice.invoice_id == invoice_id).first()
        if not invoice:
            raise HTTPException(status_code=404, detail="Facture non trouvée")
        
        if invoice.paid_amount > 0:
            raise HTTPException(status_code=400, detail="Impossible de supprimer une facture avec des paiements")
        
        # Restaurer le stock pour les produits liés
        items = db.query(SupplierInvoiceItem).filter(SupplierInvoiceItem.invoice_id == invoice_id).all()
        for item in items:
            if item.product_id:
                product = db.query(Product).filter(Product.product_id == item.product_id).first()
                if product:
                    product.quantity -= item.quantity
                    
                    # Créer un mouvement de stock de correction
                    movement = StockMovement(
                        product_id=item.product_id,
                        quantity=-item.quantity,
                        movement_type="OUT",
                        reference_type="SUPPLIER_INVOICE_DELETE",
                        reference_id=invoice_id,
                        unit_price=item.unit_price,
                        notes=f"Suppression facture fournisseur {invoice.invoice_number}"
                    )
                    db.add(movement)
        
        db.delete(invoice)
        db.commit()
        
        return {"message": "Facture fournisseur supprimée avec succès"}
        
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/{invoice_id}/payments", response_model=SupplierInvoicePaymentResponse)
async def create_payment(
    invoice_id: int,
    payment_data: SupplierInvoicePaymentCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Ajouter un paiement à une facture fournisseur"""
    try:
        invoice = db.query(SupplierInvoice).filter(SupplierInvoice.invoice_id == invoice_id).first()
        if not invoice:
            raise HTTPException(status_code=404, detail="Facture non trouvée")
        
        if payment_data.amount <= 0:
            raise HTTPException(status_code=400, detail="Le montant doit être positif")
        
        if payment_data.amount > invoice.remaining_amount:
            raise HTTPException(status_code=400, detail="Le montant dépasse le solde restant")
        
        # Créer le paiement
        payment = SupplierInvoicePayment(
            supplier_invoice_id=invoice_id,
            amount=payment_data.amount,
            payment_date=payment_data.payment_date,
            payment_method=payment_data.payment_method,
            reference=payment_data.reference,
            notes=payment_data.notes
        )
        db.add(payment)
        
        # Mettre à jour la facture
        invoice.paid_amount += payment_data.amount
        invoice.remaining_amount = invoice.total - invoice.paid_amount
        
        # Mettre à jour le statut
        if invoice.remaining_amount <= 0:
            invoice.status = "paid"
        else:
            invoice.status = "partial"
        
        # Créer une transaction bancaire de sortie (paiement fournisseur)
        bank_transaction = BankTransaction(
            type="exit",
            motif="Paiement fournisseur",
            description=f"Paiement facture {invoice.invoice_number} - {invoice.supplier.name if invoice.supplier else 'Fournisseur'}",
            amount=payment_data.amount,
            date=payment_data.payment_date.date(),
            method="virement" if payment_data.payment_method in ["virement", "virement bancaire"] else "cheque",
            reference=payment_data.reference or f"PAY-{invoice.invoice_number}"
        )
        db.add(bank_transaction)
        
        db.commit()
        db.refresh(payment)
        
        return SupplierInvoicePaymentResponse(
            payment_id=payment.payment_id,
            supplier_invoice_id=payment.supplier_invoice_id,
            amount=payment.amount,
            payment_date=payment.payment_date,
            payment_method=payment.payment_method,
            reference=payment.reference,
            notes=payment.notes
        )
        
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/{invoice_id}/payments", response_model=List[SupplierInvoicePaymentResponse])
async def get_payments(
    invoice_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Récupérer les paiements d'une facture fournisseur"""
    payments = db.query(SupplierInvoicePayment).filter(SupplierInvoicePayment.supplier_invoice_id == invoice_id).all()
    
    return [
        SupplierInvoicePaymentResponse(
            payment_id=payment.payment_id,
            supplier_invoice_id=payment.supplier_invoice_id,
            amount=payment.amount,
            payment_date=payment.payment_date,
            payment_method=payment.payment_method,
            reference=payment.reference,
            notes=payment.notes
        )
        for payment in payments
    ]

@router.get("/stats/summary")
async def get_summary_stats(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Récupérer les statistiques des factures fournisseur"""
    try:
        total_invoices = db.query(SupplierInvoice).count()
        pending_invoices = db.query(SupplierInvoice).filter(SupplierInvoice.status == "pending").count()
        overdue_invoices = db.query(SupplierInvoice).filter(SupplierInvoice.status == "overdue").count()
        
        total_amount = db.query(func.sum(SupplierInvoice.total)).scalar() or 0
        paid_amount = db.query(func.sum(SupplierInvoice.paid_amount)).scalar() or 0
        remaining_amount = total_amount - paid_amount
        
        return {
            "total_invoices": total_invoices,
            "pending_invoices": pending_invoices,
            "overdue_invoices": overdue_invoices,
            "total_amount": float(total_amount),
            "paid_amount": float(paid_amount),
            "remaining_amount": float(remaining_amount)
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
