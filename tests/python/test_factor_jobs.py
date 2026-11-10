"""In-memory background jobs: outcomes, owners, kinds, progress, dedup and the time limits."""

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


def blocked(release: threading.Event):
    """A job body that waits for ``release``; it takes the report callback when there is one."""
    def work(*args):
        release.wait(5)
        return {}

    return work


def test_a_job_that_returns_a_result_ends_done_and_a_new_start_is_a_new_job():
    job_id = factor_jobs.start("u1", lambda: {"effects": []})
    factor_jobs.join(job_id)
    assert factor_jobs.get("u1", job_id) == {
        "state": "done", "result": {"effects": []}, "error": "",
        "kind": "research", "done": 0, "total": 0,
    }
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
    assert factor_jobs.get("u1", job_id)["state"] == "failed"
    assert factor_jobs.get("u1", job_id)["error"] == error


def test_an_unexpected_error_is_logged_by_class_name_only(caplog):
    def work():
        raise ValueError("Петренко Ігор, 1990-01-02")

    job_id = factor_jobs.start("u1", work)
    factor_jobs.join(job_id)
    assert "research job failed: ValueError" in caplog.text
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


def test_two_kinds_of_job_for_one_owner_run_side_by_side():
    release = threading.Event()
    research_id = factor_jobs.start("u1", blocked(release))
    try:
        scan_id = factor_jobs.start("u1", blocked(release), kind="scan", with_progress=True)
        assert scan_id != research_id
        assert factor_jobs.start("u1", blocked(release)) == research_id
        assert factor_jobs.start("u1", blocked(release), kind="scan", with_progress=True) == scan_id
        assert factor_jobs.get("u1", scan_id)["kind"] == "scan"
        assert factor_jobs.get("u1", research_id)["kind"] == "research"
    finally:
        release.set()
    factor_jobs.join(research_id)
    factor_jobs.join(scan_id)


def test_progress_is_visible_through_get_while_the_job_is_blocked():
    reported = threading.Event()
    proceed = threading.Event()

    def work(report):
        report(1, 3)
        reported.set()
        proceed.wait(5)
        return {"read": 3}

    job_id = factor_jobs.start("u1", work, kind="scan", with_progress=True)
    try:
        assert reported.wait(5)
        status = factor_jobs.get("u1", job_id)
        assert (status["state"], status["done"], status["total"]) == ("running", 1, 3)
    finally:
        proceed.set()
    factor_jobs.join(job_id)
    status = factor_jobs.get("u1", job_id)
    assert (status["state"], status["done"], status["total"], status["result"]) == (
        "done", 1, 3, {"read": 3})


def test_a_job_that_keeps_reporting_is_not_stale_after_the_limit_from_its_start(fresh_jobs):
    reported = threading.Event()
    proceed = threading.Event()
    second_reported = threading.Event()
    finished = threading.Event()

    def work(report):
        report(1, 3)
        reported.set()
        proceed.wait(5)
        report(2, 3)
        second_reported.set()
        finished.wait(5)
        return {}

    job_id = factor_jobs.start("u1", work, kind="scan", with_progress=True)
    try:
        assert reported.wait(5)
        fresh_jobs["now"] += factor_jobs.STALE_SECONDS - 1
        proceed.set()
        assert second_reported.wait(5)
        fresh_jobs["now"] += 2
        status = factor_jobs.get("u1", job_id)
        assert status["state"] == "running"
        assert (status["done"], status["total"]) == (2, 3)
        assert factor_jobs.running("u1", "scan") == job_id
    finally:
        finished.set()
    factor_jobs.join(job_id)
    assert factor_jobs.get("u1", job_id)["state"] == "done"


def test_running_names_the_owners_running_job_of_that_kind_and_is_none_after_it_finishes():
    release = threading.Event()
    job_id = factor_jobs.start("u1", blocked(release), kind="scan", with_progress=True)
    try:
        assert factor_jobs.running("u1", "scan") == job_id
        assert factor_jobs.running("u1", "research") is None
        assert factor_jobs.running("u2", "scan") is None
    finally:
        release.set()
    factor_jobs.join(job_id)
    assert factor_jobs.running("u1", "scan") is None


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
        assert factor_jobs.get("u1", job_id) == {
            "state": "failed", "result": None, "error": "lost",
            "kind": "research", "done": 0, "total": 0,
        }
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


def test_same_key_returns_the_running_job():
    release = threading.Event()
    runs: list[str] = []

    def work():
        runs.append("run")
        release.wait(5)
        return {}

    first_id = factor_jobs.start("u1", work, key="a")
    try:
        assert factor_jobs.start("u1", work, key="a") == first_id
    finally:
        release.set()
    factor_jobs.join(first_id)
    assert runs == ["run"]


def test_a_different_key_starts_its_own_job():
    release = threading.Event()

    def answering(who: str):
        def work():
            release.wait(5)
            return {"who": who}

        return work

    a_id = factor_jobs.start("u1", answering("a"), key="a")
    try:
        b_id = factor_jobs.start("u1", answering("b"), key="b")
        assert b_id != a_id
    finally:
        release.set()
    factor_jobs.join(a_id)
    factor_jobs.join(b_id)
    assert factor_jobs.get("u1", a_id)["result"] == {"who": "a"}
    assert factor_jobs.get("u1", b_id)["result"] == {"who": "b"}


def test_default_key_still_reuses():
    release = threading.Event()
    first_id = factor_jobs.start("u1", blocked(release))
    try:
        assert factor_jobs.start("u1", blocked(release)) == first_id
    finally:
        release.set()
    factor_jobs.join(first_id)
