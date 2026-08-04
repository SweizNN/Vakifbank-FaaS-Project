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

        # ── Step 2.5: Apply YAML config & save source state in annotations ──
        # NOTE: We use RAW TEXT injection for func.yaml instead of yaml.load/dump.
        # Reason: PyYAML parses the `created` timestamp field into a Python datetime
        # object and re-serializes it WITHOUT the 'T' separator (e.g. "2026-08-04 07:32:15"
        # instead of "2026-08-04T07:32:15Z"), which breaks func deploy's strict RFC3339 parser.
        # By injecting annotations as raw text we leave every other field byte-for-byte intact.
        yield sse_event("step", "⚙️  Step 2.5/4 — Applying Configuration & Saving State")
        try:
            import re
            import base64
            func_yaml_path = fn_dir / "func.yaml"

            if func_yaml_path.exists():
                raw = func_yaml_path.read_text(encoding="utf-8")

                # ── Build annotations dict to inject ──────────────────────────
                encoded_code = base64.b64encode(req.code.encode("utf-8")).decode("utf-8")
                new_annotations: dict[str, str] = {
                    "faas.vakifbank.com/code-b64": encoded_code,
                    "faas.vakifbank.com/lang": req.language,
                }
                if req.config_yaml:
                    new_annotations["faas.vakifbank.com/yaml-b64"] = base64.b64encode(
                        req.config_yaml.encode("utf-8")
                    ).decode("utf-8")

                # ── Serialize annotations as YAML block (2-space indent) ──────
                ann_block_lines = ["annotations:"]
                for k, v in new_annotations.items():
                    ann_block_lines.append(f"  {k}: {v}")
                ann_block = "\n".join(ann_block_lines)

                # Replace existing annotations block if present, otherwise append
                if re.search(r"^annotations:", raw, re.MULTILINE):
                    # Remove old annotations block (key + all its indented children)
                    raw = re.sub(
                        r"^annotations:(\n  .*)*",
                        ann_block,
                        raw,
                        flags=re.MULTILINE,
                    )
                else:
                    raw = raw.rstrip("\n") + "\n" + ann_block + "\n"

                # ── Apply user envs/options via safe text append if provided ──
                if req.config_yaml:
                    import yaml as _yaml
                    user_cfg = _yaml.safe_load(req.config_yaml) or {}
                    if "envs" in user_cfg or "options" in user_cfg:
                        # These blocks are simple lists/maps — safe to append
                        if "envs" in user_cfg and not re.search(r"^envs:", raw, re.MULTILINE):
                            envs_lines = ["envs:"] + [f"- name: {e['name']}\n  value: {e.get('value','')}" for e in user_cfg["envs"]]
                            raw = raw.rstrip("\n") + "\n" + "\n".join(envs_lines) + "\n"

                func_yaml_path.write_text(raw, encoding="utf-8")
                yield sse_event("log", "   → Successfully injected config & state into func.yaml")
            else:
                yield sse_event("log", "   → Warning: func.yaml not found, skipping config merge.")
        except Exception as e:
            yield sse_event("error", f"❌ Failed to parse or apply YAML config: {str(e)}")
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
