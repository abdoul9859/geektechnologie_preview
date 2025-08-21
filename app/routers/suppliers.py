from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List, Optional
from datetime import datetime
import json

from ..database import get_db, User
from ..auth import get_current_user

router = APIRouter(prefix="/api/suppliers", tags=["suppliers"])

# Données en mémoire (temporaire) — vide par défaut
# TODO: remplacer par un modèle SQLAlchemy et des appels DB
suppliers_data = []

@router.get("/")
async def get_suppliers(
    skip: int = 0,
    limit: int = 20,
    search: Optional[str] = None,
    status: Optional[str] = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Récupérer la liste des fournisseurs"""
    try:
        filtered_suppliers = suppliers_data.copy()
        
        # Filtrer par recherche
        if search:
            search_lower = search.lower()
            filtered_suppliers = [
                s for s in filtered_suppliers 
                if search_lower in s["name"].lower() or 
                   search_lower in s["email"].lower() or
                   search_lower in s["contact_person"].lower()
            ]
        
        # Filtrer par statut
        if status:
            filtered_suppliers = [s for s in filtered_suppliers if s["status"] == status]
        
        # Pagination
        total = len(filtered_suppliers)
        suppliers = filtered_suppliers[skip:skip + limit]
        
        return {
            "suppliers": suppliers,
            "total": total,
            "page": (skip // limit) + 1,
            "pages": (total + limit - 1) // limit
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/{supplier_id}")
async def get_supplier(
    supplier_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Récupérer un fournisseur par ID"""
    supplier = next((s for s in suppliers_data if s["id"] == supplier_id), None)
    if not supplier:
        raise HTTPException(status_code=404, detail="Fournisseur non trouvé")
    return supplier

@router.post("/")
async def create_supplier(
    supplier_data: dict,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Créer un nouveau fournisseur"""
    try:
        new_id = max([s["id"] for s in suppliers_data], default=0) + 1
        new_supplier = {
            "id": new_id,
            "name": supplier_data.get("name"),
            "email": supplier_data.get("email"),
            "phone": supplier_data.get("phone"),
            "address": supplier_data.get("address"),
            "contact_person": supplier_data.get("contact_person"),
            "tax_number": supplier_data.get("tax_number"),
            "created_at": datetime.now().isoformat(),
            "status": "active",
            "total_purchases": 0,
            "outstanding_balance": 0
        }
        suppliers_data.append(new_supplier)
        return new_supplier
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.put("/{supplier_id}")
async def update_supplier(
    supplier_id: int,
    supplier_data: dict,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Mettre à jour un fournisseur"""
    try:
        supplier_index = next((i for i, s in enumerate(suppliers_data) if s["id"] == supplier_id), None)
        if supplier_index is None:
            raise HTTPException(status_code=404, detail="Fournisseur non trouvé")
        
        # Mettre à jour les champs
        suppliers_data[supplier_index].update({
            "name": supplier_data.get("name", suppliers_data[supplier_index]["name"]),
            "email": supplier_data.get("email", suppliers_data[supplier_index]["email"]),
            "phone": supplier_data.get("phone", suppliers_data[supplier_index]["phone"]),
            "address": supplier_data.get("address", suppliers_data[supplier_index]["address"]),
            "contact_person": supplier_data.get("contact_person", suppliers_data[supplier_index]["contact_person"]),
            "tax_number": supplier_data.get("tax_number", suppliers_data[supplier_index]["tax_number"]),
            "status": supplier_data.get("status", suppliers_data[supplier_index]["status"])
        })
        
        return suppliers_data[supplier_index]
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.delete("/{supplier_id}")
async def delete_supplier(
    supplier_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Supprimer un fournisseur"""
    try:
        supplier_index = next((i for i, s in enumerate(suppliers_data) if s["id"] == supplier_id), None)
        if supplier_index is None:
            raise HTTPException(status_code=404, detail="Fournisseur non trouvé")
        
        deleted_supplier = suppliers_data.pop(supplier_index)
        return {"message": "Fournisseur supprimé avec succès", "supplier": deleted_supplier}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/stats/summary")
async def get_suppliers_stats(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Récupérer les statistiques des fournisseurs"""
    try:
        total_suppliers = len(suppliers_data)
        active_suppliers = len([s for s in suppliers_data if s["status"] == "active"])
        total_purchases = sum(s["total_purchases"] for s in suppliers_data)
        outstanding_balance = sum(s["outstanding_balance"] for s in suppliers_data)
        
        return {
            "total_suppliers": total_suppliers,
            "active_suppliers": active_suppliers,
            "inactive_suppliers": total_suppliers - active_suppliers,
            "total_purchases": total_purchases,
            "outstanding_balance": outstanding_balance,
            "average_purchase": total_purchases / total_suppliers if total_suppliers > 0 else 0
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
