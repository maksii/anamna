"""Paperless-ngx integration — a copy service that must never change how the
app behaves without it.

The contract under test: the operator's switch and URL live in
``app_settings``; each person's token and upload consent live in
``paperless_accounts`` and gate everything done with their record; an ingest
hands the file over and stores the consumption task, the document page
resolves the task into a link; full-text matches from Paperless only ever
widen search to documents the person already owns; and with the feature off
every page renders exactly as it always did.  HTTP is stubbed at the
``_request`` seam — the one door every real call goes through.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from anamna import paperless
from anamna.db import connect, migrate, utc_now

from test_web_panels import build, settings_for
from test_web_issue_reports import csrf_for


TASK_UUID = "982089e0-8c23-4ddd-9a63-f23d52c94709"


def configure_paperless(settings, url: str = "http://paperless.test") -> None:
    paperless.save_paperless_settings(settings, {"paperless_enabled": "1", "paperless_url": url})
    paperless.reset_caches()  # module-level caches must not leak between tests


def connect_user(settings, user_id: str, *, upload: bool = True) -> None:
    paperless.save_account(settings, user_id, token="pl-token-abcdef", upload_enabled=upload)


def fake_request(replies: dict[str, object], calls: list | None = None):
    """A stand-in for ``paperless._request`` answering by path prefix."""

    def request(url, token, path, **kwargs):
        if calls is not None:
            calls.append({"url": url, "token": token, "path": path, **kwargs})
        for prefix, reply in replies.items():
            if path.startswith(prefix):
                if isinstance(reply, Exception):
                    raise reply
                return reply
        raise AssertionError(f"unexpected paperless path {path}")

    return request


def task_reply(status: str, document_id: int | None = None) -> dict:
    return {
        "results": [
            {
                "task_id": TASK_UUID,
                "status": status,
                "related_document": None,
                "result_data": {"document_id": document_id} if document_id else None,
            }
        ]
    }


# --- module: configuration and consent ---------------------------------------


def test_feature_is_dormant_until_the_operator_names_a_server(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("PAPERLESS_URL", raising=False)
    settings = settings_for(tmp_path)
    migrate(settings)
    config = paperless.paperless_settings(settings)
    assert config["enabled"] == "1" and config["url"] == ""
    assert not paperless.paperless_active(settings)
    configure_paperless(settings)
    assert paperless.paperless_active(settings)
    paperless.save_paperless_settings(settings, {"paperless_enabled": "0"})
    assert not paperless.paperless_active(settings)


def test_reading_and_sending_are_separate_consents(tmp_path: Path):
    from anamna.security import create_user

    settings = settings_for(tmp_path)
    migrate(settings)
    configure_paperless(settings)
    user_id = create_user(settings, "consent@example.test", "Consent", "another-long-password")
    assert paperless.connection_for(settings, user_id) is None  # no token yet
    paperless.save_account(settings, user_id, token="pl-secret", upload_enabled=False)
    assert paperless.connection_for(settings, user_id) == ("http://paperless.test", "pl-secret")
    assert paperless.upload_ready(settings, user_id) is None  # connected ≠ consenting to send
    paperless.save_account(settings, user_id, upload_enabled=True)
    assert paperless.upload_ready(settings, user_id) == ("http://paperless.test", "pl-secret")
    # None keeps the stored token, empty string forgets it.
    paperless.save_account(settings, user_id, token=None, upload_enabled=True)
    assert paperless.account(settings, user_id)["token"] == "pl-secret"
    paperless.save_account(settings, user_id, token="")
    assert paperless.connection_for(settings, user_id) is None


# --- module: the wire --------------------------------------------------------


def test_upload_file_speaks_multipart_and_returns_the_task(tmp_path: Path, monkeypatch):
    calls: list = []
    monkeypatch.setattr(paperless, "_request", fake_request({"/api/documents/post_document/": TASK_UUID}, calls))
    source = tmp_path / "scan.pdf"
    source.write_bytes(b"%PDF-fake")
    task = paperless.upload_file("http://paperless.test", "tok", source, title="Panel", created="2026-02-13")
    assert task == TASK_UUID
    sent = calls[0]
    assert sent["method"] == "POST"
    assert "multipart/form-data" in sent["headers"]["Content-Type"]
    for expected in (b'name="document"', b"scan.pdf", b"%PDF-fake", b"Panel", b"2026-02-13"):
        assert expected in sent["data"]


def test_task_state_reads_both_id_spellings_and_folds_case(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(paperless, "_request", fake_request({"/api/tasks/": task_reply("SUCCESS", 42)}))
    state = paperless.task_state("http://paperless.test", "tok", TASK_UUID)
    assert state == {"status": "success", "document_id": 42}
    older = {"results": [{"status": "success", "related_document": "7", "result_data": None}]}
    monkeypatch.setattr(paperless, "_request", fake_request({"/api/tasks/": older}))
    assert paperless.task_state("http://paperless.test", "tok", TASK_UUID)["document_id"] == 7


def test_search_cache_answers_repeats_and_swallows_failures(tmp_path: Path, monkeypatch):
    paperless.reset_caches()
    calls: list = []
    monkeypatch.setattr(
        paperless, "_request", fake_request({"/api/documents/": {"results": [{"id": 7}]}}, calls)
    )
    assert paperless.cached_search_ids("http://paperless.test", "tok", "гемоглобін") == [7]
    assert paperless.cached_search_ids("http://paperless.test", "tok", "гемоглобін") == [7]
    assert len(calls) == 1  # second answer came from the cache
    paperless.reset_caches()
    monkeypatch.setattr(
        paperless, "_request", fake_request({"/api/documents/": paperless.PaperlessError("down")})
    )
    assert paperless.cached_search_ids("http://paperless.test", "tok", "anything") == []


# --- module: push and resolve -------------------------------------------------


def test_push_document_records_the_task_and_never_double_sends(tmp_path: Path, monkeypatch):
    settings, user_id, _ = build(tmp_path)
    configure_paperless(settings)
    connect_user(settings, user_id)
    monkeypatch.setattr(paperless, "_request", fake_request({"/api/documents/post_document/": TASK_UUID}))
    assert paperless.push_document(settings, "doc-1") is True
    with connect(settings) as connection:
        row = connection.execute(
            "SELECT paperless_task_id, paperless_id FROM documents WHERE id='doc-1'"
        ).fetchone()
    assert row["paperless_task_id"] == TASK_UUID and row["paperless_id"] is None
    assert paperless.push_document(settings, "doc-1") is False  # already on its way


def test_push_document_respects_every_gate(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("PAPERLESS_URL", raising=False)
    settings, user_id, _ = build(tmp_path)
    monkeypatch.setattr(
        paperless, "_request", fake_request({"/api/documents/post_document/": TASK_UUID})
    )
    assert paperless.push_document(settings, "doc-1") is False  # feature off
    configure_paperless(settings)
    assert paperless.push_document(settings, "doc-1") is False  # no token
    connect_user(settings, user_id, upload=False)
    assert paperless.push_document(settings, "doc-1") is False  # consent unticked
    connect_user(settings, user_id)
    monkeypatch.setattr(
        paperless, "_request", fake_request({"/api/documents/post_document/": paperless.PaperlessError("down")})
    )
    assert paperless.push_document(settings, "doc-1") is False  # server down, ingest unharmed
    with connect(settings) as connection:
        assert (
            connection.execute("SELECT paperless_task_id FROM documents WHERE id='doc-1'").fetchone()[0]
            is None
        )


def test_duplicates_are_not_re_sent(tmp_path: Path, monkeypatch):
    settings, user_id, _ = build(tmp_path)
    configure_paperless(settings)
    connect_user(settings, user_id)
    with connect(settings) as connection:
        # Self-reference keeps the foreign key honest without a second row.
        connection.execute("UPDATE documents SET duplicate_of_document_id='doc-1' WHERE id='doc-1'")
    monkeypatch.setattr(paperless, "_request", fake_request({"/api/documents/post_document/": TASK_UUID}))
    assert paperless.push_document(settings, "doc-1") is False


def test_resolve_pending_links_success_and_forgets_failure(tmp_path: Path, monkeypatch):
    settings, user_id, _ = build(tmp_path)
    configure_paperless(settings)
    connect_user(settings, user_id)
    with connect(settings) as connection:
        connection.execute("UPDATE documents SET paperless_task_id=? WHERE id='doc-1'", (TASK_UUID,))
    monkeypatch.setattr(paperless, "_request", fake_request({"/api/tasks/": task_reply("pending")}))
    assert paperless.resolve_pending(settings, "doc-1") is None  # still cooking, nothing changed
    monkeypatch.setattr(paperless, "_request", fake_request({"/api/tasks/": task_reply("success", 42)}))
    assert paperless.resolve_pending(settings, "doc-1") == 42
    with connect(settings) as connection:
        row = connection.execute(
            "SELECT paperless_id, paperless_task_id FROM documents WHERE id='doc-1'"
        ).fetchone()
    assert row["paperless_id"] == 42 and row["paperless_task_id"] is None

    with connect(settings) as connection:
        connection.execute(
            "UPDATE documents SET paperless_id=NULL, paperless_task_id=? WHERE id='doc-1'", (TASK_UUID,)
        )
    monkeypatch.setattr(paperless, "_request", fake_request({"/api/tasks/": task_reply("failure")}))
    assert paperless.resolve_pending(settings, "doc-1") is None
    with connect(settings) as connection:
        # Cleared, so a later sync may try the upload again.
        assert (
            connection.execute("SELECT paperless_task_id FROM documents WHERE id='doc-1'").fetchone()[0]
            is None
        )


def test_sync_pushes_the_unsent_and_resolves_the_pending(tmp_path: Path, monkeypatch):
    settings, user_id, _ = build(tmp_path)
    configure_paperless(settings)
    connect_user(settings, user_id)
    source = settings.source_dir / "second.pdf"
    source.write_bytes(b"%PDF-second")
    with connect(settings) as connection:
        connection.execute(
            """INSERT INTO documents(id, owner_user_id, patient_id, vendor_id, original_filename,
                   source_path, mime_type, byte_size, sha256, page_count, title, clinical_type,
                   extraction_strategy, imported_at, status, paperless_task_id)
               SELECT 'doc-2', owner_user_id, patient_id, vendor_id, 'second.pdf', ?, mime_type,
                   11, 'sha-2', 1, 'Second', clinical_type, extraction_strategy, ?, status, ?
               FROM documents WHERE id='doc-1'""",
            (str(source), utc_now(), TASK_UUID),
        )
    monkeypatch.setattr(
        paperless,
        "_request",
        fake_request(
            {
                "/api/documents/post_document/": "11111111-2222-3333-4444-555555555555",
                "/api/tasks/": task_reply("success", 42),
            }
        ),
    )
    outcome = paperless.sync_documents(settings, user_id)
    assert outcome == {"pushed": 1, "resolved": 1}
    counts = paperless.link_counts(settings, user_id)
    assert counts["linked"] == 1 and counts["pending"] == 1 and counts["total"] == 2


def test_sync_retries_a_failed_consumption_in_one_pass(tmp_path: Path, monkeypatch):
    """A wrong token or a rejected file must heal on a single press: the sync
    sees the failed task, forgets it, and sends the file again immediately."""
    settings, user_id, _ = build(tmp_path)
    configure_paperless(settings)
    connect_user(settings, user_id)
    with connect(settings) as connection:
        connection.execute("UPDATE documents SET paperless_task_id=? WHERE id='doc-1'", (TASK_UUID,))
    retry_task = "11111111-2222-3333-4444-555555555555"
    monkeypatch.setattr(
        paperless,
        "_request",
        fake_request({"/api/tasks/": task_reply("failure"), "/api/documents/post_document/": retry_task}),
    )
    assert paperless.sync_documents(settings, user_id) == {"pushed": 1, "resolved": 0}
    with connect(settings) as connection:
        assert (
            connection.execute("SELECT paperless_task_id FROM documents WHERE id='doc-1'").fetchone()[0]
            == retry_task
        )


def test_sync_all_users_honours_each_persons_consent(tmp_path: Path, monkeypatch):
    from anamna.security import create_user

    settings, user_id, _ = build(tmp_path)
    configure_paperless(settings)
    connect_user(settings, user_id)
    bystander = create_user(settings, "bystander@example.test", "Bystander", "another-long-password")
    paperless.save_account(settings, bystander, token="pl-other", upload_enabled=False)
    calls: list = []
    monkeypatch.setattr(
        paperless, "_request", fake_request({"/api/documents/post_document/": TASK_UUID}, calls)
    )
    totals = paperless.sync_all_users(settings)
    assert totals == {"users": 1, "pushed": 1, "resolved": 0}
    assert {call["token"] for call in calls} == {"pl-token-abcdef"}  # never the bystander's


# --- intake: the ingest hook --------------------------------------------------


def test_a_finished_ingest_offers_the_document_to_paperless(tmp_path: Path, monkeypatch):
    from anamna.ingest import intake

    settings, user_id, _ = build(tmp_path)
    offered: list[str] = []
    monkeypatch.setattr(paperless, "push_document", lambda s, document_id: offered.append(document_id))
    monkeypatch.setattr(
        intake,
        "ingest_file",
        lambda *a, **k: {"document_id": "doc-new", "action": "ingested", "observations": 3},
    )
    source = settings.source_dir / "fresh.pdf"
    source.write_bytes(b"%PDF-fresh")
    job_id = intake.enqueue(
        settings, owner_user_id=user_id, patient_id=f"patient-{user_id}", batch_id="b1",
        kind="document", filename="fresh.pdf", source_path=source, byte_size=9, start=False,
    )
    with connect(settings) as connection:
        job = connection.execute("SELECT * FROM upload_jobs WHERE id=?", (job_id,)).fetchone()
    intake.run_job(settings, job)
    assert offered == ["doc-new"]

    # An unchanged re-read is not a new file and must not be re-offered.
    offered.clear()
    monkeypatch.setattr(
        intake,
        "ingest_file",
        lambda *a, **k: {"document_id": "doc-new", "action": "unchanged", "observations": 0},
    )
    source.write_bytes(b"%PDF-fresh")
    with connect(settings) as connection:
        job = connection.execute("SELECT * FROM upload_jobs WHERE id=?", (job_id,)).fetchone()
    intake.run_job(settings, job)
    assert offered == []


def test_a_paperless_failure_can_never_fail_the_ingest_that_worked(tmp_path: Path, monkeypatch):
    """`push_document` promises it never raises, and the promise has teeth.

    The hook runs after the job is already marked done, inside `run_job`'s
    blanket `except Exception`, which re-finishes the job as failed with an
    observation count of zero.  So a locked database or an antivirus holding
    the just-written file would report a perfectly good import — values and
    all — as "import failed", inviting the person to upload it again.
    """
    from anamna.ingest import intake

    settings, user_id, _ = build(tmp_path)

    def raiser(_settings, _document_id):
        raise OSError(32, "The process cannot access the file")

    monkeypatch.setattr(paperless, "push_document", raiser)
    monkeypatch.setattr(
        intake,
        "ingest_file",
        lambda *a, **k: {"document_id": "doc-new", "action": "ingested", "observations": 3},
    )
    source = settings.source_dir / "unlucky.pdf"
    source.write_bytes(b"%PDF-unlucky")
    job_id = intake.enqueue(
        settings, owner_user_id=user_id, patient_id=f"patient-{user_id}", batch_id="b2",
        kind="document", filename="unlucky.pdf", source_path=source, byte_size=12, start=False,
    )
    with connect(settings) as connection:
        job = connection.execute("SELECT * FROM upload_jobs WHERE id=?", (job_id,)).fetchone()
    intake.run_job(settings, job)

    with connect(settings) as connection:
        row = connection.execute(
            "SELECT state, observation_count FROM upload_jobs WHERE id=?", (job_id,)
        ).fetchone()
    assert row["state"] == "done", "a mirroring failure marked a good ingest as failed"
    assert row["observation_count"] == 3


def test_a_proxy_block_is_not_reported_as_a_missing_token(tmp_path: Path, monkeypatch):
    """A Cloudflare tunnel refusing us answers 403, and so does Paperless when
    a token is wrong — but they are different jobs for different people.

    Reporting "the server answered, it asks for a token" sends the operator
    hunting a credential problem that does not exist, which is exactly what
    happened when a tunnel blocked our requests on their signature.
    """
    monkeypatch.delenv("PAPERLESS_URL", raising=False)
    settings, user_id, client = build(tmp_path)
    csrf = csrf_for(settings, user_id)
    configure_paperless(settings)

    monkeypatch.setattr(
        paperless, "_request",
        fake_request({"/api/documents/": paperless.PaperlessError(
            "HTTP 403: <!DOCTYPE html><html>error code: 1010</html>")}),
    )
    blocked = client.post(
        "/admin/paperless/test", data={"csrf_token": csrf}, follow_redirects=False
    )
    assert "error=paperless.error_blocked" in blocked.headers["location"]

    # Paperless's own 403 still means "store a token", not "you are blocked".
    monkeypatch.setattr(
        paperless, "_request",
        fake_request({"/api/documents/": paperless.PaperlessError(
            'HTTP 403: {"detail":"Invalid token."}')}),
    )
    needs_token = client.post(
        "/admin/paperless/test", data={"csrf_token": csrf}, follow_redirects=False
    )
    assert "done=reachable" in needs_token.headers["location"]

    # The person's own test button says the same thing, since that is the one
    # they press when their upload failed.
    connect_user(settings, user_id)
    monkeypatch.setattr(
        paperless, "_request",
        fake_request({"/api/documents/": paperless.PaperlessError(
            "HTTP 403: <!DOCTYPE html><html>error code: 1010</html>")}),
    )
    mine = client.post(
        "/profile/paperless/test", data={"csrf_token": csrf}, follow_redirects=False
    )
    assert "error=paperless.error_blocked" in mine.headers["location"]


def test_requests_identify_the_application_rather_than_urllib(tmp_path: Path):
    """Cloudflare's browser integrity check refuses `Python-urllib/3.x`.

    A self-hosted Paperless behind a Cloudflare tunnel answered every upload
    with 403 and error 1010 — which reads like a bad token or a server that is
    down, not like a header we failed to send.
    """
    import threading
    from http.server import BaseHTTPRequestHandler, HTTPServer

    seen: list[str | None] = []

    class Recorder(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            seen.append(self.headers.get("User-Agent"))
            body = b'{"count": 0, "results": []}'
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            return

    server = HTTPServer(("127.0.0.1", 0), Recorder)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        paperless._request(f"http://127.0.0.1:{server.server_port}", "tok", "/api/documents/")
    finally:
        server.shutdown()
        server.server_close()

    assert seen == [paperless.USER_AGENT]
    assert "urllib" not in (seen[0] or "").lower()


def test_the_api_token_is_never_handed_to_a_redirect_target(tmp_path: Path):
    """urllib copies Authorization onto a redirected request, so a 302 would
    give every consenting user's Paperless token to whatever host the Location
    names.  Paperless does not redirect its own API; a 3xx is a wrong address
    or an attack, and must fail rather than follow."""
    import threading
    from http.server import BaseHTTPRequestHandler, HTTPServer

    seen: list[str | None] = []

    class Redirector(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            seen.append(self.headers.get("Authorization"))
            self.send_response(302)
            self.send_header("Location", "http://127.0.0.1:1/stolen")
            self.end_headers()

        def log_message(self, *args):  # keep the test output clean
            return

    server = HTTPServer(("127.0.0.1", 0), Redirector)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        url = f"http://127.0.0.1:{server.server_port}"
        with pytest.raises(paperless.PaperlessError):
            paperless._request(url, "pl-token-abcdef", "/api/documents/")
    finally:
        server.shutdown()
        server.server_close()

    # The first hop legitimately carries the token; there must be no second.
    assert seen == ["Token pl-token-abcdef"]


# --- web: search enrichment ---------------------------------------------------


def test_paperless_full_text_widens_search_to_owned_documents_only(tmp_path: Path, monkeypatch):
    settings, user_id, client = build(tmp_path)
    configure_paperless(settings)
    connect_user(settings, user_id)
    with connect(settings) as connection:
        connection.execute("UPDATE documents SET paperless_id=7 WHERE id='doc-1'")
    # The local index knows 'lipids'; only Paperless knows this wording.
    monkeypatch.setattr(
        paperless, "_request", fake_request({"/api/documents/": {"results": [{"id": 7}, {"id": 999}]}})
    )
    reply = client.get("/api/documents/search?q=cholesterol+wording").json()
    assert reply["total"] == 1  # id 999 maps to nobody's document and vanishes
    assert "doc-1" in reply["documents"]
    page = client.get("/documents?q=cholesterol+wording")
    assert "doc-1" in page.text


def test_search_stays_local_without_a_connection_or_with_the_server_down(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("PAPERLESS_URL", raising=False)
    settings, user_id, client = build(tmp_path)
    with connect(settings) as connection:
        connection.execute("UPDATE documents SET paperless_id=7 WHERE id='doc-1'")

    def exploding(*args, **kwargs):
        raise AssertionError("no connection stored — Paperless must not be asked")

    monkeypatch.setattr(paperless, "_request", exploding)
    assert client.get("/api/documents/search?q=nothing-local").json()["total"] == 0
    assert client.get("/api/documents/search?q=lipids").json()["total"] == 1

    configure_paperless(settings)
    connect_user(settings, user_id)
    monkeypatch.setattr(
        paperless, "_request", fake_request({"/api/documents/": paperless.PaperlessError("down")})
    )
    assert client.get("/api/documents/search?q=lipids").json()["total"] == 1  # local still answers


# --- web: document page -------------------------------------------------------


def test_document_page_links_the_paperless_copy(tmp_path: Path, monkeypatch):
    settings, user_id, client = build(tmp_path)
    configure_paperless(settings)
    connect_user(settings, user_id)
    with connect(settings) as connection:
        connection.execute("UPDATE documents SET paperless_id=7 WHERE id='doc-1'")
    page = client.get("/documents/doc-1")
    assert "http://paperless.test/documents/7/details" in page.text

    # Pending: the page itself resolves the task the moment it succeeds.
    with connect(settings) as connection:
        connection.execute(
            "UPDATE documents SET paperless_id=NULL, paperless_task_id=? WHERE id='doc-1'", (TASK_UUID,)
        )
    monkeypatch.setattr(paperless, "_request", fake_request({"/api/tasks/": task_reply("success", 8)}))
    page = client.get("/documents/doc-1")
    assert "http://paperless.test/documents/8/details" in page.text


def test_document_page_without_paperless_never_mentions_it(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("PAPERLESS_URL", raising=False)
    settings, user_id, client = build(tmp_path)
    page = client.get("/documents/doc-1")
    assert "paperless.test" not in page.text
    assert "Open in Paperless" not in page.text


# --- web: admin page ----------------------------------------------------------


def test_admin_page_saves_url_and_switch(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("PAPERLESS_URL", raising=False)
    settings, user_id, client = build(tmp_path)
    csrf = csrf_for(settings, user_id)
    page = client.get("/admin/paperless")
    assert page.status_code == 200 and "not set" in page.text
    response = client.post(
        "/admin/paperless",
        data={"enabled": "1", "url": "http://paperless.test/", "csrf_token": csrf},
        follow_redirects=False,
    )
    assert response.status_code == 303
    config = paperless.paperless_settings(settings)
    assert config == {"enabled": "1", "url": "http://paperless.test"}  # trailing slash folded
    bad = client.post(
        "/admin/paperless",
        data={"enabled": "1", "url": "paperless.test", "csrf_token": csrf},
        follow_redirects=False,
    )
    assert "error=paperless.error_url" in bad.headers["location"]


def test_a_document_paperless_keeps_refusing_stops_being_re_sent(tmp_path: Path, monkeypatch):
    """A deterministic rejection — a duplicate checksum, a PDF its OCR cannot
    read — used to be re-uploaded on every sync forever while the profile
    reported it as "never sent", inviting the press that would fail again."""
    monkeypatch.delenv("PAPERLESS_URL", raising=False)
    settings, user_id, _ = build(tmp_path)
    configure_paperless(settings)
    connect_user(settings, user_id)
    calls: list = []
    monkeypatch.setattr(
        paperless, "_request",
        fake_request({"/api/documents/post_document/": paperless.PaperlessError("HTTP 400: duplicate")}, calls),
    )
    for _ in range(paperless.MAX_UPLOAD_ATTEMPTS + 2):
        assert paperless.push_document(settings, "doc-1") is False
    assert len(calls) == paperless.MAX_UPLOAD_ATTEMPTS, "it kept re-sending a document already refused"

    counts = paperless.link_counts(settings, user_id)
    assert counts["refused"] == 1
    assert counts["unsent"] == counts["total"] - 1  # refused is carved out, not double-counted

    # Queue acceptance preserves the count until OCR actually succeeds.
    with connect(settings) as connection:
        connection.execute("UPDATE documents SET paperless_attempts=1 WHERE id='doc-1'")
    monkeypatch.setattr(
        paperless, "_request", fake_request({"/api/documents/post_document/": TASK_UUID})
    )
    assert paperless.push_document(settings, "doc-1") is True
    with connect(settings) as connection:
        assert connection.execute(
            "SELECT paperless_attempts FROM documents WHERE id='doc-1'"
        ).fetchone()[0] == 1
    monkeypatch.setattr(paperless, "task_state", lambda *args: {"status": "success", "document_id": 77})
    assert paperless.resolve_pending(settings, "doc-1") == 77
    with connect(settings) as connection:
        assert connection.execute(
            "SELECT paperless_attempts FROM documents WHERE id='doc-1'"
        ).fetchone()[0] == 0


def test_a_working_connection_test_lets_refused_documents_be_tried_again(tmp_path: Path, monkeypatch):
    """The cap must not outlive its cause.

    Uploads that a proxy refused — a Cloudflare tunnel turning away our
    requests, a wrong token, a server that was down — burn the attempt budget.
    Once a round trip proves the transport works, those refusals mean nothing,
    and the sync button has to do something.
    """
    monkeypatch.delenv("PAPERLESS_URL", raising=False)
    settings, user_id, client = build(tmp_path)
    csrf = csrf_for(settings, user_id)
    configure_paperless(settings)
    connect_user(settings, user_id)
    with connect(settings) as connection:
        connection.execute(
            "UPDATE documents SET paperless_attempts=? WHERE id='doc-1'",
            (paperless.MAX_UPLOAD_ATTEMPTS,),
        )
    assert paperless.link_counts(settings, user_id)["refused"] == 1

    monkeypatch.setattr(
        paperless, "_request", fake_request({"/api/documents/": {"count": 3, "results": []}})
    )
    response = client.post(
        "/profile/paperless/test", data={"csrf_token": csrf}, follow_redirects=False
    )
    assert response.status_code == 303
    assert "saved=paperless_test" in response.headers["location"]
    assert paperless.link_counts(settings, user_id)["refused"] == 0

    # And the document really is sendable again.
    calls: list = []
    monkeypatch.setattr(
        paperless, "_request",
        fake_request({"/api/documents/post_document/": TASK_UUID}, calls),
    )
    assert paperless.push_document(settings, "doc-1") is True


def test_changing_the_server_address_takes_everyones_consent_with_it(tmp_path: Path, monkeypatch):
    """Consent was given for a *named* server — the profile page says so.

    Without this, two clicks (save a new URL, then "Send everyone's
    documents") ship every consenting person's back catalogue to a host they
    never agreed to, each request carrying their own Paperless token.
    """
    monkeypatch.delenv("PAPERLESS_URL", raising=False)
    settings, user_id, client = build(tmp_path)
    csrf = csrf_for(settings, user_id)
    configure_paperless(settings)
    connect_user(settings, user_id)
    assert paperless.upload_ready(settings, user_id)

    response = client.post(
        "/admin/paperless",
        data={"enabled": "1", "url": "https://elsewhere.test", "csrf_token": csrf},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert "done=saved_reconsent" in response.headers["location"]  # and it says so

    assert paperless.upload_ready(settings, user_id) is None
    person = paperless.account(settings, user_id)
    assert person["token"] == "" and not person["upload_enabled"]

    # Re-saving the same address is not a change and must not clear anything.
    connect_user(settings, user_id)
    again = client.post(
        "/admin/paperless",
        data={"enabled": "1", "url": "https://elsewhere.test", "csrf_token": csrf},
        follow_redirects=False,
    )
    assert "done=saved" in again.headers["location"]
    assert paperless.upload_ready(settings, user_id)


def test_admin_test_button_tells_reachable_from_signed_in(tmp_path: Path, monkeypatch):
    settings, user_id, client = build(tmp_path)
    configure_paperless(settings)
    csrf = csrf_for(settings, user_id)
    # No token stored: a 401 from the server is reachability, not failure.
    monkeypatch.setattr(
        paperless, "_request", fake_request({"/api/documents/": paperless.PaperlessError("HTTP 401: who?")})
    )
    response = client.post("/admin/paperless/test", data={"csrf_token": csrf}, follow_redirects=False)
    assert "done=reachable" in response.headers["location"]
    connect_user(settings, user_id)
    monkeypatch.setattr(paperless, "_request", fake_request({"/api/documents/": {"count": 3, "results": []}}))
    response = client.post("/admin/paperless/test", data={"csrf_token": csrf}, follow_redirects=False)
    assert "done=test" in response.headers["location"]
    monkeypatch.setattr(
        paperless, "_request", fake_request({"/api/documents/": paperless.PaperlessError("timed out")})
    )
    response = client.post("/admin/paperless/test", data={"csrf_token": csrf}, follow_redirects=False)
    assert "error=paperless.error_unreachable" in response.headers["location"]


def test_admin_sync_button_starts_the_all_accounts_sync(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("PAPERLESS_URL", raising=False)
    settings, user_id, client = build(tmp_path)
    csrf = csrf_for(settings, user_id)
    started: list = []
    monkeypatch.setattr(paperless, "start_sync_all", lambda s: started.append(True))
    # Dormant feature: nothing to sync against, and the page says so.
    response = client.post("/admin/paperless/sync", data={"csrf_token": csrf}, follow_redirects=False)
    assert "error=paperless.error_url" in response.headers["location"]
    assert started == []
    configure_paperless(settings)
    response = client.post("/admin/paperless/sync", data={"csrf_token": csrf}, follow_redirects=False)
    assert "done=sync" in response.headers["location"]
    assert started == [True]


def test_admin_page_refuses_non_admins(tmp_path: Path):
    from fastapi.testclient import TestClient

    from anamna.security import create_session, create_user
    from anamna.web.app import create_app

    settings, _, _ = build(tmp_path)
    other_id = create_user(settings, "second@example.test", "Second", "another-long-password")
    client = TestClient(create_app(settings))
    token, _ = create_session(settings, other_id)
    client.cookies.set("anamna_session", token)
    assert client.get("/admin/paperless").status_code == 403


# --- web: profile -------------------------------------------------------------


def test_connections_tab_appears_only_when_the_feature_is_on(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("PAPERLESS_URL", raising=False)
    settings, user_id, client = build(tmp_path)
    assert 'data-profile-tab="connections"' not in client.get("/profile").text
    configure_paperless(settings)
    page = client.get("/profile").text
    assert 'data-profile-tab="connections"' in page
    assert "http://paperless.test" in page  # which server, said on the page


def test_profile_stores_token_and_consent_and_keeps_the_secret(tmp_path: Path):
    settings, user_id, client = build(tmp_path)
    configure_paperless(settings)
    csrf = csrf_for(settings, user_id)
    response = client.post(
        "/profile/paperless",
        data={"api_token": "pl-secret-123456", "upload_enabled": "1", "csrf_token": csrf},
        follow_redirects=False,
    )
    assert response.status_code == 303
    person = paperless.account(settings, user_id)
    assert person == {"token": "pl-secret-123456", "upload_enabled": True}
    page = client.get("/profile").text
    assert "...123456" in page and "pl-secret-123456" not in page
    # Blank keeps the token while unticking withdraws the sending consent.
    client.post("/profile/paperless", data={"api_token": "", "csrf_token": csrf}, follow_redirects=False)
    person = paperless.account(settings, user_id)
    assert person == {"token": "pl-secret-123456", "upload_enabled": False}
    client.post("/profile/paperless", data={"clear_token": "1", "csrf_token": csrf}, follow_redirects=False)
    assert paperless.account(settings, user_id)["token"] == ""


def test_profile_paperless_routes_hide_when_the_feature_is_off(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("PAPERLESS_URL", raising=False)
    settings, user_id, client = build(tmp_path)
    csrf = csrf_for(settings, user_id)
    response = client.post(
        "/profile/paperless", data={"api_token": "x", "csrf_token": csrf}, follow_redirects=False
    )
    assert response.status_code == 404


def test_profile_test_and_sync_require_their_preconditions(tmp_path: Path, monkeypatch):
    settings, user_id, client = build(tmp_path)
    configure_paperless(settings)
    csrf = csrf_for(settings, user_id)
    response = client.post("/profile/paperless/test", data={"csrf_token": csrf}, follow_redirects=False)
    assert "error=paperless.error_no_token" in response.headers["location"]
    connect_user(settings, user_id, upload=False)
    monkeypatch.setattr(paperless, "_request", fake_request({"/api/documents/": {"count": 1, "results": []}}))
    response = client.post("/profile/paperless/test", data={"csrf_token": csrf}, follow_redirects=False)
    assert "saved=paperless_test" in response.headers["location"]
    response = client.post("/profile/paperless/sync", data={"csrf_token": csrf}, follow_redirects=False)
    assert "error=paperless.error_upload_off" in response.headers["location"]
    connect_user(settings, user_id, upload=True)
    started: list[str] = []
    monkeypatch.setattr(paperless, "start_sync", lambda s, uid: started.append(uid))
    response = client.post("/profile/paperless/sync", data={"csrf_token": csrf}, follow_redirects=False)
    assert "saved=paperless_sync" in response.headers["location"]
    assert started == [user_id]
