// ═══════════════════════════════════════════════════════════════
// CONFIGURATION — shared global state used across the other js/ files
// ═══════════════════════════════════════════════════════════════
const API_BASE = window.location.origin;
let editor = null;
let currentLiveUrl = '';
let logLineCount = 0;
let isUpdateMode = false;
let fullBuildLog = []; // raw log/step/error lines for the "Full Log" modal — the
                        // main Build Output panel only shows step/error summaries
