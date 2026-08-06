#!/usr/bin/env python3
"""
health_check.py — Phase 1 Startup Tool Verifier
================================================
Verifies all required CLI tools are accessible in PATH and that
Kubernetes (kubectl) can reach the cluster.

Run directly: python health_check.py
Called by:   FastAPI startup event (via importlib)
Returns:     Dict[str, ToolStatus] for the /health endpoint
"""

import subprocess
import shutil
import sys
import json
from dataclasses import dataclass, asdict
from typing import Optional


# ── Data Model ───────────────────────────────────────────────────────────────

@dataclass
class ToolStatus:
    name: str
    found: bool
    version: Optional[str] = None
    critical: bool = True
    error: Optional[str] = None

    def to_dict(self) -> dict:
        return asdict(self)


# ── Tool Definitions ──────────────────────────────────────────────────────────

TOOLS = [
    {
        "name": "docker",
        "cmd": ["docker", "--version"],
        "critical": True,
        "description": "Container runtime (required for Cloud Native Buildpacks)",
    },
    {
        "name": "kubectl",
        "cmd": ["kubectl", "version", "--client", "--output=json"],
        "critical": True,
        "description": "Kubernetes CLI (required for ksvc management)",
    },
    {
        "name": "func",
        "cmd": ["func", "version"],
        "critical": True,
        "description": "Knative func CLI (required for function deployment)",
    },
    {
        "name": "k3s",
        "cmd": ["k3s", "--version"],
        "critical": False,  # only present on server, not local dev
        "description": "Lightweight Kubernetes distribution (server only)",
    },
    {
        "name": "git",
        "cmd": ["git", "--version"],
        "critical": True,
        "description": "Version control (required by func CLI internals)",
    },
    {
        "name": "pack",
        "cmd": ["pack", "--version"],
        "critical": False,  # func uses its own embedded pack
        "description": "Cloud Native Buildpacks CLI (optional, used by func internally)",
    },
]


# ── Kubernetes Cluster Check ──────────────────────────────────────────────────

def check_kubernetes_cluster() -> ToolStatus:
    """Verify kubectl can reach the cluster and list namespaces."""
    status = ToolStatus(name="kubernetes-cluster", found=False, critical=True)
    if not shutil.which("kubectl"):
        status.error = "kubectl not found in PATH"
        return status

    try:
        result = subprocess.run(
            ["kubectl", "get", "namespace", "tenant-functions", "--no-headers"],
            capture_output=True, text=True, timeout=10
        )
        if result.returncode == 0:
            status.found = True
            status.version = "namespace 'tenant-functions' exists ✓"
        else:
            # Cluster reachable but namespace may not exist yet
            result2 = subprocess.run(
                ["kubectl", "cluster-info", "--request-timeout=5s"],
                capture_output=True, text=True, timeout=15
            )
            if result2.returncode == 0:
                status.found = True
                status.version = "cluster reachable (tenant-functions namespace not yet created)"
            else:
                status.error = result2.stderr.strip()[:200]
    except subprocess.TimeoutExpired:
        status.error = "kubectl timed out — is the cluster running?"
    except FileNotFoundError:
        status.error = "kubectl binary not found"
    except Exception as exc:
        status.error = str(exc)

    return status


def check_knative_serving() -> ToolStatus:
    """Verify Knative Serving CRDs are installed."""
    status = ToolStatus(name="knative-serving", found=False, critical=True)
    if not shutil.which("kubectl"):
        status.error = "kubectl not found in PATH"
        return status

    try:
        result = subprocess.run(
            ["kubectl", "get", "crd", "services.serving.knative.dev", "--no-headers"],
            capture_output=True, text=True, timeout=10
        )
        if result.returncode == 0:
            status.found = True
            status.version = "Knative Serving CRDs installed ✓"
        else:
            status.error = "Knative Serving CRDs not found — run: kubectl apply -f https://github.com/knative/serving/releases/..."
    except subprocess.TimeoutExpired:
        status.error = "kubectl timed out"
    except Exception as exc:
        status.error = str(exc)

    return status


# ── Core Checker ──────────────────────────────────────────────────────────────

def check_tool(tool: dict) -> ToolStatus:
    """Run a single tool version command and return its status."""
    status = ToolStatus(
        name=tool["name"],
        found=False,
        critical=tool["critical"],
    )

    if not shutil.which(tool["name"]):
        status.error = f"'{tool['name']}' not found in PATH"
        return status

    try:
        result = subprocess.run(
            tool["cmd"],
            capture_output=True, text=True, timeout=15
        )
        output = (result.stdout + result.stderr).strip()

        if tool["name"] == "kubectl" and result.returncode == 0:
            # Parse JSON output for kubectl
            try:
                data = json.loads(output)
                client_ver = data.get("clientVersion", {})
                status.version = f"v{client_ver.get('major', '?')}.{client_ver.get('minor', '?')}"
            except json.JSONDecodeError:
                status.version = output.split("\n")[0][:80]
            status.found = True
        elif result.returncode == 0:
            status.version = output.split("\n")[0][:80]
            status.found = True
        else:
            status.error = output[:200] or f"exit code {result.returncode}"

    except subprocess.TimeoutExpired:
        status.error = f"'{tool['name']}' timed out after 15s"
    except FileNotFoundError:
        status.error = f"'{tool['name']}' binary not found (PATH issue)"
    except Exception as exc:
        status.error = str(exc)

    return status


def run_all_checks() -> dict:
    """
    Run all tool and cluster checks.
    Returns a structured dict suitable for the /health API endpoint.
    """
    results = {}

    # Check CLI tools
    for tool in TOOLS:
        s = check_tool(tool)
        results[s.name] = s.to_dict()

    # Check Kubernetes cluster connectivity
    cluster_status = check_kubernetes_cluster()
    results[cluster_status.name] = cluster_status.to_dict()

    # Check Knative Serving
    knative_status = check_knative_serving()
    results[knative_status.name] = knative_status.to_dict()

    return results


def print_report(results: dict) -> bool:
    """Pretty-print results to stdout. Returns True if all critical tools OK."""
    print("\n" + "=" * 60)
    print("  VakifBank FaaS Platform - System Health Check")
    print("=" * 60)

    all_critical_ok = True

    for name, info in results.items():
        if info["found"]:
            icon = "[OK] "
        elif not info["critical"]:
            icon = "[WARN]"
        else:
            icon = "[FAIL]"
        status_str = info.get("version") or info.get("error") or "unknown"
        print(f"  {icon}  {name:<25} {status_str}")
        if not info["found"] and info["critical"]:
            all_critical_ok = False

    print("=" * 60)
    if all_critical_ok:
        print("  >>> All critical tools are available. Ready to deploy!")
    else:
        print("  !!! One or more CRITICAL tools are missing. Fix before deploying.")
    print("=" * 60 + "\n")

    return all_critical_ok


# ── Entry Point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    results = run_all_checks()
    ok = print_report(results)
    sys.exit(0 if ok else 1)
