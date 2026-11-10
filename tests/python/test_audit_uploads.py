"""The upload door and the writes an unchecked suggestion can make.

Each test pins one way an upload or a suggestion used to go wrong: a sliced file
renamed to a bigger limit between slices, two photos of one name overwriting each
other, a failed admission leaving bytes that no job names, and an AI suggestion
stored as though a person had checked it.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from anamna.db import connect, utc_now
from anamna.immunizations import store_document_doses
from anamna.ingest import intake
from anamna.ingest.text import normalized_key
from anamna.security import create_session
from anamna.web import app as web
from anamna.web.app import create_app

from test_immunizations import rows, seeded
from test_web_panels import build
from test_web_review import concept_id_for, csrf_for, foreign_observation
from test_web_upload import jobs


@pytest.fixture(autouse=True)
def deterministic_worker(monkeypatch):
    """Keep the background worker still; these tests look at the queue, not at drain timing."""
    monkeypatch.setattr(intake, "start_worker", lambda settings: None)


def stored_files(settings) -> list[Path]:
    uploads = settings.source_dir / "uploads"
    return [path for path in uploads.rglob("*") if path.is_file()] if uploads.exists() else []


def test_a_slice_renamed_to_a_bigger_limit_is_judged_by_its_final_name(tmp_path: Path, monkeypatch):
    """A .zip slice gets the archive limit; the assembled file is a PDF and must meet the PDF limit."""
    settings, user_id, client = build(tmp_path)
    monkeypatch.setattr(web, "MAX_UPLOAD_BYTES", 1024)
    token = csrf_for(settings, user_id)
    session = "44444444-4444-4444-8444-444444444444"

    opening = client.post(
        "/upload/chunk",
        files={"chunk": ("x.zip", b"A" * 2000, "application/octet-stream")},
        data={"csrf_token": token, "session": session, "offset": "0",
              "filename": "x.zip", "final": "0"},
    )
    assert opening.json() == {"status": "ok", "size": 2000}

    closing = client.post(
        "/upload/chunk",
        files={"chunk": ("x.pdf", b"", "application/octet-stream")},
        data={"csrf_token": token, "session": session, "offset": "2000",
              "filename": "x.pdf", "final": "1"},
    )
    assert closing.json() == {"status": "rejected"}
    assert [(row["filename"], row["state"], row["detail_key"]) for row in jobs(settings, user_id)] == [
        ("x.pdf", "failed", "intake.failed_too_big")
    ]
    assert stored_files(settings) == []


def test_two_uploads_of_one_name_never_share_a_file(tmp_path: Path, monkeypatch):
    """The first choice of path is taken by another upload before this one opens it."""
    settings, user_id, client = build(tmp_path)
    real_target = web._upload_target
    raced: list[bool] = []

    def lose_the_race(settings_arg, name):
        if raced:
            return real_target(settings_arg, name)
        raced.append(True)
        target = real_target(settings_arg, name)
        target.write_bytes(b"first upload")
        return target

    monkeypatch.setattr(web, "_upload_target", lose_the_race)
    response = client.post(
        "/upload", files={"files": ("image.jpg", b"new upload bytes", "image/jpeg")},
        data={"csrf_token": csrf_for(settings, user_id)}, follow_redirects=False,
    )
    assert response.status_code == 303

    first = next(path for path in stored_files(settings) if path.read_bytes() == b"first upload")
    assert first.name == "image.jpg"
    queued = jobs(settings, user_id)
    assert len(queued) == 1
    landed = Path(str(queued[0]["source_path"]))
    assert landed.name == "image-1.jpg"
    assert landed.read_bytes() == b"new upload bytes"


def test_a_failed_admission_leaves_no_orphan_file(tmp_path: Path, monkeypatch):
    settings, user_id, client = build(tmp_path)

    async def refuse(*args, **kwargs):
        raise RuntimeError("queue unavailable")

    monkeypatch.setattr(web, "_admit_upload", refuse)
    anonymous = TestClient(create_app(settings), raise_server_exceptions=False)
    anonymous.cookies.set("anamna_session", client.cookies.get("anamna_session"))
    response = anonymous.post(
        "/upload", files={"files": ("scan.pdf", b"%PDF-1.4 small", "application/pdf")},
        data={"csrf_token": csrf_for(settings, user_id)}, follow_redirects=False,
    )
    assert response.status_code == 500
    assert stored_files(settings) == []


def test_an_ai_suggested_missed_value_is_stored_unchecked(tmp_path: Path):
    settings, user_id, client = build(tmp_path)
    token = csrf_for(settings, user_id)
    form = {"raw_name": "Ferritin", "value_numeric": "45", "unit_raw": "ng/mL", "csrf_token": token}

    suggested = client.post(
        "/documents/doc-1/observations", data={**form, "ai_suggested": "1"}, follow_redirects=False,
    )
    assert suggested.status_code == 303
    entered = client.post(
        "/documents/doc-1/observations", data={**form, "raw_name": "Transferrin"}, follow_redirects=False,
    )
    assert entered.status_code == 303

    with connect(settings) as db:
        stored = {
            row["raw_name"]: row
            for row in db.execute(
                "SELECT id, raw_name, verification_status, extraction_method FROM observations "
                "WHERE document_id='doc-1' AND raw_name IN ('Ferritin', 'Transferrin')"
            )
        }
        ferritin_action = db.execute(
            "SELECT action FROM audit_events WHERE entity_type='observation' AND entity_id=?",
            (stored["Ferritin"]["id"],),
        ).fetchone()[0]
    assert (stored["Ferritin"]["verification_status"], stored["Ferritin"]["extraction_method"]) == (
        "extracted", "ai_suggested_entry",
    )
    assert ferritin_action == "observation_ai_entry_added"
    assert (stored["Transferrin"]["verification_status"], stored["Transferrin"]["extraction_method"]) == (
        "corrected", "human_entered",
    )


def test_an_ai_suggested_dose_is_stored_unchecked(tmp_path: Path):
    settings, user_id, client = build(tmp_path)
    base = {
        "csrf_token": csrf_for(settings, user_id), "vaccine_code": "BCG",
        "event_kind": "vaccination", "product_name": "БЦЖ",
    }
    client.post("/vaccinations", data={**base, "occurred_on": "1993-04-15", "ai_suggested": "1"},
                follow_redirects=False)
    client.post("/vaccinations", data={**base, "occurred_on": "1994-05-20"}, follow_redirects=False)

    stored = {row["occurrence_date"]: row for row in rows(settings, user_id)}
    assert (stored["1993-04-15"]["verification_status"], stored["1993-04-15"]["extraction_method"]) == (
        "extracted", "ai_suggested_entry",
    )
    assert (stored["1994-05-20"]["verification_status"], stored["1994-05-20"]["extraction_method"]) == (
        "corrected", "human_entered",
    )


def test_a_reread_keeps_an_ai_suggestion_and_replaces_the_parsers_unchecked_rows(tmp_path: Path):
    settings, user_id, client = build(tmp_path)
    patient_id = f"patient-{user_id}"
    assert seeded(settings, user_id, patient_id) > 0
    client.post(
        "/vaccinations",
        data={
            "csrf_token": csrf_for(settings, user_id), "document_id": "doc-1",
            "occurred_on": "1993-04-15", "vaccine_code": "BCG", "event_kind": "vaccination",
            "product_name": "БЦЖ", "ai_suggested": "1",
        },
        follow_redirects=False,
    )

    with connect(settings) as db:
        store_document_doses(db, user_id, patient_id, "doc-1", [], "scanned_page_ocr")
        db.commit()

    kept = rows(settings, user_id)
    assert [
        (row["occurrence_date"], row["entry_source"], row["verification_status"], row["extraction_method"])
        for row in kept
    ] == [("1993-04-15", "document", "extracted", "ai_suggested_entry")]


def test_only_an_administrators_correction_teaches_the_shared_aliases(tmp_path: Path):
    settings, admin_id, client = build(tmp_path)

    def alias_count(label: str) -> int:
        with connect(settings) as db:
            return int(db.execute(
                "SELECT COUNT(*) FROM concept_aliases WHERE normalized_alias=?", (normalized_key(label),),
            ).fetchone()[0])

    ldl = concept_id_for(settings, "LDL cholesterol")
    admin_label = "Показник 77"
    before = alias_count(admin_label)
    client.post(
        "/observations/obs-3",
        data={"raw_name": admin_label, "canonical_name": "ldl cholesterol", "value_numeric": "3.9",
              "unit_raw": "mmol/L", "csrf_token": csrf_for(settings, admin_id)},
        follow_redirects=False,
    )
    assert alias_count(admin_label) == before + 1

    member_observation = foreign_observation(settings)
    with connect(settings) as db:
        member_id = db.execute(
            "SELECT owner_user_id FROM observations WHERE id=?", (member_observation,)
        ).fetchone()[0]
    member_token, _ = create_session(settings, member_id)
    member = TestClient(create_app(settings))
    member.cookies.set("anamna_session", member_token)
    member_label = "Показник 78"
    response = member.post(
        f"/observations/{member_observation}",
        data={"raw_name": member_label, "canonical_name": "ldl cholesterol", "value_numeric": "3.9",
              "unit_raw": "mmol/L", "csrf_token": csrf_for(settings, member_id)},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert alias_count(member_label) == 0
    with connect(settings) as db:
        corrected = db.execute(
            "SELECT concept_id FROM observations WHERE id=?", (member_observation,)
        ).fetchone()[0]
    assert corrected == ldl
