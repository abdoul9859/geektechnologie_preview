"""
Script d'optimisation de la base de données pour améliorer les performances du dashboard
"""

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
import os
from dotenv import load_dotenv

load_dotenv()

def get_optimized_engine():
    """Récupère le moteur de base de données avec les optimisations"""
    from .database import DATABASE_URL, engine_kwargs
    return create_engine(DATABASE_URL, **engine_kwargs)

def create_performance_indexes(engine):
    """Crée les index nécessaires pour optimiser les performances (génériques)"""
    
    indexes_to_create = [
        # Index pour les factures (optimise les calculs dashboard)
        "CREATE INDEX IF NOT EXISTS idx_invoices_date_status ON invoices(date, status)",
        "CREATE INDEX IF NOT EXISTS idx_invoices_status ON invoices(status)",
        "CREATE INDEX IF NOT EXISTS idx_invoices_date ON invoices(date)",
        "CREATE INDEX IF NOT EXISTS idx_invoices_client_date ON invoices(client_id, date)",
        
        # Index pour les paiements de factures
        "CREATE INDEX IF NOT EXISTS idx_invoice_payments_date ON invoice_payments(payment_date)",
        "CREATE INDEX IF NOT EXISTS idx_invoice_payments_method_date ON invoice_payments(payment_method, payment_date)",
        
        # Index pour les articles de factures (top produits)
        "CREATE INDEX IF NOT EXISTS idx_invoice_items_invoice_id ON invoice_items(invoice_id)",
        "CREATE INDEX IF NOT EXISTS idx_invoice_items_product_name ON invoice_items(product_name)",
        
        # Index pour les devis
        "CREATE INDEX IF NOT EXISTS idx_quotations_date ON quotations(date)",
        "CREATE INDEX IF NOT EXISTS idx_quotations_status ON quotations(status)",
        
        # Index pour les produits (filtres stock et catégorie)
        "CREATE INDEX IF NOT EXISTS idx_products_quantity ON products(quantity)",
        "CREATE INDEX IF NOT EXISTS idx_products_category ON products(category)",
        "CREATE INDEX IF NOT EXISTS idx_products_brand ON products(brand)",
        "CREATE INDEX IF NOT EXISTS idx_products_model ON products(model)",
        "CREATE INDEX IF NOT EXISTS idx_products_barcode ON products(barcode)",
        
        # Index pour les variantes (accélère résumés et recherches)
        "CREATE INDEX IF NOT EXISTS idx_product_variants_product ON product_variants(product_id)",
        "CREATE INDEX IF NOT EXISTS idx_product_variants_product_sold ON product_variants(product_id, is_sold)",
        "CREATE INDEX IF NOT EXISTS idx_product_variants_condition ON product_variants(condition)",
        "CREATE INDEX IF NOT EXISTS idx_product_variants_barcode ON product_variants(barcode)",
        "CREATE INDEX IF NOT EXISTS idx_product_variants_imei ON product_variants(imei_serial)",
        
        # Index pour les mouvements de stock
        "CREATE INDEX IF NOT EXISTS idx_stock_movements_created_at ON stock_movements(created_at)",
        "CREATE INDEX IF NOT EXISTS idx_stock_movements_product_date ON stock_movements(product_id, created_at)",
        
        # Index pour les clients actifs
        "CREATE INDEX IF NOT EXISTS idx_invoices_client_id ON invoices(client_id)",
    ]
    
    with engine.connect() as conn:
        for index_sql in indexes_to_create:
            try:
                print(f"Création de l'index: {index_sql}")
                conn.execute(text(index_sql))
                conn.commit()
                print("✅ Index créé avec succès")
            except Exception as e:
                print(f"⚠️ Erreur lors de la création de l'index (peut-être déjà existant): {e}")
                conn.rollback()


def create_postgres_specific_indexes(engine):
    """Crée les index spécifiques PostgreSQL (trigram et fonctionnels)."""
    try:
        with engine.connect() as conn:
            version = conn.execute(text("SELECT version()"))
            version_str = version.scalar() or ''
            if 'PostgreSQL' not in version_str:
                print("📊 Base de données non-PostgreSQL: index spécifiques ignorés")
                return
            print("🐘 PostgreSQL détecté: création d'index spécifiques (pg_trgm, fonctionnels)...")
            # Activer l'extension trigram
            try:
                conn.execute(text("CREATE EXTENSION IF NOT EXISTS pg_trgm"))
                conn.commit()
            except Exception as e:
                print(f"ℹ️ Extension pg_trgm: {e}")
                conn.rollback()
            
            pg_indexes = [
                # Trigram pour recherches ILIKE sur produits
                "CREATE INDEX IF NOT EXISTS idx_products_name_trgm ON products USING gin (name gin_trgm_ops)",
                "CREATE INDEX IF NOT EXISTS idx_products_brand_trgm ON products USING gin (brand gin_trgm_ops)",
                "CREATE INDEX IF NOT EXISTS idx_products_model_trgm ON products USING gin (model gin_trgm_ops)",
                "CREATE INDEX IF NOT EXISTS idx_products_barcode_trgm ON products USING gin (barcode gin_trgm_ops)",
                
                # Trigram pour variantes (scan et recherche)
                "CREATE INDEX IF NOT EXISTS idx_product_variants_barcode_trgm ON product_variants USING gin (barcode gin_trgm_ops)",
                "CREATE INDEX IF NOT EXISTS idx_product_variants_imei_trgm ON product_variants USING gin (imei_serial gin_trgm_ops)",
                
                # Index fonctionnel pour filtres/agrégations sur condition insensible à la casse/espaces
                "CREATE INDEX IF NOT EXISTS idx_product_variants_condition_norm ON product_variants (lower(btrim(condition)))",
            ]
            for idx in pg_indexes:
                try:
                    print(f"Création index PostgreSQL: {idx}")
                    conn.execute(text(idx))
                    conn.commit()
                    print("✅ Index PostgreSQL créé")
                except Exception as e:
                    print(f"⚠️ Erreur index PostgreSQL: {e}")
                    conn.rollback()
    except Exception as e:
        print(f"❌ Erreur create_postgres_specific_indexes: {e}")

def optimize_postgresql_settings(engine):
    """Applique des optimisations spécifiques à PostgreSQL"""
    
    postgresql_optimizations = [
        # Augmenter les statistiques pour de meilleures estimations
        "ALTER TABLE invoices ALTER COLUMN date SET STATISTICS 1000",
        "ALTER TABLE invoices ALTER COLUMN status SET STATISTICS 1000",
        "ALTER TABLE invoice_payments ALTER COLUMN payment_date SET STATISTICS 1000",
        
        # Analyser les tables pour mettre à jour les statistiques
        "ANALYZE invoices",
        "ANALYZE invoice_items",
        "ANALYZE invoice_payments", 
        "ANALYZE quotations",
        "ANALYZE products",
        "ANALYZE stock_movements",
    ]
    
    try:
        with engine.connect() as conn:
            # Vérifier si c'est PostgreSQL
            result = conn.execute(text("SELECT version()"))
            version = result.scalar()
            
            if 'PostgreSQL' in version:
                print("🐘 Optimisations PostgreSQL détectées")
                for optimization_sql in postgresql_optimizations:
                    try:
                        print(f"Exécution: {optimization_sql}")
                        conn.execute(text(optimization_sql))
                        conn.commit()
                        print("✅ Optimisation appliquée")
                    except Exception as e:
                        print(f"⚠️ Erreur optimisation PostgreSQL: {e}")
                        conn.rollback()
            else:
                print("📊 Base de données non-PostgreSQL détectée, optimisations spécifiques ignorées")
                
    except Exception as e:
        print(f"❌ Erreur lors de la vérification de la base: {e}")

def add_missing_columns(engine):
    """Ajoute les colonnes manquantes si nécessaire"""
    
    column_additions = [
        # S'assurer que les colonnes condition existent
        "ALTER TABLE products ADD COLUMN IF NOT EXISTS condition VARCHAR(50) DEFAULT 'neuf'",
        "ALTER TABLE product_variants ADD COLUMN IF NOT EXISTS condition VARCHAR(50)",
    ]
    
    with engine.connect() as conn:
        for column_sql in column_additions:
            try:
                print(f"Vérification colonne: {column_sql}")
                conn.execute(text(column_sql))
                conn.commit()
                print("✅ Colonne ajoutée/vérifiée")
            except Exception as e:
                # Normal si la colonne existe déjà ou si ce n'est pas PostgreSQL
                print(f"ℹ️ Colonne probablement déjà existante: {e}")
                conn.rollback()

def optimize_database():
    """Fonction principale d'optimisation de la base de données"""
    print("🚀 Démarrage de l'optimisation de la base de données...")
    
    try:
        engine = get_optimized_engine()
        print("✅ Connexion à la base de données établie")
        
        # 1. Ajouter les colonnes manquantes
        print("\n📝 Vérification des colonnes...")
        add_missing_columns(engine)
        
        # 2. Créer les index de performance
        print("\n🔍 Création des index de performance...")
        create_performance_indexes(engine)

        # 3. Index spécifiques PostgreSQL (trigram + fonctionnels)
        print("\n🧩 Index spécifiques PostgreSQL...")
        create_postgres_specific_indexes(engine)
        
        # 4. Optimisations spécifiques PostgreSQL
        print("\n🐘 Optimisations PostgreSQL...")
        optimize_postgresql_settings(engine)
        
        print("\n✅ Optimisation de la base de données terminée avec succès!")
        print("📊 Le dashboard devrait maintenant être plus rapide")
        
    except Exception as e:
        print(f"❌ Erreur lors de l'optimisation: {e}")
        raise

if __name__ == "__main__":
    optimize_database()
