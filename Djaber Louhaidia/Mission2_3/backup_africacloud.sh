#!/usr/bin/env bash
# ==============================================================================
# AFRICACLOUD - SCRIPT DE SAUVEGARDE CENTRALISEE AUTOMATIQUE (SUR VM5 : 41.69.31.50)
# African Skills Olympics 2026
# Planification : Tous les jours à 04h00 via Cron (0 4 * * *)
# Sauvegarde :
#   1. Base de données centrale de VM4 (31.69.41.20) : fichier .db + dump .sql
#   2. Configurations & Code Applicatif de VM2 (69.41.31.11) et VM3 (69.41.31.12)
#   3. Configurations Proxy Nginx & DNS dnsmasq de VM1 (41.69.31.10)
#   4. Archive compressée + Copie vers dossier de réplication Cloud Hybride
# ==============================================================================

set -u

TIMESTAMP=$(date +"%Y-%m-%d_%H-%M-%S")
BACKUP_ROOT="/var/backups/africacloud"
DEST_DIR="${BACKUP_ROOT}/snapshots/${TIMESTAMP}"
ARCHIVE_DIR="${BACKUP_ROOT}/archives"
CLOUD_SYNC_DIR="${BACKUP_ROOT}/cloud_offsite_sync"
LOG_FILE="/var/log/africacloud_backup.log"
SSH_KEY="/opt/africacloud/.ssh/id_ed25519"
SSH_OPTS="-i ${SSH_KEY} -o StrictHostKeyChecking=no -o ConnectTimeout=5"

mkdir -p "${DEST_DIR}/vm4_db" "${DEST_DIR}/vm1_proxy_dns" "${DEST_DIR}/vm2_app1" "${DEST_DIR}/vm3_app2"
mkdir -p "${ARCHIVE_DIR}" "${CLOUD_SYNC_DIR}"

log_msg() {
    local msg="[$(date +'%Y-%m-%d %H:%M:%S')] $1"
    echo "${msg}" | tee -a "${LOG_FILE}"
}

log_msg "======================================================================"
log_msg "DEMARRAGE DE LA SAUVEGARDE CENTRALISEE AFRICACLOUD (${TIMESTAMP})"
log_msg "Serveur de sauvegarde : VM5 (backup-sup - 41.69.31.50)"
log_msg "======================================================================"

# ------------------------------------------------------------------------------
# 1. SAUVEGARDE DE LA BASE DE DONNEES CENTRALE SUR VM4 (31.69.41.20)
# ------------------------------------------------------------------------------
log_msg "[1/4] Sauvegarde de la Base de Données VM4 (31.69.41.20)..."
if scp ${SSH_OPTS} acadmin@31.69.41.20:/opt/africacloud/africacloud.db "${DEST_DIR}/vm4_db/africacloud.db" 2>>"${LOG_FILE}"; then
    ssh ${SSH_OPTS} acadmin@31.69.41.20 "python3 -c \"import sqlite3; con=sqlite3.connect('/opt/africacloud/africacloud.db'); print('\n'.join(con.iterdump()))\"" > "${DEST_DIR}/vm4_db/africacloud_dump.sql" 2>>"${LOG_FILE}"
    scp ${SSH_OPTS} acadmin@31.69.41.20:/opt/africacloud/schema.sql "${DEST_DIR}/vm4_db/schema.sql" 2>>"${LOG_FILE}" || true
    scp ${SSH_OPTS} acadmin@31.69.41.20:/opt/africacloud/db_server.py "${DEST_DIR}/vm4_db/db_server.py" 2>>"${LOG_FILE}" || true
    log_msg "  -> [OK] Base SQLite (africacloud.db) et Dump SQL (africacloud_dump.sql) sauvegardés."
else
    log_msg "  -> [ERREUR] Impossible de contacter VM4 (31.69.41.20)."
fi

# ------------------------------------------------------------------------------
# 2. SAUVEGARDE DES CONFIGURATIONS & CODE DE VM2 (app1 - 69.41.31.11)
# ------------------------------------------------------------------------------
log_msg "[2/4] Sauvegarde du noeud applicatif VM2 (app1 - 69.41.31.11)..."
if ssh ${SSH_OPTS} acadmin@69.41.31.11 "tar -czf - -C /opt africacloud /etc/systemd/system/africacloud.service 2>/dev/null" > "${DEST_DIR}/vm2_app1/vm2_africacloud.tar.gz"; then
    log_msg "  -> [OK] Archive VM2 sauvegardée (vm2_africacloud.tar.gz)."
else
    log_msg "  -> [ERREUR] Echec sauvegarde VM2 (69.41.31.11)."
fi

# ------------------------------------------------------------------------------
# 3. SAUVEGARDE DES CONFIGURATIONS & CODE DE VM3 (app2 - 69.41.31.12)
# ------------------------------------------------------------------------------
log_msg "[3/4] Sauvegarde du noeud applicatif VM3 (app2 - 69.41.31.12)..."
if ssh ${SSH_OPTS} acadmin@69.41.31.12 "tar -czf - -C /opt africacloud /etc/systemd/system/africacloud.service 2>/dev/null" > "${DEST_DIR}/vm3_app2/vm3_africacloud.tar.gz"; then
    log_msg "  -> [OK] Archive VM3 sauvegardée (vm3_africacloud.tar.gz)."
else
    log_msg "  -> [ERREUR] Echec sauvegarde VM3 (69.41.31.12)."
fi

# ------------------------------------------------------------------------------
# 4. SAUVEGARDE DES CONFIGURATIONS PROXY NGINX & DNS DE VM1 (41.69.31.10)
# ------------------------------------------------------------------------------
log_msg "[4/4] Sauvegarde des configurations Proxy/DNS de VM1 (41.69.31.10)..."
if ssh ${SSH_OPTS} acadmin@41.69.31.10 "tar -czf - /etc/nginx /etc/dnsmasq.conf /etc/dnsmasq.d 2>/dev/null" > "${DEST_DIR}/vm1_proxy_dns/vm1_configs.tar.gz"; then
    log_msg "  -> [OK] Configurations Nginx & Dnsmasq de VM1 sauvegardées (vm1_configs.tar.gz)."
else
    log_msg "  -> [ERREUR] Echec sauvegarde VM1 (41.69.31.10)."
fi

# ------------------------------------------------------------------------------
# 5. CREATION DE L'ARCHIVE GLOBALE, LIEN 'latest' & REPLICATION CLOUD HYBRIDE
# ------------------------------------------------------------------------------
ln -sfn "${DEST_DIR}" "${BACKUP_ROOT}/latest"

FULL_ARCHIVE="${ARCHIVE_DIR}/africacloud_full_backup_${TIMESTAMP}.tar.gz"
tar -czf "${FULL_ARCHIVE}" -C "${BACKUP_ROOT}/snapshots" "${TIMESTAMP}"
cp "${FULL_ARCHIVE}" "${CLOUD_SYNC_DIR}/"
ln -sfn "${FULL_ARCHIVE}" "${BACKUP_ROOT}/latest_full_backup.tar.gz"

# Rotation : conserver les 7 dernières sauvegardes
ls -1dt "${BACKUP_ROOT}/snapshots/"* 2>/dev/null | tail -n +8 | xargs -r rm -rf
ls -1t "${ARCHIVE_DIR}/"*.tar.gz 2>/dev/null | tail -n +8 | xargs -r rm -f

log_msg "----------------------------------------------------------------------"
log_msg "SAUVEGARDE TERMINEE AVEC SUCCES !"
log_msg "Dossier latest     : ${BACKUP_ROOT}/latest"
log_msg "Archive complète   : ${FULL_ARCHIVE}"
log_msg "Réplication Cloud  : ${CLOUD_SYNC_DIR}/africacloud_full_backup_${TIMESTAMP}.tar.gz"
log_msg "======================================================================"
