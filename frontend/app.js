/* ─── AI Disaster Response Coordinator — Frontend App ─── */

const API = window.location.hostname === 'localhost' 

  ? 'http://localhost:8000' 

  : window.location.origin;

// ─── State ───

const UTTARAKHAND_CENTER = [30.0668, 79.0193];

const UTTARAKHAND_ZOOM = 8;

const UTTARAKHAND_BOUNDS = [

  [28.7, 77.5],

  [31.6, 81.2],

];

let state = {

  token: localStorage.getItem('adrc_token') || null,

  user: JSON.parse(localStorage.getItem('adrc_user') || 'null'),

  incidents: [],

  resources: [],

  alerts: [],

  ws: null,

  map: null,

  markers: [],

  refreshInterval: null,

  wsReconnectTimeout: null,

  wsPingInterval: null,

  sessionId: 0,

  dashboardLoadId: 0,

  chatRequestId: 0,

  chatAbortController: null,

};

// ─── Init ───

document.addEventListener('DOMContentLoaded', () => {

  if (state.token && state.user) {

    showDashboard();

  }

  setupEventListeners();

  window.centerMapUttarakhand = centerMapUttarakhand;

});

function setupEventListeners() {

  document.getElementById('login-form').addEventListener('submit', handleLogin);

  document.getElementById('sos-form').addEventListener('submit', handleSOS);

  document.getElementById('chat-form').addEventListener('submit', handleChat);

  document.getElementById('chatbot-toggle')?.addEventListener('click', () => toggleChatbot(true));

  document.getElementById('chatbot-close')?.addEventListener('click', () => toggleChatbot(false));

  document.querySelectorAll('.nav-links li').forEach(li => {

    li.addEventListener('click', () => navigateTo(li.dataset.page));

  });

}

// ─── Auth ───

async function handleLogin(e) {

  e.preventDefault();

  const btn = document.getElementById('login-btn');

  btn.querySelector('span').textContent = 'Signing in...';

  btn.querySelector('.btn-loader').classList.remove('hidden');

  try {

    const res = await fetch(`${API}/api/auth/login`, {

      method: 'POST',

      headers: { 'Content-Type': 'application/json' },

      body: JSON.stringify({

        username: document.getElementById('login-username').value,

        password: document.getElementById('login-password').value,

      }),

    });

    if (!res.ok) throw new Error((await res.json()).detail || 'Login failed');

    const data = await res.json();

    state.token = data.access_token;

    state.user = data.user;

    localStorage.setItem('adrc_token', state.token);

    localStorage.setItem('adrc_user', JSON.stringify(state.user));

    showDashboard();

  } catch (err) {

    showToast(err.message, 'error');

  } finally {

    btn.querySelector('span').textContent = 'Sign In';

    btn.querySelector('.btn-loader').classList.add('hidden');

  }

}

function fillLogin(user, pass) {

  document.getElementById('login-username').value = user;

  document.getElementById('login-password').value = pass;

}

function logout() {

  state.sessionId += 1;

  state.token = null;

  state.user = null;

  localStorage.removeItem('adrc_token');

  localStorage.removeItem('adrc_user');

  stopRealtimeUpdates();

  if (state.map) {

    try { state.map.remove(); } catch (e) {}

    state.map = null;

  }

  document.getElementById('login-screen').classList.add('active');

  document.getElementById('dashboard-screen').classList.remove('active');

}

function stopRealtimeUpdates() {

  if (state.refreshInterval) {

    clearInterval(state.refreshInterval);

    state.refreshInterval = null;

  }

  if (state.wsReconnectTimeout) {

    clearTimeout(state.wsReconnectTimeout);

    state.wsReconnectTimeout = null;

  }

  if (state.wsPingInterval) {

    clearInterval(state.wsPingInterval);

    state.wsPingInterval = null;

  }

  if (state.chatAbortController) {

    state.chatAbortController.abort();

    state.chatAbortController = null;

  }

  if (state.ws) {

    const ws = state.ws;

    state.ws = null;

    ws.onopen = null;

    ws.onmessage = null;

    ws.onclose = null;

    ws.onerror = null;

    ws.close();

  }

}

// ─── Dashboard ───

function showDashboard() {

  stopRealtimeUpdates();

  state.sessionId += 1;

  const sessionId = state.sessionId;

  document.getElementById('login-screen').classList.remove('active');

  document.getElementById('dashboard-screen').classList.add('active');

  // Update user info

  const u = state.user;

  document.getElementById('user-name').textContent = u.full_name || u.username;

  document.getElementById('user-role').textContent = u.role;

  document.getElementById('user-avatar').textContent = (u.full_name || u.username)[0].toUpperCase();

  initMap();

  connectWebSocket(sessionId);

  loadDashboardData(sessionId);

  // Auto-refresh every minute for fresh Uttarakhand disaster updates

  if (state.refreshInterval) clearInterval(state.refreshInterval);

  state.refreshInterval = setInterval(() => {

    loadDashboardData(sessionId);

  }, 60000);

}

// ─── Navigation ───

function navigateTo(page) {

  document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));

  document.getElementById(`page-${page}`).classList.add('active');

  document.querySelectorAll('.nav-links li').forEach(li => li.classList.remove('active'));

  document.querySelector(`.nav-links li[data-page="${page}"]`).classList.add('active');

  document.getElementById('page-title').textContent = {

    dashboard: 'Dashboard', incidents: 'Incidents',

    resources: 'Resources', alerts: 'Alert History', sos: 'Report Emergency'

  }[page];

  if (page === 'incidents') refreshIncidents();

  if (page === 'resources') refreshResources();

  if (page === 'alerts') refreshAlerts();

}

function toggleSidebar() {

  document.getElementById('sidebar').classList.toggle('open');

}

// ─── API Helpers ───

async function apiFetch(path, opts = {}) {

  const headers = { 'Content-Type': 'application/json', ...opts.headers };

  if (state.token) headers['Authorization'] = `Bearer ${state.token}`;

  const res = await fetch(`${API}${path}`, { ...opts, headers });

  if (!res.ok) {

    const err = await res.json().catch(() => ({ detail: 'Request failed' }));

    throw new Error(err.detail || 'Request failed');

  }

  return res.json();

}

// ─── Load Data ───

async function loadDashboardData(sessionId = state.sessionId) {

  if (!state.token || sessionId !== state.sessionId) return;

  const loadId = ++state.dashboardLoadId;

  try {

    const [stats, incidents, alerts, liveStatus] = await Promise.all([

      apiFetch('/api/stats'),

      apiFetch('/api/incidents?limit=50'),

      apiFetch('/api/alerts?limit=20'),

      apiFetch('/api/live-status'),

    ]);

    if (sessionId !== state.sessionId || loadId !== state.dashboardLoadId) return;

    // Update stats

    document.getElementById('stat-total').textContent = stats.total_incidents;

    document.getElementById('stat-active').textContent = stats.active_incidents;

    document.getElementById('stat-resolved').textContent = stats.resolved_incidents;

    document.getElementById('stat-deployed').textContent = stats.deployed_resources;

    document.getElementById('incident-badge').textContent = stats.active_incidents;

    document.getElementById('alert-badge').textContent = stats.total_alerts;

    document.getElementById('alert-count').textContent = `${stats.total_alerts} alerts`;

    // Update map markers

    state.incidents = incidents;

    updateMapMarkers(incidents);

    // Update alerts feed

    state.alerts = alerts;

    renderAlertsFeed(alerts, liveStatus);

    // Render charts

    renderSeverityChart(stats.severity_distribution);

    renderTypeChart(stats.type_distribution);

  } catch (err) {

    if (sessionId !== state.sessionId || loadId !== state.dashboardLoadId) return;

    console.error('Failed to load data:', err);

  }

  if (sessionId !== state.sessionId || loadId !== state.dashboardLoadId) return;

  updateLastRefreshed();

}

// ─── Map ───

let heatmapLayer = null;

function renderMapError(msg) {

  const container = document.getElementById('map-container');

  if (!container) return;

  container.innerHTML = `

    <div class="map-error-overlay" style="

      display:flex; flex-direction:column; align-items:center; justify-content:center;

      height:100%; width:100%; padding:20px; text-align:center;

      background: rgba(17, 24, 39, 0.95); color: #f87171; border-radius: 12px;

    ">

      <span style="font-size:36px; margin-bottom:8px;">⚠️</span>

      <h4 style="margin-bottom:6px; color:#f1f5f9; font-weight:600;">Map Loading Issue</h4>

      <p style="font-size:13px; color:#94a3b8; max-width:320px; margin-bottom:16px;">${msg}</p>

      <button class="btn-primary btn-sm" onclick="initMap(); if(state.incidents) updateMapMarkers(state.incidents);" style="width:auto; padding:8px 18px;">

        ↻ Retry Map Loading

      </button>

    </div>

  `;

}

function initMap() {

  const container = document.getElementById('map-container');

  if (!container) return;

  if (typeof L === 'undefined') {

    renderMapError('Leaflet map library could not be loaded. Please check network connection.');

    return;

  }

  if (state.map) {

    try {

      state.map.remove();

    } catch (e) {

      console.warn('Error resetting existing map instance:', e);

    }

    state.map = null;

  }

  if (container._leaflet_id) {

    container._leaflet_id = null;

    container.innerHTML = '';

  }

  try {

    state.map = L.map('map-container', {

      center: UTTARAKHAND_CENTER,

      zoom: UTTARAKHAND_ZOOM,

      zoomControl: true,

      minZoom: 6,

      maxBounds: UTTARAKHAND_BOUNDS,

      maxBoundsViscosity: 0.8,

    });

    const primaryTiles = L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Dark_Gray_Base/MapServer/tile/{z}/{y}/{x}', {

      attribution: 'Tiles © Esri — Esri, DeLorme, NAVTEQ',

      subdomains: 'abcd',

      maxZoom: 18,

    });

    const fallbackTiles = L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {

      attribution: '© OpenStreetMap contributors',

      maxZoom: 19,

    });

    let usingFallback = false;

    primaryTiles.on('tileerror', () => {

      if (!usingFallback && state.map) {

        usingFallback = true;

        console.warn('CartoDB tiles failed to load, switching to OpenStreetMap tiles.');

        try {

          state.map.removeLayer(primaryTiles);

          fallbackTiles.addTo(state.map);

        } catch (e) {

          console.warn('Failed to switch to fallback tiles:', e);

        }

      }

    });

    primaryTiles.addTo(state.map);

    state.map.fitBounds(UTTARAKHAND_BOUNDS);

    setTimeout(() => {

      if (state.map) state.map.invalidateSize();

    }, 300);

  } catch (err) {

    console.error('Failed to initialize map:', err);

    renderMapError(`Map error: ${err.message || 'Could not initialize Leaflet map'}`);

  }

}

function updateMapMarkers(incidents) {

  if (!state.map) {

    initMap();

    if (!state.map) return;

  }

  if (state.markers && state.markers.length > 0) {

    state.markers.forEach(m => {

      try {

        if (state.map && m) state.map.removeLayer(m);

      } catch (e) {

        console.warn('Error removing marker:', e);

      }

    });

  }

  state.markers = [];

  if (!Array.isArray(incidents)) return;

  incidents.forEach(inc => {

    if (!inc) return;

    const lat = parseFloat(inc.latitude);

    const lng = parseFloat(inc.longitude);

    if (isNaN(lat) || isNaN(lng) || lat < -90 || lat > 90 || lng < -180 || lng > 180) {

      return;

    }

    const sev = Math.max(1, Math.min(5, parseInt(inc.severity) || 1));

    const color = severityColor(sev);

    const size = 12 + sev * 4;

    try {

      const icon = L.divIcon({

        className: 'custom-marker',

        html: `<div style="

          width:${size}px; height:${size}px;

          background:${color}; border-radius:50%; opacity:0.85;

          box-shadow:0 0 ${sev * 6}px ${color};

          border:2px solid rgba(255,255,255,0.4);

          cursor:pointer;

        "></div>`,

        iconSize: [size, size],

        iconAnchor: [size / 2, size / 2],

      });

      const popupContent = `

        <div style="min-width:200px; color:#1e293b;">

          <strong style="font-size:14px; color:#0f172a">${escapeHtml(inc.title || 'Incident')}</strong><br>

          <span style="color:${color};font-weight:700">Severity: ${sev}/5</span><br>

          <span>Type: ${escapeHtml(inc.disaster_type || 'N/A')}</span><br>

          <span>📍 ${escapeHtml(inc.location_name || 'Uttarakhand')}</span><br>

          <span>Status: ${escapeHtml(inc.status_marker || inc.status || 'reported')}</span><br>

          ${inc.source_url ? `<a href="${escapeHtml(inc.source_url)}" target="_blank" rel="noopener" style="color:#2563eb;font-weight:600">Source update ↗</a><br>` : ''}

          ${inc.ai_summary ? `<p style="margin-top:6px;font-size:11px;color:#475569;border-top:1px solid #e2e8f0;padding-top:4px">${escapeHtml(inc.ai_summary)}</p>` : ''}

        </div>

      `;

      const marker = L.marker([lat, lng], { icon })

        .addTo(state.map)

        .bindPopup(popupContent);

      state.markers.push(marker);

    } catch (err) {

      console.warn('Failed to render incident marker:', inc, err);

    }

  });

}

function centerMapUttarakhand() {

  if (!state.map) initMap();

  if (state.map) {

    state.map.fitBounds(UTTARAKHAND_BOUNDS);

    state.map.invalidateSize();

  }

}

async function toggleHeatmap() {

  if (!state.map) {

    initMap();

    if (!state.map) {

      showToast('Map is not active', 'warning');

      return;

    }

  }

  const btn = document.querySelector('button[onclick="toggleHeatmap()"]');

  if (heatmapLayer) {

    try { state.map.removeLayer(heatmapLayer); } catch (e) {}

    heatmapLayer = null;

    if (btn) btn.classList.remove('filter-active');

    showToast('Heatmap layer hidden', 'info');

    return;

  }

  try {

    if (btn) btn.textContent = '⌛ Loading...';

    const heatData = await apiFetch('/api/heatmap');

    if (!Array.isArray(heatData) || heatData.length === 0) {

      showToast('No heatmap data available at present', 'info');

      if (btn) btn.textContent = '🌡️ Heatmap';

      return;

    }

    const points = heatData

      .map(p => [parseFloat(p.lat), parseFloat(p.lng), parseFloat(p.intensity || 0.5)])

      .filter(p => !isNaN(p[0]) && !isNaN(p[1]));

    if (typeof L.heatLayer === 'function') {

      heatmapLayer = L.heatLayer(points, {

        radius: 25,

        blur: 15,

        maxZoom: 12,

        gradient: { 0.4: 'blue', 0.65: 'lime', 1: 'red' },

      }).addTo(state.map);

    } else {

      const circleGroup = L.layerGroup();

      points.forEach(([lat, lng, intensity]) => {

        L.circle([lat, lng], {

          radius: 15000 * intensity,

          color: '#ef4444',

          fillColor: '#f87171',

          fillOpacity: 0.35,

          stroke: false,

        }).addTo(circleGroup);

      });

      heatmapLayer = circleGroup.addTo(state.map);

    }

    if (btn) {

      btn.textContent = '🌡️ Heatmap (Active)';

      btn.classList.add('filter-active');

    }

    showToast('Heatmap overlay activated', 'success');

  } catch (err) {

    console.error('Heatmap error:', err);

    showToast('Failed to load heatmap data', 'error');

  } finally {

    if (btn && !heatmapLayer) btn.textContent = '🌡️ Heatmap';

  }

}

window.toggleHeatmap = toggleHeatmap;

function escapeHtml(str) {

  if (!str) return '';

  return String(str)

    .replace(/&/g, '&amp;')

    .replace(/</g, '&lt;')

    .replace(/>/g, '&gt;')

    .replace(/"/g, '&quot;')

    .replace(/'/g, '&#039;');

}

function severityColor(sev) {

  return { 1: '#10b981', 2: '#3b82f6', 3: '#f59e0b', 4: '#f97316', 5: '#ef4444' }[sev] || '#94a3b8';

}

// ─── Alerts Feed ───

function getNoFreshAlertMessage(liveStatus) {

  const recentNews = liveStatus?.sources?.recent_news;

  if (recentNews?.no_fresh_alerts && recentNews.message) {

    return recentNews.message;

  }

  return 'Waiting for incoming alerts...';

}

function renderAlertsFeed(alerts, liveStatus = null) {

  const feed = document.getElementById('alerts-feed');

  if (!alerts.length) {

    feed.innerHTML = `<div class="empty-state"><span>📡</span><p>${getNoFreshAlertMessage(liveStatus)}</p></div>`;

    return;

  }

  feed.innerHTML = alerts.slice(0, 15).map(a => `

    <div class="alert-item severity-${a.severity}">

      <h4>${a.title}</h4>

      <p>${a.message}</p>

      <div class="alert-time">

        ${a.status_marker ? `<span class="status-pill">${a.status_marker}</span>` : ''}

        ${timeAgo(a.created_at)}

        ${a.source_url ? ` · <a href="${a.source_url}" target="_blank" rel="noopener">source</a>` : ''}

      </div>

    </div>

  `).join('');

}

// ─── Charts ───

function renderSeverityChart(dist) {

  const container = document.getElementById('severity-chart');

  const labels = { '1': 'Low', '2': 'Moderate', '3': 'High', '4': 'Severe', '5': 'Critical' };

  const colors = { '1': '#10b981', '2': '#3b82f6', '3': '#f59e0b', '4': '#f97316', '5': '#ef4444' };

  const maxVal = Math.max(...Object.values(dist).map(Number), 1);

  container.innerHTML = Object.entries(labels).map(([k, label]) => {

    const val = dist[k] || 0;

    const pct = (val / maxVal) * 100;

    return `

      <div class="chart-bar-group">

        <div class="chart-bar-label"><span>${label}</span><span>${val}</span></div>

        <div class="chart-bar-track">

          <div class="chart-bar-fill" style="width:${pct}%;background:${colors[k]}">${val > 0 ? val : ''}</div>

        </div>

      </div>

    `;

  }).join('');

}

function renderTypeChart(dist) {

  const container = document.getElementById('type-chart');

  const icons = { earthquake: '🌍', flood: '🌊', fire: '🔥', cyclone: '🌀', landslide: '⛰️', tsunami: '🌊', industrial: '🏭', other: '❓' };

  const colors = ['#3b82f6', '#10b981', '#ef4444', '#8b5cf6', '#f59e0b', '#06b6d4', '#ec4899', '#64748b'];

  const maxVal = Math.max(...Object.values(dist).map(Number), 1);

  container.innerHTML = Object.entries(dist).map(([type, val], i) => {

    const pct = (val / maxVal) * 100;

    return `

      <div class="chart-bar-group">

        <div class="chart-bar-label"><span>${icons[type] || '❓'} ${type}</span><span>${val}</span></div>

        <div class="chart-bar-track">

          <div class="chart-bar-fill" style="width:${pct}%;background:${colors[i % colors.length]}">${val}</div>

        </div>

      </div>

    `;

  }).join('') || '<div class="empty-state"><p>No data yet</p></div>';

}

// ─── Incidents Page ───

async function refreshIncidents() {

  try {

    const incidents = await apiFetch('/api/incidents?limit=50');

    state.incidents = incidents;

    const tbody = document.getElementById('incidents-tbody');

    tbody.innerHTML = incidents.map(inc => `

      <tr>

        <td>#${inc.id}</td>

        <td>${inc.title}</td>

        <td>${inc.disaster_type || 'N/A'}</td>

        <td><span class="severity-badge sev-${inc.severity}">Level ${inc.severity}</span></td>

        <td>📍 ${inc.location_name}</td>

        <td><span class="status-badge status-${inc.status}">${inc.status_marker || inc.status}</span></td>

        <td><span class="age-badge ${inc.is_old ? 'old' : 'current'}">${inc.data_age || (inc.is_old ? 'Old' : 'Current')}</span></td>

        <td>${timeAgo(inc.created_at)}</td>

      </tr>

    `).join('');

  } catch (err) {

    showToast('Failed to load incidents', 'error');

  }

}

// ─── Resources Page ───

async function refreshResources() {

  try {

    const resources = await apiFetch('/api/resources');

    state.resources = resources;

    renderResources(resources);

  } catch (err) {

    showToast('Failed to load resources', 'error');

  }

}

function renderResources(resources) {

  const grid = document.getElementById('resources-grid');

  const typeIcons = { ndrf_team: '🛡️', ambulance: '🚑', fire_truck: '🚒', rescue_boat: '🚤', helicopter: '🚁', medical_unit: '🏥', volunteer_group: '🤝' };

  grid.innerHTML = resources.map(r => `

    <div class="resource-card">

      <h4>${typeIcons[r.resource_type] || '📦'} ${r.name}</h4>

      <div class="resource-meta">

        <span>Type: ${r.resource_type.replace(/_/g, ' ')}</span>

        <span>Capacity: ${r.capacity}</span>

        ${r.assigned_incident_id ? `<span>Assigned: Incident #${r.assigned_incident_id}</span>` : ''}

        <span>Status: <span class="resource-status rs-${r.status}">${r.status}</span></span>

      </div>

    </div>

  `).join('');

}

function filterResources(filter) {

  document.querySelectorAll('.resource-filters .btn-sm').forEach(b => b.classList.remove('filter-active'));

  document.querySelector(`.resource-filters [data-filter="${filter}"]`).classList.add('filter-active');

  const filtered = filter === 'all' ? state.resources : 

    state.resources.filter(r => filter === 'deployed' ? ['deployed', 'en_route'].includes(r.status) : r.status === filter);

  renderResources(filtered);

}

// ─── Alerts Page ───

async function refreshAlerts() {

  try {

    const [alerts, liveStatus] = await Promise.all([

      apiFetch('/api/alerts?limit=50'),

      apiFetch('/api/live-status'),

    ]);

    const list = document.getElementById('alerts-list');

    list.innerHTML = alerts.map(a => `

      <div class="alert-detail">

        <h4>${a.title}</h4>

        <p>${a.message}</p>

        <div class="alert-footer">

          <span>Severity: Level ${a.severity}${a.status_marker ? ` · ${a.status_marker}` : ''}</span>

          <span>${timeAgo(a.created_at)}</span>

        </div>

        ${a.source_url ? `<a class="source-link" href="${a.source_url}" target="_blank" rel="noopener">Open source update</a>` : ''}

      </div>

    `).join('') || `<div class="empty-state"><span>🔔</span><p>${getNoFreshAlertMessage(liveStatus)}</p></div>`;

  } catch (err) {

    showToast('Failed to load alerts', 'error');

  }

}

// ─── SOS Form ───

async function handleSOS(e) {

  e.preventDefault();

  const btn = document.getElementById('sos-submit');

  btn.textContent = '⏳ Processing...';

  btn.disabled = true;

  try {

    await apiFetch('/api/incidents', {

      method: 'POST',

      body: JSON.stringify({

        title: document.getElementById('sos-title').value,

        description: document.getElementById('sos-description').value,

        location_name: document.getElementById('sos-location').value,

      }),

    });

    showToast('🆘 Emergency report submitted! AI agents processing...', 'success');

    document.getElementById('sos-form').reset();

    navigateTo('dashboard');

    setTimeout(loadDashboardData, 2000);

  } catch (err) {

    showToast(err.message, 'error');

  } finally {

    btn.textContent = '🆘 Submit Emergency Report';

    btn.disabled = false;

  }

}

// ─── Chatbot ───

function toggleChatbot(forceOpen = null) {

  const panel = document.getElementById('chatbot');

  if (!panel) return;

  if (forceOpen === null) {

    panel.classList.toggle('open');

  } else {

    panel.classList.toggle('open', forceOpen);

  }

  if (panel.classList.contains('open')) {

    setTimeout(() => document.getElementById('chat-input')?.focus(), 120);

  }

}

window.toggleChatbot = toggleChatbot;

async function handleChat(e) {

  e.preventDefault();

  const input = document.getElementById('chat-input');

  const msg = input.value.trim();

  if (!msg) return;

  if (state.chatAbortController) {

    state.chatAbortController.abort();

  }

  const requestId = ++state.chatRequestId;

  const controller = new AbortController();

  state.chatAbortController = controller;

  addChatMessage(msg, 'user');

  input.value = '';

  const loadingId = addChatMessage('Searching emergency procedures...', 'bot', true);

  try {

    const data = await apiFetch('/api/chat', {

      method: 'POST',

      body: JSON.stringify({ message: msg }),

      signal: controller.signal,

    });

    if (requestId !== state.chatRequestId) return;

    removeChatMessage(loadingId);

    let response = data.response;

    if (data.sources && data.sources.length) {

      response += `\n\n📚 Sources: ${data.sources.join(', ')}`;

    }

    addChatMessage(response, 'bot');

  } catch (err) {

    if (err.name === 'AbortError' || requestId !== state.chatRequestId) {

      removeChatMessage(loadingId);

      return;

    }

    removeChatMessage(loadingId);

    addChatMessage('Sorry, I encountered an error. Please try again.', 'bot');

  } finally {

    if (requestId === state.chatRequestId) {

      state.chatAbortController = null;

    }

  }

}

function addChatMessage(text, sender, isLoading = false) {

  const container = document.getElementById('chat-messages');

  const id = 'msg-' + Date.now() + '-' + Math.random().toString(36).slice(2);

  const div = document.createElement('div');

  div.className = `chat-msg ${sender}`;

  div.id = id;

  const bubble = document.createElement('div');

  bubble.className = `chat-bubble${isLoading ? ' loading' : ''}`;

  bubble.textContent = text;

  bubble.innerHTML = bubble.innerHTML.replace(/\n/g, '<br>');

  div.appendChild(bubble);

  container.appendChild(div);

  container.scrollTop = container.scrollHeight;

  return id;

}

function removeChatMessage(id) {

  const el = document.getElementById(id);

  if (el) el.remove();

}

// ─── WebSocket ───

function connectWebSocket(sessionId = state.sessionId) {

  if (!state.token || sessionId !== state.sessionId) return;

  const wsUrl = API.replace('http', 'ws') + '/ws';

  const statusDot = document.querySelector('#ws-status .status-dot');

  try {

    if (state.ws && state.ws.readyState !== WebSocket.CLOSED) {

      state.ws.close();

    }

    const ws = new WebSocket(wsUrl);

    state.ws = ws;

    ws.onopen = () => {

      if (sessionId !== state.sessionId || state.ws !== ws) return;

      statusDot.className = 'status-dot connected';

      console.log('✅ WebSocket connected');

    };

    ws.onmessage = (event) => {

      if (sessionId !== state.sessionId || state.ws !== ws) return;

      const msg = JSON.parse(event.data);

      handleWSMessage(msg, sessionId);

    };

    ws.onclose = () => {

      if (sessionId !== state.sessionId || state.ws !== ws) return;

      statusDot.className = 'status-dot disconnected';

      console.log('WebSocket disconnected, reconnecting in 5s...');

      state.wsReconnectTimeout = setTimeout(() => connectWebSocket(sessionId), 5000);

    };

    ws.onerror = () => {

      if (sessionId !== state.sessionId || state.ws !== ws) return;

      statusDot.className = 'status-dot disconnected';

    };

    // Ping every 30s

    if (state.wsPingInterval) clearInterval(state.wsPingInterval);

    state.wsPingInterval = setInterval(() => {

      if (sessionId !== state.sessionId || state.ws !== ws) return;

      if (ws.readyState === WebSocket.OPEN) {

        ws.send(JSON.stringify({ type: 'ping' }));

      }

    }, 30000);

  } catch (err) {

    console.error('WebSocket error:', err);

    if (sessionId === state.sessionId) {

      state.wsReconnectTimeout = setTimeout(() => connectWebSocket(sessionId), 5000);

    }

  }

}

function handleWSMessage(msg, sessionId = state.sessionId) {

  if (sessionId !== state.sessionId) return;

  switch (msg.type) {

    case 'new_incident':

      showToast(`⚠️ New: ${msg.data.title}`, 'warning');

      state.incidents.unshift(msg.data);

      updateMapMarkers(state.incidents);

      loadDashboardData(sessionId);

      break;

    case 'new_alert':

      showToast(`🔔 ${msg.data.title}`, 'info');

      state.alerts.unshift(msg.data);

      renderAlertsFeed(state.alerts);

      const badge = document.getElementById('alert-badge');

      badge.textContent = parseInt(badge.textContent) + 1;

      break;

    case 'resource_update':

      refreshResources();

      break;

  }

}

// ─── Utilities ───

function timeAgo(dateStr) {

  if (!dateStr) return '';

  const d = new Date(dateStr);

  const diff = (Date.now() - d.getTime()) / 1000;

  if (diff < 60) return 'Just now';

  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;

  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;

  return `${Math.floor(diff / 86400)}d ago`;

}

function showToast(message, type = 'info') {

  const container = document.getElementById('toast-container');

  const toast = document.createElement('div');

  toast.className = `toast ${type}`;

  const icons = { success: '✅', error: '❌', warning: '⚠️', info: 'ℹ️' };

  toast.innerHTML = `<span>${icons[type] || ''}</span><span>${message}</span>`;

  container.appendChild(toast);

  setTimeout(() => { toast.style.opacity = '0'; setTimeout(() => toast.remove(), 300); }, 5000);

}

function updateLastRefreshed() {

  const el = document.getElementById('last-refreshed');

  if (el) {

    const now = new Date();

    el.textContent = `Updated: ${now.toLocaleTimeString()}`;

    el.title = `Dashboard auto-refreshes every minute with Uttarakhand-only data from USGS, GDACS, Open-Meteo, Bhudev, and recent trusted news`;

  }

}

