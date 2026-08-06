"""routers/jobs.py — deploy job status lookup."""

from fastapi import APIRouter, HTTPException

from services.pipeline import deploy_jobs

router = APIRouter(tags=["jobs"])


@router.get("/jobs/{job_id}", summary="Get deploy job status")
async def get_job(job_id: str):
    """Check the in-memory status of a deploy job by its job ID."""
    job = deploy_jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job '{job_id}' not found.")
    return {"job_id": job_id, **job}
