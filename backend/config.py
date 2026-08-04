"""
config.py — Centralised configuration and language definitions
==============================================================
All environment-variable reads and static lookup tables live here.
Import from this module everywhere; never read os.getenv() outside it.
"""

import logging
import os
from pathlib import Path

# ── Logging ───────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
logger = logging.getLogger("faas-platform")

# ── Runtime configuration (overridable via env / ConfigMap) ───────────────────

REGISTRY_PREFIX: str = os.getenv("REGISTRY_PREFIX", "docker.io/sweizn")
TENANT_NAMESPACE: str = os.getenv("TENANT_NAMESPACE", "tenant-functions")
WORKSPACE_BASE: Path = Path(os.getenv("WORKSPACE_BASE", "/tmp/faas-workspace"))
DEPLOY_TIMEOUT: int = int(os.getenv("DEPLOY_TIMEOUT_SECONDS", "600"))  # 10 min
POLL_INTERVAL: int = 5  # seconds between ksvc readiness polls

# Frontend HTML served by FastAPI (no separate nginx required)
FRONTEND_PATH: Path = Path(__file__).parent.parent / "frontend" / "index.html"

# ── Language → func template + entrypoint file mapping ───────────────────────

LANGUAGE_CONFIG: dict[str, dict] = {
    "python": {
        "template": "python",
        "entrypoint": "function/func.py",
        "description": "Python 3.11 — func.py → main(CloudEvent) or main(request)",
    },
    "node": {
        "template": "node",
        "entrypoint": "index.js",
        "description": "Node.js 18 — index.js → module.exports = async (context, event) => {}",
    },
    "go": {
        "template": "go",
        "entrypoint": "function.go",
        "description": "Go — function.go → func (f *MyFunction) Handle(res http.ResponseWriter, req *http.Request)",
    },
    "typescript": {
        "template": "typescript",
        "entrypoint": "index.ts",
        "description": "TypeScript — index.ts → export const handle = async (context, event) => {}",
    },
    "quarkus": {
        "template": "quarkus",
        "entrypoint": "src/main/java/functions/Function.java",
        "description": "Quarkus (Java) — Function.java",
    },
    "rust": {
        "template": "rust",
        "entrypoint": "src/main.rs",
        "description": "Rust — src/main.rs",
    },
}

SUPPORTED_LANGUAGES: list[str] = list(LANGUAGE_CONFIG.keys())
