#!/usr/bin/env python3
"""
AfricaCloud - Serveur de Base de Données Centralisé sur VM4 (31.69.41.20:5432)
African Skills Olympics 2026
Écoute sur le port 5432 (VLAN 33 : 31.69.41.20) pour partager la BDD en temps réel
entre VM2 (app1 - 31.69.41.11) et VM3 (app2 - 31.69.41.12).
"""

import json
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
DB_PATH = os.path.join(BASE_DIR, "africacloud.db")
START_TIME = time.time()
HOSTNAME = socket.gethostname().lower()
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


class CentralDBHandler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        print(f"[VM4-DB 31.69.41.20:5432] {self.address_string()} - {fmt % args}")

    def send_json(self, status_code, payload):
        body = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def read_json_body(self):
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0:
            return {}
        raw = self.rfile.read(length).decode("utf-8")
        return json.loads(raw) if raw else {}

    def do_GET(self):
        parsed = urlparse(self.path)
        pathname = parsed.path
        query = parse_qs(parsed.query)

        if pathname in ("/", "/db/health", "/api/health"):
            return self.send_json(
                200,
                {
                    "service": "AfricaCloud Central Database Server (VM4)",
                    "status": "OK",
                    "db_host": "31.69.41.20",
                    "db_port": 5432,
                    "db_path": DB_PATH,
                    "hostname": HOSTNAME,
                    "uptime_seconds": int(time.time() - START_TIME),
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                },
            )

        if pathname in ("/db/stats", "/api/stats"):
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
            return self.send_json(200, dict(row))

        if pathname in ("/db/issues", "/api/issues"):
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

        m = re.match(r"^/(?:db|api)/issues/(\d+)$", pathname)
        if m:
            issue_id = int(m.group(1))
            with DB_LOCK:
                conn = get_db()
                row = conn.execute("SELECT * FROM issues WHERE id = ?", (issue_id,)).fetchone()
                conn.close()
            if not row:
                return self.send_json(404, {"error": "Incident introuvable"})
            return self.send_json(200, dict(row))

        return self.send_json(404, {"error": f"Unknown DB endpoint: {pathname}"})

    def do_POST(self):
        parsed = urlparse(self.path)
        pathname = parsed.path

        if pathname in ("/db/issues", "/api/issues"):
            body = self.read_json_body()
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

        return self.send_json(404, {"error": f"Unknown DB endpoint: POST {pathname}"})

    def do_PUT(self):
        parsed = urlparse(self.path)
        pathname = parsed.path
        m = re.match(r"^/(?:db|api)/issues/(\d+)$", pathname)
        if not m:
            return self.send_json(404, {"error": f"Unknown DB endpoint: PUT {pathname}"})

        issue_id = int(m.group(1))
        body = self.read_json_body()

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

    def do_DELETE(self):
        parsed = urlparse(self.path)
        pathname = parsed.path
        m = re.match(r"^/(?:db|api)/issues/(\d+)$", pathname)
        if not m:
            return self.send_json(404, {"error": f"Unknown DB endpoint: DELETE {pathname}"})

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


if __name__ == "__main__":
    init_db()
    port = int(os.environ.get("DB_PORT", "5432"))
    print("====================================================================")
    print(" AfricaCloud - Serveur BDD Centralisé VM4 (VLAN 33 - 31.69.41.20)")
    print(f" Port d'écoute : 0.0.0.0:{port}")
    print(f" Fichier BDD   : {DB_PATH}")
    print("====================================================================")
    httpd = ThreadingHTTPServer(("0.0.0.0", port), CentralDBHandler)
    httpd.serve_forever()
