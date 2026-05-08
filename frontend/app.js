/* ─── AI Disaster Response Coordinator — Frontend App ─── */

const API = window.location.hostname === 'localhost' 
  ? 'http://localhost:8000' 
  : window.location.origin;

// ─── State ───
let state = {
  token: localStorage.getItem('adrc_token') || null,
  user: JSON.parse(localStorage.getItem('adrc_user') || 'null'),
  incidents: [],
  resources: [],
  alerts: [],
  ws: null,
  map: null,
  markers: [],
};

// ─── Init ───
document.addEventListener('DOMContentLoaded', () => {
  if (state.token && state.user) {
    showDashboard();
  }
  setupEventListeners();
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
  state.token = null;
  state.user = null;
  localStorage.removeItem('adrc_token');
  localStorage.removeItem('adrc_user');
  if (state.ws) state.ws.close();
  document.getElementById('login-screen').classList.add('active');
  document.getElementById('dashboard-screen').classList.remove('active');
}

// ─── Dashboard ───
function showDashboard() {
  document.getElementById('login-screen').classList.remove('active');
  document.getElementById('dashboard-screen').classList.add('active');
  
  // Update user info
  const u = state.user;
  document.getElementById('user-name').textContent = u.full_name || u.username;
  document.getElementById('user-role').textContent = u.role;
  document.getElementById('user-avatar').textContent = (u.full_name || u.username)[0].toUpperCase();
  
  initMap();
  connectWebSocket();
  loadDashboardData();
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
async function loadDashboardData() {
  try {
    const [stats, incidents, alerts] = await Promise.all([
      apiFetch('/api/stats'),
      apiFetch('/api/incidents?limit=50'),
      apiFetch('/api/alerts?limit=20'),
    ]);
    
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
    renderAlertsFeed(alerts);
    
    // Render charts
    renderSeverityChart(stats.severity_distribution);
    renderTypeChart(stats.type_distribution);
  } catch (err) {
    console.error('Failed to load data:', err);
  }
}

// ─── Map ───
function initMap() {
  if (state.map) return;
  state.map = L.map('map-container', {
    center: [22.5, 78.9],
    zoom: 5,
    zoomControl: true,
  });
  L.tileLayer('https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png', {
    attribution: '© OpenStreetMap © CARTO',
    maxZoom: 18,
  }).addTo(state.map);
  setTimeout(() => state.map.invalidateSize(), 300);
}

function updateMapMarkers(incidents) {
  // Clear old markers
  state.markers.forEach(m => state.map.removeLayer(m));
  state.markers = [];
  
  incidents.forEach(inc => {
    if (!inc.latitude || !inc.longitude) return;
    const color = severityColor(inc.severity);
    const icon = L.divIcon({
      className: 'custom-marker',
      html: `<div style="
        width:${12 + inc.severity * 4}px; height:${12 + inc.severity * 4}px;
        background:${color}; border-radius:50%; opacity:0.85;
        box-shadow:0 0 ${inc.severity * 6}px ${color};
        border:2px solid rgba(255,255,255,0.3);
      "></div>`,
      iconSize: [12 + inc.severity * 4, 12 + inc.severity * 4],
      iconAnchor: [(12 + inc.severity * 4)/2, (12 + inc.severity * 4)/2],
    });
    const marker = L.marker([inc.latitude, inc.longitude], { icon })
      .addTo(state.map)
      .bindPopup(`
        <div style="min-width:200px">
          <strong>${inc.title}</strong><br>
          <span style="color:${color};font-weight:700">Severity: ${inc.severity}/5</span><br>
          <span>Type: ${inc.disaster_type || 'N/A'}</span><br>
          <span>📍 ${inc.location_name}</span><br>
          <span>Status: ${inc.status}</span><br>
          ${inc.ai_summary ? `<p style="margin-top:8px;font-size:11px;opacity:0.8">${inc.ai_summary}</p>` : ''}
        </div>
      `);
    state.markers.push(marker);
  });
}

function centerMapIndia() {
  if (state.map) state.map.setView([22.5, 78.9], 5);
}

function toggleHeatmap() {
  showToast('Heatmap overlays incident density on the map', 'info');
}

function severityColor(sev) {
  return { 1: '#10b981', 2: '#3b82f6', 3: '#f59e0b', 4: '#f97316', 5: '#ef4444' }[sev] || '#94a3b8';
}

// ─── Alerts Feed ───
function renderAlertsFeed(alerts) {
  const feed = document.getElementById('alerts-feed');
  if (!alerts.length) {
    feed.innerHTML = '<div class="empty-state"><span>📡</span><p>Waiting for incoming alerts...</p></div>';
    return;
  }
  feed.innerHTML = alerts.slice(0, 15).map(a => `
    <div class="alert-item severity-${a.severity}">
      <h4>${a.title}</h4>
      <p>${a.message}</p>
      <div class="alert-time">${timeAgo(a.created_at)}</div>
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
        <td><span class="status-badge status-${inc.status}">${inc.status}</span></td>
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
    const alerts = await apiFetch('/api/alerts?limit=50');
    const list = document.getElementById('alerts-list');
    list.innerHTML = alerts.map(a => `
      <div class="alert-detail">
        <h4>${a.title}</h4>
        <p>${a.message}</p>
        <div class="alert-footer">
          <span>Severity: Level ${a.severity}</span>
          <span>${timeAgo(a.created_at)}</span>
        </div>
      </div>
    `).join('') || '<div class="empty-state"><span>🔔</span><p>No alerts yet</p></div>';
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
  
  addChatMessage(msg, 'user');
  input.value = '';
  
  const loadingId = addChatMessage('Searching emergency procedures...', 'bot', true);
  
  try {
    const data = await apiFetch('/api/chat', {
      method: 'POST',
      body: JSON.stringify({ message: msg }),
    });
    removeChatMessage(loadingId);
    let response = data.response;
    if (data.sources && data.sources.length) {
      response += `\n\n📚 Sources: ${data.sources.join(', ')}`;
    }
    addChatMessage(response, 'bot');
  } catch (err) {
    removeChatMessage(loadingId);
    addChatMessage('Sorry, I encountered an error. Please try again.', 'bot');
  }
}

function addChatMessage(text, sender, isLoading = false) {
  const container = document.getElementById('chat-messages');
  const id = 'msg-' + Date.now();
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
function connectWebSocket() {
  const wsUrl = API.replace('http', 'ws') + '/ws';
  const statusDot = document.querySelector('#ws-status .status-dot');
  
  try {
    state.ws = new WebSocket(wsUrl);
    
    state.ws.onopen = () => {
      statusDot.className = 'status-dot connected';
      console.log('✅ WebSocket connected');
    };
    
    state.ws.onmessage = (event) => {
      const msg = JSON.parse(event.data);
      handleWSMessage(msg);
    };
    
    state.ws.onclose = () => {
      statusDot.className = 'status-dot disconnected';
      console.log('WebSocket disconnected, reconnecting in 5s...');
      setTimeout(connectWebSocket, 5000);
    };
    
    state.ws.onerror = () => {
      statusDot.className = 'status-dot disconnected';
    };
    
    // Ping every 30s
    setInterval(() => {
      if (state.ws && state.ws.readyState === WebSocket.OPEN) {
        state.ws.send(JSON.stringify({ type: 'ping' }));
      }
    }, 30000);
  } catch (err) {
    console.error('WebSocket error:', err);
    setTimeout(connectWebSocket, 5000);
  }
}

function handleWSMessage(msg) {
  switch (msg.type) {
    case 'new_incident':
      showToast(`⚠️ New: ${msg.data.title}`, 'warning');
      state.incidents.unshift(msg.data);
      updateMapMarkers(state.incidents);
      loadDashboardData();
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
