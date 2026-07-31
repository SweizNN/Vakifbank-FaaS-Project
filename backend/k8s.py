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
