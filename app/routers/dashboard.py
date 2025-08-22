from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import func, desc, and_, or_
from typing import Optional
from datetime import datetime, timedelta, date
from functools import lru_cache
import time
import logging

from ..database import get_db, User
from ..database import (
    Invoice, InvoiceItem, InvoicePayment, Quotation, Product, ProductVariant,
    Client, StockMovement, SupplierInvoice, SupplierInvoicePayment
)
from ..auth import get_current_user

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])

# Cache simple pour les stats (5 minutes)
_cache = {}
_cache_duration = 300  # 5 minutes en secondes

def _get_cache_key(*args):
    """Génère une clé de cache basée sur les arguments"""
    return "|".join(str(arg) for arg in args)

def _is_cache_valid(cache_entry):
    """Vérifie si l'entrée de cache est encore valide"""
    return cache_entry and (time.time() - cache_entry['timestamp']) < _cache_duration

def _get_cached_or_compute(cache_key, compute_func):
    """Récupère depuis le cache ou calcule et met en cache"""
    if cache_key in _cache and _is_cache_valid(_cache[cache_key]):
        return _cache[cache_key]['data']
    
    # Calculer et mettre en cache
    result = compute_func()
    _cache[cache_key] = {
        'data': result,
        'timestamp': time.time()
    }
    return result

@router.get("/stats")
async def get_dashboard_stats(
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """
    Endpoint optimisé pour le dashboard - retourne toutes les stats essentielles
    en une seule requête avec cache de 5 minutes
    """
    try:
        cache_key = _get_cache_key("dashboard_stats", date.today().isoformat())
        
        def compute_stats():
            today = date.today()
            now = datetime.now()
            
            # Calculs optimisés en une seule session DB
            
            # 1. Stock total (somme simple)
            total_stock = db.query(func.coalesce(func.sum(Product.quantity), 0)).scalar() or 0
            
            # 2. Statistiques factures (optimisé avec un seul query par métrique)
            # Factures en attente
            pending_statuses = ["en attente", "SENT", "DRAFT", "OVERDUE", "partiellement payée"]
            pending_invoices = db.query(func.count(Invoice.invoice_id)).filter(
                Invoice.status.in_(pending_statuses)
            ).scalar() or 0
            
            # Chiffre d'affaires mensuel (factures payées)
            paid_statuses = ["payée", "PAID"]
            monthly_revenue_gross = db.query(func.coalesce(func.sum(Invoice.total), 0)).filter(
                func.extract('month', Invoice.date) == today.month,
                func.extract('year', Invoice.date) == today.year,
                Invoice.status.in_(paid_statuses)
            ).scalar() or 0
            
            # Paiements aux fournisseurs du mois
            monthly_supplier_payments = db.query(func.coalesce(func.sum(SupplierInvoice.paid_amount), 0)).filter(
                func.extract('month', SupplierInvoice.invoice_date) == today.month,
                func.extract('year', SupplierInvoice.invoice_date) == today.year
            ).scalar() or 0
            
            # Chiffre d'affaires net = revenus - paiements fournisseurs
            monthly_revenue = float(monthly_revenue_gross) - float(monthly_supplier_payments)
            
            # Montant impayé
            unpaid_statuses = ["en attente", "partiellement payée", "OVERDUE"]
            unpaid_amount = db.query(func.coalesce(func.sum(Invoice.remaining_amount), 0)).filter(
                Invoice.status.in_(unpaid_statuses)
            ).scalar() or 0
            
            # 3. KPIs avancés (période 30 jours)
            since_30 = now - timedelta(days=30)
            since_90 = now - timedelta(days=90)
            
            # Panier moyen (30 jours)
            paid_invoices_30d = db.query(Invoice).filter(
                Invoice.date >= since_30.date(),
                Invoice.status.in_(paid_statuses)
            )
            num_invoices_30d = paid_invoices_30d.count()
            total_revenue_30d_gross = db.query(func.coalesce(func.sum(Invoice.total), 0)).filter(
                Invoice.date >= since_30.date(),
                Invoice.status.in_(paid_statuses)
            ).scalar() or 0
            
            # Paiements aux fournisseurs sur 30 jours
            supplier_payments_30d = db.query(func.coalesce(func.sum(SupplierInvoicePayment.amount), 0)).filter(
                SupplierInvoicePayment.payment_date >= since_30.date()
            ).scalar() or 0
            
            # Revenus nets sur 30 jours
            total_revenue_30d = float(total_revenue_30d_gross) - float(supplier_payments_30d)
            avg_ticket = float(total_revenue_30d / num_invoices_30d) if num_invoices_30d > 0 else 0.0
            
            # Taux de conversion devis->factures (30 jours)
            quotes_30d = db.query(func.count(Quotation.quotation_id)).filter(
                Quotation.date >= since_30.date()
            ).scalar() or 0
            
            converted_quotes_30d = db.query(func.count(func.distinct(Invoice.quotation_id))).filter(
                Invoice.quotation_id.isnot(None),
                Invoice.date >= since_30.date()
            ).scalar() or 0
            
            conversion_rate = float((converted_quotes_30d / quotes_30d) * 100) if quotes_30d > 0 else 0.0
            
            # Stock critique
            out_of_stock = db.query(func.count(Product.product_id)).filter(
                or_(Product.quantity == 0, Product.quantity.is_(None))
            ).scalar() or 0
            
            low_stock = db.query(func.count(Product.product_id)).filter(
                and_(Product.quantity > 0, Product.quantity <= 3)
            ).scalar() or 0
            
            # Clients actifs (90 jours)
            active_customers = db.query(func.count(func.distinct(Invoice.client_id))).filter(
                Invoice.client_id.isnot(None),
                Invoice.date >= since_90.date()
            ).scalar() or 0
            
            # Top 3 produits par CA (30 jours) - optimisé
            top_products = db.query(
                InvoiceItem.product_name,
                func.coalesce(func.sum(InvoiceItem.total), 0).label("revenue")
            ).join(
                Invoice, InvoiceItem.invoice_id == Invoice.invoice_id
            ).filter(
                Invoice.date >= since_30.date()
            ).group_by(
                InvoiceItem.product_name
            ).order_by(
                desc("revenue")
            ).limit(3).all()
            
            top_products_list = [
                {"name": name or "-", "revenue": float(revenue or 0)}
                for name, revenue in top_products
            ]
            
            # Répartition paiements (30 jours) - optimisé
            payment_methods = db.query(
                InvoicePayment.payment_method,
                func.coalesce(func.sum(InvoicePayment.amount), 0).label("amount")
            ).filter(
                InvoicePayment.payment_date >= since_30.date()
            ).group_by(
                InvoicePayment.payment_method
            ).order_by(
                desc("amount")
            ).limit(5).all()
            
            payments_breakdown = [
                {"method": method or "Non spécifié", "amount": float(amount or 0)}
                for method, amount in payment_methods
            ]
            
            return {
                # Stats de base
                "total_stock": int(total_stock),
                "pending_invoices": int(pending_invoices),
                "monthly_revenue": float(monthly_revenue),
                "unpaid_amount": float(unpaid_amount),
                
                # KPIs avancés
                "avg_ticket": avg_ticket,
                "conversion_rate": conversion_rate,
                "critical_stock": int(low_stock + out_of_stock),
                "low_stock": int(low_stock),
                "out_of_stock": int(out_of_stock),
                "active_customers": int(active_customers),
                
                # Données détaillées
                "top_products": top_products_list,
                "payment_methods": payments_breakdown,
                
                # Meta
                "cached_at": datetime.now().isoformat(),
                "period_days": 30
            }
        
        result = _get_cached_or_compute(cache_key, compute_stats)
        return result
        
    except Exception as e:
        logging.error(f"Erreur dashboard stats: {e}")
        # Retourner des données par défaut en cas d'erreur
        return {
            "total_stock": 0,
            "pending_invoices": 0,
            "monthly_revenue": 0.0,
            "unpaid_amount": 0.0,
            "avg_ticket": 0.0,
            "conversion_rate": 0.0,
            "critical_stock": 0,
            "low_stock": 0,
            "out_of_stock": 0,
            "active_customers": 0,
            "top_products": [],
            "payment_methods": [],
            "error": "Erreur lors du calcul des statistiques",
            "cached_at": datetime.now().isoformat(),
            "period_days": 30
        }

@router.get("/recent-movements")
async def get_recent_movements(
    limit: int = 5,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """Mouvements de stock récents optimisés"""
    try:
        cache_key = _get_cache_key("recent_movements", limit)
        
        def compute_movements():
            movements = db.query(StockMovement).order_by(
                desc(StockMovement.created_at)
            ).limit(limit).all()
            
            return [
                {
                    "movement_id": m.movement_id,
                    "quantity": m.quantity,
                    "movement_type": m.movement_type,
                    "notes": m.notes,
                    "created_at": m.created_at.isoformat() if m.created_at else None
                }
                for m in movements
            ]
        
        result = _get_cached_or_compute(cache_key, compute_movements)
        return result
        
    except Exception as e:
        logging.error(f"Erreur recent movements: {e}")
        return []

@router.get("/recent-invoices")
async def get_recent_invoices(
    limit: int = 5,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """Factures récentes optimisées"""
    try:
        cache_key = _get_cache_key("recent_invoices", limit)
        
        def compute_invoices():
            invoices = db.query(Invoice).order_by(
                desc(Invoice.created_at)
            ).limit(limit).all()
            
            return [
                {
                    "invoice_id": inv.invoice_id,
                    "invoice_number": inv.invoice_number,
                    "status": inv.status,
                    "total": float(inv.total or 0),
                    "date": inv.date.isoformat() if inv.date else None
                }
                for inv in invoices
            ]
        
        result = _get_cached_or_compute(cache_key, compute_invoices)
        return result
        
    except Exception as e:
        logging.error(f"Erreur recent invoices: {e}")
        return []

@router.delete("/cache")
async def clear_dashboard_cache(
    current_user = Depends(get_current_user)
):
    """Vider le cache du dashboard (utile pour les admins)"""
    global _cache
    _cache.clear()
    return {"message": "Cache du dashboard vidé avec succès"}

@router.get("/cache/info")
async def get_cache_info(
    current_user = Depends(get_current_user)
):
    """Informations sur le cache (debugging)"""
    cache_entries = []
    current_time = time.time()
    
    for key, entry in _cache.items():
        age_seconds = current_time - entry['timestamp']
        is_valid = age_seconds < _cache_duration
        
        cache_entries.append({
            "key": key,
            "age_seconds": int(age_seconds),
            "is_valid": is_valid,
            "expires_in": int(_cache_duration - age_seconds) if is_valid else 0
        })
    
    return {
        "cache_duration_seconds": _cache_duration,
        "total_entries": len(_cache),
        "entries": cache_entries
    }

@router.post("/optimize")
async def optimize_database(
    current_user = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Déclencher l'optimisation de la base de données (admin seulement)"""
    # Vérifier les permissions admin
    if not hasattr(current_user, 'role') or current_user.role != 'admin':
        raise HTTPException(status_code=403, detail="Accès restreint aux administrateurs")
    
    try:
        from ..database_optimization import optimize_database as run_optimization
        
        # Vider le cache avant optimisation
        global _cache
        _cache.clear()
        
        # Lancer l'optimisation
        run_optimization()
        
        return {
            "message": "Optimisation de la base de données terminée avec succès",
            "cache_cleared": True,
            "timestamp": datetime.now().isoformat()
        }
        
    except Exception as e:
        logging.error(f"Erreur optimisation database: {e}")
        raise HTTPException(status_code=500, detail=f"Erreur lors de l'optimisation: {str(e)}")
