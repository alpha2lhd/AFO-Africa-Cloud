#!/usr/bin/env bash
# ==============================================================================
# AFRICACLOUD - SCRIPT DE RESTAURATION AUTOMATIQUE DE LA BDD (DEPUIS VM5 VERS VM4)
# African Skills Olympics 2026
# Restaure la dernière sauvegarde (ou une sauvegarde spécifique) de VM5 vers VM4
# ==============================================================================

set -u

BACKUP_ROOT="/var/backups/africacloud"
SOURCE_DB="${1:-${BACKUP_ROOT}/latest/vm4_db/africacloud.db}"
SSH_KEY="/opt/africacloud/.ssh/id_ed25519"
SSH_OPTS="-i ${SSH_KEY} -o StrictHostKeyChecking=no -o ConnectTimeout=5"
LOG_FILE="/var/log/africacloud_backup.log"

echo "======================================================================"
echo "RESTAURATION DE LA BASE DE DONNEES CENTRALE AFRICACLOUD (VM5 -> VM4)"
echo "Fichier source : ${SOURCE_DB}"
echo "Cible          : VM4 (31.69.41.20:/opt/africacloud/africacloud.db)"
echo "======================================================================"

if [ ! -f "${SOURCE_DB}" ]; then
    echo "[ERREUR] Fichier de sauvegarde introuvable : ${SOURCE_DB}"
    exit 1
fi

scp ${SSH_OPTS} "${SOURCE_DB}" acadmin@31.69.41.20:/tmp/africacloud_restore.db
ssh ${SSH_OPTS} acadmin@31.69.41.20 "echo 'P@ssWord' | sudo -S cp /tmp/africacloud_restore.db /opt/africacloud/africacloud.db && echo 'P@ssWord' | sudo -S systemctl restart africacloud-db"

echo "[$(date +'%Y-%m-%d %H:%M:%S')] RESTAURATION BDD EFFECTUEE VERS VM4 DEPUIS ${SOURCE_DB}" >> "${LOG_FILE}"
echo "[OK] Base de données centrale restaurée avec succès sur VM4 (31.69.41.20) !"
ssh ${SSH_OPTS} acadmin@31.69.41.20 "python3 -c \"import sqlite3; c=sqlite3.connect('/opt/africacloud/africacloud.db'); print('Incidents restaurés :', len(c.execute('SELECT * FROM issues').fetchall()))\""
echo "======================================================================"
