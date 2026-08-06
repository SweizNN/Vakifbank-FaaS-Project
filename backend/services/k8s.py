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
        # Note: the actual code/config payload is intentionally NOT included
        # here — it's fetched on demand via GET /functions/{name}/revision/
        # {revision_name}/code (see main.py) when the user clicks "Load Code",
        # so the revision list stays lightweight even with many revisions.
        revisions.append({
            "name": rev_name,
            "created_at": meta.get("creationTimestamp", ""),
            "is_active": rev_name == current_traffic_revision,
            "has_code": bool(annotations.get("faas.vakifbank.com/snippet-b64") or
                             annotations.get("faas.vakifbank.com/code-b64")),
        })
    return revisions


def service_exists(name: str, namespace: str = TENANT_NAMESPACE) -> bool:
    """True if a Knative Service with this name already exists (used by both
    the code-editor and SQL-to-API deploy flows for the duplicate-name check)."""
    return any(f.get("name") == name for f in list_ksvc(namespace))


def apply_secret(
    name: str,
    string_data: dict[str, str],
    namespace: str = TENANT_NAMESPACE,
    labels: dict[str, str] | None = None,
    timeout: int = 30,
) -> subprocess.CompletedProcess:
    """
    Create/update an Opaque Secret via `kubectl apply -f -`, piping a JSON
    manifest over stdin. Deliberately NOT built on `kubectl(*args)` with
    `--from-literal=KEY=value` — that would put the credential in the
    orchestrator process's own argv, visible to anything that can read
    `/proc/<pid>/cmdline` or run `ps` inside the pod. Idempotent, mirroring the
    `kubectl create secret ... --dry-run=client -o yaml | kubectl apply -f -`
    idiom already used for docker-hub-creds in .github/workflows/deploy.yml.
    """
    manifest = {
        "apiVersion": "v1",
        "kind": "Secret",
        "type": "Opaque",
        "metadata": {"name": name, "namespace": namespace, "labels": labels or {}},
        "stringData": string_data,
    }
    logger.debug("kubectl apply -f - (Secret/%s, keys=%s)", name, list(string_data.keys()))
    return subprocess.run(
        ["kubectl", "apply", "-f", "-"],
        input=json.dumps(manifest),
        capture_output=True,
        text=True,
        timeout=timeout,
    )  # never log `manifest` itself — it contains credentials


def delete_secret(name: str, namespace: str = TENANT_NAMESPACE, timeout: int = 30) -> subprocess.CompletedProcess:
    return kubectl("delete", "secret", name, "-n", namespace, "--ignore-not-found=true", timeout=timeout)


def annotate_ksvc(name: str, annotations: dict[str, str], namespace: str = TENANT_NAMESPACE, timeout: int = 30) -> subprocess.CompletedProcess:
    pairs = [f"{k}={v}" for k, v in annotations.items()]
    return kubectl("annotate", "ksvc", name, "-n", namespace, "--overwrite", *pairs, timeout=timeout)


def annotate_revision(revision_name: str, annotations: dict[str, str], namespace: str = TENANT_NAMESPACE, timeout: int = 30) -> subprocess.CompletedProcess:
    pairs = [f"{k}={v}" for k, v in annotations.items()]
    return kubectl("annotate", "revision", revision_name, "-n", namespace, "--overwrite", *pairs, timeout=timeout)


def get_latest_revision_name(service_name: str, namespace: str = TENANT_NAMESPACE, timeout: int = 15) -> Optional[str]:
    result = kubectl(
        "get", "ksvc", service_name, "-n", namespace,
        "-o", "jsonpath={.status.latestCreatedRevisionName}",
        timeout=timeout,
    )
    name = result.stdout.strip()
    return name if (result.returncode == 0 and name) else None


def rollback_to_revision(service_name: str, revision_name: str, namespace: str = TENANT_NAMESPACE) -> tuple[bool, str]:
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

