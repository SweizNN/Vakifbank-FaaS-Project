// ═══════════════════════════════════════════════════════════════
// URL COPY
// ═══════════════════════════════════════════════════════════════
async function copyUrl() {
  const url = document.getElementById('result-url-text').textContent;
  try { await navigator.clipboard.writeText(url); showToast('📋 URL copied to clipboard!', 'info'); }
  catch { showToast('Press Ctrl+C to copy.', 'info'); }
}

// ═══════════════════════════════════════════════════════════════
// TOAST NOTIFICATIONS
// ═══════════════════════════════════════════════════════════════
function showToast(message, type = 'info') {
  const container = document.getElementById('toast-container');
  const toast = document.createElement('div');
  toast.className = `toast ${type}`;
  toast.setAttribute('role', 'alert');
  toast.textContent = message;
  container.appendChild(toast);
  setTimeout(() => toast.remove(), 4500);
}

// ═══════════════════════════════════════════════════════════════
// UTILS
// ═══════════════════════════════════════════════════════════════
function escHtml(str) {
  const d = document.createElement('div');
  d.appendChild(document.createTextNode(String(str)));
  return d.innerHTML;
}
