"""In-memory background jobs: the medicine research and the scan of documents for factors.

A model answer can take up to a minute, and a scan of many documents takes
longer, so both run on a thread and the page polls for the answer.  A scan
reports its progress after each document.  Jobs live in memory, so a restart
loses a running one and the page then says the request was interrupted.  One
job per owner, kind and request key may run at a time, so the research button
and the document scan do not wait for each other.
"""

from __future__ import annotations

import logging
import secrets
import threading
import time
from collections.abc import Callable

from . import ai

KEEP_SECONDS = 1800      # a finished job stays readable this long
STALE_SECONDS = 600      # a job nothing has been heard from for this long is reported as lost
REASONS = frozenset(("disabled", "budget", "provider_error", "truncated", "in_progress"))

_now = time.monotonic
_LOCK = threading.Lock()
_JOBS: dict[str, dict] = {}
_LOG = logging.getLogger(__name__)


def _stale(job: dict, now: float) -> bool:
    """A job is stale when nothing was heard from it since STALE_SECONDS ago."""
    return now - job["touched"] >= STALE_SECONDS


def _running(job: dict, owner_id: str, kind: str, now: float) -> bool:
    return (job["owner"] == owner_id and job["kind"] == kind
            and job["state"] == "running" and not _stale(job, now))


def start(
    owner_id: str,
    work: Callable[..., dict],
    *,
    kind: str = "research",
    with_progress: bool = False,
    key: str = "",
) -> str:
    """Start ``work`` on a thread for ``owner_id`` and return the job id.

    A repeat press for the same request (same ``kind`` and ``key``) returns the
    running job, so the provider is asked once.  A different ``key`` is a
    different request and starts its own job.  With ``with_progress`` the thread
    calls ``work(report)``, where ``report(done, total)`` records progress on
    the job.
    """
    with _LOCK:
        now = _now()
        for old_id in [
            job_id for job_id, job in _JOBS.items()
            if job["state"] != "running" and now - job["finished"] > KEEP_SECONDS
        ]:
            del _JOBS[old_id]
        for job_id, job in _JOBS.items():
            if _running(job, owner_id, kind, now) and job["key"] == key:
                return job_id
        job_id = secrets.token_urlsafe(16)
        thread = threading.Thread(
            target=_run, args=(job_id, kind, work, with_progress), name=f"{kind}-job", daemon=True
        )
        _JOBS[job_id] = {
            "owner": owner_id, "kind": kind, "key": key, "state": "running", "result": None, "error": "",
            "started": now, "touched": now, "done": 0, "total": 0, "finished": None, "thread": thread,
        }
        thread.start()
    return job_id


def running(owner_id: str, kind: str) -> str | None:
    """The id of the owner's running job of ``kind`` that is not stale, or None."""
    with _LOCK:
        now = _now()
        for job_id, job in _JOBS.items():
            if _running(job, owner_id, kind, now):
                return job_id
    return None


def get(owner_id: str, job_id: str) -> dict | None:
    """The job's state for its owner, or None when there is no such job for them.

    ``done`` and ``total`` are 0 until the job reports progress.
    """
    with _LOCK:
        job = _JOBS.get(job_id)
        if job is None or job["owner"] != owner_id:
            return None
        state, result, error = job["state"], job["result"], job["error"]
        if state == "running" and _stale(job, _now()):
            state, result, error = "failed", None, "lost"
        return {
            "state": state, "result": result, "error": error,
            "kind": job["kind"], "done": job["done"], "total": job["total"],
        }


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


def _report(job_id: str, done: int, total: int) -> None:
    with _LOCK:
        job = _JOBS.get(job_id)
        if job is not None:
            job.update(done=done, total=total, touched=_now())


def _run(job_id: str, kind: str, work: Callable[..., dict], with_progress: bool) -> None:
    try:
        if with_progress:
            result = work(lambda done, total: _report(job_id, done, total))
        else:
            result = work()
    except ai.AIUnavailable as exc:
        _finish(job_id, "failed", error=exc.reason if exc.reason in REASONS else "provider_error")
    except Exception as exc:
        # The message can carry personal data, so only the class is logged.
        _LOG.warning("%s job failed: %s", kind, type(exc).__name__)
        _finish(job_id, "failed", error="provider_error")
    else:
        _finish(job_id, "done", result=result)


def _finish(job_id: str, state: str, *, result: dict | None = None, error: str = "") -> None:
    with _LOCK:
        job = _JOBS.get(job_id)
        if job is not None:
            job.update(state=state, result=result, error=error, finished=_now())
