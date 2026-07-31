"""
main.py — VakıfBank FaaS Platform: FastAPI application entry point
===================================================================
This file is intentionally kept thin: app wiring, lifespan, and route
handlers only. All business logic lives in the modules it imports.

Import map:
  config    → env vars, LANGUAGE_CONFIG, paths
  models    → DeployRequest, DeleteResponse
  k8s       → kubectl wrappers (kubectl, list_ksvc, ...)
  pipeline  → SSE deploy workflow
  health_check → tool + cluster checks (Phase 1 verifier)
"""

import re
import uuid
import sys
import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

# Windows'ta Uvicorn'un subprocess çalıştırmayı engelleyen (NotImplementedError) ayarını eziyoruz
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, StreamingResponse

from config import (
    FRONTEND_PATH,
    REGISTRY_PREFIX,
    SUPPORTED_LANGUAGES,
    TENANT_NAMESPACE,
    WORKSPACE_BASE,
    logger,
)
from health_check import run_all_checks
from k8s import kubectl, list_ksvc
from models import DeleteResponse, DeployRequest
from pipeline import deploy_jobs, deploy_pipeline


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


# ── Routes ────────────────────────────────────────────────────────────────────


@app.get("/", response_class=HTMLResponse, include_in_schema=False)
async def serve_frontend():
    """Serve the single-page UI (index.html)."""
    if FRONTEND_PATH.exists():
        return HTMLResponse(content=FRONTEND_PATH.read_text(encoding="utf-8"))
    return HTMLResponse(
        "<h1>FaaS Platform</h1><p>Frontend not found — place index.html in frontend/</p>"
    )


@app.get("/health", summary="System health check")
async def health_check():
    """Run all tool and cluster checks. Returns tool statuses + config."""
    results = run_all_checks()
    overall_ok = all(i["found"] for i in results.values() if i["critical"])
    return {
        "status": "healthy" if overall_ok else "degraded",
        "tools": results,
        "config": {
            "registry_prefix": REGISTRY_PREFIX,
            "tenant_namespace": TENANT_NAMESPACE,
            "supported_languages": SUPPORTED_LANGUAGES,
        },
    }


@app.get("/languages", summary="List supported runtimes")
async def list_languages():
    """Return all supported runtime languages with their template and entrypoint."""
    from config import LANGUAGE_CONFIG
    return {
        lang: {
            "template": cfg["template"],
            "entrypoint": cfg["entrypoint"],
            "description": cfg["description"],
        }
        for lang, cfg in LANGUAGE_CONFIG.items()
    }


@app.post("/deploy", summary="Deploy a function (SSE stream)")
async def deploy_function(req: DeployRequest):
    """
    Deploy user code via Knative func CLI. Streams build logs as SSE.

    SSE event types:
      step      — high-level pipeline phase
      log       — raw subprocess output line
      url       — live Knative URL (on success)
      done      — final JSON summary {status, function_name, url, ...}
      error     — error message (on failure)
      exit_code — raw process exit code
    """
    job_id = str(uuid.uuid4())[:8]
    work_dir = WORKSPACE_BASE / f"{job_id}-{req.name}"
    work_dir.mkdir(parents=True, exist_ok=True)

    logger.info("[%s] Deploy: name=%s lang=%s", job_id, req.name, req.language)
    deploy_jobs[job_id] = {"status": "running", "function_name": req.name}

    return StreamingResponse(
        deploy_pipeline(job_id, req, work_dir),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",  # Disable nginx response buffering
            "X-Job-ID": job_id,
        },
    )


@app.get("/functions", summary="List deployed functions")
async def get_functions():
    """List all Knative Services in the tenant-functions namespace."""
    # Quick cluster reachability check before calling list_ksvc
    probe = kubectl("get", "namespace", TENANT_NAMESPACE, "--no-headers", timeout=10)
    if probe.returncode != 0:
        raise HTTPException(
            status_code=503,
            detail=f"Cannot reach cluster: {probe.stderr.strip()[:200]}",
        )
    return {"functions": list_ksvc(TENANT_NAMESPACE), "namespace": TENANT_NAMESPACE}


@app.delete("/functions/{name}", response_model=DeleteResponse, summary="Delete a function")
async def delete_function(name: str):
    """Delete a Knative Service from the tenant-functions namespace."""
    if not re.match(r"^[a-z][a-z0-9-]{2,49}$", name):
        raise HTTPException(status_code=400, detail="Invalid function name format.")

    result = kubectl(
        "delete", "ksvc", name,
        "-n", TENANT_NAMESPACE,
        "--ignore-not-found=true",
        timeout=30,
    )
    if result.returncode != 0:
        raise HTTPException(
            status_code=500,
            detail=f"Delete failed: {result.stderr.strip()[:200]}",
        )

    logger.info("Deleted function '%s' from '%s'", name, TENANT_NAMESPACE)
    return DeleteResponse(message=f"Function '{name}' deleted.", function_name=name)


@app.get("/logs/{name}", summary="Tail recent pod logs for a function")
async def get_logs(name: str, tail: int = 100):
    """Return the last N log lines from pods backing a Knative Service."""
    if not re.match(r"^[a-z][a-z0-9-]{2,49}$", name):
        raise HTTPException(status_code=400, detail="Invalid function name format.")

    result = kubectl(
        "logs",
        "-n", TENANT_NAMESPACE,
        "-l", f"serving.knative.dev/service={name}",
        "--prefix",
        f"--tail={tail}",
        timeout=30,
    )

    if result.returncode != 0:
        return {
            "function_name": name,
            "logs": [],
            "message": "No active pods (function may be scaled to zero). Invoke the URL to trigger a cold start.",
        }

    lines = result.stdout.strip().split("\n") if result.stdout.strip() else []
    return {"function_name": name, "namespace": TENANT_NAMESPACE, "lines": len(lines), "logs": lines}


@app.get("/jobs/{job_id}", summary="Get deploy job status")
async def get_job(job_id: str):
    """Check the in-memory status of a deploy job by its job ID."""
    job = deploy_jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job '{job_id}' not found.")
    return {"job_id": job_id, **job}
