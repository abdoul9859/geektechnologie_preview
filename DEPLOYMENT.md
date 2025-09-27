# Déploiement GeekTechnologie sur VPS

## 📋 Informations du déploiement

- **Domaine**: https://thegeektech.store
- **Port interne**: 8001 (pour éviter les conflits avec PowerClasss sur 8000)
- **Base de données**: PostgreSQL sur port 5433
- **SSL**: Certificat Let's Encrypt configuré

## 🚀 Commandes de gestion

```bash
# Démarrer l'application
./manage.sh start

# Arrêter l'application
./manage.sh stop

# Redémarrer l'application
./manage.sh restart

# Voir les logs
./manage.sh logs

# Vérifier le statut
./manage.sh status

# Mettre à jour depuis Git
./manage.sh update

# Créer une sauvegarde
./manage.sh backup
```

## 🔧 Configuration

### Docker Compose
- **Application**: Port 8001 → 8000 (conteneur)
- **Base de données**: Port 5433 → 5432 (conteneur)
- **Volume persistant**: `geektechnologie_preview_db_data`

### Nginx
- **Fichier de config**: `/etc/nginx/sites-available/thegeektech`
- **SSL**: Certificat Let's Encrypt automatique
- **Proxy**: localhost:8001

## 👤 Comptes par défaut

- **Administrateur**: `admin` / `admin123`
- **Utilisateur**: `user` / `user123`

## 📊 Monitoring

### Vérifier le statut
```bash
docker ps | grep geek
```

### Logs en temps réel
```bash
docker logs -f geek_app
```

### Accès à la base de données
```bash
docker exec -it geek_db psql -U postgres -d geektechnologie_db
```

## 🔄 Mise à jour

1. **Mise à jour automatique**:
   ```bash
   ./manage.sh update
   ```

2. **Mise à jour manuelle**:
   ```bash
   cd /opt/geektechnologie_preview
   git pull origin main
   docker compose down
   docker compose up -d --build
   ```

## 💾 Sauvegarde

### Base de données
```bash
./manage.sh backup
```

### Fichiers de l'application
```bash
tar -czf geektechnologie_backup_$(date +%Y%m%d).tar.gz /opt/geektechnologie_preview
```

## 🚨 Dépannage

### Application ne démarre pas
1. Vérifier les logs: `./manage.sh logs`
2. Vérifier la base de données: `docker ps | grep geek_db`
3. Redémarrer: `./manage.sh restart`

### Problème de domaine
1. Vérifier Nginx: `nginx -t`
2. Recharger Nginx: `systemctl reload nginx`
3. Vérifier SSL: `certbot certificates`

### Problème de base de données
1. Vérifier les conteneurs: `docker ps`
2. Accéder à la base: `docker exec -it geek_db psql -U postgres`
3. Vérifier les logs: `docker logs geek_db`

## 📁 Structure des fichiers

```
/opt/geektechnologie_preview/
├── manage.sh              # Script de gestion
├── docker-compose.yml     # Configuration Docker
├── Dockerfile            # Image de l'application
├── start.py              # Script de démarrage
├── app/                  # Code de l'application
├── migrations/           # Migrations de base de données
└── static/               # Fichiers statiques
```

## 🔒 Sécurité

- **SSL/TLS**: Certificat Let's Encrypt automatique
- **Headers de sécurité**: Configurés dans Nginx
- **Authentification**: JWT avec rôles (admin, user, manager)
- **Base de données**: Accès restreint au conteneur

## 📞 Support

En cas de problème, vérifier dans l'ordre :
1. Les logs de l'application
2. Le statut des conteneurs Docker
3. La configuration Nginx
4. Les certificats SSL
