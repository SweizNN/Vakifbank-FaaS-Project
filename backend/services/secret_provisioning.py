"""
services/secret_provisioning.py — DB credentials + API key → K8s Secret
===========================================================================
Named `secret_provisioning` rather than `secrets` specifically to avoid
shadowing the stdlib `secrets` module (used here for token_urlsafe) — Python's
absolute-import rules would resolve `import secrets` correctly either way,
but the name clash is needless confusion for a reader.

Runs after the function directory has been scaffolded (`func create`, i.e.
after step_scaffold — needs fn_dir/func.yaml to exist) and before `func
deploy`: applies a K8s Secret holding the DB credentials + a freshly
generated API key, then binds each field into func.yaml as a secret-backed
env var via `func config envs add --value='{{ secret:name:key }}'` — verified
locally against func CLI v0.49.2 as officially documented syntax. `func
deploy` then translates these into `valueFrom.secretKeyRef` on the resulting
container automatically, so there's no manual `kubectl patch` against the
Knative Service's container spec.
"""

import secrets as py_secrets
from pathlib import Path
from typing import AsyncGenerator

from config import TENANT_NAMESPACE
from services.k8s import apply_secret
from services.sse import sse_event, stream_subprocess, parse_exit_code

# env var name -> key inside the Secret
_ENV_BINDINGS = {
    "DB_HOST": "db_host",
    "DB_PORT": "db_port",
    "DB_NAME": "db_name",
    "DB_USER": "db_user",
    "DB_PASSWORD": "db_password",
    "API_KEY": "api_key",
}


def secret_name_for(function_name: str) -> str:
    return f"{function_name}-db-secret"


def generate_api_key() -> str:
    return py_secrets.token_urlsafe(32)


async def provision_db_secret_and_envs(
    fn_dir: Path,
    function_name: str,
    db_fields: dict[str, str],
    api_key: str,
    result: dict,
    namespace: str = TENANT_NAMESPACE,
) -> AsyncGenerator[str, None]:
    """
    1) kubectl-applies the Secret (db_fields + api_key).
    2) Runs `func config envs add` once per field inside fn_dir, streaming
       output through the same stream_subprocess() used by func create/deploy
       so failures surface as ordinary SSE log/error frames.
    Sets result['ok'] = True/False.
    """
    name = secret_name_for(function_name)
    yield sse_event("step", f"🔐 Provisioning database credentials → Secret '{name}'")

    string_data = {**db_fields, "api_key": api_key}
    apply_result = apply_secret(
        name,
        string_data,
        namespace=namespace,
        labels={
            "app.kubernetes.io/managed-by": "faas-platform",
            "faas.vakifbank.com/function": function_name,
        },
    )
    if apply_result.returncode != 0:
        yield sse_event("error", f"❌ Failed to create Secret: {apply_result.stderr.strip()[:200]}")
        result["ok"] = False
        return
    yield sse_event("log", f"   → Secret '{name}' applied in namespace '{namespace}'")

    for env_name, key in _ENV_BINDINGS.items():
        cmd = [
            "func", "config", "envs", "add",
            f"--name={env_name}",
            f"--value={{{{ secret:{name}:{key} }}}}",
        ]
        last_exit = 0
        async for frame in stream_subprocess(cmd, cwd=str(fn_dir)):
            if "exit_code" in frame:
                last_exit = parse_exit_code(frame)
            else:
                yield frame
        if last_exit != 0:
            yield sse_event("error", f"❌ Failed to bind secret env '{env_name}' (exit {last_exit})")
            result["ok"] = False
            return

    yield sse_event("log", "   → All secret-backed environment variables bound to func.yaml")
    result["ok"] = True
