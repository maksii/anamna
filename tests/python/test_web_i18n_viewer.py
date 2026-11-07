from hashlib import sha256
from pathlib import Path

from fastapi.testclient import TestClient
from pypdf import PdfWriter

from anamna.config import Settings
from anamna.db import connect, migrate, utc_now
from anamna.ingest.pipeline import ensure_vendor
from anamna.security import create_user
from anamna.web.app import create_app


PASSWORD = "a-long-local-password"


def make_settings(tmp_path: Path) -> Settings:
    sources = tmp_path / "sources"
    sources.mkdir()
    return Settings(tmp_path / "health.sqlite3", sources, "test-secret", 1)


def seed_patient(settings: Settings, user_id: str) -> str:
    patient_id = f"patient-{user_id}"
    with connect(settings) as connection:
        connection.execute(
            "INSERT INTO patients(id, owner_user_id, display_name, created_at) VALUES (?, ?, ?, ?)",
            (patient_id, user_id, "Viewer Patient", utc_now()),
        )
    return patient_id


def seed_pdf(settings: Settings, user_id: str, patient_id: str, suffix: str) -> str:
    source = settings.source_dir / f"viewer-{suffix}.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=595, height=842)
    with source.open("wb") as stream:
        writer.write(stream)
    document_id = f"pdf-{suffix}"
    digest = sha256(source.read_bytes()).hexdigest()
    with connect(settings) as connection:
        vendor_id = ensure_vendor(connection, "Viewer Lab", None)
        connection.execute(
            """INSERT INTO documents(
                   id, owner_user_id, patient_id, vendor_id, original_filename, source_path,
                   mime_type, byte_size, sha256, page_count, title, clinical_type,
                   extraction_strategy, classification_confidence, imported_at, status
               ) VALUES (?, ?, ?, ?, ?, ?, 'application/pdf', ?, ?, 1, ?, 'laboratory',
                         'native_text_plus_embedded_image_ocr', 1, ?, 'final')""",
            (
                document_id, user_id, patient_id, vendor_id, source.name, str(source),
                source.stat().st_size, digest, "Viewer result", utc_now(),
            ),
        )
    return document_id


def test_rendered_pdf_page_is_owned_and_embedded(tmp_path: Path):
    settings = make_settings(tmp_path)
    migrate(settings)
    alpha = create_user(settings, "alpha@example.test", "Alpha", PASSWORD)
    beta = create_user(settings, "beta@example.test", "Beta", PASSWORD)
    alpha_doc = seed_pdf(settings, alpha, seed_patient(settings, alpha), "alpha")
    beta_doc = seed_pdf(settings, beta, seed_patient(settings, beta), "beta")

    with TestClient(create_app(settings)) as client:
        client.post("/login", data={"email": "alpha@example.test", "password": PASSWORD, "next": "/"})
        page = client.get(f"/documents/{alpha_doc}/pages/1/image")
        assert page.status_code == 200
        assert page.headers["content-type"].startswith("image/png")
        assert page.content.startswith(b"\x89PNG\r\n\x1a\n")
        assert client.get(f"/documents/{alpha_doc}/pages/2/image").status_code == 404
        assert client.get(f"/documents/{beta_doc}/pages/1/image").status_code == 404

        detail = client.get(f"/documents/{alpha_doc}")
        assert f'/documents/{alpha_doc}/pages/{{page}}/image' in detail.text
        assert "data-zoom-in" in detail.text


def test_query_locale_overrides_cookie_and_localizes_viewer(tmp_path: Path):
    settings = make_settings(tmp_path)
    migrate(settings)
    user_id = create_user(settings, "alpha@example.test", "Alpha", PASSWORD)
    document_id = seed_pdf(settings, user_id, seed_patient(settings, user_id), "alpha")

    with TestClient(create_app(settings)) as client:
        client.post("/login", data={"email": "alpha@example.test", "password": PASSWORD, "next": "/"})
        client.cookies.set("anamna_lang", "en")
        dashboard = client.get("/?lang=uk")
        assert "Медична картка" in dashboard.text
        assert dashboard.cookies.get("anamna_lang") == "uk"
        detail = client.get(f"/documents/{document_id}?lang=uk")
        assert "Оригінал" in detail.text
        assert "Збільшити" in detail.text
