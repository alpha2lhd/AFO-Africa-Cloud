#!/usr/bin/env python3
"""
AfricaCloud - Portail de Signalement d'Incidents Techniques (Web UI + API REST + BDD Partagée VM4)
African Skills Olympics 2026
Déployé sur VM2 (app1) et VM3 (app2) — Connecté en temps réel à VM4 (31.69.41.20:5432)
"""

import json
import mimetypes
import os
import re
import socket
import sqlite3
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PUBLIC_DIR = os.path.join(BASE_DIR, "public")
DB_PATH = os.path.join(BASE_DIR, "africacloud.db")
START_TIME = time.time()

HOSTNAME = socket.gethostname().lower()

# Serveur BDD centralisé sur VM4 (VLAN 33 : 31.69.41.20:5432)
CENTRAL_DB_URL = os.environ.get("CENTRAL_DB_URL", "http://31.69.41.20:5432")
# Si exécuté sur VM1 (ctrl-proxy, qui n'a pas accès direct à VM4:5432 par UFW),
# passe par VM2 (69.41.31.11:8080) ou VM3 (69.41.31.12:8080)
APP_UPSTREAMS = ["http://69.41.31.11:8080", "http://69.41.31.12:8080"]

NODE_PROFILES = {
    "app1": {
        "label": "VM2 app1 : 69.41.31.11 / 31.69.41.11 (NAT 192.168.38.102)",
        "info": {
            "node": "VM2 (app1)",
            "vlan22": "69.41.31.11",
            "vlan33": "31.69.41.11",
            "nat": "192.168.38.102",
            "db_server": "31.69.41.20:5432 (VM4)",
        },
    },
    "app2": {
        "label": "VM3 app2 : 69.41.31.12 / 31.69.41.12 (NAT 192.168.38.103)",
        "info": {
            "node": "VM3 (app2)",
            "vlan22": "69.41.31.12",
            "vlan33": "31.69.41.12",
            "nat": "192.168.38.103",
            "db_server": "31.69.41.20:5432 (VM4)",
        },
    },
    "ctrl-proxy": {
        "label": "VM1 ctrl-proxy : 41.69.31.10 / 69.41.31.10 / 31.69.41.10 (NAT 192.168.38.101)",
        "info": {
            "node": "VM1 (ctrl-proxy)",
            "vlan11": "41.69.31.10",
            "vlan22": "69.41.31.10",
            "vlan33": "31.69.41.10",
            "nat": "192.168.38.101",
            "db_server": "31.69.41.20:5432 (via App VLAN 22/33)",
        },
    },
}

PROFILE = NODE_PROFILES.get(
    HOSTNAME,
    {
        "label": f"{HOSTNAME}",
        "info": {"node": HOSTNAME, "db_server": "31.69.41.20:5432 (VM4)"},
    },
)

NODE_NAME = os.environ.get("NODE_NAME", PROFILE["label"])
SERVER_IPS = PROFILE["info"]

DB_LOCK = threading.Lock()


def get_db():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with DB_LOCK:
        conn = get_db()
        cur = conn.cursor()
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS issues (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                category TEXT NOT NULL,
                priority TEXT NOT NULL DEFAULT 'Moyenne',
                reporter TEXT NOT NULL,
                description TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'Ouvert',
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        cur.execute("SELECT COUNT(*) AS count FROM issues")
        count = cur.fetchone()["count"]
        if count == 0:
            seed_issues = [
                (
                    "Latence sur le noeud VM2 (App1)",
                    "Serveur / VM",
                    "Haute",
                    "Amine (Support NOC)",
                    "Temps de réponse élevé constaté sur 69.41.31.11 lors du pic de trafic.",
                    "En cours",
                ),
                (
                    "Routage inter-VLAN 22 vers VLAN 33 (BDD)",
                    "Réseau / VLAN",
                    "Critique",
                    "Sarah (Admin Réseau)",
                    "Perte intermittente de paquets entre VM3 (69.41.31.12) et VM4 BDD (31.69.41.20).",
                    "Ouvert",
                ),
                (
                    "Vérification sauvegarde nocturne 04h00 RedSync",
                    "Sauvegarde (VM5)",
                    "Basse",
                    "Karim (Supervision)",
                    "Confirmation du dump SQL de VM4 vers VM5 (41.69.31.50).",
                    "Résolu",
                ),
            ]
            cur.executemany(
                "INSERT INTO issues (title, category, priority, reporter, description, status) VALUES (?, ?, ?, ?, ?, ?)",
                seed_issues,
            )
        conn.commit()
        conn.close()


def sync_local_mirror(issues_list):
    """Synchronise le fichier SQLite local (/opt/africacloud/africacloud.db) avec les données de VM4."""
    if not isinstance(issues_list, list):
        return
    try:
        with DB_LOCK:
            conn = get_db()
            cur = conn.cursor()
            cur.execute("DELETE FROM issues")
            for row in issues_list:
                cur.execute(
                    """
                    INSERT INTO issues (id, title, category, priority, reporter, description, status, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        row.get("id"),
                        row.get("title", ""),
                        row.get("category", "Serveur / VM"),
                        row.get("priority", "Moyenne"),
                        row.get("reporter", "Anonyme"),
                        row.get("description", ""),
                        row.get("status", "Ouvert"),
                        row.get("created_at", ""),
                    ),
                )
            conn.commit()
            conn.close()
    except Exception:
        pass


def remote_db_request(method, path, payload=None):
    """
    Interroge la base de données centralisée sur VM4 (31.69.41.20:5432).
    Si on est sur VM1 (ctrl-proxy), passe par VM2/VM3 pour respecter le pare-feu UFW de VM4.
    Retourne (status_code, data_dict_or_list) ou None si VM4 est injoignable.
    """
    targets = [CENTRAL_DB_URL] if HOSTNAME != "ctrl-proxy" else APP_UPSTREAMS
    data_bytes = json.dumps(payload).encode("utf-8") if payload is not None else None

    for base in targets:
        url = f"{base}{path}"
        req = urllib.request.Request(url, data=data_bytes, method=method)
        req.add_header("Content-Type", "application/json; charset=utf-8")
        req.add_header("X-Internal-Sync", "1")
        try:
            with urllib.request.urlopen(req, timeout=1.5) as resp:
                raw = resp.read().decode("utf-8")
                parsed = json.loads(raw) if raw else {}
                return resp.status, parsed
        except urllib.error.HTTPError as e:
            try:
                raw = e.read().decode("utf-8")
                return e.code, json.loads(raw) if raw else {"error": str(e)}
            except Exception:
                return e.code, {"error": str(e)}
        except Exception:
            continue
    return None


def refresh_mirror_from_remote():
    res = remote_db_request("GET", "/api/issues")
    if res and res[0] == 200 and isinstance(res[1], list):
        sync_local_mirror(res[1])


class AfricaCloudHandler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        print(f"[{self.log_date_time_string()}] {self.address_string()} - {fmt % args}")

    def send_json(self, status_code, payload):
        body = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PUT, PATCH, DELETE, OPTIONS")
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
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PUT, PATCH, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)
        pathname = parsed.path
        query = parse_qs(parsed.query)

        if pathname == "/api/health":
            db_check = remote_db_request("GET", "/db/health")
            db_status_label = (
                "Connected to VM4 Central DB (31.69.41.20:5432)"
                if db_check and db_check[0] == 200
                else "Connected (Local SQLite Fallback - africacloud.db)"
            )
            return self.send_json(
                200,
                {
                    "service": "AfricaCloud - Technical Issue Reporting API",
                    "status": "OK",
                    "database": db_status_label,
                    "db_host": "31.69.41.20:5432",
                    "served_by_node": NODE_NAME,
                    "hostname": HOSTNAME,
                    "server_network": SERVER_IPS,
                    "uptime_seconds": int(time.time() - START_TIME),
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                },
            )

        if pathname == "/api/stats":
            remote_res = remote_db_request("GET", "/api/stats")
            if remote_res and remote_res[0] == 200:
                data = dict(remote_res[1])
                data["served_by_node"] = NODE_NAME
                data["db_host"] = "31.69.41.20:5432 (VM4)"
                return self.send_json(200, data)

            with DB_LOCK:
                conn = get_db()
                row = conn.execute(
                    """
                    SELECT
                      COUNT(*) AS total,
                      COALESCE(SUM(CASE WHEN status = 'Ouvert' THEN 1 ELSE 0 END), 0) AS open_count,
                      COALESCE(SUM(CASE WHEN status = 'En cours' THEN 1 ELSE 0 END), 0) AS in_progress_count,
                      COALESCE(SUM(CASE WHEN status = 'Résolu' THEN 1 ELSE 0 END), 0) AS resolved_count,
                      COALESCE(SUM(CASE WHEN priority = 'Critique' AND status != 'Résolu' THEN 1 ELSE 0 END), 0) AS critical_active
                    FROM issues
                    """
                ).fetchone()
                conn.close()
            data = dict(row)
            data["served_by_node"] = NODE_NAME
            return self.send_json(200, data)

        if pathname in ("/api/issues", "/api/tickets"):
            status_filter = query.get("status", [None])[0]
            remote_path = "/api/issues"
            if status_filter:
                remote_path += f"?status={urllib.parse.quote(status_filter)}"
            remote_res = remote_db_request("GET", remote_path)
            if remote_res and remote_res[0] == 200 and isinstance(remote_res[1], list):
                if not status_filter:
                    sync_local_mirror(remote_res[1])
                return self.send_json(200, remote_res[1])

            with DB_LOCK:
                conn = get_db()
                if status_filter:
                    rows = conn.execute(
                        "SELECT * FROM issues WHERE status = ? ORDER BY id DESC",
                        (status_filter,),
                    ).fetchall()
                else:
                    rows = conn.execute("SELECT * FROM issues ORDER BY id DESC").fetchall()
                conn.close()
            return self.send_json(200, [dict(r) for r in rows])

        m = re.match(r"^/api/(?:issues|tickets)/(\d+)$", pathname)
        if m:
            issue_id = int(m.group(1))
            remote_res = remote_db_request("GET", f"/api/issues/{issue_id}")
            if remote_res:
                return self.send_json(remote_res[0], remote_res[1])

            with DB_LOCK:
                conn = get_db()
                row = conn.execute("SELECT * FROM issues WHERE id = ?", (issue_id,)).fetchone()
                conn.close()
            if not row:
                return self.send_json(404, {"error": "Incident introuvable"})
            return self.send_json(200, dict(row))

        if pathname.startswith("/api/"):
            return self.send_json(404, {"error": f"API endpoint not found: GET {pathname}"})

        # Serve static files from ./public
        rel_path = "index.html" if pathname == "/" else pathname.lstrip("/")
        full_path = os.path.realpath(os.path.join(PUBLIC_DIR, rel_path))
        if not full_path.startswith(os.path.realpath(PUBLIC_DIR)):
            self.send_error(403, "Forbidden")
            return

        if os.path.isfile(full_path):
            ctype, _ = mimetypes.guess_type(full_path)
            ctype = ctype or "application/octet-stream"
            if ctype.startswith("text/") or ctype in ("application/javascript", "application/json"):
                ctype += "; charset=utf-8"
            with open(full_path, "rb") as f:
                content = f.read()
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            self.wfile.write(content)
        else:
            self.send_error(404, "Not Found")

    def do_POST(self):
        parsed = urlparse(self.path)
        pathname = parsed.path

        if pathname in ("/api/issues", "/api/tickets"):
            try:
                body = self.read_json_body()
            except Exception:
                return self.send_json(400, {"error": "Invalid JSON payload"})

            title = str(body.get("title", "")).strip()
            description = str(body.get("description", "")).strip()
            category = str(body.get("category", "Serveur / VM")).strip()
            priority = str(body.get("priority", "Moyenne")).strip()
            reporter = str(body.get("reporter", "Utilisateur")).strip() or "Anonyme"
            status = str(body.get("status", "Ouvert")).strip() or "Ouvert"

            if not title or not description:
                return self.send_json(400, {"error": "Champs requis manquants : title, description"})

            remote_res = remote_db_request("POST", "/api/issues", body)
            if remote_res:
                refresh_mirror_from_remote()
                return self.send_json(remote_res[0], remote_res[1])

            with DB_LOCK:
                conn = get_db()
                cur = conn.cursor()
                cur.execute(
                    "INSERT INTO issues (title, category, priority, reporter, description, status) VALUES (?, ?, ?, ?, ?, ?)",
                    (title, category, priority, reporter, description, status),
                )
                new_id = cur.lastrowid
                conn.commit()
                row = conn.execute("SELECT * FROM issues WHERE id = ?", (new_id,)).fetchone()
                conn.close()
            return self.send_json(201, dict(row))

        return self.send_json(404, {"error": f"API endpoint not found: POST {pathname}"})

    def do_PUT(self):
        parsed = urlparse(self.path)
        pathname = parsed.path
        m = re.match(r"^/api/(?:issues|tickets)/(\d+)$", pathname)
        if not m:
            return self.send_json(404, {"error": f"API endpoint not found: PUT {pathname}"})

        issue_id = int(m.group(1))
        try:
            body = self.read_json_body()
        except Exception:
            return self.send_json(400, {"error": "Invalid JSON payload"})

        remote_res = remote_db_request("PUT", f"/api/issues/{issue_id}", body)
        if remote_res:
            refresh_mirror_from_remote()
            return self.send_json(remote_res[0], remote_res[1])

        with DB_LOCK:
            conn = get_db()
            existing = conn.execute("SELECT * FROM issues WHERE id = ?", (issue_id,)).fetchone()
            if not existing:
                conn.close()
                return self.send_json(404, {"error": "Incident introuvable"})

            updated = {
                "title": body.get("title", existing["title"]),
                "category": body.get("category", existing["category"]),
                "priority": body.get("priority", existing["priority"]),
                "reporter": body.get("reporter", existing["reporter"]),
                "description": body.get("description", existing["description"]),
                "status": body.get("status", existing["status"]),
            }
            conn.execute(
                """
                UPDATE issues
                SET title = ?, category = ?, priority = ?, reporter = ?, description = ?, status = ?
                WHERE id = ?
                """,
                (
                    updated["title"],
                    updated["category"],
                    updated["priority"],
                    updated["reporter"],
                    updated["description"],
                    updated["status"],
                    issue_id,
                ),
            )
            conn.commit()
            row = conn.execute("SELECT * FROM issues WHERE id = ?", (issue_id,)).fetchone()
            conn.close()
        return self.send_json(200, dict(row))

    def do_PATCH(self):
        return self.do_PUT()

    def do_DELETE(self):
        parsed = urlparse(self.path)
        pathname = parsed.path
        m = re.match(r"^/api/(?:issues|tickets)/(\d+)$", pathname)
        if not m:
            return self.send_json(404, {"error": f"API endpoint not found: DELETE {pathname}"})

        issue_id = int(m.group(1))
        remote_res = remote_db_request("DELETE", f"/api/issues/{issue_id}")
        if remote_res:
            refresh_mirror_from_remote()
            return self.send_json(remote_res[0], remote_res[1])

        with DB_LOCK:
            conn = get_db()
            existing = conn.execute("SELECT * FROM issues WHERE id = ?", (issue_id,)).fetchone()
            if not existing:
                conn.close()
                return self.send_json(404, {"error": "Incident introuvable"})
            conn.execute("DELETE FROM issues WHERE id = ?", (issue_id,))
            conn.commit()
            conn.close()
        return self.send_json(200, {"message": f"Incident #{issue_id} supprimé", "id": issue_id})


def serve_on_port(port):
    try:
        httpd = ThreadingHTTPServer(("0.0.0.0", port), AfricaCloudHandler)
        print(f" -> Listening on 0.0.0.0:{port}")
        httpd.serve_forever()
    except Exception as e:
        print(f"Could not bind port {port}: {e}")


if __name__ == "__main__":
    init_db()
    refresh_mirror_from_remote()
    # Sur VM1 (ctrl-proxy), le port 80 est réservé au Load Balancer Nginx
    ports = [8080, 3000] if HOSTNAME == "ctrl-proxy" else [8080, 80, 3000]
    print("====================================================================")
    print(" AfricaCloud - Signalement d'Incidents Techniques (BDD Partagée VM4)")
    print(f" Noeud Actif   : {NODE_NAME}")
    print(f" BDD Centrale  : {CENTRAL_DB_URL}")
    print(f" Ports actifs  : {', '.join(str(p) for p in ports)}")
    print("====================================================================")

    for p in ports:
        t = threading.Thread(target=serve_on_port, args=(p,), daemon=True)
        t.start()

    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        pass
