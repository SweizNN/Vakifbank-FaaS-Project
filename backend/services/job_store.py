"""services/job_store.py — Shared deploy-job status store (Redis-backed)
==========================================================================
Deploy job status used to live in a plain in-memory dict (`deploy_jobs` in
services/pipeline.py). That only works with exactly one orchestrator pod:
scale the Deployment to 2 replicas (or lose the pod to a restart/rollout)
and GET /jobs/{id} would 404 depending on which pod happened to handle
the request, since each pod had its own private copy of the dict.

This module replaces that dict with a small wrapper around a Redis key per
job (`faas:job:<id>`), so any orchestrator replica can read a job written
by any other replica — see k8s/redis.yaml for the in-cluster instance and
k8s/deployment.yaml for `replicas: 2` + REDIS_URL.

Writes are best-effort: a job's SSE stream has already produced (or failed
to produce) the real result by the time we persist its status here, so a
Redis hiccup shouldn't turn a successful deploy into a reported failure —
it's logged and swallowed. Reads are not: if Redis is unreachable, GET
/jobs/{id} should surface that as a 503, not a misleading 404 (job existed,
we just can't currently confirm it), so get_job() lets the error propagate.

NEVER put credentials/API keys into a job's data — GET /jobs/{job_id} is
unauthenticated and readable for JOB_TTL_SECONDS (see config.py).
"""

import json

import redis.asyncio as redis

from config import JOB_TTL_SECONDS, REDIS_URL, logger

_KEY_PREFIX = "faas:job:"

_client: redis.Redis | None = None


def _get_client() -> redis.Redis:
    """Lazily create the shared async Redis client (module-level singleton).

    redis.from_url() doesn't open a connection by itself — the actual TCP
    connect happens on the first command — so importing this module (e.g.
    from tests that never deploy anything) never touches the network.
    """
    global _client
    if _client is None:
        _client = redis.from_url(REDIS_URL, decode_responses=True)
    return _client


async def set_job(job_id: str, data: dict) -> None:
    """Persist a job's status, expiring after JOB_TTL_SECONDS."""
    try:
        await _get_client().set(f"{_KEY_PREFIX}{job_id}", json.dumps(data), ex=JOB_TTL_SECONDS)
    except Exception:
        logger.exception("[%s] Failed to write job status to Redis (deploy result unaffected)", job_id)


async def get_job(job_id: str) -> dict | None:
    """Fetch a job's status, or None if it doesn't exist (or has expired)."""
    raw = await _get_client().get(f"{_KEY_PREFIX}{job_id}")
    return json.loads(raw) if raw is not None else None
