"""routers/sql_deploy.py — SQL-to-API deploy endpoint (SSE stream)."""

import uuid

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from config import TENANT_NAMESPACE, WORKSPACE_BASE, logger
from models import SqlDeployRequest
from services.k8s import service_exists
from services.pipeline import deploy_jobs
from services.sql_pipeline import run_sql_api_deploy

router = APIRouter(tags=["sql-deploy"])


@router.post("/sql/deploy", summary="Deploy a SQL-to-API function (SSE stream)")
async def sql_deploy_function(req: SqlDeployRequest):
    if service_exists(req.name, TENANT_NAMESPACE):
        raise HTTPException(
            status_code=409,
            detail=f"Function '{req.name}' already exists! Please choose a different name."
        )

    job_id = str(uuid.uuid4())[:8]
    work_dir = WORKSPACE_BASE / f"{job_id}-{req.name}"
    work_dir.mkdir(parents=True, exist_ok=True)

    logger.info("[%s] SQL-to-API deploy: name=%s db_type=%s", job_id, req.name, req.db_type)
    deploy_jobs[job_id] = {"status": "running", "function_name": req.name}

    return StreamingResponse(
        run_sql_api_deploy(job_id, req, work_dir),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "X-Job-ID": job_id,
        },
    )
