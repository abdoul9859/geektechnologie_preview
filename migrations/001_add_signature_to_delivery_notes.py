#!/usr/bin/env python3
"""
Migration 001: Ajouter le champ signature_data_url à la table delivery_notes
"""

import os
import sys
import logging
from sqlalchemy import create_engine, text
from dotenv import load_dotenv

# Configuration du logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def run_migration():
    """Exécute la migration pour ajouter le champ signature_data_url"""
    
    load_dotenv()
    
    # Récupérer l'URL de la base de données
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        logger.error("DATABASE_URL non définie dans les variables d'environnement")
        return False
    
    # Normaliser l'URL pour SQLAlchemy
    if database_url.startswith("postgres://"):
        database_url = database_url.replace("postgres://", "postgresql+psycopg://", 1)
    elif database_url.startswith("postgresql://"):
        database_url = database_url.replace("postgresql://", "postgresql+psycopg://", 1)
    
    try:
        # Connexion à la base de données
        engine = create_engine(database_url)
        
        with engine.connect() as conn:
            # Vérifier si la colonne existe déjà
            result = conn.execute(text("""
                SELECT column_name 
                FROM information_schema.columns 
                WHERE table_name = 'delivery_notes' 
                AND column_name = 'signature_data_url'
            """))
            
            if result.fetchone():
                logger.info("✅ La colonne signature_data_url existe déjà")
                return True
            
            # Ajouter la colonne signature_data_url
            conn.execute(text("""
                ALTER TABLE delivery_notes 
                ADD COLUMN signature_data_url TEXT
            """))
            
            # Valider les changements
            conn.commit()
            logger.info("✅ Migration réussie : colonne signature_data_url ajoutée à delivery_notes")
            
            return True
            
    except Exception as e:
        logger.error(f"❌ Erreur lors de la migration : {e}")
        return False

if __name__ == "__main__":
    success = run_migration()
    sys.exit(0 if success else 1)
