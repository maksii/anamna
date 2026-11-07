from pathlib import Path

from fastapi.testclient import TestClient

from anamna.config import Settings
from anamna.db import connect, migrate, utc_now
from anamna.ingest.pipeline import ensure_concept, ensure_vendor
from anamna.security import create_user, set_open_registration
from anamna.web.app import create_app


PASSWORD = "a-long-local-password"


def settings_for(tmp_path: Path) -> Settings:
    sources = tmp_path / "sources"
    sources.mkdir()
    return Settings(
        database_path=tmp_path / "health.sqlite3",
        source_dir=sources,
        secret_key="test-secret",
        session_days=1,
    )


def seed_document(settings: Settings, user_id: str, patient_id: str, title: str, filename: str) -> str:
    source = settings.source_dir / filename
    source.write_text(title, encoding="utf-8")
    document_id = f"doc-{filename}"
    with connect(settings) as connection:
        vendor_id = ensure_vendor(connection, "Test Lab", None)
        connection.execute(
            """INSERT INTO documents(
                   id, owner_user_id, patient_id, vendor_id, original_filename, source_path,
                   mime_type, byte_size, sha256, page_count, title, clinical_type,
                   extraction_strategy, classification_confidence, imported_at, status
               ) VALUES (?, ?, ?, ?, ?, ?, 'text/plain', ?, ?, 1, ?, 'laboratory', 'native_text', 1, ?, 'final')""",
            (
                document_id, user_id, patient_id, vendor_id, filename, str(source),
                source.stat().st_size, filename * 2, title, utc_now(),
            ),
        )
        connection.execute(
            "INSERT INTO search_index(document_id, owner_user_id, content) VALUES (?, ?, ?)",
            (document_id, user_id, f"{title} {filename}"),
        )
    return document_id


def seed_patient(settings: Settings, user_id: str, name: str) -> str:
    patient_id = f"patient-{user_id}"
    with connect(settings) as connection:
        connection.execute(
            "INSERT INTO patients(id, owner_user_id, display_name, created_at) VALUES (?, ?, ?, ?)",
            (patient_id, user_id, name, utc_now()),
        )
    return patient_id


def test_document_routes_enforce_user_ownership(tmp_path: Path):
    settings = settings_for(tmp_path)
    migrate(settings)
    alpha = create_user(settings, "alpha@example.test", "Alpha", PASSWORD)
    beta = create_user(settings, "beta@example.test", "Beta", PASSWORD)
    alpha_patient = seed_patient(settings, alpha, "Alpha Patient")
    beta_patient = seed_patient(settings, beta, "Beta Patient")
    alpha_doc = seed_document(settings, alpha, alpha_patient, "Alpha private result", "alpha.txt")
    beta_doc = seed_document(settings, beta, beta_patient, "Beta private result", "beta.txt")

    with TestClient(create_app(settings)) as client:
        response = client.post(
            "/login",
            data={"email": "alpha@example.test", "password": PASSWORD, "next": "/documents"},
            follow_redirects=False,
        )
        assert response.status_code == 303
        listing = client.get("/documents")
        assert listing.status_code == 200
        assert "Alpha private result" in listing.text
        assert "Beta private result" not in listing.text
        assert client.get(f"/documents/{alpha_doc}").status_code == 200
        assert client.get(f"/documents/{beta_doc}").status_code == 404
        assert client.get(f"/documents/{beta_doc}/source").status_code == 404
        with connect(settings) as connection:
            csrf = connection.execute(
                "SELECT csrf_token FROM sessions WHERE user_id=? ORDER BY created_at DESC LIMIT 1",
                (alpha,),
            ).fetchone()[0]
        assert client.post(
            f"/documents/{beta_doc}/delete", data={"csrf_token": csrf}
        ).status_code == 404
        assert client.post(
            f"/documents/{alpha_doc}/delete", data={"csrf_token": "wrong"}
        ).status_code == 403


def test_source_resolves_after_database_relocation(tmp_path: Path):
    settings = settings_for(tmp_path)
    migrate(settings)
    alpha = create_user(settings, "alpha@example.test", "Alpha", PASSWORD)
    patient = seed_patient(settings, alpha, "Alpha Patient")
    document_id = seed_document(settings, alpha, patient, "Moved evidence", "moved.txt")
    with connect(settings) as connection:
        # the database was created on another machine with absolute paths
        connection.execute(
            "UPDATE documents SET source_path=? WHERE id=?",
            (r"D:\old\machine\sources\moved.txt", document_id),
        )
    with TestClient(create_app(settings)) as client:
        client.post("/login", data={"email": "alpha@example.test", "password": PASSWORD, "next": "/"})
        response = client.get(f"/documents/{document_id}/source")
        assert response.status_code == 200
        assert "Moved evidence" in response.text


def test_anonymous_user_is_redirected_to_login(tmp_path: Path):
    settings = settings_for(tmp_path)
    migrate(settings)
    with TestClient(create_app(settings)) as client:
        response = client.get("/documents", follow_redirects=False)
        assert response.status_code == 303
        assert response.headers["location"].startswith("/login")


def test_human_correction_is_owned_and_audited(tmp_path: Path):
    settings = settings_for(tmp_path)
    migrate(settings)
    alpha = create_user(settings, "alpha@example.test", "Alpha", PASSWORD)
    beta = create_user(settings, "beta@example.test", "Beta", PASSWORD)
    alpha_patient = seed_patient(settings, alpha, "Alpha Patient")
    beta_patient = seed_patient(settings, beta, "Beta Patient")
    alpha_doc = seed_document(settings, alpha, alpha_patient, "Alpha result", "alpha.txt")
    beta_doc = seed_document(settings, beta, beta_patient, "Beta result", "beta.txt")
    with connect(settings) as connection:
        vendor_id = ensure_vendor(connection, "Test Lab", None)
        observation_ids = []
        for user_id, patient_id, document_id, suffix in (
            (alpha, alpha_patient, alpha_doc, "alpha"),
            (beta, beta_patient, beta_doc, "beta"),
        ):
            report_id = f"report-{suffix}"
            connection.execute(
                """INSERT INTO reports(
                       id, owner_user_id, patient_id, document_id, vendor_id, title,
                       clinical_type, report_date, start_page, end_page, created_at
                   ) VALUES (?, ?, ?, ?, ?, 'Test report', 'laboratory', '2026-01-01', 1, 1, ?)""",
                (report_id, user_id, patient_id, document_id, vendor_id, utc_now()),
            )
            concept_id, _ = ensure_concept(connection, "Glucose", vendor_id)
            observation_id = f"observation-{suffix}"
            observation_ids.append(observation_id)
            connection.execute(
                """INSERT INTO observations(
                       id, owner_user_id, patient_id, document_id, report_id, page_number,
                       concept_id, raw_name, value_type, value_numeric, unit_raw, observed_at,
                       verification_status, extraction_method, confidence, evidence_text,
                       parser_version, created_at
                   ) VALUES (?, ?, ?, ?, ?, 1, ?, 'Glucose', 'numeric', 5.1, 'mmol/L',
                             '2026-01-01', 'extracted', 'test', 0.9, 'Glucose 5.1', 'test', ?)""",
                (observation_id, user_id, patient_id, document_id, report_id, concept_id, utc_now()),
            )

    with TestClient(create_app(settings)) as client:
        client.post("/login", data={"email": "alpha@example.test", "password": PASSWORD, "next": "/"})
        with connect(settings) as connection:
            csrf = connection.execute("SELECT csrf_token FROM sessions WHERE user_id=?", (alpha,)).fetchone()[0]
        response = client.post(
            f"/observations/{observation_ids[0]}",
            data={
                "raw_name": "Glucose corrected",
                "value_numeric": "5.4",
                "value_text": "",
                "unit_raw": "mmol/L",
                "vendor_reference_text": "3.9 - 5.5",
                "csrf_token": csrf,
            },
            follow_redirects=False,
        )
        assert response.status_code == 303
        assert client.post(
            f"/observations/{observation_ids[1]}",
            data={"raw_name": "No", "value_numeric": "1", "csrf_token": csrf},
        ).status_code == 404
    with connect(settings) as connection:
        corrected = connection.execute("SELECT * FROM observations WHERE id=?", (observation_ids[0],)).fetchone()
        assert corrected["value_numeric"] == 5.4
        assert corrected["verification_status"] == "corrected"
        assert connection.execute(
            "SELECT COUNT(*) FROM audit_events WHERE entity_id=? AND action='observation_corrected'",
            (observation_ids[0],),
        ).fetchone()[0] == 1


def test_self_registration_is_closed_until_an_administrator_opens_it(tmp_path: Path):
    """A server reachable from the internet does not collect accounts by default.

    The refusal is the same on the form and on the POST: a page opened before
    registration closed must not still be able to create an account.

    An account already exists here, because an empty database deliberately
    lets its first visitor in — see the first-run test in test_web_admin.
    """
    settings = settings_for(tmp_path)
    migrate(settings)
    create_user(settings, "owner@example.test", "Owner", PASSWORD)
    with TestClient(create_app(settings)) as client:
        page = client.get("/register", follow_redirects=False)
        assert page.status_code == 303
        assert page.headers["location"] == "/login?error=closed"
        posted = client.post(
            "/register",
            data={"email": "walkin@example.test", "display_name": "Walk In", "password": PASSWORD},
            follow_redirects=False,
        )
        assert posted.headers["location"] == "/login?error=closed"
        # The sign-in page says so rather than offering a link to a refusal.
        assert "Sign-up is closed on this server" in client.get("/login").text
    with connect(settings) as connection:
        assert connection.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 1


def test_self_registration_creates_account_patient_and_session(tmp_path: Path):
    settings = settings_for(tmp_path)
    migrate(settings)
    # An installation that has been set up: on an empty database even an open
    # toggle leads to /setup, so the first account always needs the code.
    create_user(settings, "owner@example.test", "Owner", PASSWORD)
    set_open_registration(settings, True)
    with TestClient(create_app(settings)) as client:
        response = client.post(
            "/register",
            data={"email": "new@example.test", "display_name": "New Person", "password": PASSWORD},
            follow_redirects=False,
        )
        assert response.status_code == 303
        assert response.headers["location"] == "/"
        assert "anamna_session" in response.cookies
        assert client.get("/documents").status_code == 200

    with connect(settings) as connection:
        user = connection.execute("SELECT * FROM users WHERE email='new@example.test'").fetchone()
        assert user["display_name"] == "New Person"
        patient = connection.execute(
            "SELECT * FROM patients WHERE owner_user_id=?", (user["id"],)
        ).fetchone()
        assert patient["display_name"] == "New Person"


def test_registration_rejects_duplicates_and_weak_passwords(tmp_path: Path):
    settings = settings_for(tmp_path)
    migrate(settings)
    set_open_registration(settings, True)
    create_user(settings, "taken@example.test", "Taken", PASSWORD)
    with TestClient(create_app(settings)) as client:
        duplicate = client.post(
            "/register",
            data={"email": "taken@example.test", "display_name": "Twin", "password": PASSWORD},
            follow_redirects=False,
        )
        assert duplicate.headers["location"] == "/register?error=register.error_exists"
        weak = client.post(
            "/register",
            data={"email": "weak@example.test", "display_name": "Weak", "password": "short"},
            follow_redirects=False,
        )
        assert weak.headers["location"] == "/register?error=register.error_password"
        page = client.get("/register?error=register.error_exists")
        assert "already exists" in page.text
    with connect(settings) as connection:
        assert connection.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 1
