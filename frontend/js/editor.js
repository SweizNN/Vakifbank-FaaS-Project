// ═══════════════════════════════════════════════════════════════
// INIT
// ═══════════════════════════════════════════════════════════════
document.addEventListener('DOMContentLoaded', () => {
  editor = CodeMirror.fromTextArea(document.getElementById('code-editor-textarea'), {
    mode: 'python', theme: 'dracula', lineNumbers: true,
    matchBrackets: true, autoCloseBrackets: true,
    indentUnit: 4, tabSize: 4, indentWithTabs: false, lineWrapping: false,
    extraKeys: { Tab: (cm) => cm.execCommand('indentMore') },
  });
  loadTemplate('python');

  document.getElementById('fn-language').addEventListener('change', (e) => {
    const lang = e.target.value;
    const meta = LANG_META[lang];
    document.getElementById('editor-lang-label').textContent = meta?.label || lang;
    if (meta?.mode) editor.setOption('mode', meta.mode);
    document.querySelectorAll('.lang-chip[data-lang]').forEach(c => c.classList.toggle('active', c.dataset.lang === lang));
    if (TEMPLATES[lang]) loadTemplate(lang);
  });

  checkHealth();
  loadFunctions();
  setInterval(loadFunctions, 30000);
});

// ═══════════════════════════════════════════════════════════════
// TEMPLATE LOADER
// ═══════════════════════════════════════════════════════════════
function loadTemplate(lang) {
  if (lang === 'clear') { clearEditor(); return; }
  if (TEMPLATES[lang]) {
    editor.setValue(TEMPLATES[lang]);
    applyReadOnlyMarkers(lang);
  }

  const sel = document.getElementById('fn-language');
  if ([...sel.options].some(o => o.value === lang)) sel.value = lang;
  const meta = LANG_META[lang];
  document.getElementById('editor-lang-label').textContent = meta?.label || lang;
  if (meta?.mode) editor.setOption('mode', meta.mode);
  document.querySelectorAll('.lang-chip[data-lang]').forEach(c => c.classList.toggle('active', c.dataset.lang === lang));
}

function clearEditor() {
  editor.setValue('');
  editor.focus();
  document.querySelectorAll('.lang-chip[data-lang]').forEach(c => c.classList.remove('active'));
  isUpdateMode = false;
  const fnNameInput = document.getElementById('fn-name');
  fnNameInput.disabled = false;
  document.getElementById('deploy-btn-text').textContent = 'Deploy Function';
}

function handleFileUpload(event) {
  const file = event.target.files[0];
  if (!file) return;
  const reader = new FileReader();
  reader.onload = (e) => {
    const content = e.target.result;
    if (file.name.endsWith('.yaml') || file.name.endsWith('.yml')) {
      document.getElementById('yaml-config-editor').value = content;
      document.querySelector('details').open = true;
      showToast(`✅ YAML loaded: ${file.name}`, 'success');
    } else {
      const ext = file.name.split('.').pop();
      let lang = 'python';
      if (ext === 'js') lang = 'node';
      else if (ext === 'go') lang = 'go';
      else if (ext === 'ts') lang = 'typescript';
      else if (ext === 'java') lang = 'quarkus';
      else if (ext === 'rs') lang = 'rust';

      document.getElementById('fn-language').value = lang;
      document.getElementById('fn-language').dispatchEvent(new Event('change'));

      setTimeout(() => {
        const markers = TEMPLATE_MARKERS[lang] || [];
        let firstUnlocked = 1;
        let lastUnlocked = editor.lineCount() - 1;

        if (markers.length === 2) {
          firstUnlocked = markers[0].to + 1;
          lastUnlocked = markers[1].from - 1;
        } else if (markers.length === 1 && markers[0].from === 0) {
          firstUnlocked = 1;
        }

        let spaces = '';
        if (['python', 'quarkus', 'rust'].includes(lang)) spaces = '    ';
        if (['node', 'typescript'].includes(lang)) spaces = '  ';
        if (lang === 'go') spaces = '\t';

        const finalContent = content.split('\n').map(l => l ? spaces + l : '').join('\n');

        editor.replaceRange(finalContent + '\n', {line: firstUnlocked, ch: 0}, {line: lastUnlocked + 1, ch: 0});
        showToast(`✅ Code inserted into template: ${file.name}`, 'success');
      }, 100);
    }
  };
  reader.readAsText(file);
  event.target.value = '';
}
