// ═══════════════════════════════════════════════════════════════
// DEPLOY (SSE streaming)
// ═══════════════════════════════════════════════════════════════
document.getElementById('deploy-form').addEventListener('submit', async (e) => {
  e.preventDefault();
  const name = document.getElementById('fn-name').value.trim();
  const language = document.getElementById('fn-language').value;
  const code = editor.getValue().trim();
  const config_yaml = document.getElementById('yaml-config-editor').value.trim();

  if (!name || !language || !code) { showToast('Please fill in all fields and provide your function code.', 'error'); return; }
  if (!/^[a-z][a-z0-9-]{2,49}$/.test(name)) { showToast('Function name must start with a lowercase letter and contain only letters, digits, and hyphens.', 'error'); return; }

  currentDeployMode = 'code';
  resetDeployUI();
  setDeployLoading(true);
  clearLogs();
  document.getElementById('result-card').classList.remove('visible');
  appendLog('step', `🚀 Starting deployment: ${name} (${language})`);
  appendLog('muted', '─────────────────────────────────────────');

  try {
    const response = await fetch(`${API_BASE}/deploy`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name, language, code: wrapCode(language, code), user_snippet: code, config_yaml, is_update: isUpdateMode }),
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
    setDeployLoading(false);
  }
});

// Shared by both the code-editor form (deploy.js) and the SQL-to-API form
// (sql-deploy.js) — currentDeployMode says which one is currently streaming,
// since the two flows have separate buttons and result cards.
function setCurrentDeployLoading(loading) {
  if (currentDeployMode === 'sql') setSqlDeployLoading(loading);
  else setDeployLoading(loading);
}

function handleSSEEvent(event, data, fnName) {
  switch (event) {
    case 'step': appendLog('step', data); pushFullLog(data); updateStages(data); break;
    case 'log':
      pushFullLog(data);
      // Lines prefixed with "| " are the underlying buildpack/lifecycle's own
      // detailed output (pip/npm/cython/etc. build steps under --verbose) —
      // verbose and noisy, so they stay in the Full Log modal only. func's own
      // short status lines ("Still building", "Building function image", ...)
      // have no such prefix, so they still show here — same as before --verbose.
      if (!/^\s*\|/.test(data)) appendLog('muted', data);
      break;
    case 'url':
      currentLiveUrl = data;
      if (currentDeployMode === 'sql') {
        document.getElementById('sql-result-url-text').textContent = data;
        document.getElementById('sql-result-card').classList.add('visible');
      } else {
        document.getElementById('result-url-text').textContent = data;
        document.getElementById('result-card').classList.add('visible');
      }
      break;
    case 'error':
      appendLog('error', data);
      pushFullLog(data);
      setLogStatus('error', 'Failed');
      setCurrentDeployLoading(false);
      showToast(`Deployment failed: ${data}`, 'error');
      break;
    case 'done':
      try {
        const payload = JSON.parse(data);
        if (payload.status === 'success') {
          const successLine = `✅ ${fnName} is live at: ${payload.url}`;
          appendLog('success', successLine);
          pushFullLog(successLine);
          setLogStatus('success', 'Complete');
          showToast(`✅ ${fnName} deployed successfully!`, 'success');
          setStage('ready', 'done');
          if (payload.api_key) {
            document.getElementById('sql-result-api-key-text').textContent = payload.api_key;
          }
          loadFunctions();
        } else {
          setLogStatus('error', 'Failed');
        }
      } catch { /* ignore parse error */ }
      setCurrentDeployLoading(false);
      break;
    case 'exit_code': break;
    default: appendLog('muted', data); pushFullLog(data);
  }
}

function updateStages(stepMsg) {
  if (stepMsg.includes('Step 1')) setStage('scaffold', 'active');
  else if (stepMsg.includes('Step 2')) { setStage('scaffold', 'done'); setStage('inject', 'active'); }
  else if (stepMsg.includes('Step 3')) { setStage('inject', 'done'); setStage('build', 'active'); }
  else if (stepMsg.includes('Step 4')) { setStage('build', 'done'); setStage('ready', 'active'); }
}

function setStage(id, state) {
  const icon = document.getElementById(`stage-${id}-icon`);
  const item = document.getElementById(`stage-${id}`);
  if (!icon || !item) return;
  icon.textContent = { active: '⟳', done: '✅', error: '❌' }[state] || '○';
  item.style.color = { active: 'var(--accent-blue)', done: 'var(--accent-green)', error: 'var(--accent-red)' }[state] || 'var(--text-muted)';
}

function resetDeployUI() {
  ['scaffold', 'inject', 'build', 'ready'].forEach(s => {
    const icon = document.getElementById(`stage-${s}-icon`);
    const item = document.getElementById(`stage-${s}`);
    if (icon) icon.textContent = '○';
    if (item) item.style.color = 'var(--text-muted)';
  });
}

// ═══════════════════════════════════════════════════════════════
// LOG HELPERS
// ═══════════════════════════════════════════════════════════════
// A verbose build (--verbose buildpack output) can emit hundreds of SSE
// "log" events within a few milliseconds. Writing to the DOM synchronously
// on every single one (one <p> + a scrollTop reflow, or worse a growing
// pre.textContent +=) blocks the main thread long enough to freeze the tab.
// Instead, queue incoming lines and flush them in one batched DOM update per
// animation frame — no matter how big the burst, the browser stays responsive.
let pendingCleanLines = [];
let pendingFullLines = [];
let logFlushScheduled = false;

function scheduleLogFlush() {
  if (logFlushScheduled) return;
  logFlushScheduled = true;
  requestAnimationFrame(flushLogQueues);
}

function flushLogQueues() {
  logFlushScheduled = false;

  if (pendingCleanLines.length) {
    const content = document.getElementById('log-content');
    const placeholder = document.getElementById('log-placeholder');
    if (placeholder) placeholder.remove();
    const frag = document.createDocumentFragment();
    for (const { type, text } of pendingCleanLines) {
      const line = document.createElement('p');
      line.className = `log-line ${type}`;
      line.textContent = text;
      frag.appendChild(line);
    }
    logLineCount += pendingCleanLines.length;
    pendingCleanLines.length = 0;
    content.appendChild(frag);
    content.scrollTop = content.scrollHeight;
    document.getElementById('log-line-count').textContent = `${logLineCount} lines`;
  }

  if (pendingFullLines.length) {
    const overlay = document.getElementById('full-log-modal-overlay');
    if (overlay && overlay.classList.contains('active')) {
      const pre = document.getElementById('full-log-content');
      pre.insertAdjacentText('beforeend', (pre.textContent ? '\n' : '') + pendingFullLines.join('\n'));
      pre.scrollTop = pre.scrollHeight;
    }
    pendingFullLines.length = 0;
  }
}

function appendLog(type, text) {
  pendingCleanLines.push({ type, text });
  scheduleLogFlush();
}

function clearLogs() {
  pendingCleanLines.length = 0;
  pendingFullLines.length = 0;
  document.getElementById('log-content').innerHTML = `
    <div class="log-placeholder" id="log-placeholder">
      <div class="log-placeholder-icon" aria-hidden="true">📡</div>
      <div>Build logs will stream here in real-time</div>
    </div>`;
  logLineCount = 0;
  document.getElementById('log-line-count').textContent = '0 lines';
  setLogStatus('', 'Idle');
  fullBuildLog = [];
  const fullLogEl = document.getElementById('full-log-content');
  if (fullLogEl) fullLogEl.textContent = '';
}

// ═══════════════════════════════════════════════════════════════
// FULL LOG MODAL
// ═══════════════════════════════════════════════════════════════
function pushFullLog(line) {
  fullBuildLog.push(line);
  pendingFullLines.push(line);
  scheduleLogFlush();
}

function openFullLogModal() {
  const pre = document.getElementById('full-log-content');
  pre.textContent = fullBuildLog.length
    ? fullBuildLog.join('\n')
    : 'No logs yet — deploy a function to see build output here.';
  document.getElementById('full-log-modal-overlay').classList.add('active');
  pre.scrollTop = pre.scrollHeight;
}

function closeFullLogModal() {
  document.getElementById('full-log-modal-overlay').classList.remove('active');
}

async function copyFullLog() {
  if (!fullBuildLog.length) { showToast('No logs to copy.', 'warn'); return; }
  try {
    await navigator.clipboard.writeText(fullBuildLog.join('\n'));
    showToast('📋 Full log copied to clipboard!', 'success');
  } catch {
    showToast('Failed to copy logs.', 'error');
  }
}

function setLogStatus(type, label) {
  document.getElementById('log-status-dot').className = `log-status-dot ${type}`;
  document.getElementById('log-status-label').textContent = label;
}

function setDeployLoading(loading) {
  const btn = document.getElementById('deploy-btn');
  const icon = document.getElementById('deploy-btn-icon');
  const text = document.getElementById('deploy-btn-text');
  btn.disabled = loading;
  btn.setAttribute('aria-busy', loading);
  if (loading) { icon.className = 'spinner'; text.textContent = 'Deploying...'; }
  else { icon.className = ''; icon.textContent = '⚡'; text.textContent = 'Deploy Function'; }
}
