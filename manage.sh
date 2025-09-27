#!/bin/bash

# Script de gestion pour GeekTechnologie
# Usage: ./manage.sh [start|stop|restart|logs|status|update]

APP_DIR="/opt/geektechnologie_preview"
APP_NAME="GeekTechnologie"

case "$1" in
    start)
        echo "🚀 Démarrage de $APP_NAME..."
        cd $APP_DIR
        docker compose up -d
        echo "✅ $APP_NAME démarré"
        ;;
    stop)
        echo "⏹️  Arrêt de $APP_NAME..."
        cd $APP_DIR
        docker compose down
        echo "✅ $APP_NAME arrêté"
        ;;
    restart)
        echo "🔄 Redémarrage de $APP_NAME..."
        cd $APP_DIR
        docker compose down
        docker compose up -d --build
        echo "✅ $APP_NAME redémarré"
        ;;
    logs)
        echo "📋 Logs de $APP_NAME..."
        cd $APP_DIR
        docker compose logs -f
        ;;
    status)
        echo "📊 Statut de $APP_NAME..."
        cd $APP_DIR
        docker compose ps
        echo ""
        echo "🌐 Accès: https://thegeektech.store"
        echo "💡 Comptes par défaut:"
        echo "   - Admin: admin / admin123"
        echo "   - Utilisateur: user / user123"
        ;;
    update)
        echo "🔄 Mise à jour de $APP_NAME..."
        cd $APP_DIR
        git pull origin main
        docker compose down
        docker compose up -d --build
        echo "✅ $APP_NAME mis à jour"
        ;;
    backup)
        echo "💾 Sauvegarde de la base de données..."
        cd $APP_DIR
        docker exec geek_db pg_dump -U postgres geektechnologie_db > backup_$(date +%Y%m%d_%H%M%S).sql
        echo "✅ Sauvegarde créée"
        ;;
    *)
        echo "Usage: $0 {start|stop|restart|logs|status|update|backup}"
        echo ""
        echo "Commandes disponibles:"
        echo "  start   - Démarrer l'application"
        echo "  stop    - Arrêter l'application"
        echo "  restart - Redémarrer l'application"
        echo "  logs    - Afficher les logs en temps réel"
        echo "  status  - Afficher le statut des conteneurs"
        echo "  update  - Mettre à jour depuis Git et redémarrer"
        echo "  backup  - Créer une sauvegarde de la base de données"
        exit 1
        ;;
esac
