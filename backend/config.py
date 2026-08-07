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

# Redis-backed deploy-job store (services/job_store.py). Defaults to a local
# instance for dev; k8s/deployment.yaml overrides this to the in-cluster
# redis Service (see k8s/redis.yaml) so every orchestrator replica reads/
# writes the same job state instead of an unshared in-memory dict.
REDIS_URL: str = os.getenv("REDIS_URL", "redis://localhost:6379/0")
JOB_TTL_SECONDS: int = int(os.getenv("JOB_TTL_SECONDS", str(24 * 60 * 60)))  # 24h

# Frontend HTML served by FastAPI (no separate nginx required)
FRONTEND_PATH: Path = Path(__file__).parent.parent / "frontend" / "index.html"

# Static scaffold directories for languages `func create` can't produce
# (see LANGUAGE_CONFIG's "build_mode": "dockerfile" entries below)
SCAFFOLDS_DIR: Path = Path(__file__).parent / "scaffolds"

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
    "dotnet": {
        "template": "dotnet",
        "entrypoint": "Function.cs",
        "description": ".NET 8 — Function.cs → Handle(HttpRequest, ILogger)",
        # `func` has no built-in dotnet runtime/template (and its "host"
        # builder explicitly rejects unknown runtimes even with a Dockerfile
        # present). So this language is scaffolded from a static local
        # template and built via `docker build`/`docker push` ourselves;
        # `func deploy --build=false --push=false --image ...` is then used
        # only to create/update the Knative Service. See services/pipeline.py.
        "build_mode": "dockerfile",
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
        # frontend/js/templates.js's wrapCode() wraps every Rust deploy in
        # `use serde_json::Value;` + `actix_web::web::Json<Value>` — and the
        # default starter template itself uses serde_json::json!() — so
        # every Rust deploy needs this crate, not just ones where the user
        # opts into a `dependencies:` YAML block. func's own rust scaffold's
        # Cargo.toml ships actix-web/serde/tokio but not serde_json.
        "required_dependencies": ["serde_json@1"],
    },
}

SUPPORTED_LANGUAGES: list[str] = list(LANGUAGE_CONFIG.keys())
