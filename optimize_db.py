#!/usr/bin/env python3
"""
Script standalone pour optimiser la base de données GEEK TECHNOLOGIE
Usage: python optimize_db.py
"""

import sys
from pathlib import Path

# Ajouter le répertoire racine au PYTHONPATH
root_dir = Path(__file__).parent
sys.path.insert(0, str(root_dir))

def main():
    """Exécuter l'optimisation de la base de données"""
    print("🚀 Script d'optimisation de la base de données GEEK TECHNOLOGIE")
    print("=" * 60)
    
    try:
        from app.database_optimization import optimize_database
        optimize_database()
        
        print("\n" + "=" * 60)
        print("✅ Optimisation terminée avec succès!")
        print("📊 Votre dashboard devrait maintenant être plus rapide.")
        print("🔄 Redémarrez l'application pour bénéficier pleinement des améliorations.")
        
    except ImportError as e:
        print(f"❌ Erreur d'import: {e}")
        print("Assurez-vous que toutes les dépendances sont installées avec:")
        print("pip install -r requirements.txt")
        sys.exit(1)
    except Exception as e:
        print(f"❌ Erreur lors de l'optimisation: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
