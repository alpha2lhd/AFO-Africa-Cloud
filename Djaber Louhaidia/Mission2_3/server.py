#!/usr/bin/env python3
"""
AfricaCloud - Portail de Signalement d'Incidents Techniques (Web UI + API REST + SQLite DB)
African Skills Olympics 2026
Déployé sur VM2 (app1) et VM3 (app2)
"""

import json
import mimetypes
import os
import re
import socket
import sqlite3
import threading
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PUBLIC_DIR = os.path.join(BASE_DIR, "public")
DB_PATH = os.path.join(BASE_DIR, "africacloud.db")
START_TIME = time.time()

HOSTNAME = socket.gethostname().lower()

NODE_PROFILES = {
    "app1": {
        "label": "VM2 app1 : 69.41.31.11 / 31.69.41.11 (NAT 192.168.38.102)",
        "info": {
            "node": "VM2 (app1)",
            "vlan22": "69.41.31.11",
            "vlan33": "31.69.41.11",
            "nat": "192.168.38.102",
        },
    },
    "app2": {
        "label": "VM3 app2 : 69.41.31.12 / 31.69.41.12 (NAT 192.168.38.103)",
        "info": {
            "node": "VM3 (app2)",
            "vlan22": "69.41.31.12",
            "vlan33": "31.69.41.12",
            "nat": "192.168.38.103",
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
        },
    },
}

PROFILE = NODE_PROFILES.get(
    HOSTNAME,
    {
        "label": f"{HOSTNAME}",
        "info": {"node": HOSTNAME},
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
            return self.send_json(
                200,
                {
                    "service": "AfricaCloud - Technical Issue Reporting API",
                    "status": "OK",
                    "database": "Connected (SQLite File - africacloud.db)",
                    "served_by_node": NODE_NAME,
                    "hostname": HOSTNAME,
                    "server_network": SERVER_IPS,
                    "uptime_seconds": int(time.time() - START_TIME),
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                },
            )

        if pathname == "/api/stats":
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
    ports = [8080, 80, 3000]
    print("====================================================================")
    print(" AfricaCloud - Signalement d'Incidents Techniques (Python3 + SQLite)")
    print(f" Noeud Actif   : {NODE_NAME}")
    print(" Ports actifs  : 8080, 80, 3000")
    print("====================================================================")

    for p in ports:
        t = threading.Thread(target=serve_on_port, args=(p,), daemon=True)
        t.start()

    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        pass
