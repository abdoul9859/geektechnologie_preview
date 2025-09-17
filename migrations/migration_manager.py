#!/usr/bin/env python3
"""
Gestionnaire de migrations automatiques pour l'application
S'exécute automatiquement lors du démarrage de l'application
"""

import os
import sys
import logging
from datetime import datetime
from typing import List, Dict, Any
from sqlalchemy import create_engine, text, inspect
from sqlalchemy.exc import SQLAlchemyError
from dotenv import load_dotenv

# Configuration du logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class MigrationManager:
    """Gestionnaire de migrations de base de données"""
    
    def __init__(self):
        load_dotenv()
        self.database_url = self._get_database_url()
        self.engine = create_engine(self.database_url)
        self.migrations_table = "schema_migrations"
    
    def _get_database_url(self) -> str:
        """Récupère et normalise l'URL de la base de données"""
        database_url = os.getenv("DATABASE_URL")
        if not database_url:
            raise ValueError("DATABASE_URL non définie dans les variables d'environnement")
        
        # Normaliser l'URL pour SQLAlchemy
        if database_url.startswith("postgres://"):
            database_url = database_url.replace("postgres://", "postgresql+psycopg://", 1)
        elif database_url.startswith("postgresql://"):
            database_url = database_url.replace("postgresql://", "postgresql+psycopg://", 1)
        
        return database_url
    
    def _create_migrations_table(self):
        """Crée la table de suivi des migrations si elle n'existe pas"""
        try:
            with self.engine.connect() as conn:
                conn.execute(text(f"""
                    CREATE TABLE IF NOT EXISTS {self.migrations_table} (
                        id SERIAL PRIMARY KEY,
                        version VARCHAR(50) UNIQUE NOT NULL,
                        description TEXT,
                        applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        checksum VARCHAR(64)
                    )
                """))
                conn.commit()
                logger.info(f"Table {self.migrations_table} créée/vérifiée")
        except Exception as e:
            logger.error(f"Erreur lors de la création de la table migrations: {e}")
            raise
    
    def _get_applied_migrations(self) -> List[str]:
        """Récupère la liste des migrations déjà appliquées"""
        try:
            with self.engine.connect() as conn:
                result = conn.execute(text(f"SELECT version FROM {self.migrations_table} ORDER BY applied_at"))
                return [row[0] for row in result.fetchall()]
        except Exception as e:
            logger.warning(f"Erreur lors de la récupération des migrations: {e}")
            return []
    
    def _register_migration(self, version: str, description: str, checksum: str = None):
        """Enregistre une migration comme appliquée"""
        try:
            with self.engine.connect() as conn:
                conn.execute(text(f"""
                    INSERT INTO {self.migrations_table} (version, description, checksum)
                    VALUES (:version, :description, :checksum)
                    ON CONFLICT (version) DO NOTHING
                """), {
                    "version": version,
                    "description": description,
                    "checksum": checksum
                })
                conn.commit()
                logger.info(f"Migration {version} enregistrée")
        except Exception as e:
            logger.error(f"Erreur lors de l'enregistrement de la migration {version}: {e}")
            raise
    
    def _execute_migration(self, migration: Dict[str, Any]) -> bool:
        """Exécute une migration spécifique"""
        try:
            logger.info(f"Exécution de la migration: {migration['version']} - {migration['description']}")
            
            with self.engine.connect() as conn:
                # Exécuter la migration
                if 'up' in migration:
                    conn.execute(text(migration['up']))
                
                # Enregistrer la migration
                self._register_migration(
                    migration['version'],
                    migration['description'],
                    migration.get('checksum')
                )
                
                conn.commit()
                logger.info(f"Migration {migration['version']} appliquée avec succès")
                return True
                
        except Exception as e:
            logger.error(f"Erreur lors de l'exécution de la migration {migration['version']}: {e}")
            return False
    
    def run_migrations(self):
        """Exécute toutes les migrations en attente"""
        try:
            logger.info("Démarrage du processus de migration")
            
            # Créer la table de suivi des migrations
            self._create_migrations_table()
            
            # Récupérer les migrations déjà appliquées
            applied_migrations = self._get_applied_migrations()
            logger.info(f"Migrations déjà appliquées: {applied_migrations}")
            
            # Récupérer toutes les migrations disponibles
            available_migrations = self._get_available_migrations()
            
            # Exécuter les migrations en attente
            pending_migrations = [
                m for m in available_migrations 
                if m['version'] not in applied_migrations
            ]
            
            if not pending_migrations:
                logger.info("Aucune migration en attente")
                return True
            
            logger.info(f"Migration(s) en attente: {len(pending_migrations)}")
            
            # Exécuter chaque migration
            for migration in pending_migrations:
                if not self._execute_migration(migration):
                    logger.error(f"Échec de la migration {migration['version']}")
                    return False
            
            logger.info("Toutes les migrations ont été appliquées avec succès")
            return True
            
        except Exception as e:
            logger.error(f"Erreur lors de l'exécution des migrations: {e}")
            return False
    
    def _get_available_migrations(self) -> List[Dict[str, Any]]:
        """Récupère la liste de toutes les migrations disponibles"""
        return [
            {
                "version": "001_add_signature_to_delivery_notes",
                "description": "Ajouter le champ signature_data_url à la table delivery_notes",
                "up": """
                    ALTER TABLE delivery_notes 
                    ADD COLUMN IF NOT EXISTS signature_data_url TEXT
                """,
                "checksum": "signature_delivery_notes_001"
            },
            # Ajouter d'autres migrations ici au fur et à mesure
        ]
    
    def check_database_connection(self) -> bool:
        """Vérifie la connexion à la base de données"""
        try:
            with self.engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            logger.info("Connexion à la base de données réussie")
            return True
        except Exception as e:
            logger.error(f"Erreur de connexion à la base de données: {e}")
            return False

def run_migrations():
    """Fonction principale pour exécuter les migrations"""
    try:
        migration_manager = MigrationManager()
        
        # Vérifier la connexion
        if not migration_manager.check_database_connection():
            logger.error("Impossible de se connecter à la base de données")
            return False
        
        # Exécuter les migrations
        return migration_manager.run_migrations()
        
    except Exception as e:
        logger.error(f"Erreur lors de l'exécution des migrations: {e}")
        return False

if __name__ == "__main__":
    success = run_migrations()
    sys.exit(0 if success else 1)
