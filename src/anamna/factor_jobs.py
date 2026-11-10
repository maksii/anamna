"""Background research for the medicine form.

A model answer can take up to a minute, so research for the medicine form runs
on a thread: the form starts a job and polls for the answer.  Jobs live in
memory, so a restart loses a running one and the form then says the request
was interrupted.
"""

from __future__ import annotations

import logging
import secrets
import threading
import time
from collections.abc import Callable

from . import ai

KEEP_SECONDS = 1800      # a finished job stays readable this long
STALE_SECONDS = 600      # a job still "running" after this is reported as lost
REASONS = frozenset(("disabled", "budget", "provider_error", "truncated", "in_progress"))

_now = time.monotonic
_LOCK = threading.Lock()
_JOBS: dict[str, dict] = {}
_LOG = logging.getLogger(__name__)


def start(owner_id: str, work: Callable[[], dict]) -> str:
    """Start ``work`` on a thread for ``owner_id`` and return the job id.

    A press of the button while the owner's job is still running returns that
    job, so the provider gets one request.
    """
    with _LOCK:
        now = _now()
        for old_id in [
            job_id for job_id, job in _JOBS.items()
            if job["state"] != "running" and now - job["finished"] > KEEP_SECONDS
        ]:
            del _JOBS[old_id]
        for job_id, job in _JOBS.items():
            if (job["owner"] == owner_id and job["state"] == "running"
                    and now - job["started"] < STALE_SECONDS):
                return job_id
        job_id = secrets.token_urlsafe(16)
        thread = threading.Thread(
            target=_run, args=(job_id, work), name="medicine-research", daemon=True
        )
        _JOBS[job_id] = {
            "owner": owner_id, "state": "running", "result": None, "error": "",
            "started": now, "finished": None, "thread": thread,
        }
        thread.start()
    return job_id


def get(owner_id: str, job_id: str) -> dict | None:
    """The job's state for its owner, or None when there is no such job for them."""
    with _LOCK:
        job = _JOBS.get(job_id)
        if job is None or job["owner"] != owner_id:
            return None
        if job["state"] == "running" and _now() - job["started"] >= STALE_SECONDS:
            return {"state": "failed", "result": None, "error": "lost"}
        return {"state": job["state"], "result": job["result"], "error": job["error"]}


def join(job_id: str, timeout: float = 10.0) -> None:
    """Wait for the job's thread.  For tests."""
    with _LOCK:
        job = _JOBS.get(job_id)
    if job is not None:
        job["thread"].join(timeout)


def reset() -> None:
    """Forget every job.  For tests."""
    with _LOCK:
        _JOBS.clear()


def _run(job_id: str, work: Callable[[], dict]) -> None:
    try:
        result = work()
    except ai.AIUnavailable as exc:
        _finish(job_id, "failed", error=exc.reason if exc.reason in REASONS else "provider_error")
    except Exception as exc:
        # The message can carry personal data, so only the class is logged.
        _LOG.warning("medicine research failed: %s", type(exc).__name__)
        _finish(job_id, "failed", error="provider_error")
    else:
        _finish(job_id, "done", result=result)


def _finish(job_id: str, state: str, *, result: dict | None = None, error: str = "") -> None:
    with _LOCK:
        job = _JOBS.get(job_id)
        if job is not None:
            job.update(state=state, result=result, error=error, finished=_now())
