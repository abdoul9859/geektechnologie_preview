#!/usr/bin/env python3
"""
Script de test pour les API des factures fournisseur
"""

import os
import sys
from pathlib import Path
import asyncio
from datetime import datetime

# Ajouter le répertoire racine au path Python
root_dir = Path(__file__).parent
sys.path.insert(0, str(root_dir))

from app.database import get_db, SessionLocal
from app.routers.supplier_invoices import get_supplier_invoices, get_summary_stats
from app.auth import get_current_user

async def test_api():
    """Tester les API des factures fournisseur"""
    try:
        print("🔄 Test des API des factures fournisseur...")
        
        # Créer une session de base de données
        db = SessionLocal()
        
        # Créer un utilisateur factice pour le test
        class MockUser:
            def __init__(self):
                self.user_id = 1
                self.username = "test_user"
        
        mock_user = MockUser()
        
        # Test 1: Obtenir la liste des factures
        print("📋 Test 1: Liste des factures...")
        try:
            result = await get_supplier_invoices(
                skip=0,
                limit=20,
                search=None,
                supplier_id=None,
                status=None,
                current_user=mock_user,
                db=db
            )
            print(f"  ✅ Liste récupérée: {len(result.get('invoices', []))} factures")
        except Exception as e:
            print(f"  ❌ Erreur liste: {e}")
        
        # Test 2: Obtenir les statistiques
        print("📊 Test 2: Statistiques...")
        try:
            stats = await get_summary_stats(
                current_user=mock_user,
                db=db
            )
            print(f"  ✅ Statistiques récupérées: {stats}")
        except Exception as e:
            print(f"  ❌ Erreur statistiques: {e}")
        
        db.close()
        print("✅ Tests terminés!")
        
    except Exception as e:
        print(f"❌ Erreur générale: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(test_api())
