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
let currentDeployMode = 'code'; // 'code' | 'sql' — which form/deploy button is
                                 // active, since handleSSEEvent() in deploy.js
                                 // is shared by both the code-editor and
                                 // SQL-to-API submit flows
