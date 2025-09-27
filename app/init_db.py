from sqlalchemy.orm import Session
from sqlalchemy import text
from datetime import datetime, timedelta, date
from decimal import Decimal
import random
import string
import os

from .database import (
    engine,
    SessionLocal,
    create_tables,
    User,
    Category,
    Client,
    Product,
    ProductVariant,
    ProductVariantAttribute,
    ProductSerialNumber,
    StockMovement,
    Quotation,
    QuotationItem,
    Invoice,
    InvoiceItem,
    InvoicePayment,
    BankTransaction,
    Supplier,
)
from .auth import get_password_hash

def init_database():
    """Initialiser la base de données avec les tables et données de base"""
    try:
        # Créer toutes les tables
        create_tables()
        print("✅ Tables créées avec succès")
        
        # Créer une session
        db = SessionLocal()
        
        try:
            # Migration légère (spécifique SQLite) supprimée pour compatibilité PostgreSQL.
            # La colonne 'requires_variants' est déjà définie dans les modèles SQLAlchemy et sera créée via create_tables().
            
            # Garde-fou: ne semer les données par défaut que si la variable d'env est activée
            seed_defaults = os.getenv("SEED_DEFAULT_DATA", "false").lower() == "true"
            if seed_defaults:
                # Créer l'utilisateur admin par défaut
                admin_user = db.query(User).filter(User.username == "admin").first()
                if not admin_user:
                    admin_user = User(
                        username="admin",
                        email="admin@geek-technologie.com",
                        password_hash=get_password_hash("admin123"),
                        full_name="Administrateur",
                        role="admin",
                        is_active=True
                    )
                    db.add(admin_user)
                    print("✅ Utilisateur admin créé")
                
                # Créer un utilisateur normal par défaut
                user = db.query(User).filter(User.username == "user").first()
                if not user:
                    user = User(
                        username="user",
                        email="user@geek-technologie.com",
                        password_hash=get_password_hash("user123"),
                        full_name="Utilisateur",
                        role="user",
                        is_active=True
                    )
                    db.add(user)
                    print("✅ Utilisateur normal créé")
                
                # Créer quelques catégories par défaut (+ config requires_variants)
                categories = [
                    {"name": "Smartphones", "requires_variants": True},
                    {"name": "Ordinateurs portables", "requires_variants": True},
                    {"name": "Tablettes", "requires_variants": True},
                    {"name": "Accessoires", "requires_variants": False},
                    {"name": "Téléphones fixes", "requires_variants": False},
                    {"name": "Montres connectées", "requires_variants": True},
                    {"name": "Électroménager", "requires_variants": False},
                    {"name": "Télévisions", "requires_variants": False},
                    {"name": "Audio & Son", "requires_variants": False},
                    {"name": "Gaming", "requires_variants": True},
                ]
                
                for cat in categories:
                    existing_cat = db.query(Category).filter(Category.name == cat["name"]).first()
                    if not existing_cat:
                        category = Category(
                            name=cat["name"],
                            description=f"Catégorie {cat['name']}",
                            requires_variants=bool(cat.get("requires_variants", False))
                        )
                        db.add(category)
                print("✅ Catégories par défaut créées")
                
                # Créer quelques clients sénégalais par défaut
                senegal_clients = [
                    {
                        "name": "Boutique Tech Plus",
                        "contact": "Mamadou Diallo",
                        "email": "contact@techplus.sn",
                        "phone": "+221 77 123 45 67",
                        "address": "Avenue Bourguiba, Plateau",
                        "city": "Dakar",
                        "country": "Sénégal"
                    },
                    {
                        "name": "Électronique Saint-Louis",
                        "contact": "Fatou Sarr",
                        "email": "info@elecstlouis.sn",
                        "phone": "+221 33 961 23 45",
                        "address": "Rue de la République",
                        "city": "Saint-Louis",
                        "country": "Sénégal"
                    },
                    {
                        "name": "Digital Thies",
                        "contact": "Ibrahima Ndiaye",
                        "email": "vente@digitalthies.sn",
                        "phone": "+221 77 456 78 90",
                        "address": "Marché Central",
                        "city": "Thies",
                        "country": "Sénégal"
                    }
                ]
                
                for client_data in senegal_clients:
                    existing_client = db.query(Client).filter(Client.name == client_data["name"]).first()
                    if not existing_client:
                        client = Client(**client_data)
                        db.add(client)
                print("✅ Clients sénégalais par défaut créés")
            
            # Seed massif de données de test si demandé
            seed_large = os.getenv("SEED_LARGE_TEST_DATA", "false").lower() == "true"
            if seed_large:
                sizes = {
                    "clients": int(os.getenv("SEED_CLIENTS", "100")),
                    "products": int(os.getenv("SEED_PRODUCTS", "300")),
                    "variants_per_product_min": int(os.getenv("SEED_VARIANTS_MIN", "1")),
                    "variants_per_product_max": int(os.getenv("SEED_VARIANTS_MAX", "5")),
                    "invoices": int(os.getenv("SEED_INVOICES", "150")),
                    "quotations": int(os.getenv("SEED_QUOTATIONS", "150")),
                    "bank_transactions": int(os.getenv("SEED_BANK_TX", "200")),
                }
                seed_large_test_data(db, sizes)

            # Commit seulement si des changements ont été ajoutés à la session
            if db.new or db.dirty or db.deleted:
                db.commit()
                print("✅ Base de données initialisée/mise à jour avec succès")
            else:
                print("ℹ️ Aucun semis de données par défaut (SEED_DEFAULT_DATA!=true) et aucune écriture effectuée")
            
        except Exception as e:
            db.rollback()
            print(f"❌ Erreur lors de l'initialisation des données: {e}")
            raise
        finally:
            db.close()
            
    except Exception as e:
        print(f"❌ Erreur lors de l'initialisation de la base de données: {e}")
        raise

def migrate_from_postgresql():
    """Fonction pour migrer les données depuis PostgreSQL (à implémenter)"""
    # Cette fonction pourra être utilisée pour migrer les données existantes
    # depuis la base PostgreSQL vers SQLite
    pass

if __name__ == "__main__":
    init_database()

# ===================== SEEDING HELPERS =====================

def _rand_choice(seq):
    return seq[random.randrange(0, len(seq))]

def _rand_str(prefix: str, n: int = 8):
    return prefix + "".join(random.choices(string.ascii_uppercase + string.digits, k=n))

def _price(min_v=1000, max_v=500000):
    v = random.randint(min_v, max_v)
    return Decimal(v)

def _rand_date_within(days: int = 180) -> datetime:
    delta = random.randint(0, days)
    return datetime.now() - timedelta(days=delta)

def seed_large_test_data(db: Session, sizes: dict):
    print("🧪 Seed massif: démarrage...")

    # Ensure some suppliers
    suppliers = []
    supplier_names = [
        "TechGlobal SARL",
        "SenCom Import",
        "DigitalExpress",
        "Afrique Devices",
        "ElectroHub Dakar",
        "Import Tech Sénégal",
        "Dakar Digital Solutions",
        "West Africa Electronics",
        "Senegal Tech Hub",
        "Digital Africa SARL",
    ]
    for name in supplier_names:
        s = db.query(Supplier).filter(Supplier.name == name).first()
        if not s:
            s = Supplier(name=name, contact_person="Commercial", phone="+22177" + str(random.randint(1000000, 9999999)))
            db.add(s)
        suppliers.append(s)

    # Categories baseline
    cat_specs = [
        ("Smartphones", True),
        ("Ordinateurs portables", True),
        ("Tablettes", True),
        ("Accessoires", False),
        ("Montres connectées", True),
        ("Électroménager", False),
        ("Télévisions", False),
        ("Audio & Son", False),
        ("Gaming", True),
        ("Téléphones fixes", False),
    ]
    cats = {}
    for (cname, req_var) in cat_specs:
        c = db.query(Category).filter(Category.name == cname).first()
        if not c:
            c = Category(name=cname, description=f"Catégorie {cname}", requires_variants=req_var)
            db.add(c)
        cats[cname] = c

    db.flush()  # assign IDs

    # Clients
    existing_clients = db.query(Client).count()
    to_create_clients = max(0, sizes.get("clients", 0) - existing_clients)
    for i in range(to_create_clients):
        c = Client(
            name=f"Client {i+1}",
            contact=f"Contact {i+1}",
            email=f"client{i+1}@example.com",
            phone=f"+221 77 {random.randint(1000000, 9999999)}",
            address=f"Adresse {i+1}",
            city=_rand_choice(["Dakar", "Thies", "Saint-Louis", "Touba", "Kaolack", "Ziguinchor", "Diourbel", "Tambacounda", "Kolda", "Fatick", "Matam", "Kédougou", "Sédhiou", "Louga"]),
            country="Sénégal",
        )
        db.add(c)

    # Products with optional variants
    brands = ["Samsung", "Apple", "Xiaomi", "Infinix", "Tecno", "HP", "Dell", "Lenovo", "Oppo", "Vivo", "Realme", "Huawei", "Nokia", "LG", "Sony", "Canon", "Epson"]
    conditions = ["neuf", "occasion", "venant", "reconditionné", "garantie"]
    existing_products = db.query(Product).count()
    to_create_products = max(0, sizes.get("products", 0) - existing_products)
    for i in range(to_create_products):
        catname = _rand_choice(list(cats.keys()))
        cat_requires_variants = cats[catname].requires_variants
        # Noms de produits plus réalistes pour le marché sénégalais
        product_names = {
            "Smartphones": ["Galaxy A", "iPhone", "Redmi Note", "Infinix Hot", "Tecno Spark", "Oppo A", "Vivo Y"],
            "Ordinateurs portables": ["ThinkPad", "Inspiron", "Pavilion", "MacBook Air", "IdeaPad", "Vostro"],
            "Tablettes": ["iPad", "Galaxy Tab", "Mi Pad", "MediaPad", "Surface"],
            "Accessoires": ["Écouteurs", "Chargeur", "Câble USB", "Coque", "Écran protecteur"],
            "Montres connectées": ["Galaxy Watch", "Apple Watch", "Mi Band", "Amazfit", "Fitbit"],
            "Électroménager": ["Réfrigérateur", "Congélateur", "Lave-linge", "Climatiseur", "Ventilateur"],
            "Télévisions": ["Smart TV", "LED TV", "4K TV", "OLED TV"],
            "Audio & Son": ["Enceinte Bluetooth", "Home Cinéma", "Amplificateur", "Microphone"],
            "Gaming": ["PlayStation", "Xbox", "Nintendo Switch", "Manette", "Casque Gaming"],
            "Téléphones fixes": ["Téléphone IP", "Téléphone sans fil", "Téléphone DECT"]
        }
        
        if catname in product_names:
            name = f"{_rand_choice(brands)} {_rand_choice(product_names[catname])} {random.randint(1,99)}"
        else:
            name = f"{_rand_choice(brands)} {_rand_choice(['S','Note','Pro','Air','Plus','Max'])}-{random.randint(1,999)}"
        p = Product(
            name=name,
            description=f"Produit de test {name}",
            quantity=0,
            price=_price(50000, 1500000) / Decimal(100),
            purchase_price=_price(30000, 900000) / Decimal(100),
            category=catname,
            brand=_rand_choice(brands),
            model=_rand_choice(["A1","A2","M2","G5","Z10","2023","2024"]),
            barcode=_rand_str("BC", 10),
            condition=_rand_choice(conditions),
            has_unique_serial=cat_requires_variants,
            entry_date=_rand_date_within(120),
        )
        db.add(p)
        db.flush()

        # Stock movements (IN) to populate quantity
        in_qty = random.randint(1, 30)
        db.add(StockMovement(product_id=p.product_id, quantity=in_qty, movement_type="IN", reference_type="SEED", unit_price=p.purchase_price))
        p.quantity += in_qty

        # Create variants if required
        if cat_requires_variants:
            nvars = random.randint(sizes.get("variants_per_product_min", 1), sizes.get("variants_per_product_max", 3))
            for _ in range(nvars):
                imei = _rand_str("IMEI", 12)
                v = ProductVariant(
                    product_id=p.product_id,
                    imei_serial=imei,
                    barcode=_rand_str("VB", 10),
                    condition=_rand_choice(conditions),
                    is_sold=False,
                )
                db.add(v)
                db.flush()
                # Attributes example
                if cats[catname].name in ("Smartphones", "Montres connectées"):
                    db.add(ProductVariantAttribute(variant=v, attribute_name="couleur", attribute_value=_rand_choice(["noir","bleu","argent","or"])) )
                    db.add(ProductVariantAttribute(variant=v, attribute_name="stockage", attribute_value=_rand_choice(["64Go","128Go","256Go"])) )

    db.flush()

    # Quotations
    all_clients = db.query(Client).all()
    all_products = db.query(Product).all()
    for i in range(sizes.get("quotations", 0)):
        if not all_clients or not all_products:
            break
        cl = _rand_choice(all_clients)
        q = Quotation(
            quotation_number=f"Q{datetime.now().strftime('%y%m%d')}-{i+1:04d}",
            client_id=cl.client_id,
            date=_rand_date_within(100),
            status=_rand_choice(["en attente","accepté","refusé","expiré"]),
            subtotal=Decimal(0), tax_rate=Decimal("18.00"), tax_amount=Decimal(0), total=Decimal(0),
            notes=None,
        )
        db.add(q)
        db.flush()
        nitems = random.randint(1, 4)
        subtotal = Decimal(0)
        for _ in range(nitems):
            pr = _rand_choice(all_products)
            qty = random.randint(1, 3)
            price = Decimal(float(pr.price))
            total = price * qty
            db.add(QuotationItem(quotation_id=q.quotation_id, product_id=pr.product_id, product_name=pr.name, quantity=qty, price=price, total=total))
            subtotal += total
        tax = (subtotal * Decimal("0.18")).quantize(Decimal("1."))
        q.subtotal = subtotal
        q.tax_amount = tax
        q.total = subtotal + tax

    # Invoices with payments and OUT stock movements
    for i in range(sizes.get("invoices", 0)):
        if not all_clients or not all_products:
            break
        cl = _rand_choice(all_clients)
        inv = Invoice(
            invoice_number=f"F{datetime.now().strftime('%y%m%d')}-{i+1:05d}",
            client_id=cl.client_id,
            date=_rand_date_within(90),
            status=_rand_choice(["en attente","payée","partiellement payée","en retard","annulée"]),
            payment_method=_rand_choice(["espèces","carte","virement"]),
            subtotal=Decimal(0), tax_rate=Decimal("18.00"), tax_amount=Decimal(0), total=Decimal(0),
            paid_amount=Decimal(0), remaining_amount=Decimal(0),
        )
        db.add(inv)
        db.flush()
        nitems = random.randint(1, 4)
        subtotal = Decimal(0)
        for _ in range(nitems):
            pr = _rand_choice(all_products)
            qty = random.randint(1, 3)
            price = Decimal(float(pr.price))
            total = price * qty
            db.add(InvoiceItem(invoice_id=inv.invoice_id, product_id=pr.product_id, product_name=pr.name, quantity=qty, price=price, total=total))
            subtotal += total
            # stock OUT movement
            db.add(StockMovement(product_id=pr.product_id, quantity=qty, movement_type="OUT", reference_type="INVOICE", reference_id=inv.invoice_id, unit_price=price))
            pr.quantity = max(0, (pr.quantity or 0) - qty)
        tax = (subtotal * Decimal("0.18")).quantize(Decimal("1."))
        inv.subtotal = subtotal
        inv.tax_amount = tax
        inv.total = subtotal + tax
        # payments
        paid = subtotal if random.random() < 0.6 else subtotal * Decimal("0.5")
        paid = paid.quantize(Decimal("1."))
        if paid > 0:
            db.add(InvoicePayment(invoice_id=inv.invoice_id, amount=paid, payment_method=inv.payment_method, payment_date=_rand_date_within(60)))
        inv.paid_amount = paid
        inv.remaining_amount = inv.total - paid

    # Bank Transactions
    for i in range(sizes.get("bank_transactions", 0)):
        ttype = _rand_choice(["entry", "exit"])
        method = _rand_choice(["virement", "cheque"])
        amt = Decimal(random.randint(5000, 200000))
        bt = BankTransaction(
            type=ttype,
            motif=_rand_choice(["Vente", "Achat", "Dépense", "Avoir", "Divers"]),
            description=f"Transaction {i+1}",
            amount=amt,
            date=_rand_date_within(200).date(),
            method=method,
            reference=_rand_str("TX", 8),
        )
        db.add(bt)

    print("🧪 Seed massif: terminé.")
