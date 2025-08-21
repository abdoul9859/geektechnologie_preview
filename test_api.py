#!/usr/bin/env python3

import requests
import json

def test_supplier_invoices_api():
    """Test l'API des factures fournisseur"""
    
    # Configuration
    base_url = 'http://localhost:8000'
    url = f'{base_url}/api/supplier-invoices/'
    
    # Test avec paramètres de base
    params = {
        'skip': 0,
        'limit': 20
    }
    
    try:
        print('Test de l\'API avec paramètres de base...')
        response = requests.get(url, params=params, timeout=10)
        print(f'Status: {response.status_code}')
        print(f'Content-Type: {response.headers.get("content-type", "N/A")}')
        print(f'URL complète: {response.url}')
        
        if response.status_code == 200:
            data = response.json()
            print(f'Nombre de factures: {len(data.get("invoices", []))}')
            print(f'Total: {data.get("total", 0)}')
            print('✅ Succès!')
            
        elif response.status_code == 401:
            print('❌ Erreur 401: Non authentifié')
            print('Ceci est normal si vous n\'êtes pas connecté dans le navigateur')
            
        elif response.status_code == 422:
            print('❌ Erreur 422 (Unprocessable Content)')
            try:
                error_data = response.json()
                print(f'Détails: {json.dumps(error_data, indent=2)}')
            except:
                print(f'Texte de l\'erreur: {response.text}')
                
        else:
            print(f'❌ Erreur {response.status_code}: {response.text}')
            
    except requests.exceptions.ConnectionError:
        print('❌ Erreur: Impossible de se connecter au serveur.')
        print('   Vérifiez que le serveur FastAPI est démarré sur http://localhost:8000')
        
    except Exception as e:
        print(f'❌ Erreur inattendue: {e}')

if __name__ == '__main__':
    test_supplier_invoices_api()
