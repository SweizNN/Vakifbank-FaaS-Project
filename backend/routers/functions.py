"""routers/functions.py — list/inspect/rollback/delete deployed functions."""

import base64
import json
import re

from fastapi import APIRouter, HTTPException

from config import TENANT_NAMESPACE, logger
from models import DeleteResponse
from services.k8s import (
    delete_secret,
    get_revisions,
    kubectl,
    list_ksvc,
    rollback_to_revision,
)
from services.secret_provisioning import secret_name_for

router = APIRouter(tags=["functions"])

_NAME_RE = re.compile(r"^[a-z][a-z0-9-]{2,49}$")


@router.get("/functions", summary="List deployed functions")
async def get_functions():
    """List all Knative Services in the tenant-functions namespace."""
    probe = kubectl("get", "namespace", TENANT_NAMESPACE, "--no-headers", timeout=10)
    if probe.returncode != 0:
        raise HTTPException(
            status_code=503,
            detail=f"Cannot reach cluster: {probe.stderr.strip()[:200]}",
        )
    return {"functions": list_ksvc(TENANT_NAMESPACE), "namespace": TENANT_NAMESPACE}


@router.get("/functions/{name}/code", summary="Get function code and config")
async def get_function_code(name: str):
    """Retrieve base64 encoded source code and config from ksvc annotations."""
    try:
        result = kubectl("get", "ksvc", name, "-n", TENANT_NAMESPACE, "-o", "json")

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
            # This function was deployed before the Edit feature existed —
            # or (for SQL-to-API functions) code-editor annotations were never
            # written in the first place; "delete and re-deploy" is correct
            # advice either way, since v1 has no SQL-to-API update path.
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


@router.get("/functions/{name}/revisions", summary="List all revisions for a function")
async def list_function_revisions(name: str):
    """Return all Knative Revisions for a function, newest first, with code metadata."""
    if not _NAME_RE.match(name):
        raise HTTPException(status_code=400, detail="Invalid function name format.")
    revisions = get_revisions(name)
    return {"function_name": name, "revisions": revisions}


@router.post("/functions/{name}/rollback", summary="Roll back traffic to a specific revision")
async def rollback_function(name: str, body: dict):
    """Patch the Knative Service to point 100% traffic to a specific revision."""
    revision_name = body.get("revision_name", "")
    if not revision_name:
        raise HTTPException(status_code=400, detail="revision_name is required.")
    if not _NAME_RE.match(name):
        raise HTTPException(status_code=400, detail="Invalid function name format.")

    success, message = rollback_to_revision(name, revision_name)
    if not success:
        raise HTTPException(status_code=500, detail=f"Rollback failed: {message}")
    return {"status": "ok", "message": message, "function_name": name, "revision_name": revision_name}


@router.get("/functions/{name}/revision/{revision_name}/code", summary="Get code saved in a specific revision")
async def get_revision_code(name: str, revision_name: str):
    """Retrieve source code and config from a specific Knative Revision's annotations."""
    try:
        result = kubectl("get", "revision", revision_name, "-n", TENANT_NAMESPACE, "-o", "json", timeout=15)
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


@router.delete("/functions/{name}", response_model=DeleteResponse, summary="Delete a function")
async def delete_function(name: str):
    """Delete a Knative Service from the tenant-functions namespace."""
    if not _NAME_RE.match(name):
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

    # Best-effort cleanup — harmless no-op (--ignore-not-found) for functions
    # that were never SQL-to-API (i.e. have no such Secret).
    delete_secret(secret_name_for(name), TENANT_NAMESPACE)

    logger.info("Deleted function '%s' from '%s'", name, TENANT_NAMESPACE)
    return DeleteResponse(message=f"Function '{name}' deleted.", function_name=name)
