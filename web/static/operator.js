// VoltPath operator dashboard — vanilla JS, no build step. Talks to the same
// FastAPI backend as the driver app (web/static/app.js), but as a separate
// page since the audience/UI shape is completely different (tables and
// forms for a station_admin, not a map for a driver).

const API_BASE = '/v1';

const state = {
  token: localStorage.getItem('voltpath_operator_token') || null,
  user: null,
  stations: [],
  tickets: [],
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
    localStorage.removeItem('voltpath_operator_token');
    showAuthScreen();
  }
}

function afterLogin() {
  if (state.user.role !== 'station_admin' && state.user.role !== 'super_admin') {
    toast('This login is not a station operator account.', 'error');
    document.getElementById('login-error').textContent = 'This account is not a station operator — use the driver app instead.';
    return;
  }
  document.getElementById('operator-name').textContent = state.user.name;
  showAdminApp();
  goToView('stations');
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
    localStorage.setItem('voltpath_operator_token', token);
    afterLogin();
  } catch (err) {
    errorEl.textContent = err.message;
  }
});

document.getElementById('logout-btn').addEventListener('click', () => {
  state.token = null;
  state.user = null;
  localStorage.removeItem('voltpath_operator_token');
  showAuthScreen();
});

// ---------------------------------------------------------------------------
// Navigation
// ---------------------------------------------------------------------------
const VIEW_TITLES = { stations: 'Stations', pricing: 'Pricing', analytics: 'Analytics', tickets: 'Maintenance tickets' };

function goToView(name) {
  document.querySelectorAll('.admin-view').forEach(v => v.classList.remove('active'));
  document.getElementById('admin-view-' + name).classList.add('active');
  document.querySelectorAll('.admin-nav-item[data-view]').forEach(n => n.classList.toggle('on', n.dataset.view === name));
  document.getElementById('admin-page-title').textContent = VIEW_TITLES[name];

  if (name === 'stations') loadStations();
  if (name === 'pricing') loadStations();
  if (name === 'analytics') loadStationsForAnalytics();
  if (name === 'tickets') loadTickets();
}
document.querySelectorAll('.admin-nav-item[data-view]').forEach(el => {
  el.addEventListener('click', () => goToView(el.dataset.view));
});

// ---------------------------------------------------------------------------
// Stations & connectors
// ---------------------------------------------------------------------------
async function loadStations() {
  try {
    state.stations = await api('/operator/stations');
  } catch (err) {
    toast('Could not load stations: ' + err.message, 'error');
    return;
  }
  renderStationsList();
  renderTariffCurrent();
}

function renderStationsList() {
  const container = document.getElementById('stations-list');
  if (!state.stations.length) {
    container.innerHTML = '<div class="empty-state">No stations yet — add your first one above.</div>';
    return;
  }

  container.innerHTML = state.stations.map(s => `
    <div class="card" style="margin-bottom:16px;">
      <div style="display:flex; justify-content:space-between; align-items:flex-start;">
        <div>
          <div class="eyebrow">${s.address}</div>
          <div style="font-weight:700; font-size:16px;">${s.name}</div>
        </div>
        <span class="pill"><span class="dot ${s.status === 'online' ? 'live' : 'dead'}"></span>${s.status}</span>
      </div>
      <table class="data-table" style="margin-top:14px;">
        <thead><tr><th>Type</th><th>Power</th><th>Status</th><th>Reliability</th><th></th></tr></thead>
        <tbody>
          ${s.connectors.map(c => `
            <tr>
              <td>${c.type}</td>
              <td>${c.power_kw} kW</td>
              <td>
                <select data-connector-status="${c.id}">
                  <option value="available" ${c.status === 'available' ? 'selected' : ''}>available</option>
                  <option value="maintenance" ${c.status === 'maintenance' ? 'selected' : ''}>maintenance</option>
                  <option value="occupied" disabled ${c.status === 'occupied' ? 'selected' : ''}>occupied</option>
                  <option value="faulted" disabled ${c.status === 'faulted' ? 'selected' : ''}>faulted</option>
                </select>
              </td>
              <td>${c.reliability_score}${c.guaranteed ? ' · Guaranteed' : ''}</td>
              <td></td>
            </tr>
          `).join('')}
        </tbody>
      </table>
      <div class="form-row" style="margin-top:14px; margin-bottom:0;">
        <div class="field"><label>Connector type</label>
          <select data-new-connector-type="${s.id}">
            <option>CCS2</option><option>CHAdeMO</option><option>TYPE2</option><option>NACS</option>
          </select>
        </div>
        <div class="field"><label>Power (kW)</label><input data-new-connector-power="${s.id}" type="number" placeholder="150" style="width:100px;"></div>
        <button class="btn btn-ghost" data-add-connector="${s.id}">Add connector</button>
      </div>
    </div>
  `).join('');

  container.querySelectorAll('[data-connector-status]').forEach(select => {
    select.addEventListener('change', () => updateConnectorStatus(select.dataset.connectorStatus, select.value));
  });
  container.querySelectorAll('[data-add-connector]').forEach(btn => {
    btn.addEventListener('click', () => addConnector(btn.dataset.addConnector));
  });
}

async function addStation() {
  const name = document.getElementById('new-station-name').value.trim();
  const address = document.getElementById('new-station-address').value.trim();
  const lat = parseFloat(document.getElementById('new-station-lat').value);
  const lng = parseFloat(document.getElementById('new-station-lng').value);
  if (!name || !address || Number.isNaN(lat) || Number.isNaN(lng)) {
    toast('Fill in name, address, lat, and lng.', 'error');
    return;
  }
  try {
    await api('/operator/stations', { method: 'POST', body: { name, address, lat, lng } });
    document.getElementById('new-station-name').value = '';
    document.getElementById('new-station-address').value = '';
    document.getElementById('new-station-lat').value = '';
    document.getElementById('new-station-lng').value = '';
    toast('Station added.', 'success');
    loadStations();
  } catch (err) {
    toast('Could not add station: ' + err.message, 'error');
  }
}
document.getElementById('add-station-btn').addEventListener('click', addStation);

async function addConnector(stationId) {
  const type = document.querySelector(`[data-new-connector-type="${stationId}"]`).value;
  const power = parseFloat(document.querySelector(`[data-new-connector-power="${stationId}"]`).value);
  if (Number.isNaN(power) || power <= 0) {
    toast('Enter a valid power rating.', 'error');
    return;
  }
  try {
    await api(`/operator/stations/${stationId}/connectors`, { method: 'POST', body: { type, power_kw: power } });
    toast('Connector added.', 'success');
    loadStations();
  } catch (err) {
    toast('Could not add connector: ' + err.message, 'error');
  }
}

async function updateConnectorStatus(connectorId, status) {
  try {
    await api(`/operator/connectors/${connectorId}`, { method: 'PATCH', body: { status } });
    toast('Connector updated.', 'success');
  } catch (err) {
    toast('Could not update connector: ' + err.message, 'error');
    loadStations();
  }
}

// ---------------------------------------------------------------------------
// Pricing
// ---------------------------------------------------------------------------
function renderTariffCurrent() {
  const el = document.getElementById('tariff-current');
  if (!state.stations.length) { el.textContent = ''; return; }
}

document.getElementById('set-tariff-btn').addEventListener('click', async () => {
  if (!state.stations.length) { toast('Add a station first.', 'error'); return; }
  const pricing_model = document.getElementById('tariff-model').value;
  const rate = parseFloat(document.getElementById('tariff-rate').value);
  if (Number.isNaN(rate) || rate <= 0) { toast('Enter a valid rate.', 'error'); return; }
  try {
    // Path takes a station id purely to authorize the caller owns a station in
    // this operator account — the tariff itself applies operator-wide.
    await api(`/operator/stations/${state.stations[0].id}/tariffs`, { method: 'PUT', body: { pricing_model, rate } });
    document.getElementById('tariff-current').textContent = `Current: ${pricing_model.replace('_', ' ')} at $${rate.toFixed(2)}`;
    toast('Pricing updated.', 'success');
  } catch (err) {
    toast('Could not update pricing: ' + err.message, 'error');
  }
});

// ---------------------------------------------------------------------------
// Analytics
// ---------------------------------------------------------------------------
async function loadStationsForAnalytics() {
  if (!state.stations.length) await loadStations();
  const select = document.getElementById('analytics-station-select');
  select.innerHTML = state.stations.map(s => `<option value="${s.id}">${s.name}</option>`).join('');
  if (state.stations.length) loadAnalytics(state.stations[0].id);
}
document.getElementById('analytics-station-select').addEventListener('change', (e) => loadAnalytics(e.target.value));

async function loadAnalytics(stationId) {
  let data;
  try {
    data = await api(`/operator/stations/${stationId}/analytics`);
  } catch (err) {
    toast('Could not load analytics: ' + err.message, 'error');
    return;
  }

  document.getElementById('analytics-stats').innerHTML = `
    <div class="card"><div class="v">$${data.revenue_total.toFixed(2)}</div><div class="l">Revenue</div></div>
    <div class="card"><div class="v">${data.sessions_count}</div><div class="l">Sessions</div></div>
    <div class="card"><div class="v">${data.utilization_pct}%</div><div class="l">Utilization</div></div>
  `;

  const maxRevenue = Math.max(1, ...data.by_connector.map(c => c.revenue));
  document.getElementById('analytics-bars').innerHTML = data.by_connector.length
    ? data.by_connector.map(c => `
        <div class="bar-row">
          <div class="label">${c.connector_id.slice(0, 8)}</div>
          <div class="bar-track"><div class="bar-fill" style="width:${(c.revenue / maxRevenue) * 100}%"></div></div>
          <div class="amt">$${c.revenue.toFixed(2)}</div>
        </div>
      `).join('')
    : '<div class="empty-state">No sessions yet on this station.</div>';
}

// ---------------------------------------------------------------------------
// Maintenance tickets
// ---------------------------------------------------------------------------
async function loadTickets() {
  try {
    state.tickets = await api('/operator/tickets');
  } catch (err) {
    toast('Could not load tickets: ' + err.message, 'error');
    return;
  }
  const openCount = state.tickets.filter(t => t.status === 'open').length;
  document.getElementById('ticket-count').textContent = openCount ? openCount : '';
  renderTickets();
}

function renderTickets() {
  const container = document.getElementById('tickets-list');
  if (!state.tickets.length) {
    container.innerHTML = '<div class="empty-state">No maintenance tickets.</div>';
    return;
  }
  container.innerHTML = `
    <table class="data-table">
      <thead><tr><th>Issue</th><th>Status</th><th>Opened</th><th>Update</th></tr></thead>
      <tbody>
        ${state.tickets.map(t => `
          <tr>
            <td>${t.issue}${t.issue.startsWith('Auto-opened') ? '<span class="ticket-auto-tag">🚩 Plug Watch</span>' : ''}</td>
            <td><span class="ticket-status ${t.status}">${t.status.replace('_', ' ')}</span></td>
            <td>${new Date(t.created_at).toLocaleDateString()}</td>
            <td>
              <select data-ticket-status="${t.id}">
                <option value="open" ${t.status === 'open' ? 'selected' : ''}>open</option>
                <option value="in_progress" ${t.status === 'in_progress' ? 'selected' : ''}>in progress</option>
                <option value="resolved" ${t.status === 'resolved' ? 'selected' : ''}>resolved</option>
                <option value="closed" ${t.status === 'closed' ? 'selected' : ''}>closed</option>
              </select>
            </td>
          </tr>
        `).join('')}
      </tbody>
    </table>
  `;
  container.querySelectorAll('[data-ticket-status]').forEach(select => {
    select.addEventListener('change', () => updateTicket(select.dataset.ticketStatus, select.value));
  });
}

async function updateTicket(ticketId, status) {
  try {
    await api(`/operator/tickets/${ticketId}`, { method: 'PATCH', body: { status } });
    toast('Ticket updated.', 'success');
    loadTickets();
  } catch (err) {
    toast('Could not update ticket: ' + err.message, 'error');
  }
}

// ---------------------------------------------------------------------------
// Boot
// ---------------------------------------------------------------------------
tryResumeSession();
