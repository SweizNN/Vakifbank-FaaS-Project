// ═══════════════════════════════════════════════════════════════
// FUNCTIONS TABLE
// ═══════════════════════════════════════════════════════════════
async function loadFunctions() {
  try {
    const res = await fetch(`${API_BASE}/functions`);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    const funcs = data.functions || [];

    // Sort newest first (so oldest stays at the bottom)
    funcs.sort((a, b) => new Date(b.created_at || 0) - new Date(a.created_at || 0));

    renderFunctionsTable(funcs);
  } catch (err) { console.error('Failed to load functions:', err); }
}

function renderFunctionsTable(functions) {
  const container = document.getElementById('functions-table-container');
  document.getElementById('fn-count-badge').textContent = functions.length;
  document.getElementById('stat-deployed').textContent = functions.length;
  document.getElementById('stat-ready').textContent = functions.filter(f => f.ready).length;

  if (functions.length === 0) {
    container.innerHTML = `<div class="empty-state" role="status"><div class="empty-state-icon" aria-hidden="true">🪣</div><div class="empty-state-text">No functions deployed yet</div><div class="empty-state-sub">Deploy your first function using the form above</div></div>`;
    return;
  }

  const rows = functions.map(fn => {
    const readyCls = fn.ready ? 'ready' : 'not-ready';
    const readyLabel = fn.ready ? '● Ready' : '◌ Pending';
    const urlCell = fn.url ? `<a class="fn-url-link" href="${fn.url}" target="_blank" rel="noopener">${fn.url} ↗</a>` : '<span style="color:var(--text-muted)">—</span>';
    const created = fn.created_at ? new Date(fn.created_at).toLocaleString() : '—';
    return `<tr>
      <td><span class="fn-name">${escHtml(fn.name)}</span></td>
      <td>${urlCell}</td>
      <td><span class="ready-badge ${readyCls}" role="status">${readyLabel}</span></td>
      <td>${escHtml(created)}</td>
      <td style="display:flex; gap:8px;">
        <button class="btn btn-ghost btn-sm" onclick="openEditModal('${escHtml(fn.name)}')" aria-label="Edit">✏️ Edit</button>
        <button class="btn btn-ghost btn-sm" onclick="openTestModal('${escHtml(fn.url || '')}', '${escHtml(fn.name)}')" aria-label="Test">Test</button>
        <button class="btn btn-ghost btn-sm" onclick="copyCurl('${escHtml(fn.url || '')}')" aria-label="cURL">cURL</button>
        <button class="btn btn-danger btn-sm" onclick="deleteFunction('${escHtml(fn.name)}')" aria-label="Delete">Delete</button>
      </td>
    </tr>`;
  }).join('');

  container.innerHTML = `<table><thead><tr><th scope="col">Name</th><th scope="col">Live URL</th><th scope="col">Status</th><th scope="col">Created</th><th scope="col">Actions</th></tr></thead><tbody>${rows}</tbody></table>`;
}

// ═══════════════════════════════════════════════════════════════
// TEST MODAL
// ═══════════════════════════════════════════════════════════════
let currentTestUrl = '';

function openTestModal(url, name) {
  if (!url) { showToast('Function has no Live URL yet.', 'warn'); return; }
  currentTestUrl = url;
  document.getElementById('test-modal-title').textContent = name;
  document.getElementById('test-modal-result').style.display = 'none';
  document.getElementById('test-modal-overlay').classList.add('active');
}

function closeTestModal() {
  document.getElementById('test-modal-overlay').classList.remove('active');
}

async function runFunctionTest() {
  const resultDiv = document.getElementById('test-modal-result');
  resultDiv.style.display = 'block';
  resultDiv.innerHTML = '<span style="color:var(--text-muted)">Sending request...</span>';

  const bodyStr = document.getElementById('test-modal-body').value;
  let bodyData;
  try { bodyData = JSON.parse(bodyStr); }
  catch (e) { resultDiv.innerHTML = `<span style="color:var(--accent-red)">Invalid JSON: ${e.message}</span>`; return; }

  try {
    const start = Date.now();
    const res = await fetch(`${API_BASE}/proxy`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ url: currentTestUrl, method: 'POST', body: bodyData })
    });
    const ms = Date.now() - start;
    const proxyData = await res.json();
    const statusCode = proxyData.status || res.status;
    const bodyResponse = proxyData.body || proxyData;
    let text = typeof bodyResponse === 'string' ? bodyResponse : JSON.stringify(bodyResponse, null, 2);
    const color = (statusCode >= 200 && statusCode < 300) ? 'var(--accent-green)' : 'var(--accent-red)';
    resultDiv.innerHTML = `<div style="margin-bottom:8px; color:${color}; font-weight:bold;">HTTP ${statusCode} (${ms}ms)</div><div>${escHtml(text)}</div>`;
  } catch (err) {
    resultDiv.innerHTML = `<div style="color:var(--accent-red)">Request failed: ${err.message}<br><br><small style="color:var(--text-muted)">Check if the backend is running and the proxy route is deployed.</small></div>`;
  }
}

// ═══════════════════════════════════════════════════════════════
// EDIT MODAL — state
// ═══════════════════════════════════════════════════════════════
let editModalEditor = null;
let editModalFnName = '';
let editModalLanguage = '';

// ── Open ─────────────────────────────────────────────────────
async function openEditModal(name) {
  editModalFnName = name;
  document.getElementById('edit-modal-title').textContent = name;

  // Reset to Code tab
  switchEditTab('code');
  const btn = document.getElementById('edit-deploy-btn');
  if (btn) { btn.disabled = false; }
  const icon = document.getElementById('edit-deploy-btn-icon');
  if (icon) { icon.className = ''; icon.textContent = '⚡'; }

  // Show modal first so CodeMirror can measure its dimensions
  document.getElementById('edit-modal-overlay').classList.add('active');

  // Restore code panel if it was replaced by an error message
  const codePanel = document.getElementById('edit-panel-code');
  if (!codePanel.querySelector('#edit-codemirror-wrapper')) {
    codePanel.innerHTML = `
      <div class="modal-body" style="padding-bottom:0;">
        <div style="display:flex; gap:8px; align-items:center; margin-bottom:12px;">
          <span style="font-size:13px; color:var(--text-secondary);">Language:</span>
          <span id="edit-modal-lang-badge" class="edit-lang-badge"></span>
        </div>
        <label style="display:block; margin-bottom:6px; font-size:12px; color:var(--text-secondary); text-transform:uppercase; letter-spacing:.06em;">Function Code</label>
        <div id="edit-codemirror-wrapper" style="border:2px solid var(--border); border-radius:var(--radius-sm); overflow:hidden; margin-bottom:12px;">
          <textarea id="edit-code-textarea"></textarea>
        </div>
        <details id="edit-yaml-details" style="margin-bottom:12px;">
          <summary style="cursor:pointer; font-size:12px; color:var(--text-secondary); font-weight:500;">⚙️ Advanced Configuration (YAML)</summary>
          <div style="margin-top:8px;">
            <textarea id="edit-yaml-textarea" style="width:100%; height:100px; font-family:var(--font-mono); font-size:12px; padding:8px; background:var(--bg-input); color:var(--text-primary); border:1px solid var(--border); border-radius:var(--radius-sm); resize:vertical;"></textarea>
          </div>
        </details>
      </div>
      <div class="modal-footer" style="padding:16px 20px;">
        <button class="btn btn-ghost" onclick="closeEditModal()">Cancel</button>
        <button class="btn btn-primary" style="width:auto; padding:0 24px;" onclick="submitEditDeploy()" id="edit-deploy-btn">
          <span id="edit-deploy-btn-icon">⚡</span> Deploy Update
        </button>
      </div>`;
    editModalEditor = null; // force re-init
  }

  try {
    const res = await fetch(`${API_BASE}/functions/${encodeURIComponent(name)}/code`);

    if (res.status === 422) {
      document.getElementById('edit-panel-code').innerHTML = `
        <div class="modal-body" style="text-align:center; padding:32px;">
          <div style="font-size:32px; margin-bottom:12px;">⚠️</div>
          <div style="font-weight:700; margin-bottom:8px;">Code not available</div>
          <div style="color:var(--text-muted); font-size:13px;">This function was deployed before the Edit feature existed.<br>Delete it and re-deploy to enable editing and revision history.</div>
        </div>`;
      return;
    }
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || `HTTP ${res.status}`);
    }

    const data = await res.json();
    editModalLanguage = data.language || 'python';

    document.getElementById('edit-modal-lang-badge').textContent = editModalLanguage;

    const textarea = document.getElementById('edit-code-textarea');
    const meta = LANG_META[editModalLanguage] || {};

    if (!editModalEditor) {
      editModalEditor = CodeMirror.fromTextArea(textarea, {
        mode: meta.mode || 'python',
        theme: 'dracula',
        lineNumbers: true,
        matchBrackets: true,
        autoCloseBrackets: true,
        indentUnit: 4,
        tabSize: 4,
        indentWithTabs: false,
        lineWrapping: false,
        extraKeys: { Tab: (cm) => cm.execCommand('indentMore') },
      });
    } else {
      if (meta.mode) editModalEditor.setOption('mode', meta.mode);
    }

    editModalEditor.setValue(data.code || '');
    applyReadOnlyMarkers(editModalLanguage, editModalEditor);
    setTimeout(() => editModalEditor.refresh(), 60);

    const yamlTA = document.getElementById('edit-yaml-textarea');
    yamlTA.value = data.config_yaml || '';
    document.getElementById('edit-yaml-details').open = !!data.config_yaml;

    // Load revisions in background
    loadRevisions(name);

  } catch (err) {
    showToast(`Failed to load function: ${err.message}`, 'error');
    closeEditModal();
  }
}

// ── Close ────────────────────────────────────────────────────
function closeEditModal() {
  document.getElementById('edit-modal-overlay').classList.remove('active');
}

function handleEditOverlayClick(e) {
  if (e.target === document.getElementById('edit-modal-overlay')) {
    closeEditModal();
  }
}

// ── Tabs ─────────────────────────────────────────────────────
function switchEditTab(tab) {
  const panels = { code: 'edit-panel-code', revisions: 'edit-panel-revisions' };
  const btns   = { code: 'tab-code',        revisions: 'tab-revisions' };

  Object.keys(panels).forEach(t => {
    const panelEl = document.getElementById(panels[t]);
    if (panelEl) panelEl.style.display = (t === tab) ? '' : 'none';
    const btnEl = document.getElementById(btns[t]);
    if (btnEl) {
      btnEl.classList.toggle('active', t === tab);
      btnEl.setAttribute('aria-selected', t === tab);
    }
  });

  if (tab === 'code' && editModalEditor) {
    setTimeout(() => editModalEditor.refresh(), 30);
  }
  if (tab === 'revisions' && editModalFnName) {
    loadRevisions(editModalFnName);
  }
}

// ── Revisions ────────────────────────────────────────────────
async function loadRevisions(name) {
  const listEl = document.getElementById('edit-revisions-list');
  if (!listEl) return;
  listEl.innerHTML = '<div style="color:var(--text-muted); font-size:13px; text-align:center; padding:24px 0;">Loading revisions...</div>';

  try {
    const res = await fetch(`${API_BASE}/functions/${encodeURIComponent(name)}/revisions`);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    const revisions = data.revisions || [];

    if (revisions.length === 0) {
      listEl.innerHTML = '<div style="color:var(--text-muted); font-size:13px; text-align:center; padding:24px 0;">No revisions found.</div>';
      return;
    }

    listEl.innerHTML = revisions.map((rev, i) => {
      const isActive = rev.is_active;
      const date = rev.created_at ? new Date(rev.created_at).toLocaleString() : '—';
      const hasCode = rev.has_code;
      const label = i === 0 ? ' <span style="color:var(--text-muted);font-weight:400;font-size:11px;">(Latest)</span>' : '';

      return `<div class="revision-row ${isActive ? 'active-revision' : ''}">
        <div class="revision-name" title="${escHtml(rev.name)}">${escHtml(rev.name)}${label}</div>
        <div class="revision-date">${escHtml(date)}</div>
        ${isActive ? '<span class="revision-active-badge">🟢 Active</span>' : ''}
        ${hasCode
          ? `<button class="btn btn-ghost btn-sm" onclick="loadRevisionCode('${escHtml(name)}', '${escHtml(rev.name)}')">📥 Load Code</button>`
          : '<span style="font-size:11px; color:var(--text-muted);">No code</span>'}
        ${!isActive
          ? `<button class="btn btn-ghost btn-sm" style="color:var(--accent-amber);" onclick="performRollback('${escHtml(name)}', '${escHtml(rev.name)}')">↩ Rollback</button>`
          : ''}
      </div>`;
    }).join('');
  } catch (err) {
    listEl.innerHTML = `<div style="color:var(--accent-red); font-size:13px; text-align:center; padding:16px;">Failed to load revisions: ${escHtml(err.message)}</div>`;
  }
}

async function loadRevisionCode(fnName, revisionName) {
  try {
    const res = await fetch(`${API_BASE}/functions/${encodeURIComponent(fnName)}/revision/${encodeURIComponent(revisionName)}/code`);
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || `HTTP ${res.status}`);
    }
    const data = await res.json();

    editModalLanguage = data.language || editModalLanguage;
    document.getElementById('edit-modal-lang-badge').textContent = editModalLanguage;

    if (editModalEditor) {
      const meta = LANG_META[editModalLanguage] || {};
      if (meta.mode) editModalEditor.setOption('mode', meta.mode);
      editModalEditor.setValue(data.code || '');
      applyReadOnlyMarkers(editModalLanguage, editModalEditor);
    }

    const yamlTA = document.getElementById('edit-yaml-textarea');
    if (yamlTA) { yamlTA.value = data.config_yaml || ''; }
    const yamlDetails = document.getElementById('edit-yaml-details');
    if (yamlDetails) { yamlDetails.open = !!data.config_yaml; }

    switchEditTab('code');
    showToast(`📥 Loaded code from revision '${revisionName}'`, 'info');
  } catch (err) {
    showToast(`Failed to load revision code: ${err.message}`, 'error');
  }
}

async function performRollback(fnName, revisionName) {
  if (!confirm(`Roll back '${fnName}' to revision '${revisionName}'?\n\nAll traffic will be shifted to this older version immediately.`)) return;

  try {
    const res = await fetch(`${API_BASE}/functions/${encodeURIComponent(fnName)}/rollback`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ revision_name: revisionName }),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || `HTTP ${res.status}`);
    }
    showToast(`✅ Rolled back '${fnName}' to '${revisionName}'!`, 'success');
    await loadRevisions(fnName);
    await loadFunctions();
  } catch (err) {
    showToast(`Rollback failed: ${err.message}`, 'error');
  }
}

// ── Deploy Update from modal ──────────────────────────────────
async function submitEditDeploy() {
  if (!editModalFnName || !editModalEditor) return;

  const code = editModalEditor.getValue().trim();
  const yamlTA = document.getElementById('edit-yaml-textarea');
  const config_yaml = yamlTA ? yamlTA.value.trim() : '';

  if (!code) { showToast('Code cannot be empty.', 'error'); return; }

  const btn = document.getElementById('edit-deploy-btn');
  const icon = document.getElementById('edit-deploy-btn-icon');
  if (btn) btn.disabled = true;
  if (icon) { icon.className = 'spinner'; icon.textContent = ''; }

  try {
    const response = await fetch(`${API_BASE}/deploy`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        name: editModalFnName,
        language: editModalLanguage,
        code: wrapCode(editModalLanguage, code),
        user_snippet: code,
        config_yaml,
        is_update: true,
      }),
    });

    if (!response.ok) {
      const err = await response.json().catch(() => ({ detail: response.statusText }));
      throw new Error(err.detail || `HTTP ${response.status}`);
    }

    closeEditModal();
    showToast(`⚡ Deploying update for '${editModalFnName}'...`, 'info');

    clearLogs();
    resetDeployUI();
    document.getElementById('result-card').classList.remove('visible');
    appendLog('step', `🚀 Updating function: ${editModalFnName} (${editModalLanguage})`);
    appendLog('muted', '─────────────────────────────────────────');
    setDeployLoading(true);
    setLogStatus('streaming', 'Streaming...');

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';

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
        handleSSEEvent(event, data, editModalFnName);
      }
    }
  } catch (err) {
    if (btn) btn.disabled = false;
    if (icon) { icon.className = ''; icon.textContent = '⚡'; }
    showToast(`Update failed: ${err.message}`, 'error');
  }
}

// ═══════════════════════════════════════════════════════════════
// CURL COPY & DELETE
// ═══════════════════════════════════════════════════════════════
async function copyCurl(url) {
  if (!url) { showToast('Function has no Live URL yet.', 'warn'); return; }
  const cmd = `curl -X POST ${url} -H "Content-Type: application/json" -d '{"name": "test"}'`;
  if (navigator.clipboard && window.isSecureContext) {
    try { await navigator.clipboard.writeText(cmd); showToast('📋 cURL copied to clipboard!', 'success'); return; } catch (e) {}
  }
  try {
    const ta = document.createElement("textarea");
    ta.value = cmd; ta.style.position = "fixed"; ta.style.left = "-9999px";
    document.body.appendChild(ta); ta.select(); document.execCommand('copy'); document.body.removeChild(ta);
    showToast('📋 cURL copied to clipboard!', 'success');
  } catch (err) { showToast('Failed to copy', 'error'); }
}

async function deleteFunction(name) {
  if (!confirm(`Delete function "${name}"? This cannot be undone.`)) return;
  try {
    const res = await fetch(`${API_BASE}/functions/${encodeURIComponent(name)}`, { method: 'DELETE' });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    showToast(`✅ Function "${name}" deleted.`, 'success');
    await loadFunctions();
  } catch (err) { showToast(`Failed to delete "${name}": ${err.message}`, 'error'); }
}
