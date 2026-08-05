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
import subprocess
import json
import base64
from contextlib import asynccontextmanager

# Windows'ta Uvicorn'un subprocess çalıştırmayı engelleyen (NotImplementedError) ayarını eziyoruz
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from config import (
    FRONTEND_PATH,
    REGISTRY_PREFIX,
    SUPPORTED_LANGUAGES,
    TENANT_NAMESPACE,
    WORKSPACE_BASE,
    logger,
)
from health_check import run_all_checks
from k8s import kubectl, list_ksvc, get_revisions, rollback_to_revision
from models import DeleteResponse, DeployRequest, ProxyRequest
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

# index.html references its CSS/JS as /static/... — serve everything else in
# frontend/ (style.css, js/*.js) from there. index.html itself is returned by
# the explicit route below, not through this mount.
app.mount("/static", StaticFiles(directory=FRONTEND_PATH.parent), name="static")


# ── Routes ────────────────────────────────────────────────────────────────────


@app.get("/", response_class=HTMLResponse, include_in_schema=False)
async def serve_frontend():
    """Serve the single-page UI (index.html)."""
    if FRONTEND_PATH.exists():
        return HTMLResponse(content=FRONTEND_PATH.read_text(encoding="utf-8"))
    return HTMLResponse(
        "<h1>FaaS Platform</h1><p>Frontend not found — place index.html in frontend/</p>"
    )


@app.get("/health", summary="Kubernetes liveness/readiness probe")
async def health_check():
    """Lightweight health check for Kubernetes probes. Always returns 200 instantly."""
    return {"status": "ok"}


@app.get("/health/detail", summary="Full system health check")
async def health_check_detail():
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
    # Duplicate name check
    if not req.is_update:
        existing_funcs = list_ksvc(TENANT_NAMESPACE)
        if any(f.get("name") == req.name for f in existing_funcs):
            raise HTTPException(
                status_code=409,
                detail=f"Function '{req.name}' already exists! Please choose a different name or use Update mode."
            )

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
    probe = kubectl("get", "namespace", TENANT_NAMESPACE, "--no-headers", timeout=10)
    if probe.returncode != 0:
        raise HTTPException(
            status_code=503,
            detail=f"Cannot reach cluster: {probe.stderr.strip()[:200]}",
        )
    return {"functions": list_ksvc(TENANT_NAMESPACE), "namespace": TENANT_NAMESPACE}


@app.get("/functions/{name}/code", summary="Get function code and config")
async def get_function_code(name: str):
    """Retrieve base64 encoded source code and config from ksvc annotations."""
    try:
        cmd = ["kubectl", "get", "ksvc", name, "-n", TENANT_NAMESPACE, "-o", "json"]
        result = subprocess.run(cmd, capture_output=True, text=True)
        
        if result.returncode != 0:
            raise HTTPException(status_code=404, detail=f"Function '{name}' not found in cluster.")
        
        ksvc = json.loads(result.stdout)
        annotations = ksvc.get("metadata", {}).get("annotations", {})
        
        # snippet-b64 = raw editor content (user-written only, preferred)
        # code-b64    = full entrypoint file (fallback for older deploys)
        snippet_b64 = annotations.get("faas.vakifbank.com/snippet-b64", "")
        code_b64 = annotations.get("faas.vakifbank.com/code-b64", "")
        lang = annotations.get("faas.vakifbank.com/lang", "")
        yaml_b64 = annotations.get("faas.vakifbank.com/yaml-b64", "")
        
        display_b64 = snippet_b64 or code_b64   # prefer snippet, fall back to full code
        
        if not display_b64:
            # This function was deployed before the Edit feature existed
            raise HTTPException(
                status_code=422,
                detail=f"Function '{name}' was deployed before the Edit feature was added. Please delete and re-deploy it to enable editing."
            )
            
        code = base64.b64decode(display_b64).decode("utf-8")
        config_yaml = base64.b64decode(yaml_b64).decode("utf-8") if yaml_b64 else ""
        
        return {
            "name": name,
            "language": lang,
            "code": code,
            "config_yaml": config_yaml
        }
    except HTTPException:
        raise  # Re-raise HTTP exceptions as-is, don't wrap them
    except Exception as e:
        logger.error("[get_function_code] Unexpected error for '%s': %s", name, e)
        raise HTTPException(status_code=500, detail=f"Unexpected error: {str(e)}")


@app.get("/functions/{name}/revisions", summary="List all revisions for a function")
async def list_function_revisions(name: str):
    """Return all Knative Revisions for a function, newest first, with code metadata."""
    if not re.match(r"^[a-z][a-z0-9-]{2,49}$", name):
        raise HTTPException(status_code=400, detail="Invalid function name format.")
    revisions = get_revisions(name)
    return {"function_name": name, "revisions": revisions}


@app.post("/functions/{name}/rollback", summary="Roll back traffic to a specific revision")
async def rollback_function(name: str, body: dict):
    """Patch the Knative Service to point 100% traffic to a specific revision."""
    revision_name = body.get("revision_name", "")
    if not revision_name:
        raise HTTPException(status_code=400, detail="revision_name is required.")
    if not re.match(r"^[a-z][a-z0-9-]{2,49}$", name):
        raise HTTPException(status_code=400, detail="Invalid function name format.")

    success, message = rollback_to_revision(name, revision_name)
    if not success:
        raise HTTPException(status_code=500, detail=f"Rollback failed: {message}")
    return {"status": "ok", "message": message, "function_name": name, "revision_name": revision_name}


@app.get("/functions/{name}/revision/{revision_name}/code", summary="Get code saved in a specific revision")
async def get_revision_code(name: str, revision_name: str):
    """Retrieve source code and config from a specific Knative Revision's annotations."""
    try:
        result = subprocess.run(
            ["kubectl", "get", "revision", revision_name, "-n", TENANT_NAMESPACE, "-o", "json"],
            capture_output=True, text=True, timeout=15,
        )
        if result.returncode != 0:
            raise HTTPException(status_code=404, detail=f"Revision '{revision_name}' not found.")

        rev = json.loads(result.stdout)
        annotations = rev.get("metadata", {}).get("annotations", {})
        snippet_b64 = annotations.get("faas.vakifbank.com/snippet-b64", "")
        code_b64 = annotations.get("faas.vakifbank.com/code-b64", "")
        lang = annotations.get("faas.vakifbank.com/lang", "")
        yaml_b64 = annotations.get("faas.vakifbank.com/yaml-b64", "")

        display_b64 = snippet_b64 or code_b64
        if not display_b64:
            raise HTTPException(status_code=422, detail="This revision has no saved code (deployed before Edit feature).")

        code = base64.b64decode(display_b64).decode("utf-8")
        config_yaml = base64.b64decode(yaml_b64).decode("utf-8") if yaml_b64 else ""
        return {"name": name, "revision_name": revision_name, "language": lang, "code": code, "config_yaml": config_yaml}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))



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


@app.post("/proxy", summary="Proxy requests to bypass CORS for testing functions")
async def proxy_request(req: ProxyRequest):
    import urllib.request
    import urllib.error
    import json
    
    data = json.dumps(req.body).encode('utf-8')
    headers = req.headers
    headers['Content-Type'] = 'application/json'
    
    request = urllib.request.Request(req.url, data=data, headers=headers, method=req.method)
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            status = response.getcode()
            body_bytes = response.read()
    except urllib.error.HTTPError as e:
        status = e.code
        body_bytes = e.read()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
        
    try:
        resp_json = json.loads(body_bytes)
        return {"status": status, "body": resp_json}
    except json.JSONDecodeError:
        return {"status": status, "body": body_bytes.decode('utf-8')}
