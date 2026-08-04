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
        <button class="btn btn-ghost btn-sm" onclick="editFunction('${escHtml(fn.name)}')" aria-label="Edit">✏️ Edit</button>
        <button class="btn btn-ghost btn-sm" onclick="openTestModal('${escHtml(fn.url || '')}', '${escHtml(fn.name)}')" aria-label="Test">Test</button>
        <button class="btn btn-ghost btn-sm" onclick="copyCurl('${escHtml(fn.url || '')}')" aria-label="cURL">cURL</button>
        <button class="btn btn-danger btn-sm" onclick="deleteFunction('${escHtml(fn.name)}')" aria-label="Delete">Delete</button>
      </td>
    </tr>`;
  }).join('');

  container.innerHTML = `<table><thead><tr><th scope="col">Name</th><th scope="col">Live URL</th><th scope="col">Status</th><th scope="col">Created</th><th scope="col">Actions</th></tr></thead><tbody>${rows}</tbody></table>`;
}

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
    // Use the backend proxy to bypass CORS restrictions
    const res = await fetch(`${API_BASE}/proxy`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        url: currentTestUrl,
        method: 'POST',
        body: bodyData
      })
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

async function editFunction(name) {
  try {
    const res = await fetch(`${API_BASE}/functions/${encodeURIComponent(name)}/code`);

    if (res.status === 422) {
      showToast(`⚠️ '${name}' Edit özelliği eklenmeden önce deploy edildi. Silinip yeniden deploy edilmeli.`, 'warn');
      return;
    }
    if (res.status === 404) {
      showToast(`❌ '${name}' bulunamadı.`, 'error');
      return;
    }
    if (!res.ok) {
      const errData = await res.json().catch(() => ({}));
      throw new Error(errData.detail || `HTTP ${res.status}`);
    }

    const data = await res.json();

    // Populate fields
    const nameInput = document.getElementById('fn-name');
    nameInput.value = data.name;
    nameInput.disabled = true; // Lock name during update

    const langInput = document.getElementById('fn-language');
    langInput.value = data.language || 'python';
    langInput.dispatchEvent(new Event('change'));

    setTimeout(() => {
      editor.setValue(data.code || '');
      applyReadOnlyMarkers(data.language || 'python');
      const yamlEditor = document.getElementById('yaml-config-editor');
      if (data.config_yaml) {
        yamlEditor.value = data.config_yaml;
        document.querySelector('details').open = true;
      } else {
        yamlEditor.value = '';
      }

      isUpdateMode = true;
      document.getElementById('deploy-btn-text').textContent = 'Update Function';
      window.scrollTo({ top: 0, behavior: 'smooth' });
      showToast(`✏️ Editing function '${name}'`, 'info');
    }, 100);

  } catch (err) {
    showToast(`Failed to edit function: ${err.message}`, 'error');
  }
}
