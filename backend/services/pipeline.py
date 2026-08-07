"""
services/pipeline.py — Knative func CLI deploy pipeline, decomposed
======================================================================
Each `step_*` function is a standalone, reusable piece of the deploy
workflow (`func create`, inject code, `func deploy`, poll-ready, annotate).
`run_code_editor_deploy()` is the existing code-editor flow, calling these
steps in order plus its own YAML-config/dependency-injection step.
`services/sql_pipeline.py`'s `run_sql_api_deploy()` reuses the *same* step
functions instead of duplicating the func-create/func-deploy/poll
orchestration — that's the whole point of the split.

Nothing in here touches FastAPI directly — it's pure asyncio + subprocess,
making it testable in isolation without starting the HTTP server.
"""

import asyncio
import base64
import json
import shutil
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import AsyncGenerator

import yaml

from config import (
    DEPLOY_TIMEOUT,
    LANGUAGE_CONFIG,
    POLL_INTERVAL,
    REGISTRY_PREFIX,
    SCAFFOLDS_DIR,
    TENANT_NAMESPACE,
    logger,
)
from models import DeployRequest
from services.dependencies import apply_dependencies
from services.job_store import set_job
from services.k8s import (
    annotate_ksvc,
    annotate_revision,
    get_ksvc_ready,
    get_ksvc_url,
    get_latest_revision_name,
)
from services.sse import parse_exit_code, sse_event, stream_subprocess


def _merge_required_deps(language: str, user_deps: list[str]) -> list[str]:
    """Prepend LANGUAGE_CONFIG's `required_dependencies` (e.g. serde_json for
    rust — see config.py) to whatever the user's YAML config specifies,
    letting a user-supplied spec for the same package override the required
    one (e.g. pinning a different serde_json version) instead of colliding
    with it — apply_dependencies' per-language handlers key on package name,
    so two specs for the same name in the same list would otherwise produce
    a duplicate/invalid entry in the manifest (e.g. two `serde_json = ".."`
    lines in Cargo.toml)."""
    required = LANGUAGE_CONFIG.get(language, {}).get("required_dependencies", [])
    if not required:
        return user_deps
    merged = {spec.split("@", 1)[0].strip().lower(): spec for spec in required}
    for spec in user_deps:
        merged[spec.split("@", 1)[0].strip().lower()] = spec
    return list(merged.values())


# ── Shared steps ────────────────────────────────────────────────────────────


async def step_scaffold(job_id: str, name: str, language: str, work_dir: Path, result: dict) -> AsyncGenerator[str, None]:
    """Step 1: scaffold the function project. Sets result['fn_dir'], result['ok'].

    For `func`-native languages this is `func create --language <template> <name>`.
    For "dockerfile" build_mode languages (e.g. dotnet — `func` has no builtin
    template for them, see LANGUAGE_CONFIG) it copies a static local scaffold
    from SCAFFOLDS_DIR and hand-writes a func.yaml instead, since func deploy
    still needs one to recognize the directory as a function project even
    though it never builds it (see step_func_deploy's dockerfile branch)."""
    lang_cfg = LANGUAGE_CONFIG[language]
    fn_dir = work_dir / name

    if lang_cfg.get("build_mode") == "dockerfile":
        yield sse_event("step", f"📦 Step 1/4 — Creating function scaffold: '{name}' ({language}, Dockerfile build)")
        shutil.copytree(SCAFFOLDS_DIR / lang_cfg["template"], fn_dir)
        created = datetime.now(timezone.utc).isoformat()
        (fn_dir / "func.yaml").write_text(
            f"specVersion: 0.36.0\nname: {name}\nruntime: {language}\ncreated: {created}\n",
            encoding="utf-8",
        )
        yield sse_event("log", f"   → Scaffolded from {lang_cfg['template']} template")
        result["fn_dir"] = fn_dir
        result["ok"] = True
        return

    yield sse_event("step", f"📦 Step 1/4 — Creating function scaffold: '{name}' ({language})")
    logger.info("[%s] func create -l %s %s", job_id, lang_cfg["template"], name)

    create_cmd = ["func", "create", "--language", lang_cfg["template"], name]
    last_exit = 0
    async for frame in stream_subprocess(create_cmd, cwd=str(work_dir)):
        if "exit_code" in frame:
            last_exit = parse_exit_code(frame)
        yield frame

    if last_exit != 0:
        yield sse_event("error", f"❌ func create failed (exit {last_exit})")
        result["ok"] = False
        return

    if not fn_dir.exists():
        yield sse_event("error", f"❌ func create did not produce directory '{name}'")
        result["ok"] = False
        return

    result["fn_dir"] = fn_dir
    result["ok"] = True


async def step_inject_code(fn_dir: Path, language: str, code: str) -> AsyncGenerator[str, None]:
    """Step 2: write `code` into the language's entrypoint file, scrub
    conflicting auto-generated scaffold files for go/quarkus."""
    lang_cfg = LANGUAGE_CONFIG[language]
    yield sse_event("step", f"✍️  Step 2/4 — Injecting code into {lang_cfg['entrypoint']}")

    entrypoint = fn_dir / lang_cfg["entrypoint"]
    entrypoint.parent.mkdir(parents=True, exist_ok=True)
    entrypoint.write_text(code, encoding="utf-8")
    yield sse_event("log", f"   → Wrote {len(code)} bytes to {entrypoint.name}")

    if language == "go":
        for f in ["handle.go", "handle_test.go", "function_test.go"]:
            if (fn_dir / f).exists():
                (fn_dir / f).unlink()
    elif language == "quarkus":
        if (fn_dir / "src" / "test").exists():
            shutil.rmtree(fn_dir / "src" / "test")


async def step_func_deploy(
    name: str,
    fn_dir: Path,
    image: str,
    namespace: str,
    extra_envs: list[tuple[str, str]],
    result: dict,
    build_mode: str = "func",
) -> AsyncGenerator[str, None]:
    """Step 3: build (if needed) and deploy the function's Knative Service.

    build_mode="func" (default): `func deploy --builder pack --verbose`, which
    builds via Buildpacks and pushes as part of the same command.

    build_mode="dockerfile": `func` has no builder that accepts a hand-rolled
    Dockerfile for an unknown runtime (its "host" builder rejects any runtime
    it doesn't recognize outright, Dockerfile or not — verified against func
    v0.49.2). So we build & push the image ourselves via the plain `docker`
    CLI — using the same /root/.docker credentials and docker.sock the pack
    builder already relies on, see k8s/deployment.yaml — and then run
    `func deploy --build=false --push=false --image <image>` purely to have
    func create/update the Knative Service resource for an already-pushed
    image.
    """
    if build_mode == "dockerfile":
        yield sse_event("step", f"🐳 Step 3/4 — Build & push Docker image → {image}")
        yield sse_event("log", "   First build typically takes 1–3 minutes (SDK image pull + restore)...")

        build_cmd = ["docker", "build", "-t", image, "."]
        last_exit = 0
        async for frame in stream_subprocess(build_cmd, cwd=str(fn_dir)):
            if "exit_code" in frame:
                last_exit = parse_exit_code(frame)
            yield frame
        if last_exit != 0:
            yield sse_event("error", f"❌ docker build failed (exit {last_exit})")
            result["ok"] = False
            return

        yield sse_event("log", f"   → Pushing {image}...")
        push_cmd = ["docker", "push", image]
        async for frame in stream_subprocess(push_cmd, cwd=str(fn_dir)):
            if "exit_code" in frame:
                last_exit = parse_exit_code(frame)
            yield frame
        if last_exit != 0:
            yield sse_event("error", f"❌ docker push failed (exit {last_exit})")
            result["ok"] = False
            return

        yield sse_event("log", "   → Registering Knative Service (func deploy --build=false)")
        deploy_cmd = [
            "func", "deploy",
            "--namespace", namespace,
            "--image", image,
            "--build=false",
            "--push=false",
        ]
    else:
        yield sse_event("step", f"🐳 Step 3/4 — Build & deploy via Buildpacks → {image}")
        yield sse_event("log", "   First build typically takes 2–5 minutes...")

        deploy_cmd = [
            "func", "deploy",
            "--namespace", namespace,
            "--builder", "pack",
            "--image", image,
            "--verbose",  # surface the underlying pack/buildpack lifecycle output
                          # instead of func's generic "Still building..." filler —
                          # without this, a lifecycle failure (e.g. pip install
                          # error) only ever shows as "exit status: 51" with no detail.
        ]

    for env_name, val in extra_envs:
        deploy_cmd.extend(["--env", f"{env_name}={val}"])

    last_exit = 0
    async for frame in stream_subprocess(deploy_cmd, cwd=str(fn_dir)):
        if "exit_code" in frame:
            last_exit = parse_exit_code(frame)
        yield frame

    if last_exit != 0:
        yield sse_event("error", f"❌ func deploy failed (exit {last_exit})")
        result["ok"] = False
        return
    result["ok"] = True


async def step_poll_ready(name: str, timeout_seconds: int, result: dict) -> AsyncGenerator[str, None]:
    """Step 4: poll until the Knative Service is Ready. Sets result['url'], result['ok']."""
    yield sse_event("step", "⏳ Step 4/4 — Waiting for Knative Service to become Ready...")
    deadline = time.time() + timeout_seconds
    url: str | None = None

    while time.time() < deadline:
        if get_ksvc_ready(name):
            url = get_ksvc_url(name)
            if url:
                break
        remaining = int(deadline - time.time())
        yield sse_event("log", f"   Polling... ({remaining}s remaining)")
        await asyncio.sleep(POLL_INTERVAL)

    if not url:
        yield sse_event("error", f"❌ Timed out waiting for '{name}' to become Ready")
        result["ok"] = False
        return

    result["url"] = url
    result["ok"] = True


async def step_annotate_state(
    name: str,
    namespace: str,
    snippet: str,
    code: str,
    language: str,
    config_yaml: str | None,
) -> AsyncGenerator[str, None]:
    """Persist snippet/code/lang/[yaml] as base64 annotations on the ksvc + latest
    Revision, for the Edit/Revision-history feature. Best-effort: failures here
    are logged but never fail the overall deploy (the function is already live)."""
    try:
        encoded_snippet = base64.b64encode(snippet.encode("utf-8")).decode("utf-8")
        encoded_code = base64.b64encode(code.encode("utf-8")).decode("utf-8")

        annotations = {
            "faas.vakifbank.com/snippet-b64": encoded_snippet,
            "faas.vakifbank.com/code-b64": encoded_code,
            "faas.vakifbank.com/lang": language,
        }
        if config_yaml:
            annotations["faas.vakifbank.com/yaml-b64"] = base64.b64encode(config_yaml.encode("utf-8")).decode("utf-8")

        ann_result = annotate_ksvc(name, annotations, namespace=namespace)
        if ann_result.returncode == 0:
            yield sse_event("log", "   → Source state saved to ksvc annotations (Edit feature enabled)")
        else:
            yield sse_event("log", f"   ⚠️  Could not save state to ksvc: {ann_result.stderr.strip()[:120]}")

        latest_revision = get_latest_revision_name(name, namespace=namespace)
        if latest_revision:
            annotate_revision(latest_revision, annotations, namespace=namespace)
            yield sse_event("log", f"   → Code saved to revision '{latest_revision}' for history tracking")

    except Exception as ann_exc:
        yield sse_event("log", f"   ⚠️  Annotation step skipped: {ann_exc}")


# ── Code-editor orchestrator (existing flow) ────────────────────────────────


async def run_code_editor_deploy(job_id: str, req: DeployRequest, work_dir: Path) -> AsyncGenerator[str, None]:
    """Full code-editor deploy workflow: scaffold → inject code → apply
    YAML config/dependencies → deploy → annotate → poll ready."""
    try:
        scaffold_result: dict = {}
        async for frame in step_scaffold(job_id, req.name, req.language, work_dir, scaffold_result):
            yield frame
        if not scaffold_result.get("ok"):
            yield sse_event("done", json.dumps({"status": "error", "job_id": job_id}))
            return
        fn_dir = scaffold_result["fn_dir"]

        async for frame in step_inject_code(fn_dir, req.language, req.code):
            yield frame

        # ── Step 2.5: Apply YAML config & save source state ──────────────────
        # NOTE: func CLI v1.23.0 no longer allows custom top-level fields (like
        # 'annotations') in func.yaml — it fails validation with "unknown field".
        # We therefore store our state in a sidecar .faas-meta.json file which
        # the func CLI ignores completely, and only touch func.yaml for envs/options.
        yield sse_event("step", "⚙️  Step 2.5/4 — Applying Configuration & Saving State")
        user_cfg: dict = {}
        try:
            meta = {
                "lang": req.language,
                "code_b64": base64.b64encode(req.code.encode("utf-8")).decode("utf-8"),
            }
            if req.config_yaml:
                meta["yaml_b64"] = base64.b64encode(req.config_yaml.encode("utf-8")).decode("utf-8")

            meta_path = fn_dir / ".faas-meta.json"
            meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")
            yield sse_event("log", "   → Saved function state to .faas-meta.json")

            if req.config_yaml:
                try:
                    user_cfg = yaml.safe_load(req.config_yaml) or {}
                except Exception:
                    user_cfg = {}
                yield sse_event("log", "   → Parsed YAML configuration (will apply via deploy args)")

            user_deps = user_cfg.get("dependencies") if isinstance(user_cfg, dict) else None
            deps = _merge_required_deps(req.language, user_deps or [])
            if deps:
                applied = apply_dependencies(fn_dir, req.language, deps)
                if applied:
                    yield sse_event("log", f"   → Added {len(applied)} librar{'y' if len(applied) == 1 else 'ies'} to manifest: {', '.join(applied)}")
        except Exception as e:
            yield sse_event("error", f"❌ Failed to save state or apply config: {str(e)}")
            yield sse_event("done", json.dumps({"status": "error", "job_id": job_id}))
            return

        # ── Step 3: func deploy ────────────────────────────────────────────
        fn_image = f"{REGISTRY_PREFIX}/faas-fn-{req.name}"
        extra_envs: list[tuple[str, str]] = []
        if isinstance(user_cfg, dict) and user_cfg.get("envs"):
            extra_envs = [(e["name"], e.get("value", "")) for e in user_cfg["envs"]]

        build_mode = LANGUAGE_CONFIG[req.language].get("build_mode", "func")
        deploy_result: dict = {}
        async for frame in step_func_deploy(req.name, fn_dir, fn_image, TENANT_NAMESPACE, extra_envs, deploy_result, build_mode=build_mode):
            yield frame
        if not deploy_result.get("ok"):
            yield sse_event("done", json.dumps({"status": "error", "job_id": job_id}))
            return

        # ── Persist source state on the ksvc for Edit/Revision support ───────
        snippet = req.user_snippet if req.user_snippet else req.code
        async for frame in step_annotate_state(req.name, TENANT_NAMESPACE, snippet, req.code, req.language, req.config_yaml):
            yield frame

        # ── Step 4: Poll until Knative Service is Ready ────────────────────
        poll_result: dict = {}
        async for frame in step_poll_ready(req.name, DEPLOY_TIMEOUT, poll_result):
            yield frame
        if not poll_result.get("ok"):
            yield sse_event("done", json.dumps({"status": "error", "job_id": job_id}))
            return
        url = poll_result["url"]

        # ── Success ────────────────────────────────────────────────────────
        result_payload = {
            "status": "success",
            "job_id": job_id,
            "function_name": req.name,
            "url": url,
            "language": req.language,
            "image": fn_image,
        }
        await set_job(job_id, result_payload)

        yield sse_event("step", f"✅ '{req.name}' is LIVE!")
        yield sse_event("url", url)
        yield sse_event("done", json.dumps(result_payload))

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
