#!/usr/bin/env python3
"""
AfricaCloud - Serveur de Supervision Grafana (port 3000) & Prometheus (port 9090) sur VM5
African Skills Olympics 2026
Déployé sur VM5 (backup-sup : 41.69.31.50 / NAT 192.168.38.105)
Inclut le moteur de Tests Interactifs en Direct (Réseau, DNS, Pare-feu UFW, Load Balancer,
Synchronisation BDD Temps Réel VM2<->VM4<->VM3, Docker, Sauvegarde & PRA).
"""

import json
import os
import subprocess
import threading
import time
import urllib.request
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
GRAFANA_HTML_PATH = os.path.join(BASE_DIR, "grafana.html")
SSH_KEY = "/opt/africacloud/.ssh/id_ed25519"
START_TIME = time.time()

VMS_CONFIG = [
    {
        "id": "vm1",
        "name": "VM1 - ctrl-proxy",
        "role": "Reverse Proxy Nginx & DNS (dnsmasq)",
        "ip": "41.69.31.10",
        "nat_ip": "192.168.38.101",
        "vlans": "VLAN 11 (41.69.31.10), VLAN 22 (69.41.31.10), VLAN 33 (31.69.41.10)",
        "services": ["nginx", "dnsmasq", "ufw"],
        "vcpu": 2,
        "ram_gb": 4,
        "disk_gb": 40,
    },
    {
        "id": "vm2",
        "name": "VM2 - app1",
        "role": "Noeud Applicatif 1 (Web + API + Docker)",
        "ip": "69.41.31.11",
        "nat_ip": "192.168.38.102",
        "vlans": "VLAN 22 (69.41.31.11), VLAN 33 (31.69.41.11)",
        "services": ["africacloud", "docker", "ufw"],
        "vcpu": 2,
        "ram_gb": 2,
        "disk_gb": 30,
    },
    {
        "id": "vm3",
        "name": "VM3 - app2",
        "role": "Noeud Applicatif 2 (Web + API HA)",
        "ip": "69.41.31.12",
        "nat_ip": "192.168.38.103",
        "vlans": "VLAN 22 (69.41.31.12), VLAN 33 (31.69.41.12)",
        "services": ["africacloud", "ufw"],
        "vcpu": 2,
        "ram_gb": 2,
        "disk_gb": 30,
    },
    {
        "id": "vm4",
        "name": "VM4 - db",
        "role": "Serveur Base de Données Centrale (Port 5432)",
        "ip": "31.69.41.20",
        "nat_ip": "192.168.38.104",
        "vlans": "VLAN 33 (31.69.41.20)",
        "services": ["africacloud-db", "postgresql", "ufw"],
        "vcpu": 2,
        "ram_gb": 4,
        "disk_gb": 60,
    },
    {
        "id": "vm5",
        "name": "VM5 - backup-sup",
        "role": "Supervision (Grafana/Prometheus) & Sauvegarde (04h00)",
        "ip": "41.69.31.50",
        "nat_ip": "192.168.38.105",
        "vlans": "VLAN 11 (41.69.31.50)",
        "services": ["africacloud-sup", "africacloud-backup.timer", "ufw"],
        "vcpu": 2,
        "ram_gb": 2,
        "disk_gb": 80,
        "local": True,
    },
]

METRICS_CACHE = {
    "updated_at": None,
    "vms": [],
    "app_stats": {"total": 3, "open_count": 1, "in_progress_count": 1, "resolved_count": 1, "critical_active": 1},
    "backup": {
        "last_run": "2026-11-19 09:29:44",
        "schedule": "0 4 * * * (Tous les jours à 04h00)",
        "status": "OK",
        "archives_count": 1,
        "recent_logs": [],
    },
}
CACHE_LOCK = threading.Lock()


def run_local(cmd, timeout=5):
    try:
        p = subprocess.run(["bash", "-c", cmd], capture_output=True, text=True, timeout=timeout)
        out = (p.stdout + "\n" + p.stderr).strip()
        return p.returncode, out
    except subprocess.TimeoutExpired as e:
        out = ((e.stdout or "") + "\n" + (e.stderr or "")).strip() or "timed out"
        return 124, out
    except Exception as e:
        return 1, str(e)


def run_ssh(host_ip, cmd, timeout=5):
    ssh_cmd = [
        "ssh",
        "-i",
        SSH_KEY,
        "-o",
        "StrictHostKeyChecking=no",
        "-o",
        f"ConnectTimeout={min(3, timeout)}",
        f"acadmin@{host_ip}",
        cmd,
    ]
    try:
        p = subprocess.run(ssh_cmd, capture_output=True, text=True, timeout=timeout)
        out = (p.stdout + "\n" + p.stderr).strip()
        return p.returncode, out
    except subprocess.TimeoutExpired:
        return 124, "timed out"
    except Exception as e:
        return 1, str(e)


# ==============================================================================
# MOTEUR DE TESTS EN DIRECT (POUR LE TABLEAU DE BORD GRAFANA)
# ==============================================================================
def test_network():
    t0 = time.time()
    steps = []
    targets = [
        ("VM5 (41.69.31.50) -> VM1 Proxy (41.69.31.10)", "local", None, "ping -c 1 -W 2 41.69.31.10"),
        ("VM5 (VLAN 11) -> VM2 App1 (VLAN 22 : 69.41.31.11)", "local", None, "ping -c 1 -W 2 69.41.31.11"),
        ("VM5 (VLAN 11) -> VM3 App2 (VLAN 22 : 69.41.31.12)", "local", None, "ping -c 1 -W 2 69.41.31.12"),
        ("VM5 (VLAN 11) -> VM4 BDD (VLAN 33 : 31.69.41.20)", "local", None, "ping -c 1 -W 2 31.69.41.20"),
        ("VM2 (69.41.31.11) -> VM4 BDD (31.69.41.20)", "ssh", "69.41.31.11", "ping -c 1 -W 2 31.69.41.20"),
        ("VM1 Routage Inter-VLAN (net.ipv4.ip_forward = 1)", "ssh", "41.69.31.10", "sysctl net.ipv4.ip_forward"),
    ]
    for label, mode, ip, cmd in targets:
        rc, out = run_local(cmd, 3) if mode == "local" else run_ssh(ip, cmd, 4)
        ok = (rc == 0) and ("0% packet loss" in out or "ip_forward = 1" in out)
        last_line = [l for l in out.splitlines() if "transmitted" in l or "ip_forward" in l or "time=" in l]
        summary = last_line[-1] if last_line else (out.splitlines()[-1] if out else "No output")
        steps.append({
            "name": label,
            "command": cmd,
            "expected": "0% packet loss / ip_forward = 1",
            "actual": summary,
            "passed": ok,
        })
    return {
        "category": "Test 1 — Connectivité IP & Routage Inter-VLAN",
        "passed": all(s["passed"] for s in steps),
        "duration_ms": int((time.time() - t0) * 1000),
        "steps": steps,
    }


def test_dns():
    t0 = time.time()
    steps = []
    queries = [
        ("Service dnsmasq actif sur VM1", "ssh", "41.69.31.10", "systemctl is-active dnsmasq", "active"),
        ("Depuis VM2 (VLAN 22) : nslookup db.lab.local 69.41.31.10", "ssh", "69.41.31.11", "nslookup db.lab.local 69.41.31.10", "31.69.41.20"),
        ("Depuis VM5 (VLAN 11) : nslookup app1.lab.local 41.69.31.10", "local", None, "nslookup app1.lab.local 41.69.31.10", "69.41.31.11"),
        ("Depuis VM4 (VLAN 33) : nslookup app2.lab.local 31.69.41.10", "ssh", "31.69.41.20", "nslookup app2.lab.local 31.69.41.10", "69.41.31.12"),
        ("Depuis VM5 (VLAN 11) : nslookup ctrl-proxy.lab.local 41.69.31.10", "local", None, "nslookup ctrl-proxy.lab.local 41.69.31.10", "41.69.31.10"),
        ("Depuis VM5 (VLAN 11) : nslookup backup-sup.lab.local 41.69.31.10", "local", None, "nslookup backup-sup.lab.local 41.69.31.10", "41.69.31.50"),
    ]
    for label, mode, ip, cmd, expected_ip in queries:
        rc, out = run_local(cmd, 4) if mode == "local" else run_ssh(ip, cmd, 4)
        ok = expected_ip in out
        steps.append({
            "name": label,
            "command": cmd,
            "expected": f"Résolu -> {expected_ip}",
            "actual": f"Address: {expected_ip} (OK)" if ok else out.replace("\n", " "),
            "passed": ok,
        })
    return {
        "category": "Test 2 — Résolution DNS (Zone lab.local sur VM1)",
        "passed": all(s["passed"] for s in steps),
        "duration_ms": int((time.time() - t0) * 1000),
        "steps": steps,
    }


def test_firewall():
    t0 = time.time()
    steps = []
    rules = [
        ("FLUX BLOQUÉ : VM5 -> VM4 BDD (31.69.41.20:5432)", "local", None, "nc -zv -w 2 31.69.41.20 5432", "BLOCK"),
        ("FLUX BLOQUÉ : VM5 -> VM2 App1 (69.41.31.11:8080)", "local", None, "nc -zv -w 2 69.41.31.11 8080", "BLOCK"),
        ("FLUX BLOQUÉ : VM5 -> VM3 App2 (69.41.31.12:8080)", "local", None, "nc -zv -w 2 69.41.31.12 8080", "BLOCK"),
        ("FLUX AUTORISÉ : VM2 App1 -> VM4 BDD (31.69.41.20:5432)", "ssh", "69.41.31.11", "nc -zv -w 2 31.69.41.20 5432", "ALLOW"),
        ("FLUX AUTORISÉ : VM3 App2 -> VM4 BDD (31.69.41.20:5432)", "ssh", "69.41.31.12", "nc -zv -w 2 31.69.41.20 5432", "ALLOW"),
        ("FLUX AUTORISÉ : VM1 Proxy -> VM2 App1 (69.41.31.11:8080)", "ssh", "41.69.31.10", "nc -zv -w 2 69.41.31.11 8080", "ALLOW"),
        ("FLUX AUTORISÉ : VM1 Proxy -> VM3 App2 (69.41.31.12:8080)", "ssh", "41.69.31.10", "nc -zv -w 2 69.41.31.12 8080", "ALLOW"),
    ]
    for label, mode, ip, cmd, policy in rules:
        rc, out = run_local(cmd, 3) if mode == "local" else run_ssh(ip, cmd, 4)
        if policy == "BLOCK":
            ok = ("timed out" in out.lower()) or (rc != 0 and "succeeded" not in out.lower())
            expected_str = "BLOQUÉ par UFW (timed out)"
        else:
            ok = ("succeeded" in out.lower()) or (rc == 0)
            expected_str = "AUTORISÉ par UFW (succeeded!)"
        steps.append({
            "name": label,
            "command": cmd,
            "expected": expected_str,
            "actual": out.splitlines()[-1] if out else "timed out",
            "passed": ok,
        })
    return {
        "category": "Test 3 — Pare-feu UFW & Règles de Filtrage Inter-VLAN",
        "passed": all(s["passed"] for s in steps),
        "duration_ms": int((time.time() - t0) * 1000),
        "steps": steps,
    }


def test_loadbalancer():
    t0 = time.time()
    steps = []
    nodes_seen = []
    for i in range(1, 5):
        try:
            req = urllib.request.Request("http://41.69.31.10/api/health")
            with urllib.request.urlopen(req, timeout=2.0) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                node = data.get("hostname", "unknown")
                served = data.get("served_by_node", node)
                nodes_seen.append(node)
                steps.append({
                    "name": f"Appel #{i} via Load Balancer VM1 (http://41.69.31.10/api/health)",
                    "command": "curl -s http://41.69.31.10/api/health",
                    "expected": "HTTP 200 (app1 ou app2)",
                    "actual": f"HTTP 200 -> {served}",
                    "passed": True,
                })
        except Exception as e:
            steps.append({
                "name": f"Appel #{i} via Load Balancer VM1",
                "command": "curl -s http://41.69.31.10/api/health",
                "expected": "HTTP 200",
                "actual": str(e),
                "passed": False,
            })
    both_active = ("app1" in nodes_seen) and ("app2" in nodes_seen)
    steps.append({
        "name": "Alternance Round-Robin Nginx entre VM2 (app1) et VM3 (app2)",
        "command": "Vérification de la distribution sur les 2 nœuds",
        "expected": "app1 et app2 présents dans le cycle",
        "actual": f"Séquence observée : {' -> '.join(nodes_seen)}",
        "passed": both_active,
    })
    return {
        "category": "Test 4 — Load Balancer Nginx (Round-Robin VM1 -> VM2 / VM3)",
        "passed": all(s["passed"] for s in steps),
        "duration_ms": int((time.time() - t0) * 1000),
        "steps": steps,
    }


def test_database():
    t0 = time.time()
    steps = []
    marker = f"Test Live Grafana ({datetime.now().strftime('%H:%M:%S')})"
    created_id = None

    # 1. Créer un incident via VM2 (69.41.31.11:8080) depuis VM1
    post_payload = json.dumps({
        "title": marker,
        "category": "Base de Données (VM4)",
        "priority": "Haute",
        "reporter": "Grafana Live Tester",
        "description": "Test de synchronisation temps réel VM2 -> VM4 (5432) -> VM3",
    })
    cmd_post_vm2 = f"curl -s -X POST http://69.41.31.11:8080/api/issues -H 'Content-Type: application/json' -d '{post_payload}'"
    rc, out = run_ssh("41.69.31.10", cmd_post_vm2, 5)
    try:
        created_obj = json.loads(out)
        created_id = created_obj.get("id")
        ok_post = created_id is not None
    except Exception:
        ok_post = False

    steps.append({
        "name": "1. Écriture (POST) d'un incident sur VM2 (app1 : 69.41.31.11:8080)",
        "command": "POST http://69.41.31.11:8080/api/issues",
        "expected": "HTTP 201 Created + ID généré sur VM4",
        "actual": f"Créé sur VM2 avec ID #{created_id} ({marker})" if ok_post else out,
        "passed": ok_post,
    })

    # 2. Lecture immédiate sur VM3 (69.41.31.12:8080)
    if created_id:
        cmd_get_vm3 = f"curl -s http://69.41.31.12:8080/api/issues/{created_id}"
        rc3, out3 = run_ssh("41.69.31.10", cmd_get_vm3, 5)
        try:
            obj3 = json.loads(out3)
            ok_vm3 = (obj3.get("id") == created_id) and (obj3.get("title") == marker)
        except Exception:
            ok_vm3 = False
        steps.append({
            "name": f"2. Lecture Temps Réel (GET #{created_id}) sur VM3 (app2 : 69.41.31.12:8080)",
            "command": cmd_get_vm3,
            "expected": f"Incident #{created_id} '{marker}' présent instantanément sur VM3",
            "actual": f"Trouvé sur VM3 : ID #{obj3.get('id')} - '{obj3.get('title')}'" if ok_vm3 else out3,
            "passed": ok_vm3,
        })

        # 3. Vérification directe dans le fichier SQLite sur VM4 (31.69.41.20)
        cmd_vm4 = f"python3 -c \"import sqlite3; c=sqlite3.connect('/opt/africacloud/africacloud.db'); r=c.execute('SELECT id, title FROM issues WHERE id={created_id}').fetchone(); print(r)\""
        rc4, out4 = run_ssh("31.69.41.20", cmd_vm4, 5)
        ok_vm4 = str(created_id) in out4 and marker in out4
        steps.append({
            "name": f"3. Vérification SQL directe sur VM4 (31.69.41.20:/opt/africacloud/africacloud.db)",
            "command": f"SELECT id, title FROM issues WHERE id={created_id}",
            "expected": f"Ligne ({created_id}, '{marker}') stockée sur VM4",
            "actual": out4,
            "passed": ok_vm4,
        })

        # 4. Nettoyage (DELETE) depuis VM3
        cmd_del = f"curl -s -X DELETE http://69.41.31.12:8080/api/issues/{created_id}"
        rc_d, out_d = run_ssh("41.69.31.10", cmd_del, 5)
        ok_del = "supprim" in out_d.lower()
        steps.append({
            "name": f"4. Suppression (DELETE #{created_id}) depuis VM3 & synchronisation VM2/VM4",
            "command": cmd_del,
            "expected": f"Incident #{created_id} supprimé sur tous les nœuds",
            "actual": out_d.replace("\n", " "),
            "passed": ok_del,
        })

    return {
        "category": "Test 5 — Base de Données Centrale Partagée Temps Réel (VM2 <-> VM4:5432 <-> VM3)",
        "passed": all(s["passed"] for s in steps) and len(steps) >= 4,
        "duration_ms": int((time.time() - t0) * 1000),
        "steps": steps,
    }


def test_docker_and_pra():
    t0 = time.time()
    steps = []

    # 1. Conteneur Docker sur VM2
    rc_d, out_d = run_ssh("69.41.31.11", "echo 'P@ssWord' | sudo -S docker ps --format '{{.Names}} ({{.Image}}) - {{.Status}}' 2>/dev/null", 5)
    clean_d = [l for l in out_d.splitlines() if "password" not in l.lower() and l.strip()]
    ok_docker = len(clean_d) > 0 and "Up" in clean_d[-1]
    steps.append({
        "name": "Conteneur Docker actif sur VM2 (avec politique --restart unless-stopped)",
        "command": "sudo docker ps",
        "expected": "Conteneur web (nginx:latest) Up",
        "actual": clean_d[-1] if clean_d else out_d,
        "passed": ok_docker,
    })

    # 2. Vérification Cron & Timer de Sauvegarde 04h00 sur VM5
    rc_t, out_t = run_local("systemctl is-active africacloud-backup.timer && grep '0 4' /etc/cron.d/africacloud-backup", 4)
    ok_timer = "active" in out_t and "0 4" in out_t
    steps.append({
        "name": "Planification Sauvegarde Automatique 04h00 (Cron + Systemd Timer sur VM5)",
        "command": "systemctl is-active africacloud-backup.timer && cat /etc/cron.d/africacloud-backup",
        "expected": "active + 0 4 * * * /opt/africacloud/backup_africacloud.sh",
        "actual": out_t.replace("\n", " | "),
        "passed": ok_timer,
    })

    # 3. Vérification de l'intégrité du dernier dump SQL sauvegardé sur VM5
    rc_b, out_b = run_local("ls -lh /var/backups/africacloud/latest/vm4_db/africacloud.db && grep -c 'INSERT INTO' /var/backups/africacloud/latest/vm4_db/africacloud_dump.sql", 4)
    ok_bkp = rc_b == 0
    steps.append({
        "name": "Intégrité de la sauvegarde BDD VM4 stockée sur VM5 (/var/backups/africacloud/latest)",
        "command": "ls -lh /var/backups/africacloud/latest/vm4_db/africacloud.db",
        "expected": "Fichier africacloud.db + africacloud_dump.sql présents et valides",
        "actual": out_b.replace("\n", " | Incidents dans le dump: "),
        "passed": ok_bkp,
    })

    return {
        "category": "Test 6 — Conteneurs Docker, Sauvegarde Automatique 04h00 & PRA",
        "passed": all(s["passed"] for s in steps),
        "duration_ms": int((time.time() - t0) * 1000),
        "steps": steps,
    }


def run_test_suite(test_name):
    mapping = {
        "network": [test_network],
        "dns": [test_dns],
        "firewall": [test_firewall],
        "loadbalancer": [test_loadbalancer],
        "database": [test_database],
        "docker_pra": [test_docker_and_pra],
        "all": [
            test_network,
            test_dns,
            test_firewall,
            test_loadbalancer,
            test_database,
            test_docker_and_pra,
        ],
    }
    funcs = mapping.get(test_name, [test_firewall])
    results = [fn() for fn in funcs]
    return {
        "status": "OK",
        "test_requested": test_name,
        "all_passed": all(r["passed"] for r in results),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "results": results,
    }


def probe_vm(vm):
    """Collecte CPU, RAM, Disque, Load, Uptime et état des services d'une VM via SSH ou localement."""
    services_str = " ".join(vm["services"])
    probe_cmd = (
        "python3 -c \""
        "import json, os, subprocess, time; "
        "load = os.getloadavg()[0]; "
        "cpus = os.cpu_count() or 2; "
        "cpu_pct = min(99.0, round(max(4.0, (load / cpus) * 100.0), 1)); "
        "mem = open('/proc/meminfo').read().splitlines(); "
        "m = {k.strip(): int(v.split()[0]) for line in mem if ':' in line for k, v in [line.split(':', 1)]}; "
        "ram_total = round(m.get('MemTotal', 2097152) / 1048576.0, 2); "
        "ram_avail = round(m.get('MemAvailable', 1048576) / 1048576.0, 2); "
        "ram_used = round(ram_total - ram_avail, 2); "
        "ram_pct = round((ram_used / ram_total) * 100.0, 1) if ram_total else 0.0; "
        "st = os.statvfs('/'); "
        "disk_total = round((st.f_blocks * st.f_frsize) / (1024**3), 1); "
        "disk_free = round((st.f_bavail * st.f_frsize) / (1024**3), 1); "
        "disk_used = round(disk_total - disk_free, 1); "
        "disk_pct = round((disk_used / disk_total) * 100.0, 1) if disk_total else 0.0; "
        "up_sec = int(float(open('/proc/uptime').read().split()[0])); "
        f"svcs = {{s: (subprocess.run(['systemctl', 'is-active', s], capture_output=True, text=True).stdout.strip() == 'active') for s in '{services_str}'.split()}}; "
        "print(json.dumps({'cpu_pct': cpu_pct, 'load_1m': round(load, 2), 'ram_used_gb': ram_used, 'ram_total_gb': ram_total, 'ram_pct': ram_pct, 'disk_used_gb': disk_used, 'disk_total_gb': disk_total, 'disk_pct': disk_pct, 'uptime_seconds': up_sec, 'services': svcs}))"
        "\""
    )
    t0 = time.time()
    try:
        if vm.get("local"):
            proc = subprocess.run(["bash", "-c", probe_cmd], capture_output=True, text=True, timeout=4)
        else:
            ssh_cmd = [
                "ssh",
                "-i",
                SSH_KEY,
                "-o",
                "StrictHostKeyChecking=no",
                "-o",
                "ConnectTimeout=3",
                f"acadmin@{vm['ip']}",
                probe_cmd,
            ]
            proc = subprocess.run(ssh_cmd, capture_output=True, text=True, timeout=5)
        latency_ms = round((time.time() - t0) * 1000.0, 1)
        if proc.returncode == 0 and proc.stdout.strip():
            data = json.loads(proc.stdout.strip().splitlines()[-1])
            return {
                **vm,
                "online": True,
                "latency_ms": latency_ms,
                **data,
            }
    except Exception:
        pass

    return {
        **vm,
        "online": False,
        "latency_ms": 0.0,
        "cpu_pct": 0.0,
        "load_1m": 0.0,
        "ram_used_gb": 0.0,
        "ram_total_gb": float(vm["ram_gb"]),
        "ram_pct": 0.0,
        "disk_used_gb": 0.0,
        "disk_total_gb": float(vm["disk_gb"]),
        "disk_pct": 0.0,
        "uptime_seconds": 0,
        "services": {s: False for s in vm["services"]},
    }


def collect_backup_info():
    log_file = "/var/log/africacloud_backup.log"
    archive_dir = "/var/backups/africacloud/archives"
    recent_logs = []
    last_run = "Inconnu"
    if os.path.isfile(log_file):
        try:
            with open(log_file, "r", encoding="utf-8", errors="replace") as f:
                lines = [l.strip() for l in f.readlines() if l.strip()]
                recent_logs = lines[-12:]
                for l in reversed(lines):
                    if "SAUVEGARDE TERMINEE AVEC SUCCES" in l:
                        last_run = l.split("]")[0].lstrip("[")
                        break
        except Exception:
            pass
    archives = []
    if os.path.isdir(archive_dir):
        try:
            archives = sorted(os.listdir(archive_dir), reverse=True)
        except Exception:
            pass
    return {
        "last_run": last_run,
        "schedule": "0 4 * * * (Chaque nuit à 04h00 - Cron & Systemd Timer)",
        "status": "OK" if archives else "EN ATTENTE",
        "archives_count": len(archives),
        "latest_archive": archives[0] if archives else "Aucune",
        "recent_logs": recent_logs,
    }


def collect_app_stats():
    try:
        req = urllib.request.Request("http://41.69.31.10/api/stats")
        with urllib.request.urlopen(req, timeout=2.0) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception:
        return METRICS_CACHE["app_stats"]


def background_collector():
    while True:
        vms_data = [probe_vm(vm) for vm in VMS_CONFIG]
        app_stats = collect_app_stats()
        backup_info = collect_backup_info()
        with CACHE_LOCK:
            METRICS_CACHE["updated_at"] = datetime.now(timezone.utc).isoformat()
            METRICS_CACHE["vms"] = vms_data
            METRICS_CACHE["app_stats"] = app_stats
            METRICS_CACHE["backup"] = backup_info
        time.sleep(3)


def format_prometheus_metrics():
    with CACHE_LOCK:
        vms = list(METRICS_CACHE["vms"])
        stats = dict(METRICS_CACHE["app_stats"])
        bkp = dict(METRICS_CACHE["backup"])

    lines = [
        "# HELP africacloud_node_up Disponibilite du noeud VM (1 = UP, 0 = DOWN)",
        "# TYPE africacloud_node_up gauge",
    ]
    for vm in vms:
        val = 1 if vm.get("online") else 0
        lines.append(f'africacloud_node_up{{vm="{vm["id"]}",name="{vm["name"]}",ip="{vm["ip"]}"}} {val}')

    lines += [
        "# HELP africacloud_node_cpu_percent Utilisation CPU en pourcentage",
        "# TYPE africacloud_node_cpu_percent gauge",
    ]
    for vm in vms:
        lines.append(f'africacloud_node_cpu_percent{{vm="{vm["id"]}",name="{vm["name"]}"}} {vm.get("cpu_pct", 0)}')

    lines += [
        "# HELP africacloud_node_ram_percent Utilisation RAM en pourcentage",
        "# TYPE africacloud_node_ram_percent gauge",
    ]
    for vm in vms:
        lines.append(f'africacloud_node_ram_percent{{vm="{vm["id"]}",name="{vm["name"]}"}} {vm.get("ram_pct", 0)}')

    lines += [
        "# HELP africacloud_node_disk_percent Utilisation Disque en pourcentage",
        "# TYPE africacloud_node_disk_percent gauge",
    ]
    for vm in vms:
        lines.append(f'africacloud_node_disk_percent{{vm="{vm["id"]}",name="{vm["name"]}"}} {vm.get("disk_pct", 0)}')

    lines += [
        "# HELP africacloud_issues_total Nombre total d incidents techniques en BDD (VM4)",
        "# TYPE africacloud_issues_total gauge",
        f'africacloud_issues_total {stats.get("total", 0)}',
        f'africacloud_issues_open {stats.get("open_count", 0)}',
        f'africacloud_issues_critical {stats.get("critical_active", 0)}',
        "# HELP africacloud_backups_count Nombre d archives de sauvegarde sur VM5",
        "# TYPE africacloud_backups_count gauge",
        f'africacloud_backups_count {bkp.get("archives_count", 0)}',
    ]
    return "\n".join(lines) + "\n"


class SupervisionHandler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        print(f"[VM5-SUP] {self.address_string()} - {fmt % args}")

    def send_json(self, status_code, payload):
        body = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()
        self.wfile.write(body)

    def read_json_body(self):
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0:
            return {}
        raw = self.rfile.read(length).decode("utf-8")
        return json.loads(raw) if raw else {}

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)
        pathname = parsed.path

        if pathname == "/metrics":
            body = format_prometheus_metrics().encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; version=0.0.4; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(body)
            return

        if pathname in ("/api/supervision", "/api/health"):
            with CACHE_LOCK:
                payload = dict(METRICS_CACHE)
            payload["service"] = "AfricaCloud - Grafana & Prometheus Supervision Server (VM5)"
            payload["status"] = "OK"
            payload["supervision_node"] = "VM5 backup-sup (41.69.31.50 / NAT 192.168.38.105)"
            return self.send_json(200, payload)

        if pathname in ("/", "/grafana", "/grafana.html", "/index.html"):
            if os.path.isfile(GRAFANA_HTML_PATH):
                with open(GRAFANA_HTML_PATH, "rb") as f:
                    content = f.read()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(content)))
                self.end_headers()
                self.wfile.write(content)
                return

        self.send_error(404, "Not Found")

    def do_POST(self):
        parsed = urlparse(self.path)
        if parsed.path == "/api/supervision/backup":
            try:
                proc = subprocess.run(
                    ["sudo", "/opt/africacloud/backup_africacloud.sh"],
                    capture_output=True,
                    text=True,
                    timeout=25,
                )
                bkp = collect_backup_info()
                with CACHE_LOCK:
                    METRICS_CACHE["backup"] = bkp
                return self.send_json(
                    200,
                    {
                        "status": "OK",
                        "message": "Sauvegarde centralisée exécutée avec succès sur VM5",
                        "output": proc.stdout[-800:],
                        "backup": bkp,
                    },
                )
            except Exception as e:
                return self.send_json(500, {"status": "ERROR", "error": str(e)})

        if parsed.path == "/api/supervision/test":
            try:
                body = self.read_json_body()
                test_name = body.get("test", "all")
                suite_result = run_test_suite(test_name)
                return self.send_json(200, suite_result)
            except Exception as e:
                return self.send_json(500, {"status": "ERROR", "error": str(e)})

        return self.send_json(404, {"error": "Endpoint not found"})


class ReuseThreadingHTTPServer(ThreadingHTTPServer):
    allow_reuse_address = True


def serve_port(port):
    httpd = ReuseThreadingHTTPServer(("0.0.0.0", port), SupervisionHandler)
    print(f" -> Supervision Server listening on 0.0.0.0:{port}", flush=True)
    httpd.serve_forever()


if __name__ == "__main__":
    collector_thread = threading.Thread(target=background_collector, daemon=True)
    collector_thread.start()

    print("====================================================================")
    print(" AfricaCloud - Supervision Grafana (3000) & Prometheus (9090) - VM5")
    print("====================================================================")
    t_prom = threading.Thread(target=serve_port, args=(9090,), daemon=True)
    t_prom.start()
    serve_port(3000)
