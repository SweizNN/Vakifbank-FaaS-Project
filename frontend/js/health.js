// ═══════════════════════════════════════════════════════════════
// HEALTH PANEL
// ═══════════════════════════════════════════════════════════════
async function checkHealth() {
  const dot = document.getElementById('global-status-dot');
  const text = document.getElementById('global-status-text');
  try {
    const res = await fetch(`${API_BASE}/health/detail`);
    const data = await res.json();
    const ok = data.status === 'healthy';
    dot.className = `status-dot ${ok ? 'healthy' : 'degraded'}`;
    text.textContent = ok ? 'All systems OK' : 'Degraded';
    renderHealthGrid(data.tools || {});
  } catch {
    dot.className = 'status-dot error';
    text.textContent = 'Unreachable';
    document.getElementById('health-grid').innerHTML = '<div style="color:var(--accent-red);font-size:13px;padding:12px 0;">Cannot reach backend API.</div>';
  }
}

function renderHealthGrid(tools) {
  const grid = document.getElementById('health-grid');
  if (!tools || Object.keys(tools).length === 0) { grid.innerHTML = '<div style="color:var(--text-muted);font-size:13px;">No health data available.</div>'; return; }
  grid.innerHTML = Object.entries(tools).map(([name, info]) => {
    const ok = info.found;
    const iconCls = ok ? 'ok' : (info.critical ? 'fail' : 'warn');
    const icon = ok ? '✅' : (info.critical ? '❌' : '⚠️');
    const detail = ok ? (info.version || 'found') : (info.error || 'not found');
    return `<div class="health-item"><div class="health-item-icon ${iconCls}" aria-hidden="true">${icon}</div><div><div class="health-item-name">${escHtml(name)}</div><div class="health-item-detail">${escHtml(detail)}</div></div></div>`;
  }).join('');
}

function toggleHealth() {
  const content = document.getElementById('health-content');
  const chevron = document.getElementById('health-chevron');
  const btn = document.getElementById('health-toggle-btn');
  const isOpen = content.classList.toggle('open');
  chevron.classList.toggle('open', isOpen);
  btn.setAttribute('aria-expanded', isOpen);
  if (isOpen) checkHealth();
}
