"""
main.py — VakıfBank FaaS Platform: FastAPI application entry point
===================================================================
This file is intentionally kept thin: app wiring, lifespan, CORS, static
mount, and router registration only. All business logic lives in
services/, all code generation in generators/, all HTTP route handlers in
routers/ — see each package's own docstrings.
"""

import sys
import asyncio
from contextlib import asynccontextmanager

# Windows'ta Uvicorn'un subprocess çalıştırmayı engelleyen (NotImplementedError) ayarını eziyoruz
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from config import FRONTEND_PATH, REGISTRY_PREFIX, TENANT_NAMESPACE, WORKSPACE_BASE, logger
from routers import deploy, functions, health, jobs, languages, logs, proxy, sql_deploy
from services.health_check import run_all_checks


# ── Lifespan ──────────────────────────────────────────────────────────────────


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Bootstrap: create workspace dir and run startup health check."""
    WORKSPACE_BASE.mkdir(parents=True, exist_ok=True)
    logger.info("Workspace: %s | Registry: %s | Namespace: %s",
                WORKSPACE_BASE, REGISTRY_PREFIX, TENANT_NAMESPACE)

    results = run_all_checks()
    failures = [n for n, i in results.items() if not i["found"] and i["critical"]]
    if failures:
        logger.warning("⚠️  Critical tools missing: %s — deploys may fail", failures)
    else:
        logger.info("✅ All critical tools available. Ready to deploy.")

    yield

    logger.info("Shutting down FaaS Platform.")


# ── FastAPI application ───────────────────────────────────────────────────────


app = FastAPI(
    title="VakıfBank FaaS Platform",
    description="Internal Developer Platform — Serverless function deployment on Knative",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# index.html references its CSS/JS as /static/... — serve everything else in
# frontend/ (style.css, js/*.js) from there. index.html itself is returned by
# the explicit route below, not through this mount.
app.mount("/static", StaticFiles(directory=FRONTEND_PATH.parent), name="static")


# ── Frontend shell ───────────────────────────────────────────────────────────


@app.get("/", response_class=HTMLResponse, include_in_schema=False)
async def serve_frontend():
    """Serve the single-page UI (index.html)."""
    if FRONTEND_PATH.exists():
        return HTMLResponse(content=FRONTEND_PATH.read_text(encoding="utf-8"))
    return HTMLResponse(
        "<h1>FaaS Platform</h1><p>Frontend not found — place index.html in frontend/</p>"
    )


# ── Routers ───────────────────────────────────────────────────────────────────

app.include_router(health.router)
app.include_router(languages.router)
app.include_router(deploy.router)
app.include_router(sql_deploy.router)
app.include_router(functions.router)
app.include_router(logs.router)
app.include_router(jobs.router)
app.include_router(proxy.router)
