"""
services/sse.py — Server-Sent Event framing + subprocess streaming
====================================================================
Shared by every deploy flow that needs to stream a subprocess's output to the
browser as SSE frames: `func create`, `func deploy`, and `func config envs add`
(the SQL-to-API secret-provisioning step). Nothing here is FastAPI- or
deploy-flow-specific — it's pure asyncio + subprocess, testable in isolation.
"""

import asyncio
import os
import queue
import subprocess
import threading
from typing import AsyncGenerator


def sse_event(event: str, data: str) -> str:
    """Format a single Server-Sent Event frame."""
    # Newlines inside data would break SSE framing — replace with ↵
    safe_data = data.replace("\n", "↵")
    return f"event: {event}\ndata: {safe_data}\n\n"


def parse_exit_code(frame: str) -> int:
    """Extract the exit code out of an `exit_code` SSE frame produced by
    `stream_subprocess`. Returns 0 if the frame can't be parsed (matches the
    previous inline try/except-pass behavior at each call site)."""
    try:
        return int(frame.split("data: ")[1].strip())
    except (IndexError, ValueError):
        return 0


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
