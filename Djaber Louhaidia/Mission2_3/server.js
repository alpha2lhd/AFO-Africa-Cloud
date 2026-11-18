const http = require('node:http');
const fs = require('node:fs');
const path = require('node:path');
const os = require('node:os');
const { DatabaseSync } = require('node:sqlite');

const PORT = process.env.PORT || 3000;
const NODE_NAME = process.env.NODE_NAME || 'VM1 ctrl-proxy : 41.69.31.10 / 69.41.31.10 / 31.69.41.10 (NAT 192.168.38.101)';
const SERVER_IPS = {
  node: 'VM1 ctrl-proxy',
  vlan11: '41.69.31.10',
  vlan22: '69.41.31.10',
  vlan33: '31.69.41.10',
  nat: '192.168.38.101'
};
const DB_PATH = path.join(__dirname, 'africacloud.db');

const CREATE_TABLE_SQL = `
  CREATE TABLE IF NOT EXISTS issues (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    category TEXT NOT NULL,
    priority TEXT NOT NULL DEFAULT 'Moyenne',
    reporter TEXT NOT NULL,
    description TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'Ouvert',
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
  );
`;

// 1. Initialize SQLite Database (File-backed with automatic in-memory fallback)
let db;
let dbMode = 'SQLite File (africacloud.db)';
try {
  db = new DatabaseSync(DB_PATH);
  db.exec(CREATE_TABLE_SQL);
} catch (err) {
  db = new DatabaseSync(':memory:');
  db.exec(CREATE_TABLE_SQL);
  dbMode = 'SQLite Engine (In-Memory)';
}

// Seed initial technical issues if empty
const issueCount = db.prepare('SELECT COUNT(*) AS count FROM issues').get().count;
if (issueCount === 0) {
  const insertIssue = db.prepare(
    'INSERT INTO issues (title, category, priority, reporter, description, status) VALUES (?, ?, ?, ?, ?, ?)'
  );
  insertIssue.run(
    'Latence sur le noeud VM2 (App1)',
    'Serveur / VM',
    'Haute',
    'Amine (Support NOC)',
    'Temps de réponse élevé constaté sur 69.41.31.11 lors du pic de trafic.',
    'En cours'
  );
  insertIssue.run(
    'Routage inter-VLAN 22 vers VLAN 33 (BDD)',
    'Réseau / VLAN',
    'Critique',
    'Sarah (Admin Réseau)',
    'Perte intermittente de paquets entre VM3 (69.41.31.12) et VM4 BDD (31.69.41.20).',
    'Ouvert'
  );
  insertIssue.run(
    'Vérification sauvegarde nocturne 04h00 RedSync',
    'Sauvegarde (VM5)',
    'Basse',
    'Karim (Supervision)',
    'Confirmation du dump SQL de VM4 vers VM5 (41.69.31.50).',
    'Résolu'
  );
}

// Helper: Send JSON response
function sendJson(res, statusCode, data) {
  res.writeHead(statusCode, {
    'Content-Type': 'application/json; charset=utf-8',
    'Access-Control-Allow-Origin': '*',
    'Access-Control-Allow-Methods': 'GET, POST, PUT, PATCH, DELETE, OPTIONS',
    'Access-Control-Allow-Headers': 'Content-Type'
  });
  res.end(JSON.stringify(data, null, 2));
}

// Helper: Parse JSON request body
function parseBody(req) {
  return new Promise((resolve, reject) => {
    let body = '';
    req.on('data', chunk => { body += chunk.toString(); });
    req.on('end', () => {
      if (!body) return resolve({});
      try {
        resolve(JSON.parse(body));
      } catch (err) {
        reject(new Error('Invalid JSON payload'));
      }
    });
    req.on('error', reject);
  });
}

// 2. HTTP Server & REST API Router
const server = http.createServer(async (req, res) => {
  const url = new URL(req.url, `http://${req.headers.host || 'localhost'}`);
  const pathname = url.pathname;
  const method = req.method.toUpperCase();

  // Handle CORS preflight
  if (method === 'OPTIONS') {
    res.writeHead(204, {
      'Access-Control-Allow-Origin': '*',
      'Access-Control-Allow-Methods': 'GET, POST, PUT, PATCH, DELETE, OPTIONS',
      'Access-Control-Allow-Headers': 'Content-Type'
    });
    return res.end();
  }

  try {
    // --- API ROUTES ---

    // GET /api/health
    if (pathname === '/api/health' && method === 'GET') {
      return sendJson(res, 200, {
        service: 'AfricaCloud - Technical Issue Reporting API',
        status: 'OK',
        database: `Connected (${dbMode})`,
        served_by_node: NODE_NAME,
        server_network: SERVER_IPS,
        uptime_seconds: Math.floor(process.uptime()),
        timestamp: new Date().toISOString()
      });
    }

    // GET /api/stats
    if (pathname === '/api/stats' && method === 'GET') {
      const stats = db.prepare(`
        SELECT 
          COUNT(*) AS total,
          COALESCE(SUM(CASE WHEN status = 'Ouvert' THEN 1 ELSE 0 END), 0) AS open_count,
          COALESCE(SUM(CASE WHEN status = 'En cours' THEN 1 ELSE 0 END), 0) AS in_progress_count,
          COALESCE(SUM(CASE WHEN status = 'Résolu' THEN 1 ELSE 0 END), 0) AS resolved_count,
          COALESCE(SUM(CASE WHEN priority = 'Critique' AND status != 'Résolu' THEN 1 ELSE 0 END), 0) AS critical_active
        FROM issues
      `).get();
      return sendJson(res, 200, {
        ...stats,
        served_by_node: NODE_NAME
      });
    }

    // GET /api/issues (or /api/tickets)
    if ((pathname === '/api/issues' || pathname === '/api/tickets') && method === 'GET') {
      const statusFilter = url.searchParams.get('status');
      let issues;
      if (statusFilter) {
        issues = db.prepare('SELECT * FROM issues WHERE status = ? ORDER BY id DESC').all(statusFilter);
      } else {
        issues = db.prepare('SELECT * FROM issues ORDER BY id DESC').all();
      }
      return sendJson(res, 200, issues);
    }

    // Match /api/issues/:id (or /api/tickets/:id)
    const issueIdMatch = pathname.match(/^\/api\/(?:issues|tickets)\/(\d+)$/);

    // GET /api/issues/:id
    if (issueIdMatch && method === 'GET') {
      const id = Number(issueIdMatch[1]);
      const issue = db.prepare('SELECT * FROM issues WHERE id = ?').get(id);
      if (!issue) return sendJson(res, 404, { error: 'Incident introuvable' });
      return sendJson(res, 200, issue);
    }

    // POST /api/issues
    if ((pathname === '/api/issues' || pathname === '/api/tickets') && method === 'POST') {
      const body = await parseBody(req);
      const {
        title,
        category = 'Serveur / VM',
        priority = 'Moyenne',
        reporter = 'Utilisateur',
        description = '',
        status = 'Ouvert'
      } = body;

      if (!title || !description) {
        return sendJson(res, 400, { error: 'Champs requis manquants : title, description' });
      }

      const stmt = db.prepare(
        'INSERT INTO issues (title, category, priority, reporter, description, status) VALUES (?, ?, ?, ?, ?, ?)'
      );
      const result = stmt.run(
        String(title).trim(),
        String(category).trim(),
        String(priority).trim(),
        String(reporter).trim() || 'Anonyme',
        String(description).trim(),
        String(status).trim()
      );
      const created = db.prepare('SELECT * FROM issues WHERE id = ?').get(result.lastInsertRowid);
      return sendJson(res, 201, created);
    }

    // PUT or PATCH /api/issues/:id
    if (issueIdMatch && (method === 'PUT' || method === 'PATCH')) {
      const id = Number(issueIdMatch[1]);
      const existing = db.prepare('SELECT * FROM issues WHERE id = ?').get(id);
      if (!existing) return sendJson(res, 404, { error: 'Incident introuvable' });

      const body = await parseBody(req);
      const updated = {
        title: body.title ?? existing.title,
        category: body.category ?? existing.category,
        priority: body.priority ?? existing.priority,
        reporter: body.reporter ?? existing.reporter,
        description: body.description ?? existing.description,
        status: body.status ?? existing.status
      };

      db.prepare(`
        UPDATE issues
        SET title = ?, category = ?, priority = ?, reporter = ?, description = ?, status = ?
        WHERE id = ?
      `).run(
        updated.title,
        updated.category,
        updated.priority,
        updated.reporter,
        updated.description,
        updated.status,
        id
      );

      const issue = db.prepare('SELECT * FROM issues WHERE id = ?').get(id);
      return sendJson(res, 200, issue);
    }

    // DELETE /api/issues/:id
    if (issueIdMatch && method === 'DELETE') {
      const id = Number(issueIdMatch[1]);
      const existing = db.prepare('SELECT * FROM issues WHERE id = ?').get(id);
      if (!existing) return sendJson(res, 404, { error: 'Incident introuvable' });
      db.prepare('DELETE FROM issues WHERE id = ?').run(id);
      return sendJson(res, 200, { message: `Incident #${id} supprimé`, id });
    }

    // Unknown API route
    if (pathname.startsWith('/api/')) {
      return sendJson(res, 404, { error: `API endpoint not found: ${method} ${pathname}` });
    }

    // --- STATIC WEB INTERFACE ---
    let filePath = pathname === '/' ? '/index.html' : pathname;
    const resolvedPath = path.join(__dirname, 'public', filePath);

    if (!resolvedPath.startsWith(path.join(__dirname, 'public'))) {
      res.writeHead(403);
      return res.end('Forbidden');
    }

    if (fs.existsSync(resolvedPath) && fs.statSync(resolvedPath).isFile()) {
      const ext = path.extname(resolvedPath).toLowerCase();
      const mimeTypes = {
        '.html': 'text/html; charset=utf-8',
        '.css': 'text/css; charset=utf-8',
        '.js': 'application/javascript; charset=utf-8',
        '.json': 'application/json; charset=utf-8',
        '.svg': 'image/svg+xml'
      };
      res.writeHead(200, { 'Content-Type': mimeTypes[ext] || 'text/plain' });
      fs.createReadStream(resolvedPath).pipe(res);
    } else {
      res.writeHead(404, { 'Content-Type': 'text/plain; charset=utf-8' });
      res.end('404 Not Found');
    }
  } catch (err) {
    sendJson(res, 500, { error: err.message || 'Internal Server Error' });
  }
});

server.listen(PORT, '0.0.0.0', () => {
  console.log(`====================================================================`);
  console.log(` AfricaCloud - Signalement d'Incidents Techniques`);
  console.log(` Serveur : ${NODE_NAME}`);
  console.log(` Accès NAT     : http://192.168.38.101:${PORT}`);
  console.log(` Accès VLAN 11 : http://41.69.31.10:${PORT}`);
  console.log(` Accès VLAN 22 : http://69.41.31.10:${PORT}`);
  console.log(` Accès VLAN 33 : http://31.69.41.10:${PORT}`);
  console.log(` Accès Local   : http://localhost:${PORT}`);
  console.log(` REST API      : http://192.168.38.101:${PORT}/api/issues`);
  console.log(`====================================================================`);
});
