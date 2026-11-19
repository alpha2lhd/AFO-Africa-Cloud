================================================================================
AFRICACLOUD - GUIDE COMPLET DES COMMANDES DE TEST (JURY / EVALUATION)
African Skills Olympics 2026 - Missions 2 & 3
================================================================================

1. RECAPITULATIF DES 5 MACHINES VIRTUELLES & ACCES SSH
--------------------------------------------------------------------------------
Identifiants SSH sur toutes les VMs :
  - Utilisateur  : acadmin
  - Mot de passe : P@ssWord

+-----+---------------+--------------------+-------------------------------------------+
| VM  | Nom d'hôte    | IP NAT (Depuis PC) | IPs Internes (VLANs VMware)               |
+-----+---------------+--------------------+-------------------------------------------+
| VM1 | ctrl-proxy    | 192.168.38.101     | VLAN 11 : 41.69.31.10                     |
|     |               |                    | VLAN 22 : 69.41.31.10                     |
|     |               |                    | VLAN 33 : 31.69.41.10                     |
+-----+---------------+--------------------+-------------------------------------------+
| VM2 | app1          | 192.168.38.102     | VLAN 22 : 69.41.31.11                     |
|     |               |                    | VLAN 33 : 31.69.41.11                     |
+-----+---------------+--------------------+-------------------------------------------+
| VM3 | app2          | 192.168.38.103     | VLAN 22 : 69.41.31.12                     |
|     |               |                    | VLAN 33 : 31.69.41.12                     |
+-----+---------------+--------------------+-------------------------------------------+
| VM4 | db            | 192.168.38.104     | VLAN 33 : 31.69.41.20                     |
+-----+---------------+--------------------+-------------------------------------------+
| VM5 | backup-sup    | 192.168.38.105     | VLAN 11 : 41.69.31.50                     |
+-----+---------------+--------------------+-------------------------------------------+

Commandes de connexion SSH depuis Windows (PowerShell / CMD) :
  ssh acadmin@192.168.38.101    # VM1 (ctrl-proxy)
  ssh acadmin@192.168.38.102    # VM2 (app1)
  ssh acadmin@192.168.38.103    # VM3 (app2)
  ssh acadmin@192.168.38.104    # VM4 (db)
  ssh acadmin@192.168.38.105    # VM5 (backup-sup)


2. LISTE DES FICHIERS DE TESTS DANS CE DOSSIER
--------------------------------------------------------------------------------
- 01_reseau_routage_dns.txt
    -> Vérification des interfaces IP, routage inter-VLAN, ping et serveur DNS (dnsmasq).

- 02_firewall_securite_ufw.txt
    -> Vérification du pare-feu UFW sur les 5 VMs, tests de flux bloqués/autorisés (nc) et sécurité.

- 03_fichiers_deploiement_systemd.txt
    -> Vérification de l'arborescence /opt/africacloud, du code déployé, du service systemd et des ports.

- 04_docker_conteneurs.txt
    -> Vérification de Docker, Dockerfile, docker-compose.yml, conteneurs actifs et healthcheck.

- 05_health_loadbalancer_proxy.txt
    -> Vérification de l'état de santé (/api/health) et du Load Balancer Nginx (répartition VM2 / VM3).

- 06_api_rest_crud_bdd.txt
    -> Tests complets de l'API REST (GET, POST, PUT, DELETE) et inspection de la Base de Données.

- 07_supervision_sauvegarde_pra.txt
    -> Tests de supervision, sauvegardes automatisées, tolérance aux pannes (failover) et restauration (PRA).
================================================================================
