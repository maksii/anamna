"""Synevo builds an order's files on download-pdf and may take past its own
20 s gateway: the first call ends in an empty HTTP 500 (or our timeout), the
next one answers.  Seen 2026-11-07 on a 2023 order that sync filed as failed."""

from __future__ import annotations

import json

import pytest

from anamna.labsync import common, synevo

BLOB = "https://synevostatic.blob.core.windows.net/results/a.pdf?sig=1"
PDF = b"%PDF-1.7 report"


def fake(replies: list, seen: list):
    """download-pdf answers from ``replies`` in turn (an int status, the
    string ``"timeout"``, or a JSON body); the blob always serves PDF."""

    def http(method, url, *, headers, body=None, timeout=0, limit=0):
        seen.append((method, url.split("?")[0], timeout))
        if url.startswith(BLOB.split("?")[0]):
            return 200, [], PDF
        reply = replies.pop(0)
        if reply == "timeout":
            raise common.LabSyncError("labsync.error_unreachable")
        if isinstance(reply, int):
            return reply, [], b""
        return 200, [], json.dumps(reply).encode()

    return http


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(synevo.time, "sleep", lambda _seconds: None)
    return synevo.Client("https://www.synevo.ua", "x" * 64)


ORDER, PERSON = {"remote_ref": "100000001"}, {"id": "p1"}
OK = {"res": "ok", "results": {"main": BLOB, "extra": []}}


@pytest.mark.parametrize("first", [500, 504, "timeout"])
def test_a_slow_first_build_is_asked_again_and_imports(client, monkeypatch, first):
    seen: list = []
    monkeypatch.setattr(common, "_http", fake([first, OK], seen))
    assert client.pdfs(ORDER, PERSON) == [PDF]
    asks = [entry for entry in seen if entry[1].endswith("/api/order/download-pdf")]
    assert len(asks) == 2
    # Longer than the lab's own 20 s gateway, so its 500 arrives before our timeout.
    assert all(timeout > 20 for _method, _url, timeout in asks)


def test_a_lab_that_keeps_failing_gives_up_after_the_last_attempt(client, monkeypatch):
    seen: list = []
    monkeypatch.setattr(common, "_http", fake([500] * synevo.PDF_LINK_ATTEMPTS, seen))
    with pytest.raises(common.LabSyncError) as caught:
        client.pdfs(ORDER, PERSON)
    assert (caught.value.key, caught.value.status) == ("labsync.error_reply", 500)
    assert len(seen) == synevo.PDF_LINK_ATTEMPTS


@pytest.mark.parametrize(("status", "key"), [(404, "labsync.error_reply"), (401, "labsync.error_auth")])
def test_a_refusal_is_final_and_not_repeated(client, monkeypatch, status, key):
    seen: list = []
    monkeypatch.setattr(common, "_http", fake([status, OK], seen))
    with pytest.raises(common.LabSyncError) as caught:
        client.pdfs(ORDER, PERSON)
    assert caught.value.key == key
    assert len(seen) == 1
