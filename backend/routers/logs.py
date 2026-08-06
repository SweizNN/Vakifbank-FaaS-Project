"""routers/logs.py — tail pod logs for a deployed function."""

import re

from fastapi import APIRouter, HTTPException

from config import TENANT_NAMESPACE
from services.k8s import kubectl

router = APIRouter(tags=["logs"])


@router.get("/logs/{name}", summary="Tail recent pod logs for a function")
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
