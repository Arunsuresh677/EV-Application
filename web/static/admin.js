// VoltPath platform admin dashboard — vanilla JS, no build step. Talks to
// the same FastAPI backend as the driver app and operator dashboard, but as
// a separate page for a third, distinct audience: VoltPath's own team
// managing every operator on the platform, not any single charging network.

const API_BASE = '/v1';

const state = {
  token: localStorage.getItem('voltpath_admin_token') || null,
  user: null,
  operators: [],
};

async function api(path, { method = 'GET', body, headers = {} } = {}) {
  const opts = { method, headers: { 'Content-Type': 'application/json', ...headers } };
  if (state.token) opts.headers.Authorization = `Bearer ${state.token}`;
  if (body !== undefined) opts.body = JSON.stringify(body);

  const res = await fetch(API_BASE + path, opts);
  if (!res.ok) {
    let detail = res.statusText;
    try { detail = (await res.json()).detail || detail; } catch (_) {}
    throw new Error(detail);
  }
  if (res.status === 204) return null;
  return res.json();
}

function toast(message, type = '') {
  const wrap = document.getElementById('toast-wrap');
  const el = document.createElement('div');
  el.className = `toast ${type}`;
  el.textContent = message;
  wrap.appendChild(el);
  setTimeout(() => el.remove(), 4000);
}

// ---------------------------------------------------------------------------
// Auth
// ---------------------------------------------------------------------------
function showAuthScreen() {
  document.getElementById('auth-screen').classList.remove('hidden');
  document.getElementById('admin-app').classList.add('hidden');
}

function showAdminApp() {
  document.getElementById('auth-screen').classList.add('hidden');
  document.getElementById('admin-app').classList.remove('hidden');
}

async function tryResumeSession() {
  if (!state.token) return showAuthScreen();
  try {
    state.user = await api('/users/me');
    afterLogin();
  } catch (_) {
    state.token = null;
    localStorage.removeItem('voltpath_admin_token');
    showAuthScreen();
  }
}

function afterLogin() {
  if (state.user.role !== 'super_admin') {
    toast('This login is not a platform admin account.', 'error');
    document.getElementById('login-error').textContent = 'This account is not a platform admin — use the operator or driver app instead.';
    return;
  }
  showAdminApp();
  goToView('operators');
}

document.getElementById('login-form').addEventListener('submit', async (e) => {
  e.preventDefault();
  const email = document.getElementById('login-email').value;
  const password = document.getElementById('login-password').value;
  const errorEl = document.getElementById('login-error');
  errorEl.textContent = '';
  try {
    const { token, user } = await api('/auth/login', { method: 'POST', body: { email, password } });
    state.token = token;
    state.user = user;
    localStorage.setItem('voltpath_admin_token', token);
    afterLogin();
  } catch (err) {
    errorEl.textContent = err.message;
  }
});

document.getElementById('logout-btn').addEventListener('click', () => {
  state.token = null;
  state.user = null;
  localStorage.removeItem('voltpath_admin_token');
  showAuthScreen();
});

// ---------------------------------------------------------------------------
// Navigation
// ---------------------------------------------------------------------------
const VIEW_TITLES = { operators: 'Operators', stats: 'Platform stats' };

function goToView(name) {
  document.querySelectorAll('.admin-view').forEach(v => v.classList.remove('active'));
  document.getElementById('admin-view-' + name).classList.add('active');
  document.querySelectorAll('.admin-nav-item[data-view]').forEach(n => n.classList.toggle('on', n.dataset.view === name));
  document.getElementById('admin-page-title').textContent = VIEW_TITLES[name];

  if (name === 'operators') loadOperators();
  if (name === 'stats') loadStats();
}
document.querySelectorAll('.admin-nav-item[data-view]').forEach(el => {
  el.addEventListener('click', () => goToView(el.dataset.view));
});

// ---------------------------------------------------------------------------
// Operators
// ---------------------------------------------------------------------------
async function loadOperators() {
  try {
    state.operators = await api('/admin/operators');
  } catch (err) {
    toast('Could not load operators: ' + err.message, 'error');
    return;
  }
  renderOperatorsTable();
}

function renderOperatorsTable() {
  const tbody = document.getElementById('operators-table-body');
  if (!state.operators.length) {
    tbody.innerHTML = '<tr><td colspan="6">No operators yet.</td></tr>';
    return;
  }
  tbody.innerHTML = state.operators.map(op => `
    <tr>
      <td>${op.company_name}</td>
      <td><span class="pill"><span class="dot ${op.status === 'active' ? 'live' : 'dead'}"></span>${op.status}</span></td>
      <td>${op.station_count}</td>
      <td>${op.admin_count}</td>
      <td>${new Date(op.created_at).toLocaleDateString()}</td>
      <td>
        <button class="btn btn-ghost" style="padding:6px 14px; font-size:12px;" data-toggle-operator="${op.id}" data-current-status="${op.status}">
          ${op.status === 'active' ? 'Suspend' : 'Reactivate'}
        </button>
      </td>
    </tr>
  `).join('');

  tbody.querySelectorAll('[data-toggle-operator]').forEach(btn => {
    btn.addEventListener('click', async () => {
      const newStatus = btn.dataset.currentStatus === 'active' ? 'suspended' : 'active';
      try {
        await api(`/admin/operators/${btn.dataset.toggleOperator}`, { method: 'PATCH', body: { status: newStatus } });
        toast(`Operator ${newStatus === 'suspended' ? 'suspended' : 'reactivated'}.`, 'success');
        loadOperators();
      } catch (err) {
        toast('Could not update operator: ' + err.message, 'error');
      }
    });
  });
}

// ---------------------------------------------------------------------------
// Platform stats
// ---------------------------------------------------------------------------
async function loadStats() {
  let stats;
  try {
    stats = await api('/admin/stats');
  } catch (err) {
    toast('Could not load stats: ' + err.message, 'error');
    return;
  }
  document.getElementById('platform-stats').innerHTML = `
    <div class="card"><div class="v">${stats.operators_total}</div><div class="l">Operators</div></div>
    <div class="card"><div class="v">${stats.stations_total}</div><div class="l">Stations</div></div>
    <div class="card"><div class="v">${stats.drivers_total}</div><div class="l">Drivers</div></div>
    <div class="card"><div class="v">${stats.sessions_total}</div><div class="l">Sessions (all-time)</div></div>
    <div class="card"><div class="v">₹${stats.revenue_total.toFixed(2)}</div><div class="l">Revenue (all-time)</div></div>
    <div class="card"><div class="v">${stats.open_tickets}</div><div class="l">Open tickets</div></div>
  `;
}

// ---------------------------------------------------------------------------
// Boot
// ---------------------------------------------------------------------------
tryResumeSession();
