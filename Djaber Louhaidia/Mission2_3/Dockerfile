# ==============================================================================
# AfricaCloud - Dockerfile (Web Interface + REST API + SQLite DB)
# African Skills Olympics 2026
# ==============================================================================
FROM python:3.12-slim

LABEL maintainer="Djaber Louhaidia - AfricaCloud ASO 2026"
LABEL description="Portail de Signalement d'Incidents Techniques AfricaCloud"

WORKDIR /app

# Copie du serveur API REST, du schéma SQL et de l'interface Web
COPY server.py schema.sql ./
COPY public/ ./public/

# Ports exposés (8080: App VLAN 22, 80: HTTP, 3000: Dev/API)
EXPOSE 8080 80 3000

# Vérification automatique de santé du conteneur via l'API REST
HEALTHCHECK --interval=15s --timeout=3s --start-period=5s --retries=3 \
  CMD python3 -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/api/health')" || exit 1

# Démarrage du serveur
CMD ["python3", "server.py"]
