// ═══════════════════════════════════════════════════════════════
// LIBRARY MODAL — add libraries via the "dependencies:" YAML key
// Shared by the main deploy form and the Edit modal.
// ═══════════════════════════════════════════════════════════════
const LIBRARY_HINTS = {
  python: 'e.g. requests==2.31.0',
  node: 'e.g. lodash@4.17.21',
  typescript: 'e.g. lodash@4.17.21',
  go: 'e.g. github.com/google/uuid@v1.3.0 (version required)',
  quarkus: 'e.g. com.fasterxml.jackson.core:jackson-databind:2.17.0',
  rust: 'e.g. serde@1.0',
};

let libraryModalTarget = 'main';

function libraryModalTextareaId() {
  return libraryModalTarget === 'edit' ? 'edit-yaml-textarea' : 'yaml-config-editor';
}

function libraryModalLanguage() {
  if (libraryModalTarget === 'edit') return editModalLanguage || 'python';
  return document.getElementById('fn-language')?.value || 'python';
}

// ── Parse / merge the `dependencies:` block out of a YAML blob ──────────
// Flat, no-indent list style (matches how `envs:` is already documented
// in the placeholder text) — no YAML library needed for a plain string list.
function parseDependenciesFromYaml(yamlText) {
  const deps = [];
  let inDeps = false;
  for (const line of (yamlText || '').split('\n')) {
    if (/^dependencies:\s*$/.test(line)) { inDeps = true; continue; }
    if (inDeps) {
      const m = line.match(/^-\s*(.+?)\s*$/);
      if (m) { deps.push(m[1].trim()); continue; }
      if (/^\S/.test(line)) inDeps = false; // dedent = new top-level key
    }
  }
  return deps;
}

function setDependenciesInYaml(yamlText, depsList) {
  const lines = (yamlText || '').split('\n');
  const out = [];
  let inDeps = false;
  for (const line of lines) {
    if (/^dependencies:\s*$/.test(line)) { inDeps = true; continue; }
    if (inDeps) {
      if (/^-\s*/.test(line) || /^\s*$/.test(line)) continue;
      inDeps = false;
    }
    out.push(line);
  }
  let base = out.join('\n').replace(/\s+$/, '');
  if (depsList.length === 0) return base ? base + '\n' : '';
  const block = 'dependencies:\n' + depsList.map(d => `- ${d}`).join('\n');
  return base ? `${base}\n${block}\n` : `${block}\n`;
}

function openLibraryModal(target) {
  libraryModalTarget = target;
  const lang = libraryModalLanguage();
  document.getElementById('library-modal-lang-badge').textContent = lang;
  document.getElementById('library-modal-hint').textContent = LIBRARY_HINTS[lang] || 'e.g. package-name';

  const textareaEl = document.getElementById(libraryModalTextareaId());
  const existing = parseDependenciesFromYaml(textareaEl ? textareaEl.value : '');
  document.getElementById('library-modal-textarea').value = existing.join('\n');

  document.getElementById('library-modal-overlay').classList.add('active');
}

function closeLibraryModal() {
  document.getElementById('library-modal-overlay').classList.remove('active');
}

function applyLibraryModal() {
  const raw = document.getElementById('library-modal-textarea').value;
  const deps = [...new Set(raw.split('\n').map(l => l.trim()).filter(Boolean))];

  const textareaEl = document.getElementById(libraryModalTextareaId());
  if (!textareaEl) { closeLibraryModal(); return; }

  textareaEl.value = setDependenciesInYaml(textareaEl.value, deps);

  const detailsEl = textareaEl.closest('details');
  if (detailsEl) detailsEl.open = true;

  showToast(`📦 ${deps.length} librar${deps.length === 1 ? 'y' : 'ies'} added to config`, 'success');
  closeLibraryModal();
}
