"""`/upload` - the trust boundary and the page in front of it.

Everything a browser sends here is untrusted: the filename, the suffix and the
body length. The handler adds nothing to the ingestion path beyond getting the
bytes safely onto disk and putting a job in the queue; the worker does the rest.

A submission no longer produces a document by the time the response is written,
so what these assert is that the right work was *queued*, and that a file the
door turned away left neither bytes on disk nor a silent gap in the queue.
"""

from __future__ import annotations

import io
import re
import time
import zipfile
from pathlib import Path

import pytest

from anamna.db import connect, utc_now
from anamna.ingest import intake
from anamna.ingest.pipeline import SUPPORTED_SUFFIXES, file_sha256
from anamna.web import app as web

from test_web_panels import build


@pytest.fixture(autouse=True)
def deterministic_worker(monkeypatch):
    """Hold the background worker still so a test can watch the queue.

    In the application the worker starts the moment something is enqueued,
    which is the point of it. In a test that races the assertion: a job is
    "Waiting" or "Working" depending on thread scheduling. Every test here
    drives the queue explicitly with `drain_now` instead; the thread itself is
    exercised once, in `test_the_worker_thread_drains_without_being_asked`.
    """
    monkeypatch.setattr(intake, "start_worker", lambda settings: None)


def csrf_for(settings, user_id: str) -> str:
    with connect(settings) as connection:
        return connection.execute(
            "SELECT csrf_token FROM sessions WHERE user_id=?", (user_id,)
        ).fetchone()[0]


def jobs(settings, user_id: str) -> list[dict[str, object]]:
    with connect(settings) as connection:
        return [
            dict(row)
            for row in connection.execute(
                "SELECT * FROM upload_jobs WHERE owner_user_id=? ORDER BY created_at, rowid",
                (user_id,),
            )
        ]


def zip_of(entries: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, payload in entries.items():
            archive.writestr(name, payload)
    return buffer.getvalue()


def test_client_filenames_are_never_trusted():
    assert web._sanitised_upload_name("scan.pdf") == "scan.pdf"
    assert web._sanitised_upload_name("C:\\Users\\me\\scan.pdf") == "scan.pdf"
    assert web._sanitised_upload_name("../../../etc/passwd.pdf") == "passwd.pdf"
    assert web._sanitised_upload_name("результат.pdf") == "результат.pdf"
    # A phone names a scan after the first line it read. Punctuation a person
    # never chose is not a reason to answer "the file could not be opened".
    for accepted in (
        "Найменування_міністерства,_іншого_органу_виконавчої.pdf",
        "аналіз крові (2024) №17.pdf",
        "Дитяча картка щеплень — 2026 [копія]!.pdf",
        "d'Artagnan & co + результат.pdf",
    ):
        assert web._sanitised_upload_name(accepted) == accepted, accepted
    for rejected in (
        "", None, "note.exe", "archive.pdf.exe", ".hidden.pdf", "..",
        "x" * 200 + ".pdf", "con.pdf", "LPT1.pdf", "a\x00b.pdf", 'we"ird:name.pdf',
    ):
        assert web._sanitised_upload_name(rejected) is None, rejected
    assert all(suffix.startswith(".") for suffix in SUPPORTED_SUFFIXES)


def test_upload_requires_a_session(tmp_path: Path):
    settings, _, _ = build(tmp_path)
    from fastapi.testclient import TestClient

    from anamna.web.app import create_app

    anonymous = TestClient(create_app(settings))
    response = anonymous.post(
        "/upload", files={"file": ("scan.pdf", b"%PDF-1.4", "application/pdf")},
        data={"csrf_token": "x"}, follow_redirects=False,
    )
    assert response.status_code == 303
    assert response.headers["location"].startswith("/login")


def test_upload_rejects_a_missing_csrf_token(tmp_path: Path):
    settings, _, client = build(tmp_path)
    response = client.post(
        "/upload", files={"file": ("scan.pdf", b"%PDF-1.4", "application/pdf")},
        data={"csrf_token": "wrong"}, follow_redirects=False,
    )
    assert response.status_code == 303
    assert "upload_error=upload.error_csrf" in response.headers["location"]
    assert not list(settings.source_dir.rglob("scan.pdf"))


def test_upload_rejects_an_unsupported_suffix(tmp_path: Path):
    """A rejected file is named in the queue, not swallowed into a counter.

    One file could be reported in a banner. Forty cannot: "3 were rejected"
    without saying which three is not something a person can act on.
    """
    settings, user_id, client = build(tmp_path)
    client.post(
        "/upload", files={"files": ("payload.exe", b"MZ", "application/octet-stream")},
        data={"csrf_token": csrf_for(settings, user_id)}, follow_redirects=False,
    )
    assert not list(settings.source_dir.rglob("payload.exe"))
    rejected = jobs(settings, user_id)
    assert [(row["filename"], row["state"], row["detail_key"]) for row in rejected] == [
        ("payload.exe", "failed", "intake.failed_unsupported")
    ]
    # Nothing was queued for the worker to pick up.
    assert not [row for row in rejected if row["state"] == "queued"]


def test_upload_caps_the_body_size(tmp_path: Path):
    settings, user_id, client = build(tmp_path)
    oversized = b"%PDF-1.4" + b"0" * (web.MAX_UPLOAD_BYTES + 1024)
    client.post(
        "/upload", files={"files": ("huge.pdf", oversized, "application/pdf")},
        data={"csrf_token": csrf_for(settings, user_id)}, follow_redirects=False,
    )
    assert not list(settings.source_dir.rglob("huge.pdf"))
    assert [row["detail_key"] for row in jobs(settings, user_id)] == ["intake.failed_too_big"]


def test_an_archive_is_allowed_past_the_document_limit(tmp_path: Path):
    """A vendor export legitimately is a multi-gigabyte zip.

    Holding archives to the 32 MB document cap would make the whole
    device-import path unreachable from a browser.
    """
    assert web.upload_limit_for("scan.pdf") == web.MAX_UPLOAD_BYTES
    assert web.upload_limit_for("export.zip") == web.MAX_ARCHIVE_UPLOAD_BYTES
    assert web.MAX_ARCHIVE_UPLOAD_BYTES > web.MAX_UPLOAD_BYTES


def test_upload_writes_into_the_source_dir_and_queues_the_file(tmp_path: Path):
    settings, user_id, client = build(tmp_path)
    response = client.post(
        "/upload",
        files={"files": ("../../new result.pdf", b"%PDF-1.4 payload", "application/pdf")},
        data={"csrf_token": csrf_for(settings, user_id), "next": "/upload"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert response.headers["location"].startswith("/upload?batch=")
    queued = jobs(settings, user_id)
    assert len(queued) == 1
    stored = Path(str(queued[0]["source_path"]))
    # The traversal in the client's filename never reaches the filesystem.
    assert stored.parent == settings.source_dir / "uploads" / utc_now()[:7]
    assert stored.name == "new result.pdf"
    assert stored.is_file()
    assert queued[0]["kind"] == "document"
    assert queued[0]["patient_id"] == f"patient-{user_id}"


def test_a_phone_named_scan_is_accepted(tmp_path: Path):
    """The regression: an iPhone names a scan after the first line it read.

    «Найменування_міністерства,_іншого_органу_виконавчої.pdf» — the opening
    words of the MOZ form the photograph is of — was answered with "the file
    could not be opened, it may be damaged, or its name cannot be used", for
    the comma alone.  Nothing about the file was wrong.
    """
    settings, user_id, client = build(tmp_path)
    name = "Найменування_міністерства,_іншого_органу_виконавчої.pdf"
    response = client.post(
        "/upload",
        files={"files": (name, b"%PDF-1.4 payload", "application/pdf")},
        data={"csrf_token": csrf_for(settings, user_id), "next": "/upload"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    queued = jobs(settings, user_id)
    assert len(queued) == 1
    assert queued[0]["detail_key"] != "intake.failed_unreadable"
    assert queued[0]["kind"] == "document"
    assert Path(str(queued[0]["source_path"])).name == name


def test_a_failing_file_fails_only_itself(tmp_path: Path, monkeypatch):
    """One unreadable page must not take the other thirty-nine with it."""
    settings, user_id, client = build(tmp_path)
    calls: list[str] = []

    def sometimes_explodes(passed_settings, owner_user_id, patient_id, path, run_ocr=True):
        calls.append(Path(path).name)
        if Path(path).name.startswith("broken"):
            raise RuntimeError("unreadable pdf")
        return {"document_id": f"doc-{len(calls)}", "action": "ingested", "filename": Path(path).name, "observations": 2}

    monkeypatch.setattr(intake, "ingest_file", sometimes_explodes)
    client.post(
        "/upload",
        files=[
            ("files", ("broken.pdf", b"%PDF-1.4 a", "application/pdf")),
            ("files", ("fine.pdf", b"%PDF-1.4 b", "application/pdf")),
        ],
        data={"csrf_token": csrf_for(settings, user_id)}, follow_redirects=False,
    )
    intake.drain_now(settings)
    assert calls == ["broken.pdf", "fine.pdf"]
    states = {str(row["filename"]): (row["state"], row["detail_key"]) for row in jobs(settings, user_id)}
    assert states["broken.pdf"] == ("failed", "intake.failed_error")
    assert states["fine.pdf"] == ("done", "intake.done_imported")


def test_a_bug_in_the_pipeline_is_not_reported_as_a_bad_file(tmp_path: Path, monkeypatch):
    """`ValueError` and `KeyError` said "That format is not accepted here".

    Nothing about the file is wrong in either case: those are `zip(strict=True)`
    disagreeing about page counts and a page missing from the report map. The
    deliberate rejections are decided at the door and in the archive handler,
    which answer for themselves, so what arrives here is this software's bug -
    and sending the reader off to convert their PDF is sending them to fix it
    in the one place it cannot be fixed.
    """
    settings, user_id, client = build(tmp_path)
    failures = iter([ValueError("zip() argument 2 is shorter"), KeyError(3)])
    monkeypatch.setattr(intake, "ingest_file", lambda *a, **k: (_ for _ in ()).throw(next(failures)))
    client.post(
        "/upload",
        files=[
            ("files", ("mismatched.pdf", b"%PDF-1.4 a", "application/pdf")),
            ("files", ("unmapped-page.pdf", b"%PDF-1.4 b", "application/pdf")),
        ],
        data={"csrf_token": csrf_for(settings, user_id)}, follow_redirects=False,
    )
    intake.drain_now(settings)
    assert {row["detail_key"] for row in jobs(settings, user_id)} == {"intake.failed_error"}


def test_upload_error_redirects_stay_on_this_site(tmp_path: Path):
    settings, user_id, client = build(tmp_path)
    response = client.post(
        "/upload", files={"files": ("scan.pdf", b"%PDF-1.4", "application/pdf")},
        data={"csrf_token": csrf_for(settings, user_id), "next": "https://evil.test/steal"},
        follow_redirects=False,
    )
    assert response.headers["location"].startswith("/upload?batch=")
    csrf_failure = client.post(
        "/upload", files={"files": ("scan.pdf", b"%PDF-1.4", "application/pdf")},
        data={"csrf_token": "wrong", "next": "https://evil.test/steal"},
        follow_redirects=False,
    )
    assert csrf_failure.headers["location"].startswith("/upload?upload_error=")


# --- sliced uploads ---------------------------------------------------------


def test_a_file_can_arrive_in_slices(tmp_path: Path):
    """Cloudflare 413s any request body over ~100 MB before the app sees it,
    so the page sends big submissions in slices; assembled, they join the same
    queue as a one-request upload, under the session as their batch."""
    settings, user_id, client = build(tmp_path)
    token = csrf_for(settings, user_id)
    session = "11111111-1111-4111-8111-111111111111"
    first, second = b"%PDF-1.4 sliced ", b"payload"

    opening = client.post(
        "/upload/chunk",
        files={"chunk": ("scan.pdf", first, "application/octet-stream")},
        data={"csrf_token": token, "session": session, "offset": "0",
              "filename": "scan.pdf", "final": "0"},
    )
    assert opening.json() == {"status": "ok", "size": len(first)}

    # A repeated or out-of-order slice is refused, answered with what landed.
    replay = client.post(
        "/upload/chunk",
        files={"chunk": ("scan.pdf", first, "application/octet-stream")},
        data={"csrf_token": token, "session": session, "offset": "999",
              "filename": "scan.pdf", "final": "0"},
    )
    assert (replay.status_code, replay.json()["size"]) == (409, len(first))

    closing = client.post(
        "/upload/chunk",
        files={"chunk": ("scan.pdf", second, "application/octet-stream")},
        data={"csrf_token": token, "session": session, "offset": str(len(first)),
              "filename": "scan.pdf", "final": "1"},
    )
    assert closing.json() == {"status": "done"}

    queued = jobs(settings, user_id)
    assert len(queued) == 1
    assert queued[0]["batch_id"] == session
    stored = Path(str(queued[0]["source_path"]))
    assert stored.parent == settings.source_dir / "uploads" / utc_now()[:7]
    assert stored.read_bytes() == first + second
    # Nothing half-assembled stays behind for the validator to trip over.
    assert not list((settings.source_dir / "uploads" / ".partial").iterdir())


def test_a_slice_session_enforces_the_same_door_rules(tmp_path: Path):
    settings, user_id, client = build(tmp_path)
    token = csrf_for(settings, user_id)

    forged = client.post(
        "/upload/chunk",
        files={"chunk": ("scan.pdf", b"x", "application/octet-stream")},
        data={"csrf_token": "wrong", "session": "22222222-2222-4222-8222-222222222222",
              "offset": "0", "filename": "scan.pdf", "final": "1"},
    )
    assert forged.status_code == 403

    # The session names the partial file on disk, so it is a UUID or nothing.
    traversal = client.post(
        "/upload/chunk",
        files={"chunk": ("scan.pdf", b"x", "application/octet-stream")},
        data={"csrf_token": token, "session": "../../etc", "offset": "0",
              "filename": "scan.pdf", "final": "1"},
    )
    assert traversal.status_code == 400

    # The suffix allowlist applies on the first slice, before any byte lands,
    # not after the last slice of a file that was never going to be accepted.
    refused = client.post(
        "/upload/chunk",
        files={"chunk": ("payload.exe", b"MZ", "application/octet-stream")},
        data={"csrf_token": token, "session": "33333333-3333-4333-8333-333333333333",
              "offset": "0", "filename": "payload.exe", "final": "1"},
    )
    assert refused.json() == {"status": "rejected"}
    assert jobs(settings, user_id)[-1]["detail_key"] == "intake.failed_unsupported"
    assert not list(settings.source_dir.rglob("payload.exe"))


# --- the dedicated page -----------------------------------------------------


def recording_ingest(settings):
    """A stand-in for the pipeline that records the file under its real digest.

    The duplicate check reads `documents.sha256`, so a fake ingest has to write
    the same hash the pipeline would.
    """

    def ingest(passed_settings, owner_user_id, patient_id, path, run_ocr=True):
        with connect(settings) as connection:
            vendor_id = connection.execute("SELECT vendor_id FROM documents LIMIT 1").fetchone()[0]
            connection.execute(
                """INSERT INTO documents(
                       id, owner_user_id, patient_id, vendor_id, original_filename, source_path,
                       mime_type, byte_size, sha256, page_count, title, clinical_type,
                       extraction_strategy, classification_confidence, report_date, imported_at, status
                   ) VALUES ('doc-new', ?, ?, ?, ?, ?, 'application/pdf', 10, ?, 1, 'New result',
                             'laboratory', 'native_text', 1, '2025-03-01', ?, 'final')""",
                (
                    owner_user_id, patient_id, vendor_id, path.name, str(path),
                    file_sha256(path), utc_now(),
                ),
            )
        return {"document_id": "doc-new", "action": "ingested", "filename": path.name}

    return ingest


def test_upload_page_states_the_promise_the_limits_and_the_next_step(tmp_path: Path):
    settings, _, client = build(tmp_path)
    body = client.get("/upload").text
    assert "extracted values remain marked as unchecked until you review them" not in body
    # Formats come from the pipeline, never from a list typed into the page.
    for suffix in SUPPORTED_SUFFIXES:
        assert suffix in body
    # The picker offers everything the door takes, archives included. Listing
    # only SUPPORTED_SUFFIXES greyed out the .zip in the iOS Files picker on the
    # same page that tells the reader to upload one, putting every vendor export
    # out of reach on the platform this application is built for first.
    assert f'accept="{",".join(sorted(intake.INTAKE_SUFFIXES))}"' in body
    assert ".zip" in body
    assert "32 MB" in body
    # The most recent upload is listed with how far its extraction has got.
    assert "8 of 8 values still to check" in body
    assert 'id="processing"' in body and "data-upload-disclosure" in body
    assert 'id="upload-next"' not in body and 'id="recent-uploads"' in body
    assert 'action="/documents/doc-1/delete"' in body
    script = (Path(web.__file__).parent / "static" / "uploads.js").read_text(encoding="utf-8")
    assert "anamna:upload-page-state" in script
    # A finished batch updates the list from the poll's own answer instead of
    # reloading the page, and a hidden tab polls nothing (PERF-14).
    assert "location.reload" not in script
    assert "payload.recent_html" in script and "visibilitychange" in script


def test_upload_page_requires_a_session(tmp_path: Path):
    settings, _, _ = build(tmp_path)
    from fastapi.testclient import TestClient

    from anamna.web.app import create_app

    anonymous = TestClient(create_app(settings), follow_redirects=False)
    assert anonymous.get("/upload").headers["location"].startswith("/login")


def test_upload_page_shows_the_specific_error_and_reflects_nothing_else(tmp_path: Path):
    settings, _, client = build(tmp_path)
    named = client.get("/upload?upload_error=upload.error_too_large").text
    assert "That file is too large." in named
    assert 'class="an-upload__error"' in named
    # An unknown key is never resolved onto the page, so nothing arbitrary can
    # be put in front of a reader by handing them a URL.
    forged = client.get("/upload?upload_error=%3Cscript%3Ealert(1)%3C/script%3E").text
    assert "an-upload__error" not in forged
    assert "<script>alert(1)</script>" not in forged


def test_upload_page_is_localized(tmp_path: Path):
    settings, _, client = build(tmp_path)
    client.cookies.set("anamna_lang", "uk")
    body = client.get("/upload").text
    assert "Завантажити документ" in body
    assert "32 МБ" in body
    assert "Upload a document" not in body
    client.cookies.set("anamna_lang", "en")


def test_the_same_file_twice_is_recognised_not_duplicated(tmp_path: Path, monkeypatch):
    settings, user_id, client = build(tmp_path)
    monkeypatch.setattr(intake, "ingest_file", recording_ingest(settings))
    payload = b"%PDF-1.4 the same bytes"
    token = csrf_for(settings, user_id)

    client.post(
        "/upload", files={"files": ("result.pdf", payload, "application/pdf")},
        data={"csrf_token": token}, follow_redirects=False,
    )
    intake.drain_now(settings)

    client.post(
        "/upload", files={"files": ("copy-of-result.pdf", payload, "application/pdf")},
        data={"csrf_token": token}, follow_redirects=False,
    )
    # Matched by checksum, not by name, and reported where the reader is
    # already looking rather than as a banner they have to connect back up.
    duplicate = jobs(settings, user_id)[-1]
    assert (duplicate["state"], duplicate["detail_key"]) == ("skipped", "intake.done_duplicate")
    assert duplicate["document_id"] == "doc-new"

    # No second document, and no second copy of the bytes on disk.
    with connect(settings) as connection:
        assert connection.execute("SELECT COUNT(*) FROM documents WHERE id='doc-new'").fetchone()[0] == 1
    assert not list(settings.source_dir.rglob("copy-of-result.pdf"))

    page = client.get("/upload").text
    assert "Already in your ledger" in page
    assert 'href="/documents/doc-new"' in page


# --- bulk, archives and vendor exports --------------------------------------


def test_many_files_arrive_as_one_batch(tmp_path: Path, monkeypatch):
    settings, user_id, client = build(tmp_path)
    monkeypatch.setattr(
        intake, "ingest_file",
        lambda *_a, **_k: {"document_id": "doc-x", "action": "ingested", "observations": 1},
    )
    response = client.post(
        "/upload",
        files=[
            ("files", (f"scan-{index}.pdf", f"%PDF-1.4 {index}".encode(), "application/pdf"))
            for index in range(5)
        ],
        data={"csrf_token": csrf_for(settings, user_id)}, follow_redirects=False,
    )
    queued = jobs(settings, user_id)
    assert len(queued) == 5
    assert len({row["batch_id"] for row in queued}) == 1
    assert response.headers["location"].endswith(str(queued[0]["batch_id"]))


def test_an_archive_expands_into_one_job_per_document(tmp_path: Path, monkeypatch):
    settings, user_id, client = build(tmp_path)
    monkeypatch.setattr(
        intake, "ingest_file",
        lambda *a, **k: {"document_id": "doc-x", "action": "ingested", "observations": 3},
    )
    bundle = zip_of(
        {
            "clinic/2024/first.pdf": b"%PDF-1.4 one",
            "clinic/2024/notes/second.pdf": b"%PDF-1.4 two",
            "clinic/readme.txt": b"ignore me",
        }
    )
    client.post(
        "/upload", files={"files": ("clinic.zip", bundle, "application/zip")},
        data={"csrf_token": csrf_for(settings, user_id)}, follow_redirects=False,
    )
    intake.drain_now(settings)
    rows = jobs(settings, user_id)
    archive = [row for row in rows if row["kind"] == "archive"][0]
    assert (archive["state"], archive["detail_key"]) == ("done", "intake.done_expanded")
    # Nesting depth is irrelevant; the unsupported file is simply not queued.
    documents = sorted(str(row["filename"]) for row in rows if row["kind"] == "document")
    assert documents == ["first.pdf", "second.pdf"]
    assert all(row["batch_id"] == archive["batch_id"] for row in rows)


def deduping_ingest(settings):
    """A stand-in that answers `unchanged` exactly where the pipeline does.

    `ingest_file` returns `unchanged`, and writes nothing whatsoever, when a
    document already holds these bytes under this name. The zips here are not
    readable PDFs so the real extractor cannot run them, but the branch under
    test is what intake does with that answer.
    """

    def ingest(passed_settings, owner_user_id, patient_id, path, run_ocr=True):
        digest = file_sha256(path)
        with connect(settings) as connection:
            held = connection.execute(
                "SELECT id FROM documents WHERE owner_user_id=? AND sha256=? AND original_filename=?",
                (owner_user_id, digest, path.name),
            ).fetchone()
            if held:
                return {"filename": path.name, "document_id": str(held["id"]), "action": "unchanged"}
            document_id = f"doc-{digest[:8]}"
            vendor_id = connection.execute("SELECT vendor_id FROM documents LIMIT 1").fetchone()[0]
            connection.execute(
                """INSERT INTO documents(
                       id, owner_user_id, patient_id, vendor_id, original_filename, source_path,
                       mime_type, byte_size, sha256, page_count, title, clinical_type,
                       extraction_strategy, classification_confidence, report_date, imported_at, status
                   ) VALUES (?, ?, ?, ?, ?, ?, 'application/pdf', 10, ?, 1, 'Bundled result',
                             'laboratory', 'native_text', 1, '2025-03-01', ?, 'final')""",
                (
                    document_id, owner_user_id, patient_id, vendor_id, path.name, str(path),
                    digest, utc_now(),
                ),
            )
        return {"document_id": document_id, "action": "ingested", "filename": path.name, "observations": 1}

    return ingest


def test_re_uploading_an_archive_leaves_no_file_the_record_does_not_point_at(
    tmp_path: Path, monkeypatch
):
    """The door dedupes a single file by checksum; an archive's contents skip it.

    So the same zip a second time expands into a fresh directory, every file in
    it resolves as already held, and the copies stay on disk referenced by
    nothing - which `validate_source_extraction.py` reports as an error, and
    correctly: a file in `sources/` that no document points at looks exactly
    like an upload that was lost.
    """
    settings, user_id, client = build(tmp_path)
    monkeypatch.setattr(intake, "ingest_file", deduping_ingest(settings))
    bundle = zip_of({"clinic/first.pdf": b"%PDF-1.4 one", "clinic/second.pdf": b"%PDF-1.4 two"})
    token = csrf_for(settings, user_id)
    for _ in range(2):
        client.post(
            "/upload", files={"files": ("clinic.zip", bundle, "application/zip")},
            data={"csrf_token": token}, follow_redirects=False,
        )
        intake.drain_now(settings)

    uploads = settings.source_dir / "uploads"
    with connect(settings) as connection:
        referenced = {
            Path(str(row["source_path"])).resolve()
            for row in connection.execute("SELECT source_path FROM documents")
        }
    on_disk = {path.resolve() for path in uploads.rglob("*.pdf")}
    assert on_disk and on_disk <= referenced
    # And the expansion directory the second upload created is gone with them,
    # rather than left as an empty tree under this month's arrivals.
    assert len([path for path in uploads.rglob("clinic-*") if path.is_dir()]) == 1
    # Both jobs still report what happened; nothing was swallowed.
    assert [row["detail_key"] for row in jobs(settings, user_id)].count("intake.done_unchanged") == 2


def test_a_curated_source_file_is_never_removed_by_the_queue(tmp_path: Path):
    """The CLI hands `ingest_file` the record's own evidence from `sources/`.

    Those files are what every document row points at, so "this one is already
    held" is the last reason to delete one. Only a fresh arrival under
    `sources/uploads` is this queue's to clean up.
    """
    settings, _, _ = build(tmp_path)
    curated = settings.source_dir / "report.pdf"
    intake._discard_upload_copy(settings, curated)
    assert curated.is_file()


def test_an_archive_entry_cannot_write_outside_the_upload_directory(tmp_path: Path):
    """Zip slip. The entry is skipped, and nothing lands above the target."""
    outside = tmp_path / "escaped.pdf"
    target = tmp_path / "extract"
    (tmp_path / "b.zip").write_bytes(
        zip_of({"../../escaped.pdf": b"%PDF-1.4 evil", "safe.pdf": b"%PDF-1.4 ok"})
    )
    produced = intake.expand_archive(tmp_path / "b.zip", target)
    assert not outside.exists()
    assert all(target.resolve() in path.resolve().parents for path in produced)
    assert [path.name for path in produced] == ["safe.pdf"]


def test_an_apple_health_export_is_recognised_by_its_own_layout(tmp_path: Path):
    bundle = zip_of(
        {
            "apple_health_export/export.xml": b"<HealthData/>",
            "apple_health_export/electrocardiograms/ecg.csv": b"Name,x",
            "apple_health_export/workout-routes/route.gpx": b"<gpx/>",
        }
    )
    path = tmp_path / "export.zip"
    path.write_bytes(bundle)
    adapter, root = intake.detect_archive_adapter(path)
    # The adapter looks for export.xml *beside* the root it is handed, so the
    # detected root has to be the directory that holds it, not the zip's top.
    assert (adapter, root) == ("apple_health", "apple_health_export")


def test_oura_and_garmin_are_told_apart_by_their_field_names(tmp_path: Path):
    oura = tmp_path / "oura-export.zip"
    oura.write_bytes(zip_of({"sleep/data.json": b'[{"bedtime_start":"2026-01-01","readiness_score":88}]'}))
    assert intake.detect_archive_adapter(oura)[0] == "oura"

    garmin = tmp_path / "connect.zip"
    garmin.write_bytes(
        zip_of({"DI_CONNECT/wellness/UDSFile_1.json": b'[{"calendarDate":"2026-01-01","restingHeartRate":52}]'})
    )
    assert intake.detect_archive_adapter(garmin)[0] == "garmin"

    documents = tmp_path / "scans.zip"
    documents.write_bytes(zip_of({"a.pdf": b"%PDF-1.4", "b.pdf": b"%PDF-1.4"}))
    assert intake.detect_archive_adapter(documents) == (None, "")


def test_official_oura_takeout_is_recognised_by_its_layout(tmp_path: Path):
    takeout = tmp_path / "data.zip"
    takeout.write_bytes(zip_of({
        "App Data/dailyactivity.csv": b"id;day;score;steps\na;2026-08-01;80;8000\n",
        "App Data/dailyreadiness.csv": b"id;day;score\nr;2026-08-01;82\n",
        "App Data/dailysleep.csv": b"id;day;score\ns;2026-08-01;84\n",
        "App Data/sleepmodel.csv": b"id;day;total_sleep_duration\nz;2026-08-01;25200\n",
        "Subscriptions/account.csv": b"id;email\n1;person@example.test\n",
    }))

    assert intake.detect_archive_adapter(takeout) == ("oura", "")


def test_official_oura_takeout_runs_end_to_end_as_a_device_import(tmp_path: Path):
    settings, user_id, client = build(tmp_path)
    bundle = zip_of({
        "App Data/dailyactivity.csv": (
            b"id;day;score;steps;active_calories;total_calories;medium_activity_time;high_activity_time\n"
            b"a;2026-08-01;80;8000;400;2400;3600;600\n"
        ),
        "App Data/dailyreadiness.csv": (
            b"id;day;score;temperature_deviation\nr;2026-08-01;82;-0.1\n"
        ),
        "App Data/dailysleep.csv": b"id;day;score\ns;2026-08-01;84\n",
        "App Data/sleepmodel.csv": (
            b"id;day;type;bedtime_start;total_sleep_duration;deep_sleep_duration;"
            b"rem_sleep_duration;light_sleep_duration;awake_time;time_in_bed;lowest_heart_rate;"
            b"average_hrv;average_breath;efficiency\n"
            b"z;2026-08-01;long_sleep;2026-08-01T00:00:00+00:00;25200;3600;5400;"
            b"16200;1800;27000;52;45;13.5;93\n"
        ),
    })

    response = client.post(
        "/upload", files={"files": ("data.zip", bundle, "application/zip")},
        data={"csrf_token": csrf_for(settings, user_id)}, follow_redirects=False,
    )
    assert response.status_code == 303
    intake.drain_now(settings)

    rows = jobs(settings, user_id)
    device = [row for row in rows if row["kind"] == "device_export"][0]
    assert (device["adapter_key"], device["state"]) == ("oura", "done")
    with connect(settings) as connection:
        stored = {
            str(row["metric_key"]): float(row["value"])
            for row in connection.execute(
                "SELECT metric_key, value FROM device_metric_days WHERE owner_user_id=?",
                (user_id,),
            )
        }
    assert stored["steps"] == 8000
    assert stored["activity_score"] == 80
    assert stored["readiness_score"] == 82
    assert stored["sleep_score"] == 84
    assert stored["sleep_duration"] == 7


def test_a_vendor_export_becomes_a_device_import_job(tmp_path: Path, monkeypatch):
    settings, user_id, client = build(tmp_path)
    seen: dict[str, object] = {}

    def fake_import(passed_settings, *, owner_user_id, patient_id, vendor_key, source):
        seen.update({"vendor": vendor_key, "root": Path(source)})
        return {"import_id": "import-1", "daily_metrics": 42}

    monkeypatch.setattr("anamna.devices.import_device_export", fake_import)
    bundle = zip_of({"apple_health_export/export.xml": b"<HealthData/>"})
    client.post(
        "/upload", files={"files": ("export.zip", bundle, "application/zip")},
        data={"csrf_token": csrf_for(settings, user_id)}, follow_redirects=False,
    )
    intake.drain_now(settings)
    assert seen["vendor"] == "apple_health"
    assert seen["root"].name == "apple_health_export"
    device = [row for row in jobs(settings, user_id) if row["kind"] == "device_export"][0]
    assert (device["state"], device["import_id"], device["observation_count"]) == ("done", "import-1", 42)


def test_a_document_shaped_file_inside_a_device_export_is_recorded_not_stranded(
    tmp_path: Path, monkeypatch
):
    """Garmin exports ship the account's avatar PNGs beside the health data.

    They stay on disk with the export, so each needs a queue row naming it —
    a kept file with no row reads as a lost import to the extraction validator.
    """
    settings, user_id, client = build(tmp_path)
    monkeypatch.setattr(
        "anamna.devices.import_device_export",
        lambda *a, **k: {"import_id": "import-4", "daily_metrics": 1},
    )
    bundle = zip_of({
        "DI_CONNECT/wellness/UDSFile_1.json": b'[{"calendarDate":"2026-01-01","restingHeartRate":52}]',
        "DI_CONNECT/DI-Connect-User/profile-image-large.png": b"\x89PNG\r\n\x1a\n",
    })
    client.post(
        "/upload", files={"files": ("connect.zip", bundle, "application/zip")},
        data={"csrf_token": csrf_for(settings, user_id)}, follow_redirects=False,
    )
    intake.drain_now(settings)
    rows = jobs(settings, user_id)
    rejected = [row for row in rows if row["detail_key"] == "intake.failed_device_archive_member"]
    assert len(rejected) == 1
    assert rejected[0]["filename"] == "profile-image-large.png"
    assert rejected[0]["state"] == "failed"
    assert rejected[0]["source_path"] and Path(str(rejected[0]["source_path"])).is_file()
    device = [row for row in rows if row["kind"] == "device_export"][0]
    assert device["state"] == "done"


def test_naming_the_vendor_skips_detection(tmp_path: Path, monkeypatch):
    """A reader who knows what they exported should not have to hope."""
    settings, user_id, client = build(tmp_path)
    monkeypatch.setattr(
        "anamna.devices.import_device_export",
        lambda *a, **k: {"import_id": "import-2", "daily_metrics": 7},
    )
    client.post(
        "/upload", files={"files": ("recording.pdf", b"%PDF-1.4 ecg", "application/pdf")},
        data={"csrf_token": csrf_for(settings, user_id), "kind": "kardia"},
        follow_redirects=False,
    )
    job = jobs(settings, user_id)[-1]
    assert (job["kind"], job["adapter_key"]) == ("device_export", "kardia")
    intake.drain_now(settings)
    assert jobs(settings, user_id)[-1]["import_id"] == "import-2"


def test_naming_the_vendor_wins_over_detection_for_an_archive(tmp_path: Path, monkeypatch):
    """Detection reads structure; the reader knows what they exported.

    An Oura zip of plain JSON has no layout that names it, so an archive that
    ignored the answer on the form would silently unpack as documents and find
    nothing to file.
    """
    settings, user_id, client = build(tmp_path)
    seen: dict[str, object] = {}
    monkeypatch.setattr(
        "anamna.devices.import_device_export",
        lambda *a, **k: seen.update(k) or {"import_id": "import-3", "daily_metrics": 5},
    )
    bundle = zip_of({"sleep/2026-01.json": b'[{"day":"2026-01-01","score":77}]'})
    client.post(
        "/upload", files={"files": ("my-ring-data.zip", bundle, "application/zip")},
        data={"csrf_token": csrf_for(settings, user_id), "kind": "oura"},
        follow_redirects=False,
    )
    intake.drain_now(settings)
    assert seen["vendor_key"] == "oura"
    device = [row for row in jobs(settings, user_id) if row["kind"] == "device_export"][0]
    assert (device["adapter_key"], device["state"]) == ("oura", "done")


def test_an_unknown_vendor_key_is_refused(tmp_path: Path):
    settings, user_id, client = build(tmp_path)
    response = client.post(
        "/upload", files={"files": ("scan.pdf", b"%PDF-1.4", "application/pdf")},
        data={"csrf_token": csrf_for(settings, user_id), "kind": "../etc"},
        follow_redirects=False,
    )
    assert response.status_code == 400
    assert not jobs(settings, user_id)


# --- the processing area ----------------------------------------------------


def test_the_queue_endpoint_reports_progress_in_the_reader_s_language(tmp_path: Path, monkeypatch):
    settings, user_id, client = build(tmp_path)
    monkeypatch.setattr(
        intake, "ingest_file",
        lambda *a, **k: {"document_id": "doc-1", "action": "ingested", "observations": 8},
    )
    client.post(
        "/upload", files={"files": ("result.pdf", b"%PDF-1.4", "application/pdf")},
        data={"csrf_token": csrf_for(settings, user_id)}, follow_redirects=False,
    )
    waiting = client.get("/api/uploads/queue").json()
    assert waiting["active"] == 1
    assert waiting["jobs"][0]["state_text"] == "Waiting"
    assert waiting["jobs"][0]["filename"] == "result.pdf"

    intake.drain_now(settings)
    finished = client.get("/api/uploads/queue").json()
    assert (finished["active"], finished["done"]) == (0, 1)
    assert finished["jobs"][0]["summary_text"] == "8 values"
    assert finished["jobs"][0]["url"] == "/documents/doc-1"

    client.cookies.set("anamna_lang", "uk")
    localized = client.get("/api/uploads/queue").json()
    assert localized["jobs"][0]["state_text"] == "Готово"
    assert localized["jobs"][0]["summary_text"] == "8 значень"
    client.cookies.set("anamna_lang", "en")


def test_the_queue_is_private_to_its_owner(tmp_path: Path):
    settings, user_id, client = build(tmp_path)
    from fastapi.testclient import TestClient

    from anamna.web.app import create_app

    anonymous = TestClient(create_app(settings), follow_redirects=False)
    # An API path answers 401 rather than redirecting: a poll that follows a
    # redirect would parse the login page as its payload.
    assert anonymous.get("/api/uploads/queue").status_code == 401

    # A real second account, because the queue's owner column is a foreign key
    # and an invented id would prove nothing about isolation.
    from anamna.security import create_user

    other = create_user(settings, "other@example.test", "Other", "correct horse battery")
    with connect(settings) as connection:
        connection.execute(
            """INSERT INTO patients(id, owner_user_id, display_name, date_of_birth, sex_at_birth, created_at)
               VALUES (?, ?, 'Other Patient', '1990-01-01', 'female', ?)""",
            (f"patient-{other}", other, utc_now()),
        )
    intake.enqueue(
        settings, owner_user_id=other, patient_id=f"patient-{other}", batch_id="b",
        kind="document", filename="theirs.pdf", start=False,
    )
    assert client.get("/api/uploads/queue").json()["jobs"] == []


def test_the_worker_thread_drains_without_being_asked(tmp_path: Path, monkeypatch):
    """The one test that lets the real worker run.

    Everything else here freezes it for determinism, so this is where the
    thread that actually does the work in production is proven to start on
    enqueue, finish the batch, and stand down.
    """
    settings, user_id, client = build(tmp_path)
    monkeypatch.undo()  # release the module-wide freeze on start_worker
    monkeypatch.setattr(
        intake, "ingest_file",
        lambda *a, **k: {"document_id": "doc-1", "action": "ingested", "observations": 1},
    )
    client.post(
        "/upload",
        files=[("files", (f"s{index}.pdf", b"%PDF-1.4", "application/pdf")) for index in range(3)],
        data={"csrf_token": csrf_for(settings, user_id)}, follow_redirects=False,
    )
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        if all(row["state"] == "done" for row in jobs(settings, user_id)):
            break
        time.sleep(0.05)
    assert [row["state"] for row in jobs(settings, user_id)] == ["done"] * 3
    # It stops when there is nothing left rather than spinning on an empty queue.
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline and intake._WORKERS.get(str(settings.database_path)):
        time.sleep(0.05)
    assert not intake._WORKERS.get(str(settings.database_path))


def test_clearing_the_queue_leaves_work_in_progress_alone(tmp_path: Path):
    settings, user_id, client = build(tmp_path)
    common = dict(owner_user_id=user_id, patient_id=f"patient-{user_id}", batch_id="b", start=False)
    intake.enqueue(settings, **common, kind="document", filename="waiting.pdf")
    done = intake.enqueue(settings, **common, kind="document", filename="finished.pdf")
    intake._finish(settings, done, "done", "intake.done_imported", observations=2)

    client.post("/uploads/clear", data={"csrf_token": csrf_for(settings, user_id)}, follow_redirects=False)
    assert [row["filename"] for row in jobs(settings, user_id)] == ["waiting.pdf"]


def test_a_duplicate_id_from_another_owner_is_ignored(tmp_path: Path):
    settings, _, client = build(tmp_path)
    assert "duplicate_notice" not in client.get("/upload?duplicate=doc-does-not-exist").text
    assert "already in your ledger" not in client.get("/upload?duplicate=doc-1x").text


# --- what stays on disk -----------------------------------------------------


def test_an_expanded_archive_does_not_keep_a_second_copy_of_itself(tmp_path: Path):
    """Every byte of the zip is on disk unpacked once it has been expanded.

    Keeping both doubled the storage of every upload for no second copy of
    anything -- and a vendor export is gigabytes, so the duplicate is the
    largest single thing in the sources tree.
    """
    settings, user_id, client = build(tmp_path)
    payload = zip_of({"a.pdf": b"%PDF-1.4 first", "b.pdf": b"%PDF-1.4 second"})
    client.post(
        "/upload",
        files={"files": ("clinic.zip", payload, "application/zip")},
        data={"csrf_token": csrf_for(settings, user_id)},
        follow_redirects=False,
    )
    intake.drain_now(settings)

    remaining = sorted(p.name for p in settings.source_dir.rglob("*") if p.is_file())
    assert "clinic.zip" not in remaining
    assert {"a.pdf", "b.pdf"} <= set(remaining)


def test_an_archive_nothing_could_be_read_from_keeps_the_zip_not_the_expansion(tmp_path: Path):
    settings, user_id, client = build(tmp_path)
    payload = zip_of({"notes.txt": b"nothing importable here"})
    client.post(
        "/upload",
        files={"files": ("empty-clinic.zip", payload, "application/zip")},
        data={"csrf_token": csrf_for(settings, user_id)},
        follow_redirects=False,
    )
    intake.drain_now(settings)

    files = [p for p in settings.source_dir.rglob("*") if p.is_file()]
    # The zip is the only evidence of what arrived, so it stays; its expansion
    # produced nothing and does not.
    assert [p.name for p in files if p.suffix == ".zip"] == ["empty-clinic.zip"]
    assert not any(p.name == "notes.txt" for p in files)
    assert jobs(settings, user_id)[-1]["detail_key"] == "intake.failed_empty"


def test_clearing_the_queue_takes_the_bytes_of_what_it_clears(tmp_path: Path, monkeypatch):
    """A rejected upload is kept so a person can see it, and the queue row is
    the only thing naming it. Clearing the row without the file left bytes that
    `validate_source_extraction.py` reports as a blocking error for good."""
    def explode(*args, **kwargs):
        raise RuntimeError("unreadable")

    monkeypatch.setattr("anamna.ingest.intake.ingest_file", explode)
    settings, user_id, client = build(tmp_path)
    client.post(
        "/upload",
        files={"files": ("broken.pdf", b"%PDF-1.4 truncated", "application/pdf")},
        data={"csrf_token": csrf_for(settings, user_id)},
        follow_redirects=False,
    )
    intake.drain_now(settings)

    kept = [p for p in settings.source_dir.rglob("broken.pdf")]
    assert kept, "a rejected upload is kept so the reader can see which file it was"
    assert jobs(settings, user_id)[-1]["state"] == "failed"

    intake.clear_finished(settings, user_id)
    assert not list(settings.source_dir.rglob("broken.pdf"))
    assert jobs(settings, user_id) == []


def test_a_bearer_credential_may_use_the_door(tmp_path: Path):
    """The one route an agent token most needs, and the one it was locked out of.

    CSRF guards a cookie session: a browser attaches cookies on its own and an
    `Authorization` header on nobody's behalf, so a bearer request has no
    cross-site request to forge. Every other write route says so by going
    through `require_csrf`; both upload routes compared the token by hand
    instead, and answered an agent credential with "your session expired" on the
    one route a deployment check has to exercise.
    """
    from fastapi.testclient import TestClient

    from anamna.security import create_access_token
    from anamna.web.app import create_app

    settings, user_id, client = build(tmp_path)
    _, secret = create_access_token(settings, user_id, kind="agent", label="deploy check")
    anonymous = TestClient(create_app(settings))

    response = anonymous.post(
        "/upload",
        files={"files": ("scan.pdf", b"%PDF-1.4 payload", "application/pdf")},
        data={"next": "/upload"},
        headers={"Authorization": f"Bearer {secret}"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert "upload_error" not in response.headers["location"]
    assert len(jobs(settings, user_id)) == 1

    # A cookie session with no token is still refused: the exemption is for the
    # header, not for everyone.
    refused = client.post(
        "/upload",
        files={"files": ("other.pdf", b"%PDF-1.4 payload", "application/pdf")},
        data={"csrf_token": "wrong", "next": "/upload"},
        follow_redirects=False,
    )
    assert "upload_error=upload.error_csrf" in refused.headers["location"]
    assert len(jobs(settings, user_id)) == 1


def test_finished_uploads_fold_after_the_newest_few(tmp_path: Path):
    """Sixty finished imports under one failure made /upload an 11,000px phone
    page: only the newest five finished rows show, the failure always does,
    and the rest are one "Show all" away (the poll applies the same rule)."""
    settings, user_id, client = build(tmp_path)
    with connect(settings) as connection:
        for number in range(8):
            connection.execute(
                """INSERT INTO upload_jobs(id, owner_user_id, patient_id, batch_id, kind, filename,
                       state, detail_key, created_at)
                   VALUES (?, ?, ?, 'b', 'document', ?, 'done', 'intake.done_imported', ?)""",
                (f"done-{number}", user_id, f"patient-{user_id}", f"scan-{number}.pdf",
                 f"2026-11-0{number + 1}T10:00:00+00:00"),
            )
        connection.execute(
            """INSERT INTO upload_jobs(id, owner_user_id, patient_id, batch_id, kind, filename,
                   state, detail_key, created_at)
               VALUES ('broken', ?, ?, 'b', 'document', 'broken.pdf', 'failed', 'intake.failed_unreadable',
                       '2026-10-01T10:00:00+00:00')""",
            (user_id, f"patient-{user_id}"),
        )
    body = client.get("/upload").text
    rows = re.findall(r'<li class="an-queue__item[^"]*" data-job="([\w-]+)"([^>]*)>', body)
    hidden = [job for job, attrs in rows if " hidden" in attrs]
    assert len(rows) == 9 and len(hidden) == 3
    # The oldest finished rows fold; the failure, older still, never does.
    assert set(hidden) == {"done-0", "done-1", "done-2"}
    assert 'data-job="broken">' in body
    assert re.search(r'<p class="an-queue__more">\s*<button[^>]*data-queue-all[^>]*>Show all 9</button>', body)
    payload = client.get("/api/uploads/queue").json()
    assert sum(job["finished"] for job in payload["jobs"]) == 8
    script = (Path(web.__file__).parent / "static" / "uploads.js").read_text(encoding="utf-8")
    assert "fold();" in script and "data-finished" in script
