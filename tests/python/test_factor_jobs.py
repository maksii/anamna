"""In-memory research jobs for the medicine form: outcomes, owners, dedup and the time limits."""

from __future__ import annotations

import threading

import pytest

from anamna import ai, factor_jobs


@pytest.fixture(autouse=True)
def fresh_jobs(monkeypatch):
    factor_jobs.reset()
    clock = {"now": 1000.0}
    monkeypatch.setattr(factor_jobs, "_now", lambda: clock["now"])
    yield clock
    factor_jobs.reset()


def test_a_job_that_returns_a_result_ends_done_and_a_new_start_is_a_new_job():
    job_id = factor_jobs.start("u1", lambda: {"effects": []})
    factor_jobs.join(job_id)
    assert factor_jobs.get("u1", job_id) == {"state": "done", "result": {"effects": []}, "error": ""}
    again = factor_jobs.start("u1", lambda: {"effects": [1]})
    factor_jobs.join(again)
    assert again != job_id
    assert factor_jobs.get("u1", again)["result"] == {"effects": [1]}


@pytest.mark.parametrize("raised, error", [
    (ai.AIUnavailable("budget"), "budget"),
    (ai.AIUnavailable("made_up_reason"), "provider_error"),
    (ValueError("boom"), "provider_error"),
])
def test_a_failed_job_reports_a_reason_the_form_can_name(raised, error):
    def work():
        raise raised

    job_id = factor_jobs.start("u1", work)
    factor_jobs.join(job_id)
    assert factor_jobs.get("u1", job_id) == {"state": "failed", "result": None, "error": error}


def test_an_unexpected_error_is_logged_by_class_name_only(caplog):
    def work():
        raise ValueError("Петренко Ігор, 1990-01-02")

    job_id = factor_jobs.start("u1", work)
    factor_jobs.join(job_id)
    assert "medicine research failed: ValueError" in caplog.text
    assert "Петренко" not in caplog.text


def test_a_second_start_for_the_same_owner_while_one_runs_returns_the_same_job():
    release = threading.Event()
    second_calls: list[str] = []

    def first():
        release.wait(5)
        return {"n": 1}

    def second():
        second_calls.append("second")
        return {"n": 2}

    first_id = factor_jobs.start("u1", first)
    try:
        assert factor_jobs.start("u1", second) == first_id
        assert factor_jobs.get("u1", first_id)["state"] == "running"
        other_id = factor_jobs.start("u2", second)
        assert other_id != first_id
    finally:
        release.set()
    factor_jobs.join(first_id)
    factor_jobs.join(other_id)
    assert second_calls == ["second"]
    assert factor_jobs.get("u1", first_id)["result"] == {"n": 1}


def test_another_owners_job_and_an_unknown_id_read_as_none():
    job_id = factor_jobs.start("u1", lambda: {})
    factor_jobs.join(job_id)
    assert factor_jobs.get("u2", job_id) is None
    assert factor_jobs.get("u1", "no-such-job") is None


def test_a_job_still_running_after_the_stale_limit_reads_as_lost(fresh_jobs):
    release = threading.Event()

    def work():
        release.wait(5)
        return {}

    job_id = factor_jobs.start("u1", work)
    try:
        fresh_jobs["now"] += factor_jobs.STALE_SECONDS
        assert factor_jobs.get("u1", job_id) == {"state": "failed", "result": None, "error": "lost"}
        replacement = factor_jobs.start("u1", lambda: {})
        assert replacement != job_id
        factor_jobs.join(replacement)
    finally:
        release.set()
    factor_jobs.join(job_id)


def test_a_finished_job_is_kept_for_the_keep_limit_and_dropped_by_a_later_start(fresh_jobs):
    old_id = factor_jobs.start("u1", lambda: {"x": 1})
    factor_jobs.join(old_id)
    fresh_jobs["now"] += factor_jobs.KEEP_SECONDS - 1
    kept_id = factor_jobs.start("u2", lambda: {})
    factor_jobs.join(kept_id)
    assert factor_jobs.get("u1", old_id)["state"] == "done"
    fresh_jobs["now"] += 2
    last_id = factor_jobs.start("u3", lambda: {})
    factor_jobs.join(last_id)
    assert factor_jobs.get("u1", old_id) is None
