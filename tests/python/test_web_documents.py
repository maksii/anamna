from __future__ import annotations

from pathlib import Path

from anamna.db import connect
from anamna.web import app as web

from test_web_panels import build


def csrf_for(settings, user_id: str) -> str:
    with connect(settings) as connection:
        return str(
            connection.execute(
                "SELECT csrf_token FROM sessions WHERE user_id=?", (user_id,)
            ).fetchone()[0]
        )


def add_document(
    settings,
    user_id: str,
    document_id: str,
    filename: str,
    imported_at: str,
    *,
    report_date: str | None = None,
    duplicate_of: str | None = None,
    vendor: bool = True,
) -> Path:
    source = settings.source_dir / "uploads" / "2026-08" / filename
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text(f"source for {document_id}", encoding="utf-8")
    with connect(settings) as connection:
        seed = connection.execute(
            "SELECT patient_id, vendor_id FROM documents WHERE id='doc-1'"
        ).fetchone()
        connection.execute(
            """INSERT INTO documents(
                   id, owner_user_id, patient_id, vendor_id, original_filename, source_path,
                   mime_type, byte_size, sha256, page_count, title, clinical_type,
                   extraction_strategy, classification_confidence, report_date, imported_at,
                   status, duplicate_of_document_id
               ) VALUES (?, ?, ?, ?, ?, ?, 'text/plain', ?, 'sha-1', 0, '', '', '', 0, ?, ?,
                         'processing', ?)""",
            (
                document_id,
                user_id,
                seed["patient_id"],
                seed["vendor_id"] if vendor else None,
                filename,
                str(source),
                source.stat().st_size,
                report_date,
                imported_at,
                duplicate_of,
            ),
        )
    return source


def test_document_lists_include_unindexed_incomplete_uploads_and_use_upload_order(tmp_path: Path):
    settings, user_id, client = build(tmp_path)
    with connect(settings) as connection:
        connection.execute(
            "UPDATE documents SET imported_at='2024-01-01T00:00:00+00:00', report_date='2099-01-01' WHERE id='doc-1'"
        )
    add_document(
        settings, user_id, "doc-middle", "middle.txt", "2025-01-01T00:00:00+00:00",
        report_date="2000-01-01",
    )
    add_document(
        settings, user_id, "doc-new", "new-unindexed.txt", "2026-01-01T00:00:00+00:00",
        vendor=False,
    )

    documents = client.get("/documents").text
    home = client.get("/").text
    for body in (documents, home):
        assert '/documents/doc-new' in body
        assert '/documents/doc-middle' in body
        assert '/documents/doc-1' in body
        assert body.index('/documents/doc-new') < body.index('/documents/doc-middle')
        assert body.index('/documents/doc-middle') < body.index('/documents/doc-1')

    # A missing derived search row does not make even filename search lose it,
    # and a missing vendor does not make its detail route unreachable.
    assert '/documents/doc-new' in client.get("/documents?q=new-unindexed").text
    assert client.get("/documents/doc-new").status_code == 200


def test_deleting_a_duplicate_removes_only_that_row_and_its_file(tmp_path: Path):
    settings, user_id, client = build(tmp_path)
    duplicate_source = add_document(
        settings, user_id, "doc-copy", "copy.txt", "2026-01-01T00:00:00+00:00",
        duplicate_of="doc-1",
    )
    with connect(settings) as connection:
        original_source = Path(
            connection.execute("SELECT source_path FROM documents WHERE id='doc-1'").fetchone()[0]
        )

    response = client.post(
        "/documents/doc-copy/delete",
        data={"csrf_token": csrf_for(settings, user_id), "next": "/upload"},
        follow_redirects=False,
    )
    assert response.headers["location"] == "/upload?deleted=1"
    assert original_source.is_file()
    assert not duplicate_source.exists()
    with connect(settings) as connection:
        assert connection.execute("SELECT 1 FROM documents WHERE id='doc-1'").fetchone()
        assert connection.execute("SELECT 1 FROM documents WHERE id='doc-copy'").fetchone() is None
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []


def test_deleting_the_primary_promotes_and_requeues_a_surviving_copy(
    tmp_path: Path, monkeypatch
):
    settings, user_id, client = build(tmp_path)
    monkeypatch.setattr(web, "start_worker", lambda settings: None)
    first = add_document(
        settings, user_id, "doc-copy-1", "copy-1.txt", "2025-01-01T00:00:00+00:00",
        duplicate_of="doc-1",
    )
    second = add_document(
        settings, user_id, "doc-copy-2", "copy-2.txt", "2026-01-01T00:00:00+00:00",
        duplicate_of="doc-1",
    )
    with connect(settings) as connection:
        original_source = Path(
            connection.execute("SELECT source_path FROM documents WHERE id='doc-1'").fetchone()[0]
        )
        patient = connection.execute("SELECT patient_id FROM documents WHERE id='doc-1'").fetchone()[0]
        connection.execute(
            """INSERT INTO upload_jobs(
                   id, owner_user_id, patient_id, batch_id, kind, filename, state,
                   detail_key, document_id, created_at
               ) VALUES ('old-duplicate-job', ?, ?, 'old-batch', 'document', 'same-again.txt',
                         'skipped', 'intake.done_duplicate', 'doc-1', '2026-01-02T00:00:00+00:00')""",
            (user_id, patient),
        )

    response = client.post(
        "/documents/doc-1/delete",
        data={"csrf_token": csrf_for(settings, user_id), "next": "/documents"},
        follow_redirects=False,
    )
    assert response.headers["location"] == "/documents?deleted=1&promoted=1"
    assert not original_source.exists()
    assert first.is_file() and second.is_file()
    with connect(settings) as connection:
        assert connection.execute("SELECT 1 FROM documents WHERE id='doc-1'").fetchone() is None
        assert connection.execute(
            "SELECT duplicate_of_document_id FROM documents WHERE id='doc-copy-1'"
        ).fetchone()[0] is None
        assert connection.execute(
            "SELECT duplicate_of_document_id FROM documents WHERE id='doc-copy-2'"
        ).fetchone()[0] == "doc-copy-1"
        jobs = connection.execute(
            "SELECT kind, state, document_id FROM upload_jobs ORDER BY rowid"
        ).fetchall()
        assert (jobs[0][0], jobs[0][1], jobs[0][2]) == ("document", "skipped", "doc-copy-1")
        assert (jobs[-1][0], jobs[-1][1], jobs[-1][2]) == ("rescan", "queued", "doc-copy-1")
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []

    promoted_page = client.get("/documents/doc-copy-1").text
    assert "Exact duplicate linked" not in promoted_page
    assert 'action="/documents/doc-copy-1/delete"' in promoted_page


def test_a_running_rescan_prevents_a_delete_race(tmp_path: Path):
    settings, user_id, client = build(tmp_path)
    with connect(settings) as connection:
        patient = connection.execute("SELECT patient_id FROM documents WHERE id='doc-1'").fetchone()[0]
        connection.execute(
            """INSERT INTO upload_jobs(
                   id, owner_user_id, patient_id, batch_id, kind, filename, state,
                   detail_key, document_id, created_at
               ) VALUES ('live-rescan', ?, ?, 'batch', 'rescan', 'report.pdf', 'running',
                         'intake.step_reading', 'doc-1', '2026-01-01T00:00:00+00:00')""",
            (user_id, patient),
        )
        source = Path(connection.execute(
            "SELECT source_path FROM documents WHERE id='doc-1'"
        ).fetchone()[0])

    response = client.post(
        "/documents/doc-1/delete",
        data={"csrf_token": csrf_for(settings, user_id), "next": "/documents"},
        follow_redirects=False,
    )
    assert response.headers["location"] == "/documents?delete_error=busy"
    assert source.is_file()
    with connect(settings) as connection:
        assert connection.execute("SELECT 1 FROM documents WHERE id='doc-1'").fetchone()
