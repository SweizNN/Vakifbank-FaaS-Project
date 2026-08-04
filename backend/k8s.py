"""
k8s.py — kubectl helper functions
==================================
Thin wrappers around kubectl CLI calls.
All Kubernetes interaction goes through this module so the rest of
the application never constructs kubectl commands directly.
"""

import json
import subprocess
from typing import Optional

from config import TENANT_NAMESPACE, logger


def kubectl(*args: str, timeout: int = 30) -> subprocess.CompletedProcess:
    """
    Run a kubectl command and return the CompletedProcess result.
    Raises subprocess.TimeoutExpired if the command exceeds `timeout` seconds.
    """
    cmd = ["kubectl", *args]
    logger.debug("kubectl: %s", " ".join(cmd))
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


def get_ksvc_url(name: str) -> Optional[str]:
    """Return the live URL for a Knative Service, or None if not yet assigned."""
    result = kubectl(
        "get", "ksvc", name,
        "-n", TENANT_NAMESPACE,
        "-o", "jsonpath={.status.url}",
    )
    url = result.stdout.strip()
    return url if url else None


def get_ksvc_ready(name: str) -> bool:
    """Return True only when the Knative Service's Ready condition is True."""
    result = kubectl(
        "get", "ksvc", name,
        "-n", TENANT_NAMESPACE,
        "-o", "jsonpath={.status.conditions[?(@.type=='Ready')].status}",
    )
    return result.stdout.strip() == "True"


def list_ksvc(namespace: str = TENANT_NAMESPACE) -> list[dict]:
    """
    Return a list of Knative Service summary dicts from `namespace`.
    Returns an empty list if the namespace is empty or kubectl fails.
    """
    result = kubectl("get", "ksvc", "-n", namespace, "-o", "json", timeout=20)
    if result.returncode != 0:
        return []

    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError:
        return []

    services = []
    for item in data.get("items", []):
        meta = item.get("metadata", {})
        status = item.get("status", {})
        conditions = status.get("conditions", [])
        ready = next(
            (c["status"] == "True" for c in conditions if c.get("type") == "Ready"),
            False,
        )
        services.append({
            "name": meta.get("name", ""),
            "url": status.get("url", ""),
            "ready": ready,
            "created_at": meta.get("creationTimestamp", ""),
            "namespace": namespace,
            "image": (
                item.get("spec", {})
                    .get("template", {})
                    .get("spec", {})
                    .get("containers", [{}])[0]
                    .get("image", "")
            ),
        })
    return services


def get_revisions(name: str, namespace: str = TENANT_NAMESPACE) -> list[dict]:
    """
    Return a list of Knative Revisions for a given Service, newest first.
    Each dict contains the revision name, creation time, whether it is currently
    receiving 100% traffic, and any faas.vakifbank.com annotations saved during deploy.
    """
    # Fetch traffic config from the ksvc so we know the current active revision
    ksvc_result = kubectl("get", "ksvc", name, "-n", namespace, "-o", "json", timeout=15)
    current_traffic_revision = ""
    if ksvc_result.returncode == 0:
        try:
            ksvc_data = json.loads(ksvc_result.stdout)
            traffic = ksvc_data.get("status", {}).get("traffic", [])
            for t in traffic:
                if t.get("percent", 0) == 100:
                    current_traffic_revision = t.get("revisionName", "")
                    break
        except Exception:
            pass

    result = kubectl(
        "get", "revisions",
        "-n", namespace,
        "-l", f"serving.knative.dev/service={name}",
        "-o", "json",
        "--sort-by=.metadata.creationTimestamp",
        timeout=20,
    )
    if result.returncode != 0:
        return []

    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError:
        return []

    revisions = []
    for item in reversed(data.get("items", [])):  # newest first
        meta = item.get("metadata", {})
        annotations = meta.get("annotations", {})
        rev_name = meta.get("name", "")
        revisions.append({
            "name": rev_name,
            "created_at": meta.get("creationTimestamp", ""),
            "is_active": rev_name == current_traffic_revision,
            "has_code": bool(annotations.get("faas.vakifbank.com/snippet-b64") or
                             annotations.get("faas.vakifbank.com/code-b64")),
            "language": annotations.get("faas.vakifbank.com/lang", ""),
            "snippet_b64": annotations.get("faas.vakifbank.com/snippet-b64", ""),
            "code_b64": annotations.get("faas.vakifbank.com/code-b64", ""),
            "yaml_b64": annotations.get("faas.vakifbank.com/yaml-b64", ""),
        })
    return revisions


def rollback_to_revision(service_name: str, revision_name: str, namespace: str = TENANT_NAMESPACE) -> tuple[bool, str]:
    """
    Point 100% of traffic for `service_name` to `revision_name`.
    Returns (success: bool, message: str).
    """
    patch = json.dumps({
        "spec": {
            "traffic": [
                {"revisionName": revision_name, "percent": 100, "latestRevision": False}
            ]
        }
    })
    result = kubectl(
        "patch", "ksvc", service_name,
        "-n", namespace,
        "--type=merge",
        "-p", patch,
        timeout=30,
    )
    if result.returncode == 0:
        return True, f"Traffic switched to revision '{revision_name}'."
    return False, result.stderr.strip()[:300]

