"""routers/jobs.py — deploy job status lookup."""

from fastapi import APIRouter, HTTPException

from config import logger
from services import job_store

router = APIRouter(tags=["jobs"])


@router.get("/jobs/{job_id}", summary="Get deploy job status")
async def get_job(job_id: str):
    """Check the status of a deploy job by its job ID (shared across all
    orchestrator replicas via Redis — see services/job_store.py)."""
    try:
        job = await job_store.get_job(job_id)
    except Exception:
        logger.exception("[%s] Job store unreachable", job_id)
        raise HTTPException(status_code=503, detail="Job store temporarily unavailable, try again shortly.")
    if not job:
        raise HTTPException(status_code=404, detail=f"Job '{job_id}' not found.")
    return {"job_id": job_id, **job}
