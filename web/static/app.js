// VoltPath driver web app — vanilla JS, no build step.
// Talks to the FastAPI backend at /v1. Same REST/WebSocket contract a
// Next.js production frontend would use, per docs/api-spec.yaml.

const API_BASE = '/v1';

// Coimbatore demo point — matches the seeded Gandhipuram/RS Puram stations
// so "nearby search" returns real results without needing geolocation
// permission in a sandboxed preview. Real geolocation is tried first anyway.
// The San Francisco demo stations (Downtown Transit Plaza, Riverside
// Shopping Center, Harborview Garage) still exist in the seed data — they're
// just too far from this origin to show up within the 100km slider max.
const DEMO_ORIGIN = { lat: 11.0168, lng: 76.9558 };

const state = {
  token: localStorage.getItem('voltpath_token') || null,
  user: null,
  origin: DEMO_ORIGIN,
  stations: [],
  selectedStationId: null,
  selectedStationDetail: null,
  selectedConnectorId: null,
  vehicles: [],
  connectorFilter: '',
  availableOnlyFilter: false,
  radiusKm: 25,
  session: null,
  ws: null,
  idempotencyKeyByConnector: {},
};

// ---------------------------------------------------------------------------
// API helper
// ---------------------------------------------------------------------------
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

function uuidv4() {
  if (window.crypto && window.crypto.randomUUID) return window.crypto.randomUUID();
  return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, (c) => {
    const r = (Math.random() * 16) | 0;
    return (c === 'x' ? r : (r & 0x3) | 0x8).toString(16);
  });
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
  document.getElementById('main-app').classList.add('hidden');
}

function showMainApp() {
  document.getElementById('auth-screen').classList.add('hidden');
  document.getElementById('main-app').classList.remove('hidden');
}

async function tryResumeSession() {
  if (!state.token) return showAuthScreen();
  try {
    state.user = await api('/users/me');
    afterLogin();
  } catch (_) {
    state.token = null;
    localStorage.removeItem('voltpath_token');
    showAuthScreen();
  }
}

function afterLogin() {
  document.getElementById('avatar').textContent = state.user.name.split(' ').map(p => p[0]).join('').slice(0, 2).toUpperCase();
  showMainApp();
  initMapView();
  refreshWalletPill();
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
    localStorage.setItem('voltpath_token', token);
    afterLogin();
  } catch (err) {
    errorEl.textContent = err.message;
  }
});

document.getElementById('register-form').addEventListener('submit', async (e) => {
  e.preventDefault();
  const name = document.getElementById('register-name').value;
  const email = document.getElementById('register-email').value;
  const password = document.getElementById('register-password').value;
  const errorEl = document.getElementById('register-error');
  errorEl.textContent = '';
  try {
    const { token, user } = await api('/auth/register', { method: 'POST', body: { name, email, password } });
    state.token = token;
    state.user = user;
    localStorage.setItem('voltpath_token', token);
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
  localStorage.removeItem('voltpath_token');
  if (state.ws) state.ws.close();
  showAuthScreen();
});

// ---------------------------------------------------------------------------
// Navigation
// ---------------------------------------------------------------------------
function goTo(name) {
  document.querySelectorAll('.view').forEach(v => v.classList.remove('active'));
  document.getElementById('view-' + name).classList.add('active');
  document.querySelectorAll('.tab').forEach(t => t.classList.toggle('on', t.dataset.nav === name));
  document.querySelectorAll('.navlink').forEach(n => n.classList.toggle('on', n.dataset.nav === name));

  if (name === 'map') loadStations();   // re-fetch so occupied/available reflects any session started elsewhere
  if (name === 'history') loadHistory();
  if (name === 'account') { loadWallet(); loadVehicleList(); loadPaymentMethodList(); loadReservationList(); }
}
document.querySelectorAll('[data-nav]').forEach(el => {
  el.addEventListener('click', () => goTo(el.dataset.nav));
});

// ---------------------------------------------------------------------------
// Map / station search
// ---------------------------------------------------------------------------
function trustBadgeHtml(connector) {
  if (connector.guaranteed) return `<span class="pill badge-guaranteed"><span class="dot live"></span>Guaranteed · ${connector.reliability_score}</span>`;
  if (connector.reliability_score >= 75) return `<span class="pill badge-good"><span class="dot warn"></span>Good · ${connector.reliability_score}</span>`;
  return `<span class="pill badge-low"><span class="dot dead"></span>Low trust · ${connector.reliability_score}</span>`;
}

function statusDotClass(status) {
  if (status === 'available') return 'live';
  if (status === 'occupied' || status === 'reserved') return 'warn';
  return 'dead';
}

// Drivers never need to know *why* a connector is down (an auto-detected
// fault vs. the operator's own planned toggle) — both read the same, calm
// label. The operator dashboard shows the real distinction instead.
function statusLabel(status) {
  if (status === 'faulted' || status === 'maintenance') return 'Under maintenance';
  return status.charAt(0).toUpperCase() + status.slice(1);
}

// Map pin color, in priority order: a real trust problem matters more than
// momentary occupancy, so low reliability wins even if a connector happens
// to be free right now. Otherwise: fully free / some free / fully occupied.
function pinClass(station) {
  if (station.reliability_score < 60) return 'fault';
  if (station.connectors_available === 0) return 'full';
  if (station.connectors_available < station.connectors_total) return 'partial';
  return 'avail';
}

function initMapView() {
  // Deliberately not using navigator.geolocation: it triggers a native
  // permission prompt, and the seeded demo stations only exist around
  // DEMO_ORIGIN anyway — a real deployment would use the device's actual
  // location instead of a fixed point.
  loadStations();
}

async function loadStations() {
  const params = new URLSearchParams({
    lat: state.origin.lat, lng: state.origin.lng, radius_km: state.radiusKm,
  });
  if (state.connectorFilter) params.set('connector_type', state.connectorFilter);
  if (state.availableOnlyFilter) params.set('available_only', 'true');

  try {
    state.stations = await api('/stations/search?' + params.toString());
  } catch (err) {
    toast('Could not load stations: ' + err.message, 'error');
    return;
  }
  renderStationList();
  renderMapPins();
  if (state.stations.length && !state.selectedStationId) {
    selectStation(state.stations[0].id);
  } else if (state.selectedStationId) {
    // Refresh the already-open sheet too — otherwise its connector
    // statuses (available/occupied) go stale even though the list/pins
    // just updated.
    selectStation(state.selectedStationId);
  }
}

function renderStationList() {
  const list = document.getElementById('station-list-scroll');
  if (!state.stations.length) {
    list.innerHTML = '<div class="empty-state">No stations match these filters nearby.</div>';
    return;
  }
  list.innerHTML = state.stations.map(s => `
    <div class="slist-row ${s.id === state.selectedStationId ? 'sel' : ''}" data-station="${s.id}">
      <div class="thumb">⚡</div>
      <div class="meta">
        <div class="name">${s.name}</div>
        <div class="sub">${s.distance_km} km · ${s.reliability_score}% reliable · ${s.connectors_available}/${s.connectors_total} free</div>
      </div>
      <div class="price">₹${(s.min_price_per_kwh ?? 0).toFixed(2)}</div>
    </div>
  `).join('');
  list.querySelectorAll('[data-station]').forEach(el => {
    el.addEventListener('click', () => selectStation(el.dataset.station));
  });
}

function renderMapPins() {
  const canvas = document.getElementById('map-canvas');
  canvas.querySelectorAll('.pin').forEach(p => p.remove());

  const w = canvas.clientWidth || 400;
  const h = canvas.clientHeight || 400;
  const scale = 4000; // pixels per degree, purely schematic — not a real map projection

  state.stations.forEach(s => {
    const dx = (s.lng - state.origin.lng) * scale;
    const dy = -(s.lat - state.origin.lat) * scale;
    const x = Math.max(20, Math.min(w - 20, w / 2 + dx));
    const y = Math.max(20, Math.min(h - 20, h / 2 + dy));

    const cls = pinClass(s);
    const pin = document.createElement('div');
    pin.className = `pin ${cls} ${s.id === state.selectedStationId ? 'sel' : ''}`;
    pin.style.top = y + 'px';
    pin.style.left = x + 'px';
    pin.innerHTML = `<span>₹${(s.min_price_per_kwh ?? 0).toFixed(0)}</span>`;
    pin.addEventListener('click', () => selectStation(s.id));
    canvas.appendChild(pin);
  });
}

// Filters are duplicated (desktop station-list-col + mobile overlay), so
// "on" state syncs by value across both copies, not just the clicked element.
document.querySelectorAll('[data-filter-connector]').forEach(chip => {
  chip.addEventListener('click', () => {
    state.connectorFilter = chip.dataset.filterConnector;
    document.querySelectorAll('[data-filter-connector]').forEach(c => {
      c.classList.toggle('on', c.dataset.filterConnector === state.connectorFilter);
    });
    loadStations();
  });
});
document.querySelectorAll('[data-filter-available]').forEach(chip => {
  chip.addEventListener('click', () => {
    state.availableOnlyFilter = !state.availableOnlyFilter;
    document.querySelectorAll('[data-filter-available]').forEach(c => c.classList.toggle('on', state.availableOnlyFilter));
    loadStations();
  });
});

// Radius slider is also duplicated (desktop + mobile) — keep both in sync.
let radiusDebounceTimer = null;
document.querySelectorAll('[data-radius-slider]').forEach(slider => {
  slider.addEventListener('input', () => {
    state.radiusKm = Number(slider.value);
    document.querySelectorAll('[data-radius-slider]').forEach(s => { s.value = state.radiusKm; });
    document.querySelectorAll('[data-radius-value]').forEach(el => { el.textContent = state.radiusKm; });
    clearTimeout(radiusDebounceTimer);
    radiusDebounceTimer = setTimeout(loadStations, 300);
  });
});

async function selectStation(stationId) {
  state.selectedStationId = stationId;
  document.querySelectorAll('.slist-row').forEach(r => r.classList.toggle('sel', r.dataset.station === stationId));
  document.querySelectorAll('.pin').forEach(p => p.classList.remove('sel'));
  renderMapPins();

  try {
    state.selectedStationDetail = await api('/stations/' + stationId);
  } catch (err) {
    toast('Could not load station: ' + err.message, 'error');
    return;
  }
  if (!state.vehicles.length) {
    try { state.vehicles = await api('/users/me/vehicles'); } catch (_) {}
  }
  renderStationSheet();
}

function renderStationSheet() {
  const d = state.selectedStationDetail;
  const content = document.getElementById('sheet-content');
  if (!d) { content.innerHTML = '<div class="empty-state">Pick a station to see details.</div>'; return; }

  if (!state.selectedConnectorId || !d.connectors.some(c => c.id === state.selectedConnectorId)) {
    const firstAvailable = d.connectors.find(c => c.status === 'available');
    state.selectedConnectorId = firstAvailable ? firstAvailable.id : d.connectors[0]?.id;
  }

  const connectorsHtml = d.connectors.map(c => `
    <div class="conn-row ${c.id === state.selectedConnectorId ? 'sel' : ''}" data-connector="${c.id}" style="cursor:pointer;">
      <div>
        <div class="conn-type">${c.type}</div>
        <div class="conn-kw">${c.power_kw} kW</div>
      </div>
      <div style="text-align:right;">
        <div class="pill"><span class="dot ${statusDotClass(c.status)}"></span>${statusLabel(c.status)}</div>
        <div style="margin-top:6px;">${trustBadgeHtml(c)}</div>
      </div>
    </div>
  `).join('');

  const selectedConnector = d.connectors.find(c => c.id === state.selectedConnectorId);
  const canStart = selectedConnector && selectedConnector.status === 'available' && state.vehicles.length > 0;
  const canReserve = selectedConnector && selectedConnector.status === 'available';

  content.innerHTML = `
    <div style="display:flex; justify-content:space-between; align-items:flex-start;">
      <div>
        <div class="eyebrow">${d.address}</div>
        <h1 class="title" style="font-size:20px;">${d.name}</h1>
      </div>
      <div class="pill"><span class="dot live"></span>${d.reliability_score}% avg</div>
    </div>

    <div class="stat-grid">
      <div class="stat-box"><div class="v">₹${(d.min_price_per_kwh ?? 0).toFixed(2)}</div><div class="l">per kWh</div></div>
      <div class="stat-box"><div class="v">${Math.max(...d.connectors.map(c => c.power_kw))}kW</div><div class="l">max speed</div></div>
      <div class="stat-box"><div class="v">${d.connectors_available}/${d.connectors_total}</div><div class="l">free now</div></div>
    </div>

    <div class="eyebrow" style="margin-top:6px;">Connectors — tap to select</div>
    ${connectorsHtml}

    <div style="margin-top:16px; display:flex; flex-direction:column; gap:10px;">
      <button class="btn btn-primary" id="start-charging-btn" ${canStart ? '' : 'disabled'}>
        ${state.vehicles.length === 0 ? 'No vehicle on file' : 'Start charging'}
      </button>
      <button class="btn btn-ghost" id="reserve-btn" ${canReserve ? '' : 'disabled'}>Reserve for 30 min</button>
      <button class="btn btn-ghost" id="report-issue-btn">🚩 Report an issue with this connector</button>
    </div>
  `;

  content.querySelectorAll('[data-connector]').forEach(el => {
    el.addEventListener('click', () => { state.selectedConnectorId = el.dataset.connector; renderStationSheet(); });
  });
  const startBtn = document.getElementById('start-charging-btn');
  if (startBtn) startBtn.addEventListener('click', () => startSession(state.selectedConnectorId));
  const reserveBtn = document.getElementById('reserve-btn');
  if (reserveBtn) reserveBtn.addEventListener('click', () => reserveConnector(state.selectedConnectorId));
  document.getElementById('report-issue-btn').addEventListener('click', () => openReportModal(state.selectedConnectorId));
}

async function reserveConnector(connectorId) {
  try {
    await api('/reservations', { method: 'POST', body: { connector_id: connectorId, hold_minutes: 30 } });
    toast('Reserved for 30 minutes.', 'success');
    if (state.selectedStationId) selectStation(state.selectedStationId);
  } catch (err) {
    toast('Could not reserve: ' + err.message, 'error');
  }
}

// ---------------------------------------------------------------------------
// Charging session
// ---------------------------------------------------------------------------
async function startSession(connectorId) {
  if (!state.vehicles.length) { toast('No vehicle on file for this account', 'error'); return; }
  const vehicleId = state.vehicles[0].id;

  if (!state.idempotencyKeyByConnector[connectorId]) {
    state.idempotencyKeyByConnector[connectorId] = uuidv4();
  }
  const idempotencyKey = state.idempotencyKeyByConnector[connectorId];

  try {
    const session = await api('/sessions', {
      method: 'POST',
      headers: { 'Idempotency-Key': idempotencyKey },
      body: { connector_id: connectorId, vehicle_id: vehicleId },
    });
    delete state.idempotencyKeyByConnector[connectorId];
    state.session = session;
    goTo('charging');
    renderChargingView();
    connectSessionSocket(session.id);
  } catch (err) {
    toast('Could not start session: ' + err.message, 'error');
  }
}

function connectSessionSocket(sessionId) {
  if (state.ws) state.ws.close();
  const proto = location.protocol === 'https:' ? 'wss' : 'ws';
  const ws = new WebSocket(`${proto}://${location.host}${API_BASE}/ws/sessions/${sessionId}?token=${state.token}`);
  state.ws = ws;

  ws.onmessage = (evt) => {
    const msg = JSON.parse(evt.data);
    if (msg.type === 'status') {
      state.session.status = msg.status;
    } else if (msg.type === 'meter_value') {
      state.session.energy_kwh = msg.energy_kwh;
      state.session.cost = msg.cost;
      state.session._tick = msg.tick;
      state.session._of = msg.of;
      state.session._power_kw = msg.power_kw;
    } else if (msg.type === 'final') {
      state.session.status = msg.status;
      state.session.energy_kwh = msg.energy_kwh;
      state.session.cost = msg.cost;
      state.session.fail_reason = msg.fail_reason;
      state.session.claim = msg.claim;
      if (msg.claim) {
        toast(`Guaranteed charge failed — ₹${msg.claim.credit_amount.toFixed(2)} credited automatically`, 'success');
        refreshWalletPill();
      }
    }
    renderChargingView();
  };
  ws.onerror = () => toast('Live telemetry connection lost', 'error');
}

function renderChargingView() {
  const s = state.session;
  const wrap = document.getElementById('charge-wrap');
  const subtitle = document.getElementById('charging-subtitle');

  if (!s) {
    subtitle.textContent = 'No active session';
    wrap.innerHTML = '<div class="empty-state" id="charging-empty">Start a session from the map to see it here.</div>';
    return;
  }

  const station = state.selectedStationDetail;
  subtitle.textContent = `${station ? station.name : 'Station'} · Connector`;

  const pct = s._of ? Math.round((s._tick / s._of) * 100) : (s.status === 'completed' || s.status === 'failed' || s.status === 'stopped_remotely' ? 100 : 0);
  const isDone = ['completed', 'failed', 'stopped_remotely'].includes(s.status);
  const ringColor = s.status === 'failed' ? 'var(--red)' : (isDone ? 'var(--lime)' : 'var(--amber)');
  const circumference = 628;
  const offset = Math.round(circumference * (1 - pct / 100));

  let banner = '';
  if (s.status === 'failed') {
    banner = `<div class="fail-banner"><div class="t">⚠ Station fault</div>${s.fail_reason || 'The connector faulted mid-session.'}${s.claim ? `<div style="margin-top:8px; color:var(--lime); font-weight:700;">✓ ₹${s.claim.credit_amount.toFixed(2)} guaranteed-charge credit issued automatically</div>` : ''}</div>`;
  } else if (s.status === 'completed') {
    banner = `<div class="claim-banner"><div class="t">✓ Session complete</div>Charged successfully. Payment captured.</div>`;
  } else if (s.status === 'stopped_remotely') {
    banner = `<div class="claim-banner"><div class="t">Session stopped</div>You ended this session early. Payment captured for energy delivered.</div>`;
  }

  wrap.innerHTML = `
    <div class="ring-wrap">
      <svg viewBox="0 0 230 230" width="230" height="230">
        <circle cx="115" cy="115" r="100" fill="none" stroke="#1B2530" stroke-width="14"/>
        <circle cx="115" cy="115" r="100" fill="none" stroke="${ringColor}" stroke-width="14"
          stroke-linecap="round" stroke-dasharray="${circumference}" stroke-dashoffset="${offset}"
          transform="rotate(-90 115 115)" style="transition: stroke-dashoffset 0.5s ease;"/>
      </svg>
      <div class="ring-center">
        <div class="ring-pct ${!isDone ? 'pulse' : ''}">${(s.energy_kwh ?? 0).toFixed(2)}<span>kWh</span></div>
        <div class="ring-label ${s.status === 'completed' ? 'ok' : ''} ${s.status === 'failed' ? 'bad' : ''}">● ${s.status.toUpperCase()}</div>
      </div>
    </div>

    <div class="charge-stats">
      <div class="card"><div class="v">${(s.energy_kwh ?? 0).toFixed(2)}</div><div class="l">kWh delivered</div></div>
      <div class="card"><div class="v">₹${(s.cost ?? 0).toFixed(2)}</div><div class="l">cost so far</div></div>
      <div class="card"><div class="v">${s._power_kw ?? '--'}</div><div class="l">kW rate</div></div>
    </div>

    ${banner}

    ${!isDone ? '<button class="btn btn-ghost" style="width:100%;" id="stop-charging-btn">Stop charging</button>' : '<button class="btn btn-primary" style="width:100%;" id="done-btn">Back to map</button>'}
  `;

  const stopBtn = document.getElementById('stop-charging-btn');
  if (stopBtn) stopBtn.addEventListener('click', stopSession);
  const doneBtn = document.getElementById('done-btn');
  if (doneBtn) doneBtn.addEventListener('click', () => { state.session = null; goTo('map'); loadStations(); });
}

async function stopSession() {
  if (!state.session) return;
  try {
    await api(`/sessions/${state.session.id}/stop`, { method: 'POST' });
  } catch (err) {
    toast('Could not stop session: ' + err.message, 'error');
  }
}

// ---------------------------------------------------------------------------
// History
// ---------------------------------------------------------------------------
async function loadHistory() {
  let sessions;
  try {
    sessions = await api('/users/me/sessions?limit=50');
  } catch (err) {
    toast('Could not load history: ' + err.message, 'error');
    return;
  }

  document.getElementById('history-subtitle').textContent = `${sessions.length} session${sessions.length === 1 ? '' : 's'}`;

  const rowsEl = document.getElementById('hist-rows');
  const tbodyEl = document.getElementById('hist-table-body');

  if (!sessions.length) {
    rowsEl.innerHTML = '<div class="empty-state">No charging sessions yet.</div>';
    tbodyEl.innerHTML = '';
    return;
  }

  rowsEl.innerHTML = sessions.map(s => `
    <div class="hist-row">
      <div>
        <div class="hist-date">${formatDate(s.start_time || s.end_time)}</div>
        <div class="hist-name">Connector ${s.connector_id.slice(0, 8)}</div>
        <div class="hist-status ${s.status}">${s.status}${s.claim_amount ? ` · ₹${s.claim_amount} credited` : ''}</div>
      </div>
      <div>
        <div class="hist-amt">₹${(s.cost ?? 0).toFixed(2)}</div>
        <div class="hist-kwh">${(s.energy_kwh ?? 0).toFixed(2)} kWh</div>
      </div>
    </div>
  `).join('');

  tbodyEl.innerHTML = sessions.map(s => `
    <tr>
      <td>${formatDate(s.start_time || s.end_time)}</td>
      <td>Connector ${s.connector_id.slice(0, 8)}</td>
      <td class="hist-status ${s.status}">${s.status}</td>
      <td>${(s.energy_kwh ?? 0).toFixed(2)} kWh</td>
      <td style="text-align:right; font-family:var(--mono); font-weight:700;">₹${(s.cost ?? 0).toFixed(2)}</td>
    </tr>
  `).join('');
}

function formatDate(iso) {
  if (!iso) return '--';
  const d = new Date(iso);
  return d.toLocaleDateString(undefined, { month: 'short', day: 'numeric' }) + ' · ' + d.toLocaleTimeString(undefined, { hour: 'numeric', minute: '2-digit' });
}

// ---------------------------------------------------------------------------
// Wallet
// ---------------------------------------------------------------------------
async function refreshWalletPill() {
  try {
    const wallet = await api('/users/me/credits');
    document.getElementById('wallet-pill-balance').textContent = `₹${wallet.balance.toFixed(2)}`;
  } catch (_) {}
}

async function loadWallet() {
  let wallet;
  try {
    wallet = await api('/users/me/credits');
  } catch (err) {
    toast('Could not load wallet: ' + err.message, 'error');
    return;
  }
  document.getElementById('wallet-balance').textContent = `₹${wallet.balance.toFixed(2)}`;
  document.getElementById('wallet-pill-balance').textContent = `₹${wallet.balance.toFixed(2)}`;

  const entriesEl = document.getElementById('wallet-entries');
  if (!wallet.entries.length) {
    entriesEl.innerHTML = '<div class="empty-state">No credits yet.</div>';
    return;
  }
  entriesEl.innerHTML = wallet.entries.map(e => `
    <div class="wallet-entry">
      <div><div class="reason">${e.reason}</div><div class="when">${formatDate(e.created_at)}</div></div>
      <div class="amt">+₹${e.amount.toFixed(2)}</div>
    </div>
  `).join('');
}

// ---------------------------------------------------------------------------
// Vehicles (Account view)
// ---------------------------------------------------------------------------
async function loadVehicleList() {
  try {
    state.vehicles = await api('/users/me/vehicles');
  } catch (err) {
    toast('Could not load vehicles: ' + err.message, 'error');
    return;
  }
  const el = document.getElementById('vehicle-list');
  if (!state.vehicles.length) {
    el.innerHTML = '<div class="empty-state">No vehicles yet — add one below.</div>';
    return;
  }
  el.innerHTML = state.vehicles.map(v => `
    <div class="wallet-entry">
      <div><div class="reason">${v.make} ${v.model}</div><div class="when">${v.connector_type} · ${v.battery_capacity_kwh} kWh</div></div>
      <button class="btn btn-ghost" style="padding:6px 14px; font-size:12px;" data-remove-vehicle="${v.id}">Remove</button>
    </div>
  `).join('');
  el.querySelectorAll('[data-remove-vehicle]').forEach(btn => {
    btn.addEventListener('click', async () => {
      try {
        await api(`/users/me/vehicles/${btn.dataset.removeVehicle}`, { method: 'DELETE' });
        loadVehicleList();
      } catch (err) {
        toast('Could not remove vehicle: ' + err.message, 'error');
      }
    });
  });
}

document.getElementById('add-vehicle-btn').addEventListener('click', async () => {
  const make = document.getElementById('vehicle-make').value.trim();
  const model = document.getElementById('vehicle-model').value.trim();
  const connector_type = document.getElementById('vehicle-connector').value;
  const battery_capacity_kwh = parseFloat(document.getElementById('vehicle-battery').value);
  if (!make || !model || Number.isNaN(battery_capacity_kwh)) {
    toast('Fill in make, model, and battery capacity.', 'error');
    return;
  }
  try {
    await api('/users/me/vehicles', { method: 'POST', body: { make, model, connector_type, battery_capacity_kwh } });
    document.getElementById('vehicle-make').value = '';
    document.getElementById('vehicle-model').value = '';
    document.getElementById('vehicle-battery').value = '';
    toast('Vehicle added.', 'success');
    loadVehicleList();
  } catch (err) {
    toast('Could not add vehicle: ' + err.message, 'error');
  }
});

// ---------------------------------------------------------------------------
// Payment methods (Account view)
// ---------------------------------------------------------------------------
async function loadPaymentMethodList() {
  let methods;
  try {
    methods = await api('/payments/methods');
  } catch (err) {
    toast('Could not load payment methods: ' + err.message, 'error');
    return;
  }
  const el = document.getElementById('payment-method-list');
  if (!methods.length) {
    el.innerHTML = '<div class="empty-state">No cards yet — add one below.</div>';
    return;
  }
  el.innerHTML = methods.map(m => `
    <div class="wallet-entry">
      <div><div class="reason">${m.brand.toUpperCase()} •••• ${m.last4}</div>${m.is_default ? '<div class="when" style="color:var(--lime);">Default</div>' : ''}</div>
      <div style="display:flex; gap:6px;">
        ${!m.is_default ? `<button class="btn btn-ghost" style="padding:6px 14px; font-size:12px;" data-set-default="${m.id}">Set default</button>` : ''}
        <button class="btn btn-ghost" style="padding:6px 14px; font-size:12px;" data-remove-method="${m.id}">Remove</button>
      </div>
    </div>
  `).join('');
  el.querySelectorAll('[data-set-default]').forEach(btn => {
    btn.addEventListener('click', async () => {
      try {
        await api(`/payments/methods/${btn.dataset.setDefault}/default`, { method: 'POST' });
        loadPaymentMethodList();
      } catch (err) {
        toast('Could not set default: ' + err.message, 'error');
      }
    });
  });
  el.querySelectorAll('[data-remove-method]').forEach(btn => {
    btn.addEventListener('click', async () => {
      try {
        await api(`/payments/methods/${btn.dataset.removeMethod}`, { method: 'DELETE' });
        loadPaymentMethodList();
      } catch (err) {
        toast('Could not remove card: ' + err.message, 'error');
      }
    });
  });
}

document.getElementById('add-card-btn').addEventListener('click', async () => {
  const cardNumber = document.getElementById('card-number').value.trim();
  if (cardNumber.length < 4) {
    toast('Enter at least 4 digits.', 'error');
    return;
  }
  try {
    const { psp_token, last4 } = await api('/payments/methods/tokenize', { method: 'POST', body: { card_number: cardNumber, brand: 'visa' } });
    await api('/payments/methods', { method: 'POST', body: { psp_token, last4 } });
    document.getElementById('card-number').value = '';
    toast('Card added.', 'success');
    loadPaymentMethodList();
  } catch (err) {
    toast('Could not add card: ' + err.message, 'error');
  }
});

// ---------------------------------------------------------------------------
// Reservations (Account view)
// ---------------------------------------------------------------------------
async function loadReservationList() {
  let reservations;
  try {
    reservations = await api('/users/me/reservations');
  } catch (err) {
    toast('Could not load reservations: ' + err.message, 'error');
    return;
  }
  const el = document.getElementById('reservation-list');
  const active = reservations.filter(r => r.status === 'active');
  if (!active.length) {
    el.innerHTML = '<div class="empty-state">No active reservations.</div>';
    return;
  }
  el.innerHTML = active.map(r => `
    <div class="wallet-entry">
      <div><div class="reason">Held until ${formatDate(r.expiry_time)}</div><div class="when">Connector ${r.connector_id.slice(0, 8)}</div></div>
      <div style="display:flex; gap:6px;">
        <button class="btn btn-primary" style="padding:6px 14px; font-size:12px;" data-start-from-reservation="${r.id}" data-reservation-connector="${r.connector_id}">Start charging</button>
        <button class="btn btn-ghost" style="padding:6px 14px; font-size:12px;" data-cancel-reservation="${r.id}">Cancel</button>
      </div>
    </div>
  `).join('');

  el.querySelectorAll('[data-cancel-reservation]').forEach(btn => {
    btn.addEventListener('click', async () => {
      try {
        await api(`/reservations/${btn.dataset.cancelReservation}/cancel`, { method: 'POST' });
        toast('Reservation cancelled.', 'success');
        loadReservationList();
      } catch (err) {
        toast('Could not cancel: ' + err.message, 'error');
      }
    });
  });
  el.querySelectorAll('[data-start-from-reservation]').forEach(btn => {
    btn.addEventListener('click', () => startSessionFromReservation(btn.dataset.startFromReservation, btn.dataset.reservationConnector));
  });
}

async function startSessionFromReservation(reservationId, connectorId) {
  if (!state.vehicles.length) { toast('Add a vehicle first, in this same Account tab.', 'error'); return; }
  const vehicleId = state.vehicles[0].id;
  try {
    const session = await api('/sessions', {
      method: 'POST',
      headers: { 'Idempotency-Key': uuidv4() },
      body: { connector_id: connectorId, vehicle_id: vehicleId, reservation_id: reservationId },
    });
    state.session = session;
    goTo('charging');
    renderChargingView();
    connectSessionSocket(session.id);
  } catch (err) {
    toast('Could not start session: ' + err.message, 'error');
  }
}

// ---------------------------------------------------------------------------
// Plug Watch report modal
// ---------------------------------------------------------------------------
function openReportModal(connectorId) {
  document.getElementById('report-modal-overlay').dataset.connector = connectorId;
  document.getElementById('report-note').value = '';
  document.getElementById('report-modal-overlay').classList.remove('hidden');
}
document.getElementById('report-cancel').addEventListener('click', () => {
  document.getElementById('report-modal-overlay').classList.add('hidden');
});
document.getElementById('report-submit').addEventListener('click', async () => {
  const overlay = document.getElementById('report-modal-overlay');
  const connectorId = overlay.dataset.connector;
  const issueType = document.getElementById('report-issue-type').value;
  const note = document.getElementById('report-note').value;

  try {
    const result = await api(`/connectors/${connectorId}/reports`, {
      method: 'POST',
      body: { issue_type: issueType, note: note || null },
    });
    overlay.classList.add('hidden');
    if (result.ticket_opened) {
      toast('Reported. Enough Plug Watch reports came in — connector flagged and a maintenance ticket opened.', 'success');
    } else {
      toast('Thanks — report recorded.', 'success');
    }
    if (state.selectedStationId) selectStation(state.selectedStationId);
  } catch (err) {
    toast('Could not submit report: ' + err.message, 'error');
  }
});

// ---------------------------------------------------------------------------
// Boot
// ---------------------------------------------------------------------------
tryResumeSession();
