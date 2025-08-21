#!/usr/bin/env python3
"""
Script de migration pour créer les tables des factures fournisseur
"""

import os
import sys
from pathlib import Path

# Ajouter le répertoire racine au path Python
root_dir = Path(__file__).parent
sys.path.insert(0, str(root_dir))

from app.database import engine, Base
from app.database import (
    SupplierInvoice, SupplierInvoiceItem, SupplierInvoicePayment
)

def create_supplier_invoice_tables():
    """Créer les tables des factures fournisseur"""
    try:
        print("🔄 Création des tables des factures fournisseur...")
        
        # Créer uniquement les nouvelles tables
        tables_to_create = [
            SupplierInvoice.__table__,
            SupplierInvoiceItem.__table__,
            SupplierInvoicePayment.__table__
        ]
        
        # Créer les tables si elles n'existent pas
        for table in tables_to_create:
            if not engine.dialect.has_table(engine.connect(), table.name):
                print(f"  📊 Création de la table: {table.name}")
                table.create(engine)
            else:
                print(f"  ✅ Table existante: {table.name}")
        
        print("✅ Migration terminée avec succès!")
        
    except Exception as e:
        print(f"❌ Erreur lors de la migration: {e}")
        sys.exit(1)

if __name__ == "__main__":
    create_supplier_invoice_tables()
