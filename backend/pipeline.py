"""
pipeline.py — Knative func CLI deploy pipeline
================================================
Owns the entire deploy workflow as an async SSE generator:
  Step 1 → func create  (scaffold template)
  Step 2 → inject user code into entrypoint file
  Step 3 → func deploy  (Buildpack build + image push + ksvc creation)
  Step 4 → poll until Knative Service is Ready, then return the live URL

Nothing in here touches FastAPI directly — it's pure asyncio + subprocess,
making it testable in isolation without starting the HTTP server.
"""

import asyncio
import json
import os
import shutil
import time
import uuid
import subprocess
import threading
import queue
from pathlib import Path
from typing import AsyncGenerator

from config import (
    DEPLOY_TIMEOUT,
    LANGUAGE_CONFIG,
    POLL_INTERVAL,
    REGISTRY_PREFIX,
    TENANT_NAMESPACE,
    logger,
)
from k8s import get_ksvc_ready, get_ksvc_url
from models import DeployRequest

# In-memory job registry so /jobs/{id} can return status after the SSE ends.
# Keyed by 8-char job UUID.
deploy_jobs: dict[str, dict] = {}


# ── SSE helpers ───────────────────────────────────────────────────────────────


def sse_event(event: str, data: str) -> str:
    """Format a single Server-Sent Event frame."""
    # Newlines inside data would break SSE framing — replace with ↵
    safe_data = data.replace("\n", "↵")
    return f"event: {event}\ndata: {safe_data}\n\n"


async def stream_subprocess(
    cmd: list[str],
    cwd: str,
    env: dict | None = None,
) -> AsyncGenerator[str, None]:
    """
    Run a subprocess asynchronously and yield its merged stdout+stderr
    as SSE `log` events, followed by a final `exit_code` event.
    (Windows-safe threaded implementation bypassing asyncio NotImplementedError)
    """
    merged_env = {**os.environ, **(env or {})}

    process = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        cwd=cwd,
        env=merged_env,
        text=True,
        bufsize=1,
        errors="replace",
    )

    q = queue.Queue()

    def reader():
        if process.stdout:
            for line in iter(process.stdout.readline, ""):
                q.put(line)
            process.stdout.close()
        process.wait()
        q.put(None)  # EOF marker

    t = threading.Thread(target=reader, daemon=True)
    t.start()

    while True:
        while not q.empty():
            line = q.get_nowait()
            if line is None:
                yield sse_event("exit_code", str(process.returncode))
                return
            line = line.rstrip()
            if line:
                yield sse_event("log", line)
        await asyncio.sleep(0.05)



# ── Core deploy pipeline ──────────────────────────────────────────────────────


async def deploy_pipeline(
    job_id: str,
    req: DeployRequest,
    work_dir: Path,
) -> AsyncGenerator[str, None]:
    """
    Full deploy workflow as an async SSE generator.
    Callers iterate over the yielded strings and forward them to the HTTP response.
    """
    lang_cfg = LANGUAGE_CONFIG[req.language]
    fn_dir = work_dir / req.name

    try:
        # ── Step 1: func create ────────────────────────────────────────────
        yield sse_event("step", f"📦 Step 1/4 — Creating function scaffold: '{req.name}' ({req.language})")
        logger.info("[%s] func create -l %s %s", job_id, lang_cfg["template"], req.name)

        create_cmd = ["func", "create", "--language", lang_cfg["template"], req.name]
        last_exit = 0
        async for frame in stream_subprocess(create_cmd, cwd=str(work_dir)):
            if "exit_code" in frame:
                try:
                    last_exit = int(frame.split("data: ")[1].strip())
                except (IndexError, ValueError):
                    pass
            yield frame

        if last_exit != 0:
            yield sse_event("error", f"❌ func create failed (exit {last_exit})")
            yield sse_event("done", json.dumps({"status": "error", "job_id": job_id}))
            return

        if not fn_dir.exists():
            yield sse_event("error", f"❌ func create did not produce directory '{req.name}'")
            yield sse_event("done", json.dumps({"status": "error", "job_id": job_id}))
            return

        # ── Step 2: Inject user code ───────────────────────────────────────
        yield sse_event("step", f"✍️  Step 2/4 — Injecting code into {lang_cfg['entrypoint']}")
        entrypoint = fn_dir / lang_cfg["entrypoint"]
        entrypoint.parent.mkdir(parents=True, exist_ok=True)
        entrypoint.write_text(req.code, encoding="utf-8")
        yield sse_event("log", f"   → Wrote {len(req.code)} bytes to {entrypoint.name}")
        
        import shutil
        # Cleanup conflicting auto-generated files to prevent signature/test errors
        if req.language == "go":
            for f in ["handle.go", "handle_test.go", "function_test.go"]:
                if (fn_dir / f).exists():
                    (fn_dir / f).unlink()
        elif req.language == "quarkus":
            if (fn_dir / "src" / "test").exists():
                shutil.rmtree(fn_dir / "src" / "test")

        # ── Step 2.5: Apply YAML config & save source state ──────────────────
        # NOTE: func CLI v1.23.0 no longer allows custom top-level fields (like
        # 'annotations') in func.yaml — it fails validation with "unknown field".
        # We therefore store our state in a sidecar .faas-meta.json file which
        # the func CLI ignores completely, and only touch func.yaml for envs/options.
        yield sse_event("step", "⚙️  Step 2.5/4 — Applying Configuration & Saving State")
        try:
            import json as _json
            import base64

            # ── Persist state for Edit/Revision support ───────────────────────
            meta = {
                "lang": req.language,
                "code_b64": base64.b64encode(req.code.encode("utf-8")).decode("utf-8"),
            }
            if req.config_yaml:
                meta["yaml_b64"] = base64.b64encode(req.config_yaml.encode("utf-8")).decode("utf-8")

            meta_path = fn_dir / ".faas-meta.json"
            meta_path.write_text(_json.dumps(meta, indent=2), encoding="utf-8")
            yield sse_event("log", "   → Saved function state to .faas-meta.json")

            # ── Apply user envs/options ─────────────────────────────────────────
            # In func CLI v1.23+, envs shouldn't be appended to func.yaml root.
            # We will pass them as --env arguments to 'func deploy' in Step 3.
            if req.config_yaml:
                yield sse_event("log", "   → Parsed YAML configuration (will apply via deploy args)")
        except Exception as e:
            yield sse_event("error", f"❌ Failed to save state or apply config: {str(e)}")
            yield sse_event("done", json.dumps({"status": "error", "job_id": job_id}))
            return


        # ── Step 3: func deploy ────────────────────────────────────────────
        fn_image = f"{REGISTRY_PREFIX}/faas-fn-{req.name}"
        yield sse_event("step", f"🐳 Step 3/4 — Build & deploy via Buildpacks → {fn_image}")
        yield sse_event("log", "   First build typically takes 2–5 minutes...")

        deploy_cmd = [
            "func", "deploy",
            "--namespace", TENANT_NAMESPACE,
            "--builder", "pack",
            "--image", fn_image,
        ]

        if req.config_yaml:
            try:
                import yaml as _yaml
                user_cfg = _yaml.safe_load(req.config_yaml) or {}
                if "envs" in user_cfg:
                    for e in user_cfg["envs"]:
                        val = e.get("value", "")
                        deploy_cmd.extend(["--env", f"{e['name']}={val}"])
            except Exception:
                pass

        last_exit = 0
        async for frame in stream_subprocess(deploy_cmd, cwd=str(fn_dir)):
            if "exit_code" in frame:
                try:
                    last_exit = int(frame.split("data: ")[1].strip())
                except (IndexError, ValueError):
                    pass
            yield frame

        if last_exit != 0:
            yield sse_event("error", f"❌ func deploy failed (exit {last_exit})")
            yield sse_event("done", json.dumps({"status": "error", "job_id": job_id}))
            return

        # ── Persist source state on the ksvc for Edit/Revision support ───────
        # We annotate the Knative Service directly so the state survives workspace
        # cleanup and can be retrieved by /functions/{name}/code.
        # snippet-b64 = raw editor content (before wrapCode) → shown on Edit
        # code-b64    = full file written to entrypoint (fallback for old deploys)
        try:
            import base64 as _b64
            import subprocess as _sp

            # Prefer user_snippet (raw editor content); fall back to full code
            snippet = req.user_snippet if req.user_snippet else req.code
            encoded_snippet = _b64.b64encode(snippet.encode("utf-8")).decode("utf-8")
            encoded_code = _b64.b64encode(req.code.encode("utf-8")).decode("utf-8")

            annotate_args = [
                "kubectl", "annotate", "ksvc", req.name,
                "-n", TENANT_NAMESPACE,
                "--overwrite",
                f"faas.vakifbank.com/snippet-b64={encoded_snippet}",
                f"faas.vakifbank.com/code-b64={encoded_code}",
                f"faas.vakifbank.com/lang={req.language}",
            ]
            if req.config_yaml:
                encoded_yaml = _b64.b64encode(req.config_yaml.encode("utf-8")).decode("utf-8")
                annotate_args.append(f"faas.vakifbank.com/yaml-b64={encoded_yaml}")

            ann_result = _sp.run(annotate_args, capture_output=True, text=True, timeout=30)
            if ann_result.returncode == 0:
                yield sse_event("log", "   → Source state saved to ksvc annotations (Edit feature enabled)")
            else:
                yield sse_event("log", f"   ⚠️  Could not save state to ksvc: {ann_result.stderr.strip()[:120]}")
        except Exception as ann_exc:
            yield sse_event("log", f"   ⚠️  Annotation step skipped: {ann_exc}")

        # ── Step 4: Poll until Knative Service is Ready ────────────────────
        yield sse_event("step", "⏳ Step 4/4 — Waiting for Knative Service to become Ready...")
        deadline = time.time() + DEPLOY_TIMEOUT
        url: str | None = None

        while time.time() < deadline:
            if get_ksvc_ready(req.name):
                url = get_ksvc_url(req.name)
                if url:
                    break
            remaining = int(deadline - time.time())
            yield sse_event("log", f"   Polling... ({remaining}s remaining)")
            await asyncio.sleep(POLL_INTERVAL)

        if not url:
            yield sse_event("error", f"❌ Timed out waiting for '{req.name}' to become Ready")
            yield sse_event("done", json.dumps({"status": "error", "job_id": job_id}))
            return

        # ── Success ────────────────────────────────────────────────────────
        result = {
            "status": "success",
            "job_id": job_id,
            "function_name": req.name,
            "url": url,
            "language": req.language,
            "image": fn_image,
        }
        deploy_jobs[job_id] = result

        yield sse_event("step", f"✅ '{req.name}' is LIVE!")
        yield sse_event("url", url)
        yield sse_event("done", json.dumps(result))

    except Exception as exc:
        logger.exception("[%s] Unexpected error during deploy", job_id)
        yield sse_event("error", f"❌ Internal error: {exc}")
        yield sse_event("done", json.dumps({"status": "error", "job_id": job_id, "error": str(exc)}))

    finally:
        try:
            shutil.rmtree(work_dir, ignore_errors=True)
            logger.info("[%s] Cleaned up workspace: %s", job_id, work_dir)
        except Exception:
            pass
