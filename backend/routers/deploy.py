"""routers/deploy.py — code-editor deploy endpoint (SSE stream)."""

import uuid

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from config import TENANT_NAMESPACE, WORKSPACE_BASE, logger
from models import DeployRequest
from services.k8s import service_exists
from services.pipeline import deploy_jobs, run_code_editor_deploy

router = APIRouter(tags=["deploy"])


@router.post("/deploy", summary="Deploy a function (SSE stream)")
async def deploy_function(req: DeployRequest):
    if not req.is_update and service_exists(req.name, TENANT_NAMESPACE):
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
        run_code_editor_deploy(job_id, req, work_dir),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",  # Disable nginx response buffering
            "X-Job-ID": job_id,
        },
    )
