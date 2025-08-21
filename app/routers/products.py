from fastapi import APIRouter, Depends, HTTPException, status, Query, Body
from sqlalchemy.orm import Session
from sqlalchemy.orm import selectinload, load_only
from sqlalchemy import or_, and_, func, text, exists
from typing import List, Optional, Dict
from decimal import Decimal
from ..database import (
    get_db, Product, ProductVariant, ProductVariantAttribute, StockMovement, Category,
    CategoryAttribute, CategoryAttributeValue, UserSettings
)
from ..schemas import (
    ProductCreate, ProductUpdate, ProductResponse, ProductVariantCreate, StockMovementCreate,
    CategoryAttributeCreate, CategoryAttributeUpdate, CategoryAttributeResponse,
    CategoryAttributeValueCreate, CategoryAttributeValueUpdate, CategoryAttributeValueResponse,
    ProductListItem, ProductVariantListItem
)
from ..auth import get_current_user, require_role
from decimal import Decimal
from pydantic import BaseModel
import logging
import time

router = APIRouter(prefix="/api/products", tags=["products"])

# Modèles Pydantic pour les catégories
class CategoryBase(BaseModel):
    name: str
    requires_variants: bool = False

class CategoryCreate(CategoryBase):
    pass

class CategoryUpdate(CategoryBase):
    pass

class CategoryResponse(CategoryBase):
    id: str
    product_count: int
    
    class Config:
        from_attributes = True

# =====================
# Conditions (état des produits)
# =====================

DEFAULT_CONDITIONS = ["neuf", "occasion", "venant"]
DEFAULT_CONDITION_KEY = "product_conditions"

def _ensure_condition_columns(db: Session):
    """Ajoute les colonnes condition aux tables si absentes (sans Alembic)."""
    try:
        bind = db.get_bind()
        dialect = bind.dialect.name
        if dialect == 'sqlite':
            # products
            res = db.execute(text("PRAGMA table_info(products)"))
            prod_cols = [row[1] for row in res]
            if 'condition' not in prod_cols:
                db.execute(text("ALTER TABLE products ADD COLUMN condition VARCHAR(50)"))
                db.commit()
            # product_variants
            res2 = db.execute(text("PRAGMA table_info(product_variants)"))
            var_cols = [row[1] for row in res2]
            if 'condition' not in var_cols:
                db.execute(text("ALTER TABLE product_variants ADD COLUMN condition VARCHAR(50)"))
                db.commit()
        else:
            # Postgres et autres: tenter, ignorer si existe
            try:
                db.execute(text("ALTER TABLE products ADD COLUMN IF NOT EXISTS condition VARCHAR(50)"))
                db.execute(text("ALTER TABLE product_variants ADD COLUMN IF NOT EXISTS condition VARCHAR(50)"))
                db.commit()
            except Exception:
                db.rollback()
    except Exception:
        pass

def _get_allowed_conditions(db: Session) -> dict:
    """Retourne {options: [...], default: str}. Stocké dans UserSettings (global)."""
    setting = db.query(UserSettings).filter(
        UserSettings.user_id.is_(None), UserSettings.setting_key == DEFAULT_CONDITION_KEY
    ).first()
    import json
    if setting and setting.setting_value:
        try:
            data = json.loads(setting.setting_value)
            options = data.get("options") or DEFAULT_CONDITIONS
            default = data.get("default") or options[0]
            return {"options": options, "default": default}
        except Exception:
            pass
    return {"options": DEFAULT_CONDITIONS, "default": DEFAULT_CONDITIONS[0]}

def _set_allowed_conditions(db: Session, options: list[str], default_value: str):
    import json
    payload = json.dumps({"options": options, "default": default_value}, ensure_ascii=False)
    setting = db.query(UserSettings).filter(
        UserSettings.user_id.is_(None), UserSettings.setting_key == DEFAULT_CONDITION_KEY
    ).first()
    if not setting:
        setting = UserSettings(user_id=None, setting_key=DEFAULT_CONDITION_KEY, setting_value=payload)
    else:
        setting.setting_value = payload
    db.add(setting)
    db.commit()

class ConditionsUpdate(BaseModel):
    options: List[str]
    default: Optional[str] = None

@router.get("/settings/conditions", tags=["settings"])
async def get_conditions_settings(db: Session = Depends(get_db), current_user = Depends(get_current_user)):
    _ensure_condition_columns(db)
    return _get_allowed_conditions(db)

@router.put("/settings/conditions", tags=["settings"])
async def update_conditions_settings(payload: ConditionsUpdate, db: Session = Depends(get_db), current_user = Depends(require_role("admin"))):
    _ensure_condition_columns(db)
    options = [o.strip() for o in (payload.options or []) if o and o.strip()]
    if not options:
        raise HTTPException(status_code=400, detail="La liste des états ne peut pas être vide")
    default_value = (payload.default or options[0]).strip()
    if default_value not in options:
        options.insert(0, default_value)
    _set_allowed_conditions(db, options, default_value)
    return {"options": options, "default": default_value}

@router.get("/", response_model=List[ProductResponse])
async def list_products(
    skip: int = 0,
    limit: int = 100,
    search: Optional[str] = None,
    category: Optional[str] = None,
    condition: Optional[str] = None,
    in_stock: Optional[bool] = None,
    has_variants: Optional[bool] = None,
    min_price: Optional[float] = None,
    max_price: Optional[float] = None,
    brand: Optional[str] = None,
    model: Optional[str] = None,
    has_barcode: Optional[bool] = None,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """Lister les produits avec recherche et filtres"""
    _ensure_condition_columns(db)
    query = db.query(Product)
    
    if search:
        # Recherche dans nom, description, marque, modèle et codes-barres (produit et variantes)
        search_filter = or_(
            Product.name.ilike(f"%{search}%"),
            Product.description.ilike(f"%{search}%"),
            Product.brand.ilike(f"%{search}%"),
            Product.model.ilike(f"%{search}%"),
            Product.barcode.ilike(f"%{search}%")
        )
        
        # Recherche aussi dans les codes-barres ou IMEI/séries des variantes
        variant_search = db.query(ProductVariant.product_id).filter(
            or_(
                ProductVariant.barcode.ilike(f"%{search}%"),
                ProductVariant.imei_serial.ilike(f"%{search}%")
            )
        ).subquery()
        
        query = query.filter(
            or_(
                search_filter,
                Product.product_id.in_(variant_search)
            )
        )
    
    if category:
        query = query.filter(Product.category == category)

    if condition:
        # Comparaison insensible à la casse et aux espaces pour produit ET variantes
        condition_lower = condition.strip().lower()
        
        # Sous-requête pour les variantes ayant cette condition
        variant_condition_subquery = db.query(ProductVariant.product_id).filter(
            func.lower(func.trim(ProductVariant.condition)) == condition_lower
        )
        
        # Filtrer les produits qui ont soit la condition au niveau produit, soit des variantes avec cette condition
        query = query.filter(
            or_(
                func.lower(func.trim(Product.condition)) == condition_lower,
                Product.product_id.in_(variant_condition_subquery)
            )
        )

    if min_price is not None:
        query = query.filter(Product.price >= Decimal(min_price))
    if max_price is not None:
        query = query.filter(Product.price <= Decimal(max_price))

    if brand:
        query = query.filter(Product.brand.ilike(f"%{brand}%"))
    if model:
        query = query.filter(Product.model.ilike(f"%{model}%"))

    if has_barcode is True:
        query = query.filter(Product.barcode.isnot(None), func.length(func.trim(Product.barcode)) > 0)
    elif has_barcode is False:
        query = query.filter(or_(Product.barcode.is_(None), func.length(func.trim(Product.barcode)) == 0))

    # Existence-based filters
    pv_exists_available = exists().where(and_(ProductVariant.product_id == Product.product_id, ProductVariant.is_sold == False))
    pv_exists_any = exists().where(ProductVariant.product_id == Product.product_id)
    if in_stock is True:
        query = query.filter(or_(Product.quantity > 0, pv_exists_available))
    elif in_stock is False:
        query = query.filter(and_(Product.quantity <= 0, ~pv_exists_available))

    if has_variants is True:
        query = query.filter(pv_exists_any)
    elif has_variants is False:
        query = query.filter(~pv_exists_any)
    
    products = query.offset(skip).limit(limit).all()
    # Si un filtre de condition est actif, ne retourner que les variantes correspondant à cette condition
    if condition:
        cond_lower = (condition or "").strip().lower()
        for p in products:
            try:
                _ = p.variants  # force load
                p.variants = [v for v in (p.variants or []) if ((v.condition or "").strip().lower() == cond_lower)]
            except Exception:
                pass
    return products

class PaginatedProductsResponse(BaseModel):
    items: List[ProductListItem]
    total: int

@router.get("/paginated", response_model=PaginatedProductsResponse)
async def list_products_paginated(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    search: Optional[str] = None,
    category: Optional[str] = None,
    condition: Optional[str] = None,
    in_stock: Optional[bool] = None,
    has_variants: Optional[bool] = None,
    min_price: Optional[float] = None,
    max_price: Optional[float] = None,
    brand: Optional[str] = None,
    model: Optional[str] = None,
    has_barcode: Optional[bool] = None,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """Lister les produits avec pagination (retourne items + total)."""
    _ensure_condition_columns(db)
    # Eager-load only the necessary columns to speed up list view
    base_query = (
        db.query(Product)
        .options(
            load_only(
                Product.product_id,
                Product.name,
                Product.description,
                Product.quantity,
                Product.price,
                Product.purchase_price,
                Product.category,
                Product.brand,
                Product.model,
                Product.barcode,
                Product.condition,
                Product.has_unique_serial,
                Product.entry_date,
                Product.notes,
                Product.created_at,
            ),
            selectinload(Product.variants).load_only(
                ProductVariant.variant_id,
                ProductVariant.imei_serial,
                ProductVariant.barcode,
                ProductVariant.condition,
                ProductVariant.is_sold,
                ProductVariant.created_at,
            ),
        )
    )

    if search:
        search_filter = or_(
            Product.name.ilike(f"%{search}%"),
            Product.description.ilike(f"%{search}%"),
            Product.brand.ilike(f"%{search}%"),
            Product.model.ilike(f"%{search}%"),
            Product.barcode.ilike(f"%{search}%")
        )
        variant_search = db.query(ProductVariant.product_id).filter(
            or_(
                ProductVariant.barcode.ilike(f"%{search}%"),
                ProductVariant.imei_serial.ilike(f"%{search}%")
            )
        ).subquery()
        base_query = base_query.filter(or_(search_filter, Product.product_id.in_(variant_search)))

    if category:
        base_query = base_query.filter(Product.category == category)

    if condition:
        # Comparaison insensible à la casse et aux espaces pour produit ET variantes
        condition_lower = condition.strip().lower()
        
        # Sous-requête pour les variantes ayant cette condition
        variant_condition_subquery = db.query(ProductVariant.product_id).filter(
            func.lower(func.trim(ProductVariant.condition)) == condition_lower
        )
        
        # Filtrer les produits qui ont soit la condition au niveau produit, soit des variantes avec cette condition
        base_query = base_query.filter(
            or_(
                func.lower(func.trim(Product.condition)) == condition_lower,
                Product.product_id.in_(variant_condition_subquery)
            )
        )

    if min_price is not None:
        base_query = base_query.filter(Product.price >= Decimal(min_price))
    if max_price is not None:
        base_query = base_query.filter(Product.price <= Decimal(max_price))

    if brand:
        base_query = base_query.filter(Product.brand.ilike(f"%{brand}%"))
    if model:
        base_query = base_query.filter(Product.model.ilike(f"%{model}%"))

    if has_barcode is True:
        base_query = base_query.filter(Product.barcode.isnot(None), func.length(func.trim(Product.barcode)) > 0)
    elif has_barcode is False:
        base_query = base_query.filter(or_(Product.barcode.is_(None), func.length(func.trim(Product.barcode)) == 0))

    pv_exists_available = exists().where(and_(ProductVariant.product_id == Product.product_id, ProductVariant.is_sold == False))
    pv_exists_any = exists().where(ProductVariant.product_id == Product.product_id)
    if in_stock is True:
        base_query = base_query.filter(or_(Product.quantity > 0, pv_exists_available))
    elif in_stock is False:
        base_query = base_query.filter(and_(Product.quantity <= 0, ~pv_exists_available))

    if has_variants is True:
        base_query = base_query.filter(pv_exists_any)
    elif has_variants is False:
        base_query = base_query.filter(~pv_exists_any)

    start_time = time.time()
    total = base_query.count()
    count_time = time.time()
    logging.info(f"Product query count took: {count_time - start_time:.4f} seconds")

    skip = (page - 1) * page_size
    items = base_query.offset(skip).limit(page_size).all()
    # Si un filtre de condition est actif, ne retourner que les variantes correspondant à cette condition
    if condition:
        cond_lower = (condition or "").strip().lower()
        for p in items:
            try:
                _ = p.variants  # force load
                p.variants = [v for v in (p.variants or []) if ((v.condition or "").strip().lower() == cond_lower)]
            except Exception:
                pass
    fetch_time = time.time()
    logging.info(f"Product query fetch took: {fetch_time - count_time:.4f} seconds")
    logging.info(f"Total paginated request took: {fetch_time - start_time:.4f} seconds")

    return {"items": items, "total": total}

@router.get("/id/{product_id}", response_model=ProductResponse)
async def get_product(
    product_id: int,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """Obtenir un produit par ID"""
    _ensure_condition_columns(db)
    product = db.query(Product).filter(Product.product_id == product_id).first()
    if not product:
        raise HTTPException(status_code=404, detail="Produit non trouvé")
    return product

@router.post("/", response_model=ProductResponse)
async def create_product(
    product_data: ProductCreate,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """Créer un nouveau produit avec variantes selon la règle métier"""
    try:
        _ensure_condition_columns(db)
        cond_cfg = _get_allowed_conditions(db)
        allowed = set([c.lower() for c in cond_cfg["options"]])
        default_cond = cond_cfg["default"]
        # Validation selon la règle métier des mémoires
        has_variants = len(product_data.variants) > 0
        
        if has_variants and product_data.barcode:
            raise HTTPException(
                status_code=400,
                detail="Un produit avec variantes ne peut pas avoir de code-barres. Les codes-barres sont gérés au niveau des variantes individuelles."
            )
        
        # Vérifier l'unicité des codes-barres
        if product_data.barcode:
            existing_product = db.query(Product).filter(Product.barcode == product_data.barcode).first()
            if existing_product:
                raise HTTPException(status_code=400, detail="Ce code-barres existe déjà")
        
        # Vérifier l'unicité des codes-barres des variantes
        variant_barcodes = [v.barcode for v in product_data.variants if v.barcode]
        if variant_barcodes:
            existing_variants = db.query(ProductVariant).filter(
                ProductVariant.barcode.in_(variant_barcodes)
            ).all()
            if existing_variants:
                raise HTTPException(status_code=400, detail="Un ou plusieurs codes-barres de variantes existent déjà")
        
        # Vérifier l'unicité des IMEI/numéros de série
        variant_serials = [v.imei_serial for v in product_data.variants]
        if variant_serials:
            existing_serials = db.query(ProductVariant).filter(
                ProductVariant.imei_serial.in_(variant_serials)
            ).all()
            if existing_serials:
                raise HTTPException(status_code=400, detail="Un ou plusieurs IMEI/numéros de série existent déjà")
        
        # Créer le produit
        # Normaliser/valider condition produit
        prod_condition = (product_data.condition or default_cond)
        if prod_condition and prod_condition.lower() not in allowed:
            raise HTTPException(status_code=400, detail="Condition de produit invalide")

        db_product = Product(
            name=product_data.name,
            description=product_data.description,
            quantity=len(product_data.variants) if has_variants else product_data.quantity,
            price=product_data.price,
            purchase_price=product_data.purchase_price,
            category=product_data.category,
            brand=product_data.brand,
            model=product_data.model,
            barcode=product_data.barcode if not has_variants else None,
            condition=prod_condition,
            has_unique_serial=product_data.has_unique_serial,
            entry_date=product_data.entry_date,
            notes=product_data.notes
        )
        
        db.add(db_product)
        db.flush()  # Pour obtenir l'ID du produit
        
        # Créer les variantes si présentes
        for variant_data in product_data.variants:
            db_variant = ProductVariant(
                product_id=db_product.product_id,
                imei_serial=variant_data.imei_serial,
                barcode=variant_data.barcode,
                condition=(variant_data.condition or prod_condition)
            )
            db.add(db_variant)
            db.flush()
            
            # Créer les attributs de la variante
            for attr_data in variant_data.attributes:
                db_attr = ProductVariantAttribute(
                    variant_id=db_variant.variant_id,
                    attribute_name=attr_data.attribute_name,
                    attribute_value=attr_data.attribute_value
                )
                db.add(db_attr)
        
        # Créer un mouvement de stock d'entrée
        if db_product.quantity > 0:
            stock_movement = StockMovement(
                product_id=db_product.product_id,
                quantity=db_product.quantity,
                movement_type="IN",
                reference_type="CREATION",
                notes="Création du produit"
            )
            db.add(stock_movement)
        
        db.commit()
        db.refresh(db_product)
        
        return db_product
        
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logging.error(f"Erreur lors de la création du produit: {e}")
        raise HTTPException(status_code=500, detail="Erreur serveur")

@router.put("/id/{product_id}", response_model=ProductResponse)
async def update_product(
    product_id: int,
    product_data: ProductUpdate,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """Mettre à jour un produit"""
    try:
        _ensure_condition_columns(db)
        cond_cfg = _get_allowed_conditions(db)
        allowed = set([c.lower() for c in cond_cfg["options"]])
        default_cond = cond_cfg["default"]
        product = db.query(Product).filter(Product.product_id == product_id).first()
        if not product:
            raise HTTPException(status_code=404, detail="Produit non trouvé")
        
        # Validation selon la règle métier
        has_variants = len(product.variants) > 0
        new_variants = product_data.variants if product_data.variants is not None else []
        will_have_variants = len(new_variants) > 0 or has_variants
        
        if will_have_variants and product_data.barcode:
            raise HTTPException(
                status_code=400,
                detail="Un produit avec variantes ne peut pas avoir de code-barres"
            )
        
        # Mettre à jour les champs du produit
        update_data = product_data.dict(exclude_unset=True, exclude={'variants'})
        # Valider condition si fournie
        if 'condition' in update_data and update_data['condition'] is not None:
            if update_data['condition'].lower() not in allowed:
                raise HTTPException(status_code=400, detail="Condition de produit invalide")
        for field, value in update_data.items():
            setattr(product, field, value)
        
        # Gérer les variantes si fournies
        if product_data.variants is not None:
            # Supprimer les anciennes variantes
            db.query(ProductVariant).filter(ProductVariant.product_id == product_id).delete()
            
            # Créer les nouvelles variantes
            for variant_data in product_data.variants:
                db_variant = ProductVariant(
                    product_id=product_id,
                    imei_serial=variant_data.imei_serial,
                    barcode=variant_data.barcode,
                    condition=(variant_data.condition or product.condition or default_cond)
                )
                db.add(db_variant)
                db.flush()
                
                # Créer les attributs
                for attr_data in variant_data.attributes:
                    db_attr = ProductVariantAttribute(
                        variant_id=db_variant.variant_id,
                        attribute_name=attr_data.attribute_name,
                        attribute_value=attr_data.attribute_value
                    )
                    db.add(db_attr)
            
            # Mettre à jour la quantité basée sur les variantes
            product.quantity = len(product_data.variants)
        
        db.commit()
        db.refresh(product)
        
        return product
        
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logging.error(f"Erreur lors de la mise à jour du produit: {e}")
        raise HTTPException(status_code=500, detail="Erreur serveur")

@router.delete("/id/{product_id}")
async def delete_product(
    product_id: int,
    db: Session = Depends(get_db),
    current_user = Depends(require_role("admin"))
):
    """Supprimer un produit"""
    try:
        product = db.query(Product).filter(Product.product_id == product_id).first()
        if not product:
            raise HTTPException(status_code=404, detail="Produit non trouvé")
        
        # Créer un mouvement de stock de sortie pour traçabilité
        if product.quantity > 0:
            stock_movement = StockMovement(
                product_id=product_id,
                quantity=-product.quantity,
                movement_type="OUT",
                reference_type="DELETION",
                notes=f"Suppression du produit: {product.name}"
            )
            db.add(stock_movement)
        
        db.delete(product)
        db.commit()
        
        return {"message": "Produit supprimé avec succès"}
        
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logging.error(f"Erreur lors de la suppression du produit: {e}")
        raise HTTPException(status_code=500, detail="Erreur serveur")

@router.get("/scan/{barcode}")
async def scan_barcode(
    barcode: str,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """Scanner un code-barres (produit ou variante) et retourner un objet JSON simple.

    Recherche sur:
    - `products.barcode`
    - `product_variants.barcode`
    - `product_variants.imei_serial`
    Les espaces en trop sont ignorés.
    """
    try:
        code = (barcode or "").strip()
        if not code:
            raise HTTPException(status_code=400, detail="Code-barres vide")

        # 1) Produit par code-barres exact (trim)
        product = (
            db.query(Product)
            .filter(func.trim(Product.barcode) == code)
            .first()
        )
        if product:
            return {
                "type": "product",
                "product_id": product.product_id,
                "product_name": product.name,
                "price": float(product.price or 0),
                "category_name": product.category,
                "stock_quantity": int(product.quantity or 0),
                "barcode": product.barcode
            }

        # 2) Variante par code-barres ou IMEI/série
        variant = (
            db.query(ProductVariant)
            .join(Product)
            .filter(
                or_(
                    func.trim(ProductVariant.barcode) == code,
                    func.trim(ProductVariant.imei_serial) == code
                )
            )
            .first()
        )
        if variant:
            # Charger les attributs
            _ = variant.attributes  # force load
            attributes_text = ", ".join(
                [f"{a.attribute_name}: {a.attribute_value}" for a in (variant.attributes or [])]
            )
            return {
                "type": "variant",
                "product_id": variant.product.product_id,
                "product_name": variant.product.name,
                "price": float(variant.product.price or 0),
                "category_name": variant.product.category,
                "stock_quantity": 0 if variant.is_sold else 1,
                "variant": {
                    "variant_id": variant.variant_id,
                    "imei_serial": variant.imei_serial,
                    "barcode": variant.barcode,
                    "is_sold": bool(variant.is_sold),
                    "attributes": attributes_text
                }
            }

        # 3) Recherche partielle (fallback) sur produits et variantes
        # Utile quand le code scanné a des préfixes/suffixes ou quand on veut matcher IMEI partiel
        like_code = f"%{code}%"
        variant_like = (
            db.query(ProductVariant)
            .join(Product)
            .filter(
                or_(
                    ProductVariant.barcode.ilike(like_code),
                    ProductVariant.imei_serial.ilike(like_code)
                )
            )
            .first()
        )
        if variant_like:
            _ = variant_like.attributes
            attributes_text = ", ".join(
                [f"{a.attribute_name}: {a.attribute_value}" for a in (variant_like.attributes or [])]
            )
            return {
                "type": "variant",
                "product_id": variant_like.product.product_id,
                "product_name": variant_like.product.name,
                "price": float(variant_like.product.price or 0),
                "category_name": variant_like.product.category,
                "stock_quantity": 0 if variant_like.is_sold else 1,
                "variant": {
                    "variant_id": variant_like.variant_id,
                    "imei_serial": variant_like.imei_serial,
                    "barcode": variant_like.barcode,
                    "is_sold": bool(variant_like.is_sold),
                    "attributes": attributes_text
                }
            }

        product_like = (
            db.query(Product)
            .filter(Product.barcode.ilike(like_code))
            .first()
        )
        if product_like:
            return {
                "type": "product",
                "product_id": product_like.product_id,
                "product_name": product_like.name,
                "price": float(product_like.price or 0),
                "category_name": product_like.category,
                "stock_quantity": int(product_like.quantity or 0),
                "barcode": product_like.barcode
            }

        raise HTTPException(status_code=404, detail="Code-barres non trouvé")

    except HTTPException:
        raise
    except Exception as e:
        logging.error(f"Erreur lors du scan: {e}")
        raise HTTPException(status_code=500, detail="Erreur serveur")

# ==== GESTION DES CATÉGORIES ====

@router.get("/categories", response_model=List[CategoryResponse])
async def get_categories(
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """Obtenir la liste des catégories avec le nombre de produits associés"""
    # Requête pour obtenir les catégories de la table Category avec le nombre de produits
    categories_with_count = db.query(
        Category.category_id.label('id'),
        Category.name.label('name'),
        Category.requires_variants.label('requires_variants'),
        func.count(Product.product_id).label('product_count')
    ).outerjoin(
        Product, Category.name == Product.category
    ).group_by(
        Category.category_id, Category.name, Category.requires_variants
    ).all()
    
    # Convertir en liste de dictionnaires pour la réponse
    result = []
    for cat in categories_with_count:
        result.append({
            "id": str(cat.id),
            "name": str(cat.name),
            "requires_variants": bool(getattr(cat, 'requires_variants', False)),
            "product_count": int(cat.product_count or 0)
        })
    
    return result

@router.get("/categories/{category_id}", response_model=CategoryResponse)
async def get_category(
    category_id: str,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """Obtenir une catégorie spécifique avec le nombre de produits associés"""
    # Chercher d'abord la catégorie par ID (numérique) ou par nom (texte)
    category = _category_query_by_identifier(db, category_id).first()
    
    if not category:
        raise HTTPException(status_code=404, detail="Catégorie non trouvée")
    
    # Compter les produits associés
    product_count = db.query(Product).filter(Product.category == category.name).count()
    
    return {
        "id": str(category.category_id),
        "name": category.name,
        "requires_variants": bool(category.requires_variants),
        "product_count": product_count
    }

@router.post("/categories", response_model=CategoryResponse)
async def create_category(
    category_data: CategoryCreate,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """Créer une nouvelle catégorie"""
    # Vérifier si la catégorie existe déjà
    existing_category = db.query(Category).filter(
        func.lower(Category.name) == func.lower(category_data.name)
    ).first()
    
    if existing_category:
        raise HTTPException(
            status_code=400,
            detail="Une catégorie avec ce nom existe déjà"
        )
    
    # Créer la nouvelle catégorie
    new_category = Category(
        name=category_data.name,
        description=getattr(category_data, 'description', None),
        requires_variants=bool(getattr(category_data, 'requires_variants', False))
    )
    
    db.add(new_category)
    db.commit()
    db.refresh(new_category)
    
    return {
        "id": str(new_category.category_id),
        "name": new_category.name,
        "requires_variants": bool(new_category.requires_variants),
        "product_count": 0
    }

@router.put("/categories/{category_id}", response_model=CategoryResponse)
async def update_category(
    category_id: str,
    category_data: CategoryUpdate,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """Mettre à jour une catégorie existante"""
    # Chercher la catégorie par ID (numérique) ou nom (texte)
    category = _category_query_by_identifier(db, category_id).first()
    
    if not category:
        raise HTTPException(status_code=404, detail="Catégorie non trouvée")
    
    # Vérifier si le nouveau nom existe déjà (sauf s'il s'agit du même)
    if category.name.lower() != category_data.name.lower():
        existing_category = db.query(Category).filter(
            func.lower(Category.name) == func.lower(category_data.name)
        ).first()
        
        if existing_category:
            raise HTTPException(
                status_code=400,
                detail="Une catégorie avec ce nom existe déjà"
            )
    
    # Sauvegarder l'ancien nom pour mettre à jour les produits
    old_name = category.name
    
    # Mettre à jour la catégorie
    category.name = category_data.name
    if hasattr(category_data, 'description'):
        category.description = category_data.description
    if hasattr(category_data, 'requires_variants'):
        category.requires_variants = bool(category_data.requires_variants)
    
    # Mettre à jour tous les produits avec cette catégorie
    db.query(Product).filter(Product.category == old_name).update(
        {"category": category_data.name}
    )
    
    db.commit()
    db.refresh(category)
    
    # Compter le nombre de produits dans la catégorie mise à jour
    product_count = db.query(Product).filter(Product.category == category.name).count()
    
    return {
        "id": str(category.category_id),
        "name": category.name,
        "requires_variants": bool(category.requires_variants),
        "product_count": product_count
    }

@router.delete("/categories/{category_id}")
async def delete_category(
    category_id: str,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """Supprimer une catégorie"""
    # Chercher la catégorie par ID (numérique) ou nom (texte)
    category = _category_query_by_identifier(db, category_id).first()
    
    if not category:
        raise HTTPException(status_code=404, detail="Catégorie non trouvée")
    
    # Vérifier si des produits utilisent cette catégorie
    products_with_category = db.query(Product).filter(
        Product.category == category.name
    ).count()
    
    if products_with_category > 0:
        raise HTTPException(
            status_code=400,
            detail=f"Impossible de supprimer la catégorie. {products_with_category} produit(s) l'utilisent encore."
        )
    
    # Supprimer la catégorie
    db.delete(category)
    db.commit()
    
    return {"message": "Catégorie supprimée avec succès"}

# =====================
# Attributs de catégorie
# =====================

def _slugify(text: str) -> str:
    return ''.join(c.lower() if c.isalnum() else '-' for c in text).strip('-')

def _category_query_by_identifier(db: Session, identifier: str):
    """Return a query for `Category` matching either numeric ID or name.

    Avoids Postgres type mismatch (integer vs varchar) by casting in Python,
    not in SQL.
    """
    try:
        # Accept strings like "001" -> 1 as id
        if str(identifier).isdigit():
            return db.query(Category).filter(Category.category_id == int(identifier))
    except Exception:
        pass
    return db.query(Category).filter(Category.name == identifier)

def _category_or_404(db: Session, category_id: str) -> Category:
    category = _category_query_by_identifier(db, category_id).first()
    if not category:
        raise HTTPException(status_code=404, detail="Catégorie non trouvée")
    return category

@router.get("/categories/{category_id}/attributes", response_model=List[CategoryAttributeResponse])
async def list_category_attributes(
    category_id: str,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    category = _category_or_404(db, category_id)
    attrs = db.query(CategoryAttribute).filter(CategoryAttribute.category_id == category.category_id).order_by(CategoryAttribute.sort_order).all()
    # charger les valeurs
    for a in attrs:
        _ = a.values  # load relationship
    return attrs

@router.post("/categories/{category_id}/attributes", response_model=CategoryAttributeResponse)
async def create_category_attribute(
    category_id: str,
    payload: CategoryAttributeCreate,
    db: Session = Depends(get_db),
    current_user = Depends(require_role("admin"))
):
    category = _category_or_404(db, category_id)
    code = payload.code or _slugify(payload.name)
    # unicité code par catégorie
    exists = db.query(CategoryAttribute).filter(
        CategoryAttribute.category_id == category.category_id,
        func.lower(CategoryAttribute.code) == func.lower(code)
    ).first()
    if exists:
        raise HTTPException(status_code=400, detail="Code d'attribut déjà utilisé pour cette catégorie")
    attr = CategoryAttribute(
        category_id=category.category_id,
        name=payload.name,
        code=code,
        type=payload.type,
        required=bool(payload.required),
        multi_select=bool(payload.multi_select),
        sort_order=payload.sort_order or 0
    )
    db.add(attr)
    db.flush()
    # valeurs initiales
    for i, v in enumerate(payload.values or []):
        vcode = v.code or _slugify(v.value)
        db.add(CategoryAttributeValue(
            attribute_id=attr.attribute_id,
            value=v.value,
            code=vcode,
            sort_order=v.sort_order if v.sort_order is not None else i
        ))
    db.commit()
    db.refresh(attr)
    return attr

@router.put("/categories/{category_id}/attributes/{attribute_id}", response_model=CategoryAttributeResponse)
async def update_category_attribute(
    category_id: str,
    attribute_id: int,
    payload: CategoryAttributeUpdate,
    db: Session = Depends(get_db),
    current_user = Depends(require_role("admin"))
):
    category = _category_or_404(db, category_id)
    attr = db.query(CategoryAttribute).filter(
        CategoryAttribute.attribute_id == attribute_id,
        CategoryAttribute.category_id == category.category_id
    ).first()
    if not attr:
        raise HTTPException(status_code=404, detail="Attribut non trouvé")
    if payload.name is not None:
        attr.name = payload.name
    if payload.code is not None:
        # vérifier unicité
        exists = db.query(CategoryAttribute).filter(
            CategoryAttribute.category_id == category.category_id,
            func.lower(CategoryAttribute.code) == func.lower(payload.code),
            CategoryAttribute.attribute_id != attr.attribute_id
        ).first()
        if exists:
            raise HTTPException(status_code=400, detail="Code d'attribut déjà utilisé pour cette catégorie")
        attr.code = payload.code
    if payload.type is not None:
        attr.type = payload.type
    if payload.required is not None:
        attr.required = bool(payload.required)
    if payload.multi_select is not None:
        attr.multi_select = bool(payload.multi_select)
    if payload.sort_order is not None:
        attr.sort_order = payload.sort_order
    db.commit()
    db.refresh(attr)
    return attr

@router.delete("/categories/{category_id}/attributes/{attribute_id}")
async def delete_category_attribute(
    category_id: str,
    attribute_id: int,
    db: Session = Depends(get_db),
    current_user = Depends(require_role("admin"))
):
    category = _category_or_404(db, category_id)
    attr = db.query(CategoryAttribute).filter(
        CategoryAttribute.attribute_id == attribute_id,
        CategoryAttribute.category_id == category.category_id
    ).first()
    if not attr:
        raise HTTPException(status_code=404, detail="Attribut non trouvé")
    # empêcher suppression si utilisé dans des variantes
    in_use = db.query(ProductVariantAttribute).filter(
        func.lower(ProductVariantAttribute.attribute_name) == func.lower(attr.name)
    ).first()
    if in_use:
        raise HTTPException(status_code=400, detail="Attribut utilisé par des variantes, suppression interdite")
    db.delete(attr)
    db.commit()
    return {"message": "Attribut supprimé avec succès"}

@router.post("/categories/{category_id}/attributes/{attribute_id}/values", response_model=CategoryAttributeValueResponse)
async def create_attribute_value(
    category_id: str,
    attribute_id: int,
    payload: CategoryAttributeValueCreate,
    db: Session = Depends(get_db),
    current_user = Depends(require_role("admin"))
):
    category = _category_or_404(db, category_id)
    attr = db.query(CategoryAttribute).filter(
        CategoryAttribute.attribute_id == attribute_id,
        CategoryAttribute.category_id == category.category_id
    ).first()
    if not attr:
        raise HTTPException(status_code=404, detail="Attribut non trouvé")
    code = payload.code or _slugify(payload.value)
    exists = db.query(CategoryAttributeValue).filter(
        CategoryAttributeValue.attribute_id == attribute_id,
        func.lower(CategoryAttributeValue.code) == func.lower(code)
    ).first()
    if exists:
        raise HTTPException(status_code=400, detail="Code de valeur déjà utilisé pour cet attribut")
    val = CategoryAttributeValue(
        attribute_id=attribute_id,
        value=payload.value,
        code=code,
        sort_order=payload.sort_order or 0
    )
    db.add(val)
    db.commit()
    db.refresh(val)
    return val

@router.put("/categories/{category_id}/attributes/{attribute_id}/values/{value_id}", response_model=CategoryAttributeValueResponse)
async def update_attribute_value(
    category_id: str,
    attribute_id: int,
    value_id: int,
    payload: CategoryAttributeValueUpdate,
    db: Session = Depends(get_db),
    current_user = Depends(require_role("admin"))
):
    _ = _category_or_404(db, category_id)
    val = db.query(CategoryAttributeValue).filter(
        CategoryAttributeValue.value_id == value_id,
        CategoryAttributeValue.attribute_id == attribute_id
    ).first()
    if not val:
        raise HTTPException(status_code=404, detail="Valeur non trouvée")
    if payload.value is not None:
        val.value = payload.value
    if payload.code is not None:
        exists = db.query(CategoryAttributeValue).filter(
            CategoryAttributeValue.attribute_id == attribute_id,
            func.lower(CategoryAttributeValue.code) == func.lower(payload.code),
            CategoryAttributeValue.value_id != value_id
        ).first()
        if exists:
            raise HTTPException(status_code=400, detail="Code de valeur déjà utilisé pour cet attribut")
        val.code = payload.code
    if payload.sort_order is not None:
        val.sort_order = payload.sort_order
    db.commit()
    db.refresh(val)
    return val

@router.delete("/categories/{category_id}/attributes/{attribute_id}/values/{value_id}")
async def delete_attribute_value(
    category_id: str,
    attribute_id: int,
    value_id: int,
    db: Session = Depends(get_db),
    current_user = Depends(require_role("admin"))
):
    category = _category_or_404(db, category_id)
    attr = db.query(CategoryAttribute).filter(
        CategoryAttribute.attribute_id == attribute_id,
        CategoryAttribute.category_id == category.category_id
    ).first()
    if not attr:
        raise HTTPException(status_code=404, detail="Attribut non trouvé")
    val = db.query(CategoryAttributeValue).filter(
        CategoryAttributeValue.value_id == value_id,
        CategoryAttributeValue.attribute_id == attribute_id
    ).first()
    if not val:
        raise HTTPException(status_code=404, detail="Valeur non trouvée")
    # empêcher suppression si valeur utilisée
    in_use = db.query(ProductVariantAttribute).filter(
        and_(
            func.lower(ProductVariantAttribute.attribute_name) == func.lower(attr.name),
            func.lower(ProductVariantAttribute.attribute_value) == func.lower(val.value)
        )
    ).first()
    if in_use:
        raise HTTPException(status_code=400, detail="Valeur utilisée par des variantes, suppression interdite")
    db.delete(val)
    db.commit()
    return {"message": "Valeur supprimée avec succès"}

# Pour la compatibilité avec l'ancien endpoint
@router.get("/categories/list")
async def get_categories_list(
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """Obtenir la liste des catégories uniques (ancien format)"""
    categories = db.query(Product.category).distinct().filter(Product.category.isnot(None)).all()
    return [cat[0] for cat in categories if cat[0]]
