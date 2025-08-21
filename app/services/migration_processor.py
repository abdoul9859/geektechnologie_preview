import asyncio
import json
import csv
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Any, Optional
from sqlalchemy.orm import Session
import threading
import time

from ..database import get_db, Migration, MigrationLog, Product, Client, Supplier
from ..routers.cache import set_cache_item

class MigrationProcessor:
    """Service de traitement des migrations en arrière-plan"""
    
    def __init__(self):
        self.running_migrations: Dict[int, bool] = {}
        self.processing_thread = None
        self.should_stop = False
    
    def start_background_processor(self):
        """Démarre le processeur en arrière-plan"""
        if self.processing_thread is None or not self.processing_thread.is_alive():
            self.should_stop = False
            self.processing_thread = threading.Thread(target=self._background_worker, daemon=True)
            self.processing_thread.start()
            print("✅ Processeur de migrations démarré")
    
    def stop_background_processor(self):
        """Arrête le processeur en arrière-plan"""
        self.should_stop = True
        if self.processing_thread and self.processing_thread.is_alive():
            self.processing_thread.join(timeout=5)
            print("✅ Processeur de migrations arrêté")
    
    def _background_worker(self):
        """Worker en arrière-plan qui traite les migrations"""
        while not self.should_stop:
            try:
                db = next(get_db())
                
                # Chercher les migrations en attente de traitement
                pending_migrations = db.query(Migration).filter(
                    Migration.status == "running",
                    Migration.migration_id.notin_(list(self.running_migrations.keys()))
                ).all()
                
                for migration in pending_migrations:
                    if migration.migration_id not in self.running_migrations:
                        # Marquer comme en cours de traitement
                        self.running_migrations[migration.migration_id] = True
                        
                        # Traiter la migration dans un thread séparé
                        thread = threading.Thread(
                            target=self._process_migration,
                            args=(migration.migration_id,),
                            daemon=True
                        )
                        thread.start()
                
                db.close()
                
            except Exception as e:
                print(f"❌ Erreur dans le worker de migrations: {e}")
            
            time.sleep(2)  # Vérifier toutes les 2 secondes
    
    def _process_migration(self, migration_id: int):
        """Traite une migration spécifique"""
        db = next(get_db())
        
        try:
            migration = db.query(Migration).get(migration_id)
            if not migration:
                return
            
            self._add_log(db, migration_id, "info", f"Début du traitement de la migration: {migration.name}")
            
            # Vérifier si un fichier est associé
            if migration.file_name:
                file_path = Path("uploads") / "migrations" / migration.file_name
                if file_path.exists():
                    self._add_log(db, migration_id, "info", f"Traitement du fichier: {migration.file_name}")
                    
                    # Traiter selon le type de migration
                    success = self._process_file(db, migration, file_path)
                    
                    if success:
                        # Marquer comme terminée avec succès
                        migration.status = "completed"
                        migration.completed_at = datetime.utcnow()
                        self._add_log(db, migration_id, "success", f"Migration terminée avec succès. {migration.success_records} enregistrements traités.")
                    else:
                        # Marquer comme échouée
                        migration.status = "failed"
                        migration.completed_at = datetime.utcnow()
                        migration.error_message = "Erreur lors du traitement du fichier"
                        self._add_log(db, migration_id, "error", "Migration échouée lors du traitement du fichier")
                else:
                    # Fichier non trouvé
                    migration.status = "failed"
                    migration.completed_at = datetime.utcnow()
                    migration.error_message = "Fichier non trouvé"
                    self._add_log(db, migration_id, "error", f"Fichier non trouvé: {migration.file_name}")
            else:
                # Pas de fichier - migration de test
                self._simulate_processing(db, migration)
            
            db.add(migration)
            db.commit()
            
        except Exception as e:
            print(f"❌ Erreur lors du traitement de la migration {migration_id}: {e}")
            migration = db.query(Migration).get(migration_id)
            if migration:
                migration.status = "failed"
                migration.completed_at = datetime.utcnow()
                migration.error_message = str(e)
                self._add_log(db, migration_id, "error", f"Erreur critique: {str(e)}")
                db.add(migration)
                db.commit()
        
        finally:
            # Retirer de la liste des migrations en cours
            if migration_id in self.running_migrations:
                del self.running_migrations[migration_id]
            db.close()
    
    def _process_file(self, db: Session, migration: Migration, file_path: Path) -> bool:
        """Traite un fichier de migration selon son type"""
        try:
            file_extension = file_path.suffix.lower()
            
            if file_extension == '.csv':
                return self._process_csv_file(db, migration, file_path)
            elif file_extension in ['.xlsx', '.xls']:
                return self._process_excel_file(db, migration, file_path)
            elif file_extension == '.json':
                return self._process_json_file(db, migration, file_path)
            else:
                self._add_log(db, migration.migration_id, "error", f"Format de fichier non supporté: {file_extension}")
                return False
                
        except Exception as e:
            self._add_log(db, migration.migration_id, "error", f"Erreur lors du traitement du fichier: {str(e)}")
            return False
    
    def _process_csv_file(self, db: Session, migration: Migration, file_path: Path) -> bool:
        """Traite un fichier CSV"""
        try:
            with open(file_path, 'r', encoding='utf-8', newline='') as csvfile:
                # Détecter le délimiteur
                sample = csvfile.read(1024)
                csvfile.seek(0)
                sniffer = csv.Sniffer()
                delimiter = sniffer.sniff(sample).delimiter
                
                reader = csv.DictReader(csvfile, delimiter=delimiter)
                rows = list(reader)
                migration.total_records = len(rows)
                
                self._add_log(db, migration.migration_id, "info", f"Fichier CSV chargé: {migration.total_records} lignes")
                
                success_count = 0
                error_count = 0
                
                for index, row in enumerate(rows):
                    try:
                        # Traiter selon le type de migration
                        if migration.type == "products":
                            success = self._import_product_from_row(db, row)
                        elif migration.type == "clients":
                            success = self._import_client_from_row(db, row)
                        elif migration.type == "suppliers":
                            success = self._import_supplier_from_row(db, row)
                        else:
                            success = True  # Migration générique
                        
                        if success:
                            success_count += 1
                        else:
                            error_count += 1
                        
                        # Mettre à jour les compteurs périodiquement
                        if (index + 1) % 10 == 0:
                            migration.processed_records = index + 1
                            migration.success_records = success_count
                            migration.error_records = error_count
                            db.add(migration)
                            db.commit()
                            
                            self._add_log(db, migration.migration_id, "info", f"Progression: {index + 1}/{migration.total_records} lignes traitées")
                    
                    except Exception as e:
                        error_count += 1
                        self._add_log(db, migration.migration_id, "warning", f"Erreur ligne {index + 1}: {str(e)}")
                
                # Mise à jour finale
                migration.processed_records = migration.total_records
                migration.success_records = success_count
                migration.error_records = error_count
                
                return error_count == 0 or success_count > 0
                
        except Exception as e:
            self._add_log(db, migration.migration_id, "error", f"Erreur lors de la lecture du CSV: {str(e)}")
            return False
    
    def _process_excel_file(self, db: Session, migration: Migration, file_path: Path) -> bool:
        """Traite un fichier Excel (nécessite openpyxl)"""
        try:
            # Pour l'instant, traitement Excel désactivé sans openpyxl
            self._add_log(db, migration.migration_id, "error", "Traitement Excel non disponible - openpyxl requis")
            return False
            
        except Exception as e:
            self._add_log(db, migration.migration_id, "error", f"Erreur lors de la lecture du fichier Excel: {str(e)}")
            return False
    
    def _process_json_file(self, db: Session, migration: Migration, file_path: Path) -> bool:
        """Traite un fichier JSON"""
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            if isinstance(data, list):
                migration.total_records = len(data)
                self._add_log(db, migration.migration_id, "info", f"Fichier JSON chargé: {migration.total_records} enregistrements")
                
                success_count = 0
                error_count = 0
                
                for index, item in enumerate(data):
                    try:
                        # Traiter selon le type
                        if migration.type == "products":
                            success = self._import_product_from_dict(db, item)
                        elif migration.type == "clients":
                            success = self._import_client_from_dict(db, item)
                        elif migration.type == "suppliers":
                            success = self._import_supplier_from_dict(db, item)
                        else:
                            success = True
                        
                        if success:
                            success_count += 1
                        else:
                            error_count += 1
                    
                    except Exception as e:
                        error_count += 1
                        self._add_log(db, migration.migration_id, "warning", f"Erreur enregistrement {index + 1}: {str(e)}")
                
                migration.processed_records = migration.total_records
                migration.success_records = success_count
                migration.error_records = error_count
                
                return error_count == 0 or success_count > 0
            else:
                self._add_log(db, migration.migration_id, "error", "Le fichier JSON doit contenir un tableau")
                return False
                
        except Exception as e:
            self._add_log(db, migration.migration_id, "error", f"Erreur lors de la lecture du JSON: {str(e)}")
            return False
    
    def _simulate_processing(self, db: Session, migration: Migration):
        """Simule le traitement d'une migration sans fichier"""
        migration.total_records = 100
        
        self._add_log(db, migration.migration_id, "info", "Début de la simulation de traitement")
        
        for i in range(0, 101, 10):
            migration.processed_records = i
            migration.success_records = i - (i // 20)  # Quelques erreurs simulées
            migration.error_records = i // 20
            
            db.add(migration)
            db.commit()
            
            self._add_log(db, migration.migration_id, "info", f"Progression: {i}/100 enregistrements traités")
            time.sleep(1)  # Simuler le temps de traitement
        
        migration.status = "completed"
        migration.completed_at = datetime.utcnow()
    
    def _import_product_from_row(self, db: Session, row) -> bool:
        """Importe un produit depuis une ligne CSV/Excel"""
        try:
            # Exemple d'import de produit - à adapter selon votre structure
            product = Product(
                name=str(row.get('name', row.get('nom', ''))),
                description=str(row.get('description', '')),
                price=float(row.get('price', row.get('prix', 0))),
                stock_quantity=int(row.get('stock', row.get('quantite', 0))),
                category_id=1  # Catégorie par défaut
            )
            db.add(product)
            db.commit()
            return True
        except Exception:
            return False
    
    def _import_client_from_row(self, db: Session, row) -> bool:
        """Importe un client depuis une ligne CSV/Excel"""
        try:
            client = Client(
                name=str(row.get('name', row.get('nom', ''))),
                email=str(row.get('email', '')),
                phone=str(row.get('phone', row.get('telephone', ''))),
                address=str(row.get('address', row.get('adresse', '')))
            )
            db.add(client)
            db.commit()
            return True
        except Exception:
            return False
    
    def _import_supplier_from_row(self, db: Session, row) -> bool:
        """Importe un fournisseur depuis une ligne CSV/Excel"""
        try:
            supplier = Supplier(
                name=str(row.get('name', row.get('nom', ''))),
                email=str(row.get('email', '')),
                phone=str(row.get('phone', row.get('telephone', ''))),
                address=str(row.get('address', row.get('adresse', '')))
            )
            db.add(supplier)
            db.commit()
            return True
        except Exception:
            return False
    
    def _import_product_from_dict(self, db: Session, data: dict) -> bool:
        """Importe un produit depuis un dictionnaire JSON"""
        return self._import_product_from_row(db, data)
    
    def _import_client_from_dict(self, db: Session, data: dict) -> bool:
        """Importe un client depuis un dictionnaire JSON"""
        return self._import_client_from_row(db, data)
    
    def _import_supplier_from_dict(self, db: Session, data: dict) -> bool:
        """Importe un fournisseur depuis un dictionnaire JSON"""
        return self._import_supplier_from_row(db, data)
    
    def _add_log(self, db: Session, migration_id: int, level: str, message: str):
        """Ajoute un log à une migration"""
        try:
            log = MigrationLog(
                migration_id=migration_id,
                level=level,
                message=message,
                timestamp=datetime.utcnow()
            )
            db.add(log)
            db.commit()
            
            # Mettre en cache pour les performances
            cache_key = f"migration_logs:{migration_id}"
            set_cache_item(cache_key, {"last_log": message, "level": level}, ttl_hours=1, cache_type="migration")
            
        except Exception as e:
            print(f"❌ Erreur lors de l'ajout du log: {e}")

# Instance globale du processeur
migration_processor = MigrationProcessor()
