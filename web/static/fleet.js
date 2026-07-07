// VoltPath fleet manager dashboard — vanilla JS, no build step. A fourth
// distinct audience on the same backend: a company that owns EV vehicles
// and employs drivers, separate from charging-network operators and the
// platform admin.

const API_BASE = '/v1';

const state = {
  token: localStorage.getItem('voltpath_fleet_token') || null,
  user: null,
  roster: [],
  vehicles: [],
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

function showFleetApp() {
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
    localStorage.removeItem('voltpath_fleet_token');
    showAuthScreen();
  }
}

function afterLogin() {
  if (state.user.role !== 'fleet_manager') {
    toast('This login is not a fleet manager account.', 'error');
    document.getElementById('login-error').textContent = 'This account is not a fleet manager — use the driver app instead.';
    return;
  }
  showFleetApp();
  goToView('roster');
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
    localStorage.setItem('voltpath_fleet_token', token);
    afterLogin();
  } catch (err) {
    errorEl.textContent = err.message;
  }
});

document.getElementById('register-form').addEventListener('submit', async (e) => {
  e.preventDefault();
  const company_name = document.getElementById('register-company').value;
  const manager_name = document.getElementById('register-name').value;
  const email = document.getElementById('register-email').value;
  const password = document.getElementById('register-password').value;
  const errorEl = document.getElementById('register-error');
  errorEl.textContent = '';
  try {
    const { token, user } = await api('/auth/register-fleet', { method: 'POST', body: { company_name, manager_name, email, password } });
    state.token = token;
    state.user = user;
    localStorage.setItem('voltpath_fleet_token', token);
    afterLogin();
  } catch (err) {
    errorEl.textContent = err.message;
  }
});

document.getElementById('switch-to-register').querySelector('a').addEventListener('click', () => {
  document.getElementById('login-form').classList.add('hidden');
  document.getElementById('register-form').classList.remove('hidden');
  document.getElementById('switch-to-register').classList.add('hidden');
  document.getElementById('switch-to-login').classList.remove('hidden');
});
document.getElementById('switch-to-login').querySelector('a').addEventListener('click', () => {
  document.getElementById('register-form').classList.add('hidden');
  document.getElementById('login-form').classList.remove('hidden');
  document.getElementById('switch-to-login').classList.add('hidden');
  document.getElementById('switch-to-register').classList.remove('hidden');
});

document.getElementById('logout-btn').addEventListener('click', () => {
  state.token = null;
  state.user = null;
  localStorage.removeItem('voltpath_fleet_token');
  showAuthScreen();
});

// ---------------------------------------------------------------------------
// Navigation
// ---------------------------------------------------------------------------
const VIEW_TITLES = { roster: 'Roster', vehicles: 'Vehicles', 'cost-report': 'Cost report' };

function goToView(name) {
  document.querySelectorAll('.admin-view').forEach(v => v.classList.remove('active'));
  document.getElementById('admin-view-' + name).classList.add('active');
  document.querySelectorAll('.admin-nav-item[data-view]').forEach(n => n.classList.toggle('on', n.dataset.view === name));
  document.getElementById('admin-page-title').textContent = VIEW_TITLES[name];

  if (name === 'roster') loadRoster();
  if (name === 'vehicles') loadVehicles();
  if (name === 'cost-report') loadCostReport();
}
document.querySelectorAll('.admin-nav-item[data-view]').forEach(el => {
  el.addEventListener('click', () => goToView(el.dataset.view));
});

// ---------------------------------------------------------------------------
// Roster
// ---------------------------------------------------------------------------
async function loadRoster() {
  try {
    state.roster = await api('/fleet/roster');
    state.vehicles = await api('/fleet/vehicles');
  } catch (err) {
    toast('Could not load roster: ' + err.message, 'error');
    return;
  }
  renderRoster();
}

const STATUS_DOT = { charging: 'warn', idle: 'live', needs_attention: 'dead' };

function renderRoster() {
  const el = document.getElementById('roster-list');
  if (!state.roster.length) {
    el.innerHTML = '<div class="empty-state">No drivers yet — add one above.</div>';
    return;
  }
  el.innerHTML = state.roster.map(d => `
    <div class="card" style="margin-bottom:12px;">
      <div style="display:flex; justify-content:space-between; align-items:flex-start;">
        <div>
          <div style="font-weight:700; font-size:15px;">${d.driver_name}</div>
          <div class="eyebrow" style="margin-top:2px;">${d.email}</div>
        </div>
        <span class="pill"><span class="dot ${STATUS_DOT[d.status]}"></span>${d.status.replace('_', ' ')}</span>
      </div>
      <div style="margin-top:12px; display:flex; gap:10px; align-items:center; flex-wrap:wrap;">
        <span style="color:var(--muted); font-size:13px;">${d.vehicle ? `${d.vehicle.make} ${d.vehicle.model} · cap ${d.vehicle.charge_cap_pct}%` : 'No vehicle assigned'}</span>
        <select data-assign-driver="${d.user_id}" style="background:var(--bg-raise); border:1px solid var(--line); border-radius:var(--radius-element); padding:6px 10px; color:var(--text); font-size:12px;">
          <option value="">Unassigned</option>
          ${state.vehicles.map(v => `<option value="${v.id}" ${d.vehicle && d.vehicle.id === v.id ? 'selected' : ''}>${v.make} ${v.model}</option>`).join('')}
        </select>
      </div>
    </div>
  `).join('');

  el.querySelectorAll('[data-assign-driver]').forEach(select => {
    select.addEventListener('change', async () => {
      try {
        await api(`/fleet/drivers/${select.dataset.assignDriver}/assign-vehicle`, { method: 'POST', body: { vehicle_id: select.value || null } });
        toast('Vehicle assignment updated.', 'success');
        loadRoster();
      } catch (err) {
        toast('Could not assign vehicle: ' + err.message, 'error');
      }
    });
  });
}

document.getElementById('add-driver-btn').addEventListener('click', async () => {
  const name = document.getElementById('new-driver-name').value.trim();
  const email = document.getElementById('new-driver-email').value.trim();
  const password = document.getElementById('new-driver-password').value;
  if (!name || !email || password.length < 6) {
    toast('Fill in name, email, and a password (6+ characters).', 'error');
    return;
  }
  try {
    await api('/fleet/drivers', { method: 'POST', body: { name, email, password } });
    document.getElementById('new-driver-name').value = '';
    document.getElementById('new-driver-email').value = '';
    document.getElementById('new-driver-password').value = '';
    toast('Driver added.', 'success');
    loadRoster();
  } catch (err) {
    toast('Could not add driver: ' + err.message, 'error');
  }
});

// ---------------------------------------------------------------------------
// Vehicles
// ---------------------------------------------------------------------------
async function loadVehicles() {
  try {
    state.vehicles = await api('/fleet/vehicles');
  } catch (err) {
    toast('Could not load vehicles: ' + err.message, 'error');
    return;
  }
  const tbody = document.getElementById('vehicles-table-body');
  if (!state.vehicles.length) {
    tbody.innerHTML = '<tr><td colspan="4">No vehicles yet — add one above.</td></tr>';
    return;
  }
  tbody.innerHTML = state.vehicles.map(v => `
    <tr>
      <td>${v.make} ${v.model}</td>
      <td>${v.connector_type}</td>
      <td>${v.battery_capacity_kwh} kWh</td>
      <td><input type="number" min="1" max="100" value="${v.charge_cap_pct}" data-policy-vehicle="${v.id}" style="width:70px; background:var(--bg-raise); border:1px solid var(--line); border-radius:var(--radius-element); padding:6px 8px; color:var(--text);">%</td>
    </tr>
  `).join('');

  tbody.querySelectorAll('[data-policy-vehicle]').forEach(input => {
    input.addEventListener('change', async () => {
      try {
        await api(`/fleet/vehicles/${input.dataset.policyVehicle}/policy`, { method: 'PATCH', body: { charge_cap_pct: parseInt(input.value, 10) } });
        toast('Charge cap updated.', 'success');
      } catch (err) {
        toast('Could not update charge cap: ' + err.message, 'error');
      }
    });
  });
}

document.getElementById('add-vehicle-btn').addEventListener('click', async () => {
  const make = document.getElementById('new-vehicle-make').value.trim();
  const model = document.getElementById('new-vehicle-model').value.trim();
  const connector_type = document.getElementById('new-vehicle-connector').value;
  const battery_capacity_kwh = parseFloat(document.getElementById('new-vehicle-battery').value);
  if (!make || !model || Number.isNaN(battery_capacity_kwh)) {
    toast('Fill in make, model, and battery capacity.', 'error');
    return;
  }
  try {
    await api('/fleet/vehicles', { method: 'POST', body: { make, model, connector_type, battery_capacity_kwh } });
    document.getElementById('new-vehicle-make').value = '';
    document.getElementById('new-vehicle-model').value = '';
    document.getElementById('new-vehicle-battery').value = '';
    toast('Vehicle added.', 'success');
    loadVehicles();
  } catch (err) {
    toast('Could not add vehicle: ' + err.message, 'error');
  }
});

// ---------------------------------------------------------------------------
// Cost report
// ---------------------------------------------------------------------------
async function loadCostReport() {
  let rows;
  try {
    rows = await api('/fleet/cost-report');
  } catch (err) {
    toast('Could not load cost report: ' + err.message, 'error');
    return;
  }
  const tbody = document.getElementById('cost-report-table-body');
  if (!rows.length) {
    tbody.innerHTML = '<tr><td colspan="5">No drivers yet.</td></tr>';
    return;
  }
  tbody.innerHTML = rows.map(r => `
    <tr>
      <td>${r.driver_name}</td>
      <td>${r.email}</td>
      <td>${r.sessions}</td>
      <td>${r.energy_kwh.toFixed(2)} kWh</td>
      <td style="text-align:right; font-family:var(--mono); font-weight:700;">₹${r.cost.toFixed(2)}</td>
    </tr>
  `).join('');
}

document.getElementById('export-csv-btn').addEventListener('click', () => {
  const url = new URL('/v1/fleet/cost-report', location.origin);
  url.searchParams.set('format', 'csv');
  fetch(url, { headers: { Authorization: 'Bearer ' + state.token } })
    .then(res => res.blob())
    .then(blob => {
      const link = document.createElement('a');
      link.href = URL.createObjectURL(blob);
      link.download = 'fleet-cost-report.csv';
      link.click();
    })
    .catch(err => toast('Could not export CSV: ' + err.message, 'error'));
});

// ---------------------------------------------------------------------------
// Boot
// ---------------------------------------------------------------------------
tryResumeSession();
