"""Record confidentiality and validation at the manual-entry boundary."""

from datetime import UTC, datetime, timedelta
import os
import subprocess
import sys
import hashlib
import io

import pytest
from fastapi.testclient import TestClient

from anamna.db import connect, migrate, utc_now
from anamna.security import create_access_token, create_user
from anamna.web.app import create_app
from test_web_panels import build
from test_web_profile import csrf_for, login
from test_web_security import PASSWORD, seed_document, seed_patient, settings_for


@pytest.mark.parametrize("credential", ["session", "bearer"])
def test_guest_cannot_inherit_records_shared_with_the_inviting_owner(tmp_path, credential):
    settings = settings_for(tmp_path)
    migrate(settings)
    owner = create_user(settings, "alpha@example.test", "Alpha", PASSWORD)
    other = create_user(settings, "beta@example.test", "Beta", PASSWORD)
    for user, label in ((owner, "Alpha"), (other, "Beta")):
        patient = seed_patient(settings, user, label)
        seed_document(settings, user, patient, f"{label} private result", f"{label}.txt")
    with connect(settings) as connection:
        connection.execute(
            "INSERT INTO record_shares(id, owner_user_id, grantee_email, grantee_user_id, created_at) VALUES (?, ?, ?, ?, ?)",
            ("share", other, "alpha@example.test", owner, utc_now()),
        )
    _, secret = create_access_token(
        settings, owner, "guest", "Read Alpha only",
        expires_at=(datetime.now(UTC) + timedelta(days=1)).isoformat(),
    )
    with TestClient(create_app(settings)) as client:
        if credential == "session":
            client.get(f"/t/{secret}")
        else:
            client.headers["Authorization"] = f"Bearer {secret}"
        client.cookies.set("anamna_record", other)
        response = client.get("/documents")
        assert response.status_code == 200
        assert "Alpha private result" in response.text
        assert "Beta private result" not in response.text


def test_sensitive_responses_cannot_be_cached_after_logout_or_revocation(tmp_path):
    settings = settings_for(tmp_path)
    migrate(settings)
    owner = create_user(settings, "alpha@example.test", "Alpha", PASSWORD)
    patient = seed_patient(settings, owner, "Alpha")
    document = seed_document(settings, owner, patient, "Private result", "source.txt")
    with TestClient(create_app(settings)) as client:
        login(client, "alpha@example.test")
        for path in ("/", "/profile", "/documents", f"/documents/{document}/source", "/api/metrics/search"):
            response = client.get(path)
            assert response.status_code == 200
            assert response.headers["cache-control"] == "private, no-store, no-transform", path
        assert "no-store" not in client.get("/static/app.css").headers.get("cache-control", "")


@pytest.mark.parametrize("route", ["/observations/obs-0", "/documents/doc-1/observations"])
def test_manual_observations_reject_invalid_dates_without_writing(tmp_path, route):
    settings, _, client = build(tmp_path)
    token = csrf_for(settings, client)
    with connect(settings) as connection:
        before = [tuple(row) for row in connection.execute("SELECT * FROM observations ORDER BY id")]
    for bad_date in ("2025-02-30", "0000-01-01", "2025-13-01", "2025-01-01unexpected"):
        response = client.post(route, data={
            "raw_name": "LDL cholesterol", "value_numeric": "4.42",
            "observed_at": bad_date, "csrf_token": token,
        }, follow_redirects=False)
        assert response.status_code == 400, bad_date
    with connect(settings) as connection:
        assert before == [tuple(row) for row in connection.execute("SELECT * FROM observations ORDER BY id")]


@pytest.mark.parametrize("route", ["/observations/obs-0", "/documents/doc-1/observations"])
def test_manual_observations_reject_nonfinite_numbers(tmp_path, route):
    settings, _, client = build(tmp_path)
    token = csrf_for(settings, client)
    for invalid in ("NaN", "Infinity", "-inf", "1e999"):
        response = client.post(route, data={
            "raw_name": "LDL cholesterol", "value_numeric": invalid, "csrf_token": token,
        }, follow_redirects=False)
        assert response.status_code == 400, invalid


@pytest.mark.parametrize("route,fields", [
    ("metadata", {"title": "Updated title"}),
    ("classification", {"clinical_type": "laboratory"}),
    ("ai-metadata", {"apply_report_date": "1"}),
])
def test_document_dates_are_valid_calendar_dates(tmp_path, route, fields):
    settings, _, client = build(tmp_path)
    for invalid in ("2025-02-29", "2025-00-10", "2025-01-01junk"):
        response = client.post(f"/documents/doc-1/{route}", data={
            **fields, "report_date": invalid, "csrf_token": csrf_for(settings, client),
        }, follow_redirects=False)
        assert response.status_code == 400, invalid


def test_valid_leap_day_and_comparator_survive_manual_entry(tmp_path):
    settings, _, client = build(tmp_path)
    response = client.post("/observations/obs-0", data={
        "raw_name": "LDL cholesterol", "value_numeric": "<0,01", "unit_raw": "mmol/L",
        "observed_at": "2024-02-29", "csrf_token": csrf_for(settings, client),
    }, follow_redirects=False)
    assert response.status_code == 303
    with connect(settings) as connection:
        row = connection.execute("SELECT * FROM observations WHERE id='obs-0'").fetchone()
    assert (row["value_numeric"], row["comparator"], row["observed_at"]) == (0.01, "<", "2024-02-29")


def test_importing_web_helpers_does_not_initialize_the_default_database(tmp_path):
    database = tmp_path / "must-not-be-created.sqlite3"
    result = subprocess.run(
        [sys.executable, "-c", "from anamna.web.app import create_app, format_date"],
        env={**os.environ, "ANAMNA_DB": str(database)},
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stderr
    assert not database.exists()


def test_default_asgi_entry_point_initializes_on_startup(tmp_path, monkeypatch):
    from anamna.web import app as web

    settings = settings_for(tmp_path)
    monkeypatch.setattr(web, "get_settings", lambda: settings)
    web._default_app.cache_clear()
    try:
        with TestClient(web.app) as client:
            assert client.get("/login").status_code == 200
            assert settings.database_path.exists()
            assert client.get("/documents", follow_redirects=False).status_code == 303
    finally:
        web._default_app.cache_clear()


def test_multiframe_tiff_evidence_is_available_page_by_page(tmp_path):
    from PIL import Image

    settings = settings_for(tmp_path)
    migrate(settings)
    owner = create_user(settings, "alpha@example.test", "Alpha", PASSWORD)
    patient = seed_patient(settings, owner, "Alpha")
    document = seed_document(settings, owner, patient, "Two scanned pages", "two.tiff")
    source = settings.source_dir / "two.tiff"
    Image.new("RGB", (20, 30), "red").save(source, save_all=True, append_images=[Image.new("RGB", (20, 30), "blue")])
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    with connect(settings) as connection:
        connection.execute("UPDATE documents SET mime_type='image/tiff', page_count=2, sha256=? WHERE id=?", (digest, document))
    with TestClient(create_app(settings)) as client:
        login(client, "alpha@example.test")
        for number, expected in ((1, (255, 0, 0)), (2, (0, 0, 255))):
            response = client.get(f"/documents/{document}/pages/{number}/image")
            assert response.status_code == 200
            assert response.headers["content-type"] == "image/png"
            assert response.headers["cache-control"] == "private, no-store, no-transform"
            with Image.open(io.BytesIO(response.content)) as rendered:
                assert rendered.getpixel((0, 0)) == expected
        assert client.get(f"/documents/{document}/pages/3/image").status_code == 404
        detail = client.get(f"/documents/{document}").text
        assert 'data-page-next' in detail
        assert f'src="/documents/{document}/pages/1/image"' in detail
        assert hashlib.sha256(source.read_bytes()).hexdigest() == digest


def test_image_preview_applies_phone_orientation_without_changing_source(tmp_path):
    from PIL import Image
    from anamna.web.app import _render_image_page

    source = tmp_path / "rotated.jpg"
    photo = Image.new("RGB", (20, 30), "red")
    exif = Image.Exif()
    exif[274] = 6
    photo.save(source, exif=exif)
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    rendered = _render_image_page(tmp_path / "cache", source, digest, 1)
    with Image.open(rendered) as image:
        assert image.size == (30, 20)
    assert hashlib.sha256(source.read_bytes()).hexdigest() == digest
