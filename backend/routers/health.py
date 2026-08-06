"""routers/health.py — cluster/tool health checks."""

from fastapi import APIRouter

from config import REGISTRY_PREFIX, SUPPORTED_LANGUAGES, TENANT_NAMESPACE
from services.health_check import run_all_checks

router = APIRouter(tags=["health"])


@router.get("/health", summary="Kubernetes liveness/readiness probe")
async def health_check():
    """Lightweight health check for Kubernetes probes. Always returns 200 instantly."""
    return {"status": "ok"}


@router.get("/health/detail", summary="Full system health check")
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
