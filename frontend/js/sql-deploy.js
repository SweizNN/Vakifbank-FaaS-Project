// ═══════════════════════════════════════════════════════════════
// PAGE TABS — Code Editor / SQL to API
// ═══════════════════════════════════════════════════════════════
function switchDeployTab(tab) {
  const panels = { code: 'deploy-panel-code', sql: 'deploy-panel-sql' };
  const btns   = { code: 'tab-code-editor',   sql: 'tab-sql-api' };

  Object.keys(panels).forEach(t => {
    document.getElementById(panels[t]).style.display = (t === tab) ? '' : 'none';
    const btnEl = document.getElementById(btns[t]);
    btnEl.classList.toggle('active', t === tab);
    btnEl.setAttribute('aria-selected', t === tab);
  });

  // CodeMirror goes stale (blank/misaligned) if its container was hidden via
  // display:none while it existed — same pitfall switchEditTab() in
  // functions.js already handles for the Edit modal.
  if (tab === 'code' && editor) setTimeout(() => editor.refresh(), 30);
}

const SQL_DEFAULT_PORTS = { postgres: '5432', mysql: '3306' };

function updateSqlPortPlaceholder() {
  const dbType = document.getElementById('sql-db-type').value;
  document.getElementById('sql-db-port').placeholder = SQL_DEFAULT_PORTS[dbType] || '';
}

// ═══════════════════════════════════════════════════════════════
// SQL-TO-API DEPLOY (SSE streaming) — reuses handleSSEEvent()/appendLog()/
// pushFullLog()/etc. from deploy.js; only the request body and the
// success-card target differ from the code-editor flow.
// ═══════════════════════════════════════════════════════════════
document.getElementById('sql-deploy-form').addEventListener('submit', async (e) => {
  e.preventDefault();
  const name = document.getElementById('sql-fn-name').value.trim();
  const db_type = document.getElementById('sql-db-type').value;
  const db_host = document.getElementById('sql-db-host').value.trim();
  const db_port = parseInt(document.getElementById('sql-db-port').value, 10);
  const db_name = document.getElementById('sql-db-name').value.trim();
  const db_user = document.getElementById('sql-db-user').value.trim();
  const db_password = document.getElementById('sql-db-password').value;
  const sql_query = document.getElementById('sql-query-editor').value.trim();

  if (!name || !db_host || !db_port || !db_name || !db_user || !db_password || !sql_query) {
    showToast('Please fill in all fields.', 'error');
    return;
  }
  if (!/^[a-z][a-z0-9-]{2,49}$/.test(name)) {
    showToast('Function name must start with a lowercase letter and contain only letters, digits, and hyphens.', 'error');
    return;
  }

  currentDeployMode = 'sql';
  resetDeployUI();
  setSqlDeployLoading(true);
  clearLogs();
  document.getElementById('sql-result-card').classList.remove('visible');
  document.getElementById('sql-result-api-key-text').textContent = '';
  appendLog('step', `🚀 Starting SQL-to-API deployment: ${name} (${db_type})`);
  appendLog('muted', '─────────────────────────────────────────');

  try {
    const response = await fetch(`${API_BASE}/sql/deploy`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name, db_type, db_host, db_port, db_name, db_user, db_password, sql_query }),
    });

    if (!response.ok) {
      const err = await response.json().catch(() => ({ detail: response.statusText }));
      throw new Error(err.detail || `HTTP ${response.status}`);
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';
    setLogStatus('streaming', 'Streaming...');

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const parts = buffer.split('\n\n');
      buffer = parts.pop() || '';
      for (const chunk of parts) {
        if (!chunk.trim()) continue;
        let event = 'log', data = '';
        for (const line of chunk.split('\n')) {
          if (line.startsWith('event: ')) event = line.slice(7).trim();
          if (line.startsWith('data: ')) data = line.slice(6);
        }
        handleSSEEvent(event, data, name);
      }
    }
  } catch (err) {
    appendLog('error', `❌ Request failed: ${err.message}`);
    setLogStatus('error', 'Error');
    showToast(`Deployment failed: ${err.message}`, 'error');
    setSqlDeployLoading(false);
  }
});

function setSqlDeployLoading(loading) {
  const btn = document.getElementById('sql-deploy-btn');
  const icon = document.getElementById('sql-deploy-btn-icon');
  const text = document.getElementById('sql-deploy-btn-text');
  btn.disabled = loading;
  btn.setAttribute('aria-busy', loading);
  if (loading) { icon.className = 'spinner'; text.textContent = 'Deploying...'; }
  else { icon.className = ''; icon.textContent = '⚡'; text.textContent = 'Deploy API'; }
}

async function copySqlUrl() {
  const url = document.getElementById('sql-result-url-text').textContent;
  try { await navigator.clipboard.writeText(url); showToast('📋 URL copied to clipboard!', 'info'); }
  catch { showToast('Press Ctrl+C to copy.', 'info'); }
}

async function copySqlApiKey() {
  const key = document.getElementById('sql-result-api-key-text').textContent;
  if (!key) { showToast('No API key to copy.', 'warn'); return; }
  try { await navigator.clipboard.writeText(key); showToast('📋 API key copied to clipboard!', 'success'); }
  catch { showToast('Press Ctrl+C to copy.', 'info'); }
}
