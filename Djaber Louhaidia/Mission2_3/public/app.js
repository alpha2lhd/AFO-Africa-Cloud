// AfricaCloud — Technical Issue Reporting Frontend (/api/issues)
// Connecté à la BDD centrale partagée sur VM4 (31.69.41.20:5432)

let currentStatusFilter = '';
let API_BASE = '';

function changeApiBase(newBase) {
  API_BASE = newBase;
  loadAll();
}

async function fetchJson(url, options = {}) {
  const fullUrl = url.startsWith('http') ? url : `${API_BASE}${url}`;
  const res = await fetch(fullUrl, {
    headers: { 'Content-Type': 'application/json' },
    ...options
  });
  return res.json();
}

async function loadHealthAndStats() {
  try {
    const [health, stats] = await Promise.all([
      fetchJson('/api/health'),
      fetchJson('/api/stats')
    ]);

    const dbText = health.database && health.database.includes('VM4')
      ? 'VM4 (31.69.41.20:5432)'
      : 'Connectée';
    document.getElementById('api-status-text').textContent = `API: ${health.status} | BDD: ${dbText}`;
    document.getElementById('node-badge').textContent = `[${health.server_network?.node || health.served_by_node}]`;
    const bannerNode = document.getElementById('banner-node-name');
    if (bannerNode) bannerNode.textContent = health.served_by_node;
    document.getElementById('api-dot').style.background = '#10b981';

    document.getElementById('stat-total').textContent = stats.total;
    document.getElementById('stat-open').textContent = stats.open_count;
    document.getElementById('stat-progress').textContent = stats.in_progress_count;
    document.getElementById('stat-resolved').textContent = stats.resolved_count;
    document.getElementById('stat-critical').textContent = stats.critical_active;
  } catch (err) {
    document.getElementById('api-status-text').textContent = 'Erreur de connexion API';
    document.getElementById('api-dot').style.background = '#ef4444';
  }
}

function getStatusBadgeClass(status) {
  if (status === 'Ouvert') return 'status-ouvert';
  if (status === 'En cours') return 'status-encours';
  return 'status-resolu';
}

function getPriorityBadgeClass(priority) {
  if (priority === 'Critique') return 'prio-critique';
  if (priority === 'Haute') return 'prio-haute';
  if (priority === 'Moyenne') return 'prio-moyenne';
  return 'prio-basse';
}

async function loadIssues() {
  const query = currentStatusFilter ? `?status=${encodeURIComponent(currentStatusFilter)}` : '';
  const issues = await fetchJson(`/api/issues${query}`);
  const tbody = document.getElementById('issues-tbody');

  if (!issues.length) {
    tbody.innerHTML = '<tr><td colspan="8">Aucun incident technique trouvé.</td></tr>';
    return;
  }

  tbody.innerHTML = issues.map(item => {
    const statusClass = getStatusBadgeClass(item.status);
    const prioClass = getPriorityBadgeClass(item.priority);

    return `
      <tr>
        <td><strong>#${item.id}</strong></td>
        <td>
          <strong>${escapeHtml(item.title)}</strong>
          <div class="issue-desc">${escapeHtml(item.description)}</div>
        </td>
        <td>${escapeHtml(item.category)}</td>
        <td><span class="badge ${prioClass}">${escapeHtml(item.priority)}</span></td>
        <td>${escapeHtml(item.reporter)}</td>
        <td>${escapeHtml(item.created_at)}</td>
        <td><span class="badge ${statusClass}">${escapeHtml(item.status)}</span></td>
        <td class="actions-cell">
          ${item.status !== 'En cours' ? `<button class="btn-blue btn-sm" onclick="updateStatus(${item.id}, 'En cours')">Prendre en charge</button>` : ''}
          ${item.status !== 'Résolu' ? `<button class="btn-green btn-sm" onclick="updateStatus(${item.id}, 'Résolu')">Résoudre</button>` : ''}
          ${item.status === 'Résolu' ? `<button class="btn-outline btn-sm" onclick="updateStatus(${item.id}, 'Ouvert')">Rouvrir</button>` : ''}
          <button class="btn-danger btn-sm" onclick="deleteIssue(${item.id})">Suppr</button>
        </td>
      </tr>
    `;
  }).join('');
}

async function updateStatus(id, status) {
  await fetchJson(`/api/issues/${id}`, {
    method: 'PUT',
    body: JSON.stringify({ status })
  });
  await loadAll();
}

async function deleteIssue(id) {
  await fetchJson(`/api/issues/${id}`, { method: 'DELETE' });
  await loadAll();
}

function setFilter(status, btn) {
  currentStatusFilter = status;
  document.querySelectorAll('.filter-group button').forEach(b => b.classList.remove('active'));
  if (btn) btn.classList.add('active');
  loadIssues();
}

async function testEndpoint(endpoint) {
  const out = document.getElementById('api-output');
  out.textContent = `Chargement GET ${endpoint}...`;
  const data = await fetchJson(endpoint);
  out.textContent = `// GET ${endpoint} (200 OK)\n` + JSON.stringify(data, null, 2);
}

function escapeHtml(str) {
  return String(str ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

document.getElementById('issue-form').addEventListener('submit', async (e) => {
  e.preventDefault();
  const payload = {
    title: document.getElementById('iss-title').value,
    category: document.getElementById('iss-category').value,
    priority: document.getElementById('iss-priority').value,
    reporter: document.getElementById('iss-reporter').value,
    description: document.getElementById('iss-description').value,
    status: 'Ouvert'
  };

  await fetchJson('/api/issues', {
    method: 'POST',
    body: JSON.stringify(payload)
  });

  document.getElementById('iss-title').value = '';
  document.getElementById('iss-description').value = '';
  await loadAll();
});

async function loadAll() {
  await Promise.all([
    loadHealthAndStats(),
    loadIssues()
  ]);
}

loadAll();
// Synchronisation temps réel automatique entre VM2 (app1), VM3 (app2) et VM4 (BDD)
setInterval(() => {
  loadAll();
}, 3000);
