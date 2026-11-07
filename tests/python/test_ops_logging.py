"""OPS-35 and PERF-13: background loops leave one counted line per run in the
container log (and nothing from the record), and a page reads each settings
group once per request."""
from __future__ import annotations

import logging
import time
from pathlib import Path

from fastapi.testclient import TestClient

from anamna import config, integrations, labsync, openwearables, paperless
from anamna.config import configure_logging, log_run, per_request, run_summary
from anamna.db import migrate
from anamna.security import create_user
from anamna.web.app import create_app

from test_web_profile import login
from test_web_security import PASSWORD, seed_patient, settings_for


def test_run_summary_keeps_counts_and_drops_every_text():
    assert run_summary(7) == "count=7"
    assert run_summary({"pushed": 2, "resolved": 1, "crosscheck": {"match": 49, "differ": 0}}) == (
        "pushed=2 resolved=1 crosscheck.match=49 crosscheck.differ=0")
    leaky = {"title": "Загальний аналіз крові", "token": "anamna_agent_secret", "Glucose": 5.4,
             "names": ["Іваненко"], "ok": True, "Bad Key": 3, "people": {"Іваненко": 1}}
    assert run_summary(leaky) == ""
    assert run_summary("anamna_agent_secret") == "" and run_summary(None) == ""


def test_one_line_per_run_with_counts_or_the_failure_class(capsys):
    configure_logging()
    configure_logging()  # idempotent: one handler, one line
    logger = logging.getLogger("anamna.test-loop")
    log_run(logger, "paperless sync", time.monotonic(), {"pushed": 3, "resolved": 1})
    log_run(logger, "labsync synevo", time.monotonic(), error=ValueError("value 5.4 for patient Іваненко"))
    out = capsys.readouterr().out.splitlines()
    assert len(out) == 2
    assert " INFO anamna.test-loop: paperless sync run done in " in out[0] and out[0].endswith("pushed=3 resolved=1")
    assert " WARNING anamna.test-loop: labsync synevo run failed after " in out[1] and out[1].endswith("ValueError")
    assert "Іваненко" not in "\n".join(out)


def test_settings_are_read_once_per_get_request_and_never_cached_across_requests(tmp_path: Path, monkeypatch):
    settings = settings_for(tmp_path)
    migrate(settings)
    alpha = create_user(settings, "alpha@example.test", "Alpha", PASSWORD)
    seed_patient(settings, alpha, "Alpha Patient")
    reads: list[tuple] = []
    for module, name in ((integrations, "integration_settings"), (paperless, "paperless_settings"),
                         (openwearables, "ow_settings"), (labsync, "_stored_settings")):
        original = getattr(module, name).__wrapped__

        def counting(settings, *args, _original=original, _name=name):
            reads.append((_name, *args))
            return _original(settings, *args)
        monkeypatch.setattr(module, name, per_request(counting))
    with TestClient(create_app(settings)) as client:
        login(client, "alpha@example.test")
        reads.clear()
        assert client.get("/profile?tab=connections").status_code == 200
        assert reads and len(reads) == len(set(reads))  # each settings group read once
        assert ("integration_settings",) in reads
        reads.clear()
        client.get("/profile?tab=connections")
        assert ("integration_settings",) in reads  # a new request reads again
    assert config._request_memo.get() is None  # nothing leaks outside a request
