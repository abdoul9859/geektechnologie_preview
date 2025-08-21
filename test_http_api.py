#!/usr/bin/env python3
"""
Script de test HTTP direct pour l'API des factures fournisseur
"""

import requests
import json

def test_api():
    """Tester l'API via HTTP"""
    base_url = "https://vast-lizzie-aadm-7bcf6531.koyeb.app"
    
    try:
        print("🔄 Test de l'API des factures fournisseur via HTTP...")
        
        # Test 1: Obtenir les statistiques (endpoint le plus simple)
        print("📊 Test 1: Statistiques...")
        try:
            response = requests.get(f"{base_url}/api/supplier-invoices/stats/summary")
            print(f"  Status Code: {response.status_code}")
            if response.status_code == 200:
                data = response.json()
                print(f"  ✅ Statistiques récupérées: {data}")
            elif response.status_code == 401:
                print("  🔒 Erreur d'authentification (normal sans login)")
            else:
                print(f"  ❌ Erreur: {response.text}")
        except Exception as e:
            print(f"  ❌ Erreur lors de la requête: {e}")
        
        # Test 2: Obtenir la liste des factures
        print("📋 Test 2: Liste des factures...")
        try:
            response = requests.get(f"{base_url}/api/supplier-invoices/")
            print(f"  Status Code: {response.status_code}")
            if response.status_code == 200:
                data = response.json()
                print(f"  ✅ Liste récupérée: {len(data.get('invoices', []))} factures")
            elif response.status_code == 401:
                print("  🔒 Erreur d'authentification (normal sans login)")
            elif response.status_code == 422:
                print(f"  ❌ Erreur 422: {response.text}")
            else:
                print(f"  ❌ Erreur: {response.text}")
        except Exception as e:
            print(f"  ❌ Erreur lors de la requête: {e}")
        
        # Test 3: Vérifier que le endpoint existe
        print("🔍 Test 3: Vérification des endpoints...")
        try:
            response = requests.options(f"{base_url}/api/supplier-invoices/")
            print(f"  Status Code OPTIONS: {response.status_code}")
            print(f"  Headers: {dict(response.headers)}")
        except Exception as e:
            print(f"  ❌ Erreur OPTIONS: {e}")
        
        print("✅ Tests HTTP terminés!")
        
    except Exception as e:
        print(f"❌ Erreur générale: {e}")

if __name__ == "__main__":
    test_api()
