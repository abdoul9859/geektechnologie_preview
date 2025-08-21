#!/usr/bin/env python3
"""
Script de migration pour simplifier les factures fournisseur.

Ce script modifie la structure de la table supplier_invoices pour passer
de l'ancienne structure complexe avec items à la nouvelle structure simplifiée
avec seulement description et montant.
"""

import sys
import os
from sqlalchemy import text, create_engine
from sqlalchemy.orm import sessionmaker

# Ajouter le répertoire parent au Python path pour les imports
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.database import engine, SessionLocal


def migrate_supplier_invoices():
    """Migrer la structure des factures fournisseur"""
    
    session = SessionLocal()
    try:
        print("🔄 Début de la migration des factures fournisseur...")
        
        # 1. Vérifier si les colonnes existent déjà
        print("📋 Vérification de la structure actuelle...")
        
        check_columns_query = text("""
            SELECT column_name, data_type 
            FROM information_schema.columns 
            WHERE table_name = 'supplier_invoices' AND table_schema = 'public'
        """)
        
        columns = session.execute(check_columns_query).fetchall()
        column_names = [col[0] for col in columns]
        
        print(f"📊 Colonnes actuelles: {column_names}")
        
        # 2. Ajouter les nouvelles colonnes si nécessaire
        migrations_needed = []
        
        if 'description' not in column_names:
            migrations_needed.append("ADD COLUMN description TEXT NOT NULL DEFAULT 'Facture fournisseur'")
        
        if 'amount' not in column_names:
            migrations_needed.append("ADD COLUMN amount NUMERIC(12,2) NOT NULL DEFAULT 0")
        
        if migrations_needed:
            print("🔧 Ajout des nouvelles colonnes...")
            alter_query = f"ALTER TABLE supplier_invoices {', '.join(migrations_needed)}"
            session.execute(text(alter_query))
            session.commit()
            print("✅ Nouvelles colonnes ajoutées")
        
        # 3. Migrer les données des anciennes colonnes vers les nouvelles
        print("📦 Migration des données...")
        
        # Compter les factures à migrer
        count_query = text("SELECT COUNT(*) FROM supplier_invoices WHERE amount = 0")
        to_migrate = session.execute(count_query).scalar()
        
        if to_migrate > 0:
            print(f"🔄 Migration de {to_migrate} facture(s)...")
            
            # Migrer les données : utiliser le total comme amount, et créer une description basée sur les items
            migration_query = text("""
                UPDATE supplier_invoices 
                SET 
                    amount = COALESCE(total, 0),
                    description = CASE 
                        WHEN notes IS NOT NULL AND notes != '' THEN notes
                        ELSE CONCAT('Facture ', invoice_number, ' - ', 
                             COALESCE((SELECT name FROM suppliers WHERE supplier_id = supplier_invoices.supplier_id), 'Fournisseur'))
                    END
                WHERE amount = 0 OR amount IS NULL
            """)
            
            result = session.execute(migration_query)
            session.commit()
            
            print(f"✅ {result.rowcount} facture(s) migrée(s)")
        else:
            print("ℹ️ Aucune migration de données nécessaire")
        
        # 4. Supprimer les anciennes colonnes si elles existent (optionnel)
        old_columns_to_remove = ['subtotal', 'tax_rate', 'tax_amount', 'total']
        columns_to_remove = [col for col in old_columns_to_remove if col in column_names]
        
        if columns_to_remove:
            print("🗑️ Suppression des anciennes colonnes...")
            for col in columns_to_remove:
                try:
                    drop_query = text(f"ALTER TABLE supplier_invoices DROP COLUMN IF EXISTS {col}")
                    session.execute(drop_query)
                    print(f"   ✅ Colonne {col} supprimée")
                except Exception as e:
                    print(f"   ⚠️ Impossible de supprimer {col}: {e}")
            
            session.commit()
        
        # 5. Supprimer la table supplier_invoice_items si elle existe
        print("🗑️ Suppression de la table supplier_invoice_items...")
        try:
            drop_items_table = text("DROP TABLE IF EXISTS supplier_invoice_items CASCADE")
            session.execute(drop_items_table)
            session.commit()
            print("   ✅ Table supplier_invoice_items supprimée")
        except Exception as e:
            print(f"   ⚠️ Erreur lors de la suppression: {e}")
        
        # 6. Vérifier le résultat final
        print("🔍 Vérification de la structure finale...")
        final_columns = session.execute(check_columns_query).fetchall()
        final_column_names = [col[0] for col in final_columns]
        
        print(f"✅ Structure finale: {final_column_names}")
        
        # 7. Afficher quelques exemples de données migrées
        print("📋 Exemples de données migrées:")
        sample_query = text("""
            SELECT invoice_number, description, amount, paid_amount, remaining_amount
            FROM supplier_invoices 
            ORDER BY created_at DESC 
            LIMIT 3
        """)
        
        samples = session.execute(sample_query).fetchall()
        for sample in samples:
            print(f"   📄 {sample[0]}: {sample[1][:50]}... - {sample[2]} (payé: {sample[3]}, reste: {sample[4]})")
        
        print("🎉 Migration terminée avec succès!")
        
    except Exception as e:
        print(f"❌ Erreur lors de la migration: {e}")
        session.rollback()
        raise
    finally:
        session.close()


def verify_migration():
    """Vérifier que la migration s'est bien passée"""
    session = SessionLocal()
    try:
        print("\n🔍 Vérification de la migration...")
        
        # Vérifier que les colonnes requises existent
        check_query = text("""
            SELECT column_name, data_type, is_nullable
            FROM information_schema.columns 
            WHERE table_name = 'supplier_invoices' AND table_schema = 'public'
            AND column_name IN ('description', 'amount')
        """)
        
        required_columns = session.execute(check_query).fetchall()
        
        if len(required_columns) >= 2:
            print("✅ Colonnes requises présentes")
            for col in required_columns:
                print(f"   - {col[0]}: {col[1]} (nullable: {col[2]})")
        else:
            print("❌ Colonnes requises manquantes")
            return False
        
        # Vérifier que les données ont été migrées
        data_check = text("SELECT COUNT(*) FROM supplier_invoices WHERE amount > 0")
        migrated_count = session.execute(data_check).scalar()
        
        print(f"📊 {migrated_count} facture(s) avec montant > 0")
        
        return True
        
    except Exception as e:
        print(f"❌ Erreur lors de la vérification: {e}")
        return False
    finally:
        session.close()


if __name__ == "__main__":
    print("🚀 Script de migration des factures fournisseur")
    print("=" * 50)
    
    try:
        migrate_supplier_invoices()
        if verify_migration():
            print("\n🎉 Migration complètement réussie!")
        else:
            print("\n⚠️ Migration avec des avertissements")
            
    except Exception as e:
        print(f"\n💥 Échec de la migration: {e}")
        sys.exit(1)
