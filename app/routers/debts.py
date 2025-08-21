from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import func
from typing import Optional
from datetime import datetime, date

from ..database import (
    get_db, User, Invoice, Client, InvoicePayment,
    Supplier, SupplierDebt, SupplierDebtPayment
)
from ..auth import get_current_user

router = APIRouter(prefix="/api/debts", tags=["debts"])

@router.get("/")
async def get_debts(
    skip: int = 0,
    limit: int = 20,
    search: Optional[str] = None,
    type: Optional[str] = None,
    status: Optional[str] = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Récupérer les dettes clients automatiquement depuis les factures."""
    try:
        # Jointure factures/clients, filtrage SQL: créances = toutes factures avec solde > 0 (partiel ou en attente)
        remaining_sql = func.coalesce(Invoice.remaining_amount, Invoice.total - func.coalesce(Invoice.paid_amount, 0))
        q = (
            db.query(Invoice, Client)
            .join(Client, Client.client_id == Invoice.client_id, isouter=True)
            .filter(remaining_sql > 0)
        )

        if search:
            s = f"%{search.lower()}%"
            q = q.filter(
                func.lower(Invoice.invoice_number).like(s) | func.lower(Client.name).like(s)
            )

        rows = q.all()

        # Construire la liste (factures partiellement payées ou en attente)
        debts_all = []
        today = date.today()
        for inv, cl in rows:
            amount = float(inv.total or 0)
            paid = float(inv.paid_amount or 0)
            remaining = float(inv.remaining_amount or (amount - paid))
            # Statut calculé (pending, partial, overdue)
            overdue = bool(inv.due_date and getattr(inv.due_date, 'date', lambda: inv.due_date)() < today and remaining > 0)
            if remaining <= 0:
                st = "paid"
            elif overdue:
                st = "overdue"
            else:
                st = ("partial" if paid > 0 else "pending")
            # Filtre statut si demandé
            if status and st != status:
                continue
            debts_all.append({
                "id": int(inv.invoice_id),
                "type": "client",
                "entity_id": int(inv.client_id) if inv.client_id is not None else None,
                "entity_name": getattr(cl, 'name', None),
                "reference": inv.invoice_number,
                "invoice_number": inv.invoice_number,
                "amount": amount,
                "paid_amount": paid,
                "remaining_amount": remaining,
                "date": inv.date,
                "due_date": inv.due_date,
                "created_at": inv.created_at,
                "status": st,
                "days_overdue": ( (today - inv.due_date.date()).days if (inv.due_date and remaining > 0 and hasattr(inv.due_date, 'date')) else 0 ),
                "description": None,
            })

        # Pagination côté Python sur la liste filtrée
        total = len(debts_all)
        debts = debts_all[skip: skip + limit]
        
        return {
            "debts": debts,
            "total": total,
            "page": (skip // limit) + 1,
            "pages": (total + limit - 1) // limit
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/{debt_id}")
async def get_debt(
    debt_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Récupérer une dette par ID"""
    inv = db.query(Invoice).filter(Invoice.invoice_id == debt_id).first()
    if not inv:
        raise HTTPException(status_code=404, detail="Dette non trouvée")
    cl = db.query(Client).filter(Client.client_id == inv.client_id).first() if inv.client_id else None
    amount = float(inv.total or 0)
    paid = float(inv.paid_amount or 0)
    remaining = float(inv.remaining_amount or (amount - paid))
    today = date.today()
    overdue = bool(inv.due_date and getattr(inv.due_date, 'date', lambda: inv.due_date)() < today and remaining > 0)
    st = "paid" if remaining <= 0 else ("overdue" if overdue else ("partial" if paid > 0 else "pending"))
    return {
        "id": int(inv.invoice_id),
        "type": "client",
        "entity_id": int(inv.client_id) if inv.client_id is not None else None,
        "entity_name": getattr(cl, 'name', None),
        "reference": inv.invoice_number,
        "invoice_number": inv.invoice_number,
        "amount": amount,
        "paid_amount": paid,
        "remaining_amount": remaining,
        "date": inv.date,
        "due_date": inv.due_date,
        "created_at": inv.created_at,
        "status": st,
        "days_overdue": ( (today - inv.due_date.date()).days if (inv.due_date and remaining > 0 and hasattr(inv.due_date, 'date')) else 0 ),
        "description": None,
    }

@router.post("/")
async def create_debt(
    debt_data: dict,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Créer une dette fournisseur."""
    try:
        if debt_data.get("type") != "supplier":
            raise HTTPException(status_code=405, detail="Création limitée aux dettes fournisseurs")

        supplier_id = debt_data.get("entity_id") or debt_data.get("supplier_id")
        if not supplier_id:
            raise HTTPException(status_code=400, detail="Fournisseur requis")
        sup = db.query(Supplier).filter(Supplier.supplier_id == supplier_id).first()
        if not sup:
            raise HTTPException(status_code=404, detail="Fournisseur non trouvé")

        amount = float(debt_data.get("amount") or 0)
        paid = 0.0  # création simplifiée: non payé au départ
        if amount <= 0:
            raise HTTPException(status_code=400, detail="Montant invalide")

        debt = SupplierDebt(
            supplier_id=supplier_id,
            reference=str(debt_data.get("reference") or "DEBT-" + datetime.now().strftime("%Y%m%d%H%M%S")),
            date=debt_data.get("date"),
            due_date=debt_data.get("due_date"),
            amount=amount,
            paid_amount=paid,
            remaining_amount=amount - paid,
            status=("paid" if amount - paid == 0 else ("partial" if paid > 0 else "pending")),
            description=debt_data.get("description"),
            notes=debt_data.get("notes"),
        )
        db.add(debt)
        db.commit()
        db.refresh(debt)
        return {
            "id": debt.debt_id,
            "type": "supplier",
            "entity_id": debt.supplier_id,
            "entity_name": sup.name,
            "reference": debt.reference,
            "amount": float(debt.amount or 0),
            "paid_amount": float(debt.paid_amount or 0),
            "remaining_amount": float(debt.remaining_amount or 0),
            "date": debt.date,
            "due_date": debt.due_date,
            "status": debt.status,
            "description": debt.description,
            "notes": debt.notes,
        }
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))

@router.put("/{debt_id}")
async def update_debt(
    debt_id: int,
    debt_data: dict,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Mettre à jour une dette"""
    # Mise à jour: uniquement dettes fournisseurs
    try:
        d = db.query(SupplierDebt).filter(SupplierDebt.debt_id == debt_id).first()
        if not d:
            raise HTTPException(status_code=405, detail="Modification réservée aux dettes fournisseurs")
        if debt_data.get("type") and debt_data.get("type") != "supplier":
            raise HTTPException(status_code=400, detail="Type invalide")
        # Champs modifiables
        for field in ["reference", "date", "due_date", "description", "notes"]:
            if field in debt_data:
                setattr(d, field, debt_data[field])
        if "amount" in debt_data or "paid_amount" in debt_data:
            amount = float(debt_data.get("amount") if "amount" in debt_data else (d.amount or 0))
            paid = float(debt_data.get("paid_amount") if "paid_amount" in debt_data else (d.paid_amount or 0))
            if amount <= 0 or paid < 0 or paid > amount:
                raise HTTPException(status_code=400, detail="Montants invalides")
            d.amount = amount
            d.paid_amount = paid
            d.remaining_amount = amount - paid
            d.status = "paid" if d.remaining_amount == 0 else ("partial" if d.paid_amount > 0 else "pending")
        db.commit()
        db.refresh(d)
        sup = db.query(Supplier).filter(Supplier.supplier_id == d.supplier_id).first()
        return {
            "id": d.debt_id,
            "type": "supplier",
            "entity_id": d.supplier_id,
            "entity_name": getattr(sup, 'name', None),
            "reference": d.reference,
            "amount": float(d.amount or 0),
            "paid_amount": float(d.paid_amount or 0),
            "remaining_amount": float(d.remaining_amount or 0),
            "date": d.date,
            "due_date": d.due_date,
            "status": d.status,
            "description": d.description,
            "notes": d.notes,
        }
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))

@router.delete("/{debt_id}")
async def delete_debt(
    debt_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Supprimer une dette"""
    # Suppression: uniquement dettes fournisseurs
    try:
        d = db.query(SupplierDebt).filter(SupplierDebt.debt_id == debt_id).first()
        if not d:
            raise HTTPException(status_code=405, detail="Suppression réservée aux dettes fournisseurs")
        db.delete(d)
        db.commit()
        return {"message": "Dette fournisseur supprimée"}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/{debt_id}/payments")
async def record_payment(
    debt_id: int,
    payment_data: dict,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Enregistrer un paiement pour une dette"""
    try:
        # Paiement sur dette fournisseur si existe, sinon paiement facture client
        d = db.query(SupplierDebt).filter(SupplierDebt.debt_id == debt_id).first()
        if d:
            amount = float(payment_data.get("amount", 0))
            if amount <= 0:
                raise HTTPException(status_code=400, detail="Le montant du paiement doit être positif")
            if amount > float(d.remaining_amount or (d.amount or 0) - (d.paid_amount or 0)):
                raise HTTPException(status_code=400, detail="Le montant dépasse le solde restant")
            pay = SupplierDebtPayment(
                debt_id=d.debt_id,
                amount=amount,
                payment_method=payment_data.get("method"),
                reference=payment_data.get("reference"),
                notes=payment_data.get("notes")
            )
            db.add(pay)
            d.paid_amount = (d.paid_amount or 0) + amount
            d.remaining_amount = (d.amount or 0) - (d.paid_amount or 0)
            if d.remaining_amount <= 0:
                d.remaining_amount = 0
                d.status = "paid"
            elif d.paid_amount > 0:
                d.status = "partial"
            db.commit()
            return {"message": "Paiement enregistré", "remaining": float(d.remaining_amount or 0)}

        # Sinon: dette client via facture
        inv = db.query(Invoice).filter(Invoice.invoice_id == debt_id).first()
        if not inv:
            raise HTTPException(status_code=404, detail="Dette/Facture non trouvée")

        amount = float(payment_data.get("amount", 0))
        if amount <= 0:
            raise HTTPException(status_code=400, detail="Le montant du paiement doit être positif")
        
        remaining = float(inv.remaining_amount or 0)
        if amount > remaining:
            raise HTTPException(status_code=400, detail="Le montant dépasse le solde restant")

        pay = InvoicePayment(
            invoice_id=inv.invoice_id,
            amount=amount,
            payment_method=payment_data.get("method"),
            reference=payment_data.get("reference"),
            notes=payment_data.get("notes")
        )
        db.add(pay)

        inv.paid_amount = (inv.paid_amount or 0) + amount
        inv.remaining_amount = (inv.total or 0) - (inv.paid_amount or 0)
        if inv.remaining_amount <= 0:
            inv.remaining_amount = 0
            inv.status = "payée"
        elif inv.paid_amount > 0:
            inv.status = "partiellement payée"

        db.commit()
        return {"message": "Paiement enregistré", "remaining": float(inv.remaining_amount or 0)}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/stats/summary")
async def get_debts_stats(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Récupérer les statistiques des dettes"""
    try:
        # Statistiques basées sur les factures: inclure factures avec solde > 0 (pending ou partial)
        invs = db.query(Invoice).all()
        def remaining_of(i):
            return float(i.remaining_amount if i.remaining_amount is not None else max(0.0, float(i.total or 0) - float(i.paid_amount or 0)))
        open_invoices = [i for i in invs if remaining_of(i) > 0]
        total_amount = sum(float(i.total or 0) for i in open_invoices)
        total_paid = sum(float(i.paid_amount or 0) for i in open_invoices)
        total_remaining = sum(remaining_of(i) for i in open_invoices)
        # Overdue: due_date passée et solde > 0
        today = date.today()
        overdue = [i for i in open_invoices if (i.due_date and getattr(i.due_date, 'date', lambda: i.due_date)() < today and remaining_of(i) > 0)]
        # Pending: solde > 0, aucun paiement et non overdue
        pending = [i for i in open_invoices if float(i.paid_amount or 0) == 0 and not (i in overdue)]
        return {
            "total_debts": len(open_invoices),
            "client_debts_count": len(open_invoices),
            "supplier_debts_count": 0,
            "total_amount": total_amount,
            "total_paid": total_paid,
            "total_remaining": total_remaining,
            "overdue_count": len(overdue),
            "overdue_amount": sum(float(i.remaining_amount or 0) for i in overdue),
            "pending_count": len(pending),
            "pending_amount": sum(remaining_of(i) for i in pending)
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
