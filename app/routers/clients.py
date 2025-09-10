from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List, Optional
from sqlalchemy import func
from ..database import get_db, Client, Invoice
from ..schemas import ClientCreate, ClientUpdate, ClientResponse
from ..auth import get_current_user
import logging

router = APIRouter(prefix="/api/clients", tags=["clients"])

@router.get("/", response_model=List[ClientResponse])
async def list_clients(
    skip: int = 0,
    limit: int = 100,
    search: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """Lister les clients avec recherche"""
    query = db.query(Client)
    
    if search:
        query = query.filter(
            Client.name.ilike(f"%{search}%") |
            Client.email.ilike(f"%{search}%") |
            Client.phone.ilike(f"%{search}%")
        )
    
    clients = query.offset(skip).limit(limit).all()
    return clients

@router.get("/{client_id}", response_model=ClientResponse)
async def get_client(
    client_id: int,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """Obtenir un client par ID"""
    client = db.query(Client).filter(Client.client_id == client_id).first()
    if not client:
        raise HTTPException(status_code=404, detail="Client non trouvé")
    return client

@router.get("/{client_id}/details")
async def get_client_details(
    client_id: int,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """Détails étendus d'un client: infos, factures, dettes et totaux."""
    client = db.query(Client).filter(Client.client_id == client_id).first()
    if not client:
        raise HTTPException(status_code=404, detail="Client non trouvé")

    # Factures du client
    invoices = (
        db.query(Invoice)
        .filter(Invoice.client_id == client_id)
        .order_by(Invoice.date.desc())
        .all()
    )

    # Dettes du client: la fonctionnalité dettes est simulée côté API debts.
    # Ici, on retourne un tableau vide pour éviter une dépendance sur un modèle inexistant.
    debts = []

    # Agrégats
    total_invoiced = float(sum([float(i.total or 0) for i in invoices]))
    total_paid = float(sum([float(i.paid_amount or 0) for i in invoices]))
    total_due = total_invoiced - total_paid
    total_debts = float(sum([float(getattr(d, 'amount', 0) or 0) for d in debts]))

    return {
        "client": ClientResponse.from_orm(client),
        "stats": {
            "total_invoiced": total_invoiced,
            "total_paid": total_paid,
            "total_due": total_due,
            "total_debts": total_debts
        },
        "invoices": [
            {
                "invoice_id": inv.invoice_id,
                "invoice_number": inv.invoice_number,
                "date": inv.date,
                "status": inv.status,
                "total": float(inv.total or 0),
                "paid": float(inv.paid_amount or 0),
                "remaining": float(inv.remaining_amount or 0)
            }
            for inv in invoices
        ],
        "debts": [
            {
                "debt_id": getattr(d, 'debt_id', None),
                "amount": float(getattr(d, 'amount', 0) or 0),
                "due_date": getattr(d, 'due_date', None),
                "status": getattr(d, 'status', None),
                "notes": getattr(d, 'notes', None)
            }
            for d in debts
        ]
    }

@router.post("/", response_model=ClientResponse)
async def create_client(
    client_data: ClientCreate,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """Créer un nouveau client"""
    try:
        # Vérifier l'unicité du numéro de téléphone s'il est fourni
        if client_data.phone:
            incoming_phone = client_data.phone.strip()
            if incoming_phone:
                existing = (
                    db.query(Client)
                    .filter(func.lower(Client.phone) == incoming_phone.lower())
                    .first()
                )
                if existing:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail="Un client avec ce numéro de téléphone existe déjà",
                    )
        
        # Normaliser les données (trim + valeurs vides -> None + défaut pays)
        payload = client_data.dict()
        for key in ["name","contact","email","phone","address","city","postal_code","country","tax_number","notes"]:
            if key in payload and isinstance(payload[key], str):
                payload[key] = payload[key].strip()
                if payload[key] == "":
                    payload[key] = None
        if not payload.get("country"):
            payload["country"] = "Sénégal"
        
        # Sécuriser les longueurs selon le schéma DB
        def _cut(s, n):
            try:
                return (s or None) if s is None else str(s)[:n]
            except Exception:
                return s
        payload["name"] = _cut(payload.get("name"), 100)
        payload["contact"] = _cut(payload.get("contact"), 100)
        payload["email"] = _cut(payload.get("email"), 100)
        payload["phone"] = _cut(payload.get("phone"), 20)
        payload["address"] = payload.get("address")  # Text
        payload["city"] = _cut(payload.get("city"), 50)
        payload["postal_code"] = _cut(payload.get("postal_code"), 10)
        payload["country"] = _cut(payload.get("country"), 50) or "Sénégal"
        payload["tax_number"] = _cut(payload.get("tax_number"), 50)
        
        db_client = Client(**payload)
        db.add(db_client)
        db.flush()  # Catch integrity errors here
        db.commit()
        db.refresh(db_client)
        return db_client
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logging.exception("Erreur lors de la création du client")
        # Renvoyer le détail si disponible pour faciliter le debug côté UI
        msg = str(getattr(e, 'orig', None) or e) or "Erreur serveur"
        raise HTTPException(status_code=500, detail=msg)

@router.put("/{client_id}", response_model=ClientResponse)
async def update_client(
    client_id: int,
    client_data: ClientUpdate,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """Mettre à jour un client"""
    try:
        client = db.query(Client).filter(Client.client_id == client_id).first()
        if not client:
            raise HTTPException(status_code=404, detail="Client non trouvé")
        
        update_data = client_data.dict(exclude_unset=True)

        # Vérifier l'unicité du numéro si modifié
        new_phone = update_data.get("phone")
        if new_phone is not None:
            new_phone_stripped = new_phone.strip()
            if new_phone_stripped:
                conflict = (
                    db.query(Client)
                    .filter(
                        func.lower(Client.phone) == new_phone_stripped.lower(),
                        Client.client_id != client_id,
                    )
                    .first()
                )
                if conflict:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail="Un autre client possède déjà ce numéro de téléphone",
                    )
            else:
                # Autoriser la mise à jour vers une valeur vide/null si souhaité
                update_data["phone"] = None
        for field, value in update_data.items():
            setattr(client, field, value)
        
        db.commit()
        db.refresh(client)
        return client
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logging.error(f"Erreur lors de la mise à jour du client: {e}")
        raise HTTPException(status_code=500, detail="Erreur serveur")

@router.delete("/{client_id}")
async def delete_client(
    client_id: int,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """Supprimer un client"""
    try:
        client = db.query(Client).filter(Client.client_id == client_id).first()
        if not client:
            raise HTTPException(status_code=404, detail="Client non trouvé")
        
        # Empêcher la suppression si des factures ou devis référencent le client
        inv_count = db.query(func.count()).select_from(Invoice).filter(Invoice.client_id == client_id).scalar() or 0
        try:
            from ..database import Quotation
            quote_count = db.query(func.count()).select_from(Quotation).filter(Quotation.client_id == client_id).scalar() or 0
        except Exception:
            quote_count = 0
        if inv_count or quote_count:
            raise HTTPException(status_code=400, detail=f"Impossible de supprimer: {inv_count} facture(s) et {quote_count} devis référencent ce client")
        
        db.delete(client)
        db.commit()
        return {"message": "Client supprimé avec succès"}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logging.error(f"Erreur lors de la suppression du client: {e}")
        raise HTTPException(status_code=500, detail="Erreur serveur")
