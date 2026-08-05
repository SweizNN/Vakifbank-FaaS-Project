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

function handleSSEEvent(event, data, fnName) {
  switch (event) {
    case 'step': appendLog('step', data); pushFullLog(data); updateStages(data); break;
    // Raw build/lifecycle output (can be very verbose — e.g. --verbose buildpack
    // logs) only goes into the Full Log modal, keeping the main panel readable.
    case 'log': pushFullLog(data); break;
    case 'url':
      currentLiveUrl = data;
      document.getElementById('result-url-text').textContent = data;
      document.getElementById('result-card').classList.add('visible');
      break;
    case 'error':
      appendLog('error', data);
      pushFullLog(data);
      setLogStatus('error', 'Failed');
      setDeployLoading(false);
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
          loadFunctions();
        } else {
          setLogStatus('error', 'Failed');
        }
      } catch { /* ignore parse error */ }
      setDeployLoading(false);
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
function appendLog(type, text) {
  const content = document.getElementById('log-content');
  const placeholder = document.getElementById('log-placeholder');
  if (placeholder) placeholder.remove();
  const line = document.createElement('p');
  line.className = `log-line ${type}`;
  line.textContent = text;
  content.appendChild(line);
  content.scrollTop = content.scrollHeight;
  logLineCount++;
  document.getElementById('log-line-count').textContent = `${logLineCount} lines`;
}

function clearLogs() {
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
  const overlay = document.getElementById('full-log-modal-overlay');
  if (overlay && overlay.classList.contains('active')) {
    const pre = document.getElementById('full-log-content');
    pre.textContent += (pre.textContent ? '\n' : '') + line;
    pre.scrollTop = pre.scrollHeight;
  }
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
