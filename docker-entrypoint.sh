#!/bin/bash
set -e

echo "🚀 Démarrage du conteneur..."

# Attendre que la base de données soit prête
echo "⏳ Attente de la base de données..."
python -c "
import time
import os
from sqlalchemy import create_engine
from dotenv import load_dotenv

load_dotenv()
database_url = os.getenv('DATABASE_URL')
if database_url.startswith('postgres://'):
    database_url = database_url.replace('postgres://', 'postgresql+psycopg://', 1)
elif database_url.startswith('postgresql://'):
    database_url = database_url.replace('postgresql://', 'postgresql+psycopg://', 1)

max_attempts = 30
attempt = 0

while attempt < max_attempts:
    try:
        engine = create_engine(database_url)
        with engine.connect() as conn:
            conn.execute('SELECT 1')
        print('✅ Base de données connectée')
        break
    except Exception as e:
        attempt += 1
        print(f'⏳ Tentative {attempt}/{max_attempts} - Base de données non prête: {e}')
        time.sleep(2)

if attempt >= max_attempts:
    print('❌ Impossible de se connecter à la base de données après 30 tentatives')
    exit(1)
"

# Exécuter les migrations
echo "🔄 Exécution des migrations..."
python -c "
import sys
sys.path.append('/app')
from migrations.migration_manager import run_migrations

if not run_migrations():
    print('❌ Échec des migrations')
    sys.exit(1)
else:
    print('✅ Migrations exécutées avec succès')
"

# Démarrer l'application
echo "🎯 Démarrage de l'application..."
exec "$@"
