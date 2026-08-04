// ═══════════════════════════════════════════════════════════════
// CONFIGURATION — shared global state used across the other js/ files
// ═══════════════════════════════════════════════════════════════
const API_BASE = window.location.origin;
let editor = null;
let currentLiveUrl = '';
let logLineCount = 0;
let isUpdateMode = false;
