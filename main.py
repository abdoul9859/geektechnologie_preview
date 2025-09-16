from fastapi import FastAPI, Request, Depends, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse, FileResponse
from sqlalchemy.orm import Session
from sqlalchemy.orm import joinedload
import uvicorn
import os
from dotenv import load_dotenv
import json
import re
from datetime import date, datetime

# Charger les variables d'environnement
load_dotenv()

# Version d'assets pour bust de cache (commit SHA si fourni par la plateforme, sinon variable ou timestamp)
ASSET_VERSION = (
    os.getenv("GIT_COMMIT_SHA")
    or os.getenv("KOYEB_COMMIT_SHA")
    or os.getenv("ASSET_VERSION")
    or str(int(datetime.now().timestamp()))
)[:12]

# Imports de l'application
from app.database import get_db
from app.database import Invoice, UserSettings, Product, DeliveryNote, DeliveryNoteItem, Client
import re
try:
    # Legacy settings model (template-application) for fallback of company info/logo
    from app.models.models import Settings as LegacySettings  # type: ignore
except Exception:
    LegacySettings = None  # type: ignore
from app.routers import auth, products, clients, stock_movements, invoices, quotations, suppliers, debts, delivery_notes, bank_transactions, reports, user_settings, migrations, cache, dashboard, supplier_invoices, daily_recap, daily_purchases
from app.init_db import init_database
from app.auth import get_current_user
from app.services.migration_processor import migration_processor

# Créer l'application FastAPI
app = FastAPI(
    title="GEEK TECHNOLOGIE - Gestion de Stock",
    description="Application de gestion de stock et facturation avec FastAPI et Bootstrap",
    version="1.0.0"
)

# (Optionnel) Middleware proxy enlevé pour compatibilité starlette; la baseURL côté frontend force déjà HTTPS

# Middleware de gestion du cache: HTML non cache, assets statiques fortement cacheés
@app.middleware("http")
async def cache_headers_middleware(request, call_next):
    response = await call_next(request)
    try:
        path = request.url.path or ""
        content_type = response.headers.get("content-type", "").lower()
        if path.startswith("/static/") or path == "/favicon.ico":
            response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        elif content_type.startswith("text/html"):
            response.headers["Cache-Control"] = "no-store"
    except Exception:
        # En cas de souci, on n'empêche pas la réponse de sortir
        pass
    return response

# Initialiser la base de données au démarrage (désactivé par défaut en déploiement)
@app.on_event("startup")
async def startup_event():
    try:
        should_init = os.getenv("INIT_DB_ON_STARTUP", "false").lower() == "true"
        if should_init:
            print("⚙️ INIT_DB_ON_STARTUP=true → initialisation de la base autorisée")
            init_database()
        else:
            print("⏭️ INIT_DB_ON_STARTUP!=true → saut de l'initialisation de la base (aucune écriture)")
        # Démarrer le processeur de migrations en arrière-plan (désactivé par défaut)
        if os.getenv("ENABLE_MIGRATIONS_WORKER", "false").lower() == "true":
            migration_processor.start_background_processor()
        else:
            print("⏭️ ENABLE_MIGRATIONS_WORKER!=true → worker migrations non démarré")
        print("✅ Application démarrée avec succès")
    except Exception as e:
        print(f"❌ Erreur lors du démarrage: {e}")

# Arrêter le processeur au shutdown
@app.on_event("shutdown")
async def shutdown_event():
    try:
        # Arrêter uniquement si le worker était activé
        if os.getenv("ENABLE_MIGRATIONS_WORKER", "false").lower() == "true":
            migration_processor.stop_background_processor()
        print("✅ Application arrêtée proprement")
    except Exception as e:
        print(f"❌ Erreur lors de l'arrêt: {e}")

# Configuration des templates et fichiers statiques
templates = Jinja2Templates(directory="templates")
# Exposer une variable globale de version pour le cache-busting des assets
templates.env.globals["ASSET_VERSION"] = ASSET_VERSION

# ---- Jinja filters ----
def _format_number(value) -> str:
    try:
        # Support Decimal, int, float; round to 0 decimals for CFA display
        n = float(value or 0)
        text = f"{n:,.0f}"
        # Replace commas with spaces for French-style grouping
        return text.replace(",", " ")
    except Exception:
        try:
            return str(int(value))
        except Exception:
            return str(value or 0)

templates.env.filters["format_number"] = _format_number

def _format_cfa(value) -> str:
    return f"{_format_number(value)} F CFA"

templates.env.filters["format_cfa"] = _format_cfa

def _format_date_no_time(value) -> str:
    try:
        if value is None:
            return ""
        if isinstance(value, (datetime, date)):
            # Always YYYY-MM-DD
            return value.strftime("%Y-%m-%d")
        s = str(value)
        if "T" in s:
            return s.split("T")[0]
        if " " in s:
            return s.split(" ")[0]
        return s
    except Exception:
        try:
            return str(value).split(" ")[0]
        except Exception:
            return str(value or "")

templates.env.filters["format_date"] = _format_date_no_time

def _normalize_logo(logo_value: str | None) -> str | None:
    try:
        if not logo_value:
            return None
        s = str(logo_value).strip()
        if not s:
            return None
        # Already a proper URL or data URI
        if s.startswith("data:image") or s.startswith("http://") or s.startswith("https://") or s.startswith("/"):
            return s
        # Heuristic: base64 without header → wrap as PNG by default
        if len(s) > 64:
            return f"data:image/png;base64,{s}"
        return s
    except Exception:
        return logo_value
app.mount("/static", StaticFiles(directory="static"), name="static")

# Inclure les routers API
app.include_router(auth.router)
app.include_router(products.router)
app.include_router(clients.router)
app.include_router(stock_movements.router)
app.include_router(invoices.router)
app.include_router(quotations.router)
app.include_router(suppliers.router)
app.include_router(supplier_invoices.router)
app.include_router(debts.router)
# Désactivation de la page Bons de Livraison
app.include_router(bank_transactions.router)
app.include_router(reports.router)
app.include_router(user_settings.router)
app.include_router(migrations.router)
app.include_router(cache.router)
app.include_router(dashboard.router)
app.include_router(daily_recap.router)
app.include_router(daily_purchases.router)

# Route pour le favicon
@app.get("/favicon.ico")
async def favicon():
    return FileResponse("static/favicon.ico")

# Route API de test
@app.get("/api")
async def api_status():
    return {
        "message": "API GEEK TECHNOLOGIE",
        "status": "running",
        "version": "1.0.0",
        "framework": "FastAPI"
    }

# Routes pour l'interface web
@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request, db: Session = Depends(get_db)):
    """Page d'accueil - Dashboard"""
    return templates.TemplateResponse("dashboard.html", {"request": request, "global_settings": _load_company_settings(db)})

@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request, db: Session = Depends(get_db)):
    """Page de connexion"""
    return templates.TemplateResponse("login.html", {"request": request, "global_settings": _load_company_settings(db)})

@app.get("/products", response_class=HTMLResponse)
async def products_page(request: Request, db: Session = Depends(get_db)):
    """Page de gestion des produits"""
    return templates.TemplateResponse("products.html", {"request": request, "global_settings": _load_company_settings(db)})

@app.get("/clients", response_class=HTMLResponse)
async def clients_page(request: Request, db: Session = Depends(get_db)):
    """Page de gestion des clients"""
    return templates.TemplateResponse("clients.html", {"request": request, "global_settings": _load_company_settings(db)})

@app.get("/clients/detail", response_class=HTMLResponse)
async def client_detail_page(request: Request, db: Session = Depends(get_db)):
    """Page de détail d'un client"""
    return templates.TemplateResponse("clients_detail.html", {"request": request, "global_settings": _load_company_settings(db)})

@app.get("/stock-movements", response_class=HTMLResponse)
async def stock_movements_page(request: Request, db: Session = Depends(get_db)):
    """Page des mouvements de stock"""
    return templates.TemplateResponse("stock_movements.html", {"request": request, "global_settings": _load_company_settings(db)})

@app.get("/invoices", response_class=HTMLResponse)
async def invoices_page(request: Request, db: Session = Depends(get_db)):
    """Page de gestion des factures"""
    return templates.TemplateResponse("invoices.html", {"request": request, "global_settings": _load_company_settings(db)})

@app.get("/quotations", response_class=HTMLResponse)
async def quotations_page(request: Request, db: Session = Depends(get_db)):
    """Page de gestion des devis"""
    return templates.TemplateResponse("quotations.html", {"request": request, "global_settings": _load_company_settings(db)})

@app.get("/scan", response_class=HTMLResponse)
async def scan_page(request: Request, db: Session = Depends(get_db)):
    """Page de scan de codes-barres"""
    return templates.TemplateResponse("scan.html", {"request": request, "global_settings": _load_company_settings(db)})

@app.get("/settings", response_class=HTMLResponse)
async def settings_page(request: Request, db: Session = Depends(get_db)):
    """Page des paramètres de l'application"""
    return templates.TemplateResponse("settings.html", {"request": request, "global_settings": _load_company_settings(db)})

@app.get("/suppliers", response_class=HTMLResponse)
async def suppliers_page(request: Request, db: Session = Depends(get_db)):
    """Page de gestion des fournisseurs"""
    return templates.TemplateResponse("suppliers.html", {"request": request, "global_settings": _load_company_settings(db)})

@app.get("/delivery-notes", response_class=HTMLResponse)
async def delivery_notes_page(request: Request, db: Session = Depends(get_db)):
    """Page de gestion des bons de livraison"""
    return templates.TemplateResponse("delivery_notes.html", {"request": request, "global_settings": _load_company_settings(db)})

@app.get("/bank-transactions", response_class=HTMLResponse)
async def bank_transactions_page(request: Request, db: Session = Depends(get_db)):
    """Page de gestion des transactions bancaires"""
    return templates.TemplateResponse("bank_transactions.html", {"request": request, "global_settings": _load_company_settings(db)})

@app.get("/reports", response_class=HTMLResponse)
async def reports_page(request: Request, db: Session = Depends(get_db)):
    """Page des rapports"""
    return templates.TemplateResponse("reports.html", {"request": request, "global_settings": _load_company_settings(db)})

@app.get("/supplier-invoices", response_class=HTMLResponse)
async def supplier_invoices_page(request: Request, db: Session = Depends(get_db)):
    """Page de gestion des factures fournisseur"""
    return templates.TemplateResponse("supplier_invoices.html", {"request": request, "global_settings": _load_company_settings(db)})

@app.get("/debts", response_class=HTMLResponse)
async def debts_page(request: Request, db: Session = Depends(get_db)):
    """Page de gestion des dettes"""
    return templates.TemplateResponse("debts.html", {"request": request, "global_settings": _load_company_settings(db)})

@app.get("/barcode-generator", response_class=HTMLResponse)
async def barcode_generator_page(request: Request, db: Session = Depends(get_db)):
    """Page du générateur de codes-barres"""
    return templates.TemplateResponse("barcode_generator.html", {"request": request, "global_settings": _load_company_settings(db)})

@app.get("/guide", response_class=HTMLResponse)
async def guide_page(request: Request, db: Session = Depends(get_db)):
    """Page du guide utilisateur"""
    return templates.TemplateResponse("guide.html", {"request": request, "global_settings": _load_company_settings(db)})

@app.get("/migration-manager", response_class=HTMLResponse)
async def migration_manager_page(request: Request, db: Session = Depends(get_db)):
    """Page du gestionnaire de migration"""
    return templates.TemplateResponse("migration_manager.html", {"request": request, "global_settings": _load_company_settings(db)})

@app.get("/cache-manager", response_class=HTMLResponse)
async def cache_manager_page(request: Request, db: Session = Depends(get_db)):
    """Page du gestionnaire de cache"""
    return templates.TemplateResponse("cache_manager.html", {"request": request, "global_settings": _load_company_settings(db)})

@app.get("/daily-recap", response_class=HTMLResponse)
async def daily_recap_page(request: Request, db: Session = Depends(get_db)):
    """Page du récap quotidien"""
    return templates.TemplateResponse("daily_recap.html", {"request": request, "global_settings": _load_company_settings(db)})

@app.get("/daily-purchases", response_class=HTMLResponse)
async def daily_purchases_page(request: Request, db: Session = Depends(get_db)):
    """Page des achats quotidiens"""
    return templates.TemplateResponse("daily_purchases.html", {"request": request, "global_settings": _load_company_settings(db)})

# ===================== PRINT ROUTES (Invoice, Delivery Note) =====================

def _load_company_settings(db: Session) -> dict:
    try:
        s = db.query(UserSettings).filter(UserSettings.setting_key == "INVOICE_COMPANY").order_by(UserSettings.updated_at.desc()).first()
        if s and s.setting_value:
            return json.loads(s.setting_value)
    except Exception:
        pass
    # Fallback 2: read from consolidated appSettings.company if present
    try:
        legacy_us = (
            db.query(UserSettings)
            .filter(UserSettings.setting_key == "appSettings")
            .order_by(UserSettings.updated_at.desc())
            .first()
        )
        if legacy_us and legacy_us.setting_value:
            data = json.loads(legacy_us.setting_value)
            comp = (data or {}).get("company") or {}
            if comp:
                return {
                    "name": comp.get("companyName") or comp.get("name"),
                    "address": comp.get("companyAddress") or comp.get("address"),
                    "email": comp.get("companyEmail") or comp.get("email"),
                    "phone": comp.get("companyPhone") or comp.get("phone"),
                    "website": comp.get("companyWebsite") or comp.get("website"),
                    "logo": comp.get("logo"),  # DataURL support
                }
    except Exception:
        pass
    # Fallback: pull from legacy Settings table if available
    try:
        if LegacySettings is not None:
            legacy = db.query(LegacySettings).first()
            if legacy:
                return {
                    "name": getattr(legacy, "company_name", None),
                    "address": getattr(legacy, "address", None),
                    "city": getattr(legacy, "city", None),
                    "email": getattr(legacy, "email", None),
                    "phone": getattr(legacy, "phone", None),
                    "phone2": getattr(legacy, "phone2", None),
                    "whatsapp": getattr(legacy, "whatsapp", None),
                    "instagram": getattr(legacy, "instagram", None),
                    "website": getattr(legacy, "website", None),
                    # Prefer unified key 'logo' for templates; keep 'logo_path' for compatibility
                    "logo": getattr(legacy, "logo_path", None),
                    "logo_path": getattr(legacy, "logo_path", None),
                    "footer_text": getattr(legacy, "footer_text", None),
                }
    except Exception:
        pass
    return {}


@app.get("/invoices/print/{invoice_id}", response_class=HTMLResponse)
async def print_invoice_page(request: Request, invoice_id: int, db: Session = Depends(get_db)):
    inv = (
        db.query(Invoice)
        .options(joinedload(Invoice.items), joinedload(Invoice.client), joinedload(Invoice.payments))
        .filter(Invoice.invoice_id == invoice_id)
        .first()
    )
    if not inv:
        raise HTTPException(status_code=404, detail="Facture non trouvée")

    # Parse IMEIs from notes meta (if present)
    imeis_by_product_id = {}
    try:
        if inv.notes:
            # Be robust: stop at next meta marker (e.g., __SIGNATURE__) or end of string
            txt = str(inv.notes)
            if "__SERIALS__=" in txt:
                sub = txt.split("__SERIALS__=", 1)[1]
                cut_idx = sub.find("\n__")
                if cut_idx != -1:
                    sub = sub[:cut_idx].strip()
                sub = sub.strip()
                try:
                    arr = json.loads(sub)
                except Exception:
                    # Fallback: non-greedy regex inside brackets
                    m = re.search(r"__SERIALS__=(\[.*?\])", txt, flags=re.S)
                    arr = json.loads(m.group(1)) if m else []
                for entry in (arr or []):
                    pid = str(entry.get("product_id"))
                    imeis_by_product_id[pid] = entry.get("imeis") or []
    except Exception:
        pass

    # Parse original quotation quantities from notes meta (if present)
    quote_qty_by_product_id = {}
    try:
        if inv.notes:
            txt = str(inv.notes)
            if "__QUOTE_QTYS__=" in txt:
                sub = txt.split("__QUOTE_QTYS__=", 1)[1]
                cut_idx = sub.find("\n__")
                if cut_idx != -1:
                    sub = sub[:cut_idx].strip()
                sub = sub.strip()
                try:
                    arrq = json.loads(sub)
                except Exception:
                    mqq = re.search(r"__QUOTE_QTYS__=(\[.*?\])", txt, flags=re.S)
                    arrq = json.loads(mqq.group(1)) if mqq else []
                for entry in (arrq or []):
                    try:
                        pid = str(int(entry.get("product_id")))
                        qty = int(entry.get("qty") or 0)
                        quote_qty_by_product_id[pid] = qty
                    except Exception:
                        pass
    except Exception:
        pass

    # Build product descriptions map for involved products
    product_descriptions = {}
    try:
        product_ids = sorted({int(it.product_id) for it in (inv.items or []) if it.product_id is not None})
        if product_ids:
            for p in db.query(Product).filter(Product.product_id.in_(product_ids)).all():
                product_descriptions[str(p.product_id)] = (p.description or "")
    except Exception:
        product_descriptions = {}

    # Group items by product_id + price and attach IMEIs (from notes or inline fallback)
    grouped = {}
    for it in (inv.items or []):
        key = f"{it.product_id}|{float(it.price or 0)}"
        if key not in grouped:
            grouped[key] = {
                "product_id": it.product_id,
                "name": it.product_name,
                "description": product_descriptions.get(str(it.product_id)) if it.product_id is not None else "",
                "price": float(it.price or 0),
                "qty": 0,
                "total": 0.0,
                "imeis": [],  # list of IMEIs to render on separate lines
                "quote_qty": None,
            }
        g = grouped[key]
        g["qty"] += int(it.quantity or 0)
        g["total"] += float(it.total or 0)
        # Fallback: extract inline IMEI from product_name like "(IMEI: 123...)"
        try:
            pname = (it.product_name or "")
            m = re.search(r"\(IMEI:\s*([^)]+)\)", pname, flags=re.I)
            if m:
                imei = (m.group(1) or "").strip()
                if imei and imei not in g["imeis"]:
                    g["imeis"].append(imei)
        except Exception:
            pass

    # Replace qty/total with IMEIs count when available (notes meta has priority; fallback to inline parsed)
    for g in grouped.values():
        lst = imeis_by_product_id.get(str(g["product_id"])) or []
        # Attach original quotation quantity if available
        try:
            g["quote_qty"] = quote_qty_by_product_id.get(str(g["product_id"]))
        except Exception:
            g["quote_qty"] = g.get("quote_qty")
        if lst:
            g["imeis"] = lst
            g["qty"] = len(lst)
            g["total"] = g["qty"] * float(g["price"])
        elif g.get("imeis"):
            g["qty"] = len(g["imeis"])
            g["total"] = g["qty"] * float(g["price"])

    # Extract signature image from notes if embedded
    signature_data_url = None
    try:
        if inv.notes:
            m2 = re.search(r"__SIGNATURE__=(.*)$", inv.notes, flags=re.S)
            if m2:
                signature_data_url = (m2.group(1) or '').strip()
    except Exception:
        pass

    company_settings = _load_company_settings(db)

    # Resolve payment method: invoice.payment_method or latest payment's method
    resolved_payment_method = getattr(inv, "payment_method", None)
    try:
        if not resolved_payment_method and getattr(inv, "payments", None):
            latest = None
            for p in inv.payments:
                if not latest:
                    latest = p
                else:
                    try:
                        if (p.payment_date or 0) > (latest.payment_date or 0):
                            latest = p
                    except Exception:
                        pass
            if latest and getattr(latest, "payment_method", None):
                resolved_payment_method = latest.payment_method
    except Exception:
        pass

    context = {
        "request": request,
        "invoice": inv,
        "grouped_items": list(grouped.values()),
        "signature_data_url": signature_data_url,
        "resolved_payment_method": resolved_payment_method,
        # Pass through the whole company settings dict to let the template use additional fields
        "settings": {
            "company_name": company_settings.get("name"),
            "address": company_settings.get("address"),
            "city": company_settings.get("city"),
            "email": company_settings.get("email"),
            "phone": company_settings.get("phone"),
            "phone2": company_settings.get("phone2"),
            "whatsapp": company_settings.get("whatsapp"),
            "instagram": company_settings.get("instagram"),
            "website": company_settings.get("website"),
            "logo": _normalize_logo(company_settings.get("logo") or company_settings.get("logo_path")),
            "logo_path": company_settings.get("logo_path"),
            "footer_text": company_settings.get("footer_text"),
            # Optional legal fields
            "rc_number": company_settings.get("rc_number"),
            "ninea_number": company_settings.get("ninea_number"),
        },
    }
    return templates.TemplateResponse("print_invoice.html", context)


@app.get("/quotations/print/{quotation_id}", response_class=HTMLResponse)
async def print_quotation_page(request: Request, quotation_id: int, db: Session = Depends(get_db)):
    from app.database import Quotation, Client
    q = (
        db.query(Quotation)
        .options(joinedload(Quotation.items), joinedload(Quotation.client))
        .filter(Quotation.quotation_id == quotation_id)
        .first()
    )
    if not q:
        raise HTTPException(status_code=404, detail="Devis non trouvé")

    # Signature depuis notes meta si présente
    signature_data_url = None
    try:
        if q.notes:
            m2 = re.search(r"__SIGNATURE__=(.*)$", q.notes, flags=re.S)
            if m2:
                signature_data_url = (m2.group(1) or '').strip()
    except Exception:
        pass

    # Build product descriptions map
    product_descriptions = {}
    try:
        product_ids = sorted({int(it.product_id) for it in (q.items or []) if it.product_id is not None})
        if product_ids:
            for p in db.query(Product).filter(Product.product_id.in_(product_ids)).all():
                product_descriptions[str(p.product_id)] = (p.description or "")
    except Exception:
        product_descriptions = {}

    company_settings = _load_company_settings(db)
    context = {
        "request": request,
        "quotation": q,
        "client": q.client,
        "settings": {
            **company_settings,
            "logo": _normalize_logo(company_settings.get("logo") or company_settings.get("logo_path")),
        },
        "signature_data_url": signature_data_url,
        "product_descriptions": product_descriptions,
    }
    return templates.TemplateResponse("print_quotation.html", context)

@app.get("/delivery-notes/print/{note_id}", response_class=HTMLResponse)
async def print_delivery_note_page(request: Request, note_id: int, db: Session = Depends(get_db)):
    # Try in-memory demo data first (from router), fallback to DB if needed
    try:
        from app.routers.delivery_notes import delivery_notes_data  # type: ignore
        note = next((n for n in delivery_notes_data if int(n.get("id")) == int(note_id)), None)
    except Exception:
        note = None

    # Fallback: charger depuis la base de données réelle
    if not note:
        dn = (
            db.query(DeliveryNote)
            .options(joinedload(DeliveryNote.items), joinedload(DeliveryNote.client))
            .filter(DeliveryNote.delivery_note_id == note_id)
            .first()
        )
        if not dn:
            raise HTTPException(status_code=404, detail="Bon de livraison non trouvé")
        
        # Traiter les items avec nettoyage des noms de produits
        items = []
        for it in (dn.items or []):
            # Nettoyer le libellé: retirer un éventuel suffixe "(IMEI: xxx)"
            clean_name = re.sub(r"\s*\(IMEI:\s*[^)]+\)\s*$", "", (it.product_name or ""), flags=re.I)
            
            # Parser les séries/IMEI
            serials = []
            try:
                serial_str = it.serial_numbers or ""
                if isinstance(serial_str, str) and serial_str.strip().startswith("["):
                    serials = json.loads(serial_str)
            except Exception:
                serials = []
            
            items.append({
                "product_id": it.product_id,
                "product_name": clean_name,
                "quantity": it.quantity,
                "unit_price": float(it.price or 0),
                "serials": serials
            })

        note = {
            "id": dn.delivery_note_id,
            "number": dn.delivery_note_number,
            "client_id": dn.client_id,
            "client_name": (dn.client.name if dn.client else None),
            "date": dn.date,
            "delivery_date": dn.delivery_date,
            "status": dn.status,
            "delivery_address": dn.delivery_address,
            "delivery_contact": dn.delivery_contact,
            "delivery_phone": dn.delivery_phone,
            "items": items,
            "subtotal": float(dn.subtotal or 0),
            "tax_rate": float(dn.tax_rate or 0),
            "tax_amount": float(dn.tax_amount or 0),
            "total": float(dn.total or 0),
            "notes": dn.notes,
            "created_at": dn.created_at,
        }

    # Construire la map des descriptions produits (clé: str(product_id))
    product_descriptions = {}
    try:
        item_list = (note.get("items") if isinstance(note, dict) else []) or []
        product_ids = sorted({int(it.get("product_id")) for it in item_list if it.get("product_id") is not None})
        if product_ids:
            for p in db.query(Product).filter(Product.product_id.in_(product_ids)).all():
                product_descriptions[str(p.product_id)] = (p.description or "")
    except Exception:
        product_descriptions = {}

    # Extraire la signature depuis les notes du bon de livraison si présente
    signature_data_url = None
    try:
        if note and note.get("notes"):
            m2 = re.search(r"__SIGNATURE__=(.*)$", note["notes"], flags=re.S)
            if m2:
                signature_data_url = (m2.group(1) or '').strip()
    except Exception:
        pass

    company_settings = _load_company_settings(db)
    context = {
        "request": request,
        "note": note,
        "product_descriptions": product_descriptions,
        "signature_data_url": signature_data_url,
        "settings": {
            "company_name": company_settings.get("name"),
            "address": company_settings.get("address"),
            "email": company_settings.get("email"),
            "phone": company_settings.get("phone"),
            "phone2": company_settings.get("phone2"),
            "whatsapp": company_settings.get("whatsapp"),
            "instagram": company_settings.get("instagram"),
            "website": company_settings.get("website"),
            "logo": company_settings.get("logo"),
            "rc_number": company_settings.get("rc_number"),
            "ninea_number": company_settings.get("ninea_number"),
        },
    }
    return templates.TemplateResponse("print_delivery_note.html", context)

# Gestion des erreurs
@app.exception_handler(404)
async def not_found_handler(request: Request, exc: HTTPException):
    return templates.TemplateResponse("404.html", {"request": request}, status_code=404)

@app.exception_handler(500)
async def internal_error_handler(request: Request, exc: HTTPException):
    return templates.TemplateResponse("500.html", {"request": request}, status_code=500)

if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level="info"
    )
