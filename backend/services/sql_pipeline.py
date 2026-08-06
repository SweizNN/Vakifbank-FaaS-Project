"""
services/sql_pipeline.py — SQL-to-API deploy orchestrator
=============================================================
Reuses the *same* func-create / func-deploy / poll-ready steps as the
code-editor flow (services/pipeline.py) — this is not a parallel deployment
mechanism. Only two things are SQL-specific: generating the Python source
(generators/sql_to_python.py) and provisioning the DB-credential Secret
(services/secret_provisioning.py).

v1 scope decision: every deploy re-scaffolds from a fresh `func create`, so a
prior deploy's secret-env bindings aren't preserved through the generic
code-editor Edit-modal redeploy path. There is deliberately no update/edit
path for SQL-to-API functions in v1 — changing the query/connection means
deleting and redeploying through this same flow again (the Secret name is
deterministic and `kubectl apply` is idempotent, so this cleanly re-provisions
and rotates the API key). Consequently this orchestrator never calls
step_annotate_state — nothing gets written to the code-editor's snippet/code
annotations, so the Edit modal correctly reports "no code available" for
these functions (its existing "delete and re-deploy" guidance happens to be
exactly the right advice here too).
"""

import json
import shutil
from pathlib import Path
from typing import AsyncGenerator

from config import DEPLOY_TIMEOUT, REGISTRY_PREFIX, TENANT_NAMESPACE, logger
from generators.sql_to_python import generate_function_code, get_dependencies
from models import SqlDeployRequest
from services.dependencies import apply_dependencies
from services.pipeline import deploy_jobs, step_func_deploy, step_poll_ready, step_scaffold
from services.secret_provisioning import generate_api_key, provision_db_secret_and_envs
from services.sql_validator import SqlValidationError, validate_select_only
from services.sse import sse_event


async def run_sql_api_deploy(job_id: str, req: SqlDeployRequest, work_dir: Path) -> AsyncGenerator[str, None]:
    try:
        try:
            validated_sql = validate_select_only(req.sql_query)
        except SqlValidationError as e:
            yield sse_event("error", f"❌ Query rejected: {e}")
            yield sse_event("done", json.dumps({"status": "error", "job_id": job_id}))
            return

        scaffold_result: dict = {}
        async for frame in step_scaffold(job_id, req.name, "python", work_dir, scaffold_result):
            yield frame
        if not scaffold_result.get("ok"):
            yield sse_event("done", json.dumps({"status": "error", "job_id": job_id}))
            return
        fn_dir = scaffold_result["fn_dir"]

        yield sse_event("step", "🧬 Generating SQL-to-API function code")
        generated_code = generate_function_code(req.db_type, validated_sql)
        entrypoint = fn_dir / "function" / "func.py"
        entrypoint.parent.mkdir(parents=True, exist_ok=True)
        entrypoint.write_text(generated_code, encoding="utf-8")
        yield sse_event("log", f"   → Wrote {len(generated_code)} bytes to func.py")

        api_key = generate_api_key()
        db_fields = {
            "db_host": req.db_host,
            "db_port": str(req.db_port),
            "db_name": req.db_name,
            "db_user": req.db_user,
            "db_password": req.db_password,
        }
        secret_result: dict = {}
        async for frame in provision_db_secret_and_envs(fn_dir, req.name, db_fields, api_key, secret_result):
            yield frame
        if not secret_result.get("ok"):
            yield sse_event("done", json.dumps({"status": "error", "job_id": job_id}))
            return

        deps = get_dependencies(req.db_type)
        applied = apply_dependencies(fn_dir, "python", deps)
        if applied:
            yield sse_event("log", f"   → Added {len(applied)} librar{'y' if len(applied) == 1 else 'ies'} to manifest: {', '.join(applied)}")

        fn_image = f"{REGISTRY_PREFIX}/faas-fn-{req.name}"
        deploy_result: dict = {}
        # No plain --env flags here — func.yaml already carries the
        # secret-backed bindings from provision_db_secret_and_envs().
        async for frame in step_func_deploy(req.name, fn_dir, fn_image, TENANT_NAMESPACE, [], deploy_result):
            yield frame
        if not deploy_result.get("ok"):
            yield sse_event("done", json.dumps({"status": "error", "job_id": job_id}))
            return

        poll_result: dict = {}
        async for frame in step_poll_ready(req.name, DEPLOY_TIMEOUT, poll_result):
            yield frame
        if not poll_result.get("ok"):
            yield sse_event("done", json.dumps({"status": "error", "job_id": job_id}))
            return
        url = poll_result["url"]

        # ── Success ────────────────────────────────────────────────────────
        # api_key deliberately never goes into deploy_jobs — GET /jobs/{id} is
        # unauthenticated and has no expiry, so anyone who learned/guessed the
        # job_id could re-fetch it later. It's emitted exactly once, in this
        # SSE frame only.
        result_payload = {
            "status": "success",
            "job_id": job_id,
            "function_name": req.name,
            "url": url,
            "language": "python",
            "db_type": req.db_type,
            "image": fn_image,
        }
        deploy_jobs[job_id] = result_payload

        yield sse_event("step", f"✅ '{req.name}' is LIVE!")
        yield sse_event("url", url)
        yield sse_event("done", json.dumps({**result_payload, "api_key": api_key}))

    except Exception as exc:
        logger.exception("[%s] Unexpected error during SQL-to-API deploy", job_id)
        yield sse_event("error", f"❌ Internal error: {exc}")
        yield sse_event("done", json.dumps({"status": "error", "job_id": job_id, "error": str(exc)}))

    finally:
        try:
            shutil.rmtree(work_dir, ignore_errors=True)
            logger.info("[%s] Cleaned up workspace: %s", job_id, work_dir)
        except Exception:
            pass
