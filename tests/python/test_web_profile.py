import hashlib
from pathlib import Path

from fastapi.testclient import TestClient

from anamna.db import connect, migrate
from anamna.security import create_user
from anamna.web.app import create_app

from test_web_security import PASSWORD, seed_document, seed_patient, settings_for


def login(client: TestClient, email: str) -> str:
    client.post("/login", data={"email": email, "password": PASSWORD, "next": "/"})
    return email


def csrf_for(settings, client: TestClient) -> str:
    token_hash = hashlib.sha256(client.cookies["anamna_session"].encode()).hexdigest()
    with connect(settings) as connection:
        return connection.execute(
            "SELECT csrf_token FROM sessions WHERE token_hash=?", (token_hash,)
        ).fetchone()[0]


def test_profile_updates_personal_data(tmp_path: Path):
    settings = settings_for(tmp_path)
    migrate(settings)
    alpha = create_user(settings, "alpha@example.test", "Alpha", PASSWORD)
    seed_patient(settings, alpha, "Alpha Patient")
    with TestClient(create_app(settings)) as client:
        login(client, "alpha@example.test")
        csrf = csrf_for(settings, client)
        response = client.post(
            "/profile",
            data={
                "full_name": "Alpha Renamed",
                "date_of_birth": "1988-04-01",
                "blood_type": "O+",
                "csrf_token": csrf,
            },
            follow_redirects=False,
        )
        assert response.headers["location"] == "/profile?saved=1"
        page = client.get("/profile")
        assert "Alpha Renamed" in page.text
        bad = client.post(
            "/profile",
            data={"full_name": "X", "date_of_birth": "3000-01-01", "csrf_token": csrf},
            follow_redirects=False,
        )
        assert bad.headers["location"] == "/profile?error=profile.error_dob"
    with connect(settings) as connection:
        patient = connection.execute("SELECT * FROM patients WHERE owner_user_id=?", (alpha,)).fetchone()
        assert patient["display_name"] == "Alpha Renamed"
        assert patient["date_of_birth"] == "1988-04-01"
        assert patient["blood_type"] == "O+"
        assert connection.execute("SELECT display_name FROM users WHERE id=?", (alpha,)).fetchone()[0] == "Alpha Renamed"


def test_share_management_and_readonly_viewing(tmp_path: Path):
    settings = settings_for(tmp_path)
    migrate(settings)
    alpha = create_user(settings, "alpha@example.test", "Alpha", PASSWORD)
    beta = create_user(settings, "beta@example.test", "Beta", PASSWORD)
    alpha_patient = seed_patient(settings, alpha, "Alpha Patient")
    seed_patient(settings, beta, "Beta Patient")
    alpha_doc = seed_document(settings, alpha, alpha_patient, "Alpha private result", "alpha.txt")

    with TestClient(create_app(settings)) as owner:
        login(owner, "alpha@example.test")
        owner_csrf = csrf_for(settings, owner)
        owner.post("/profile/shares", data={"email": "Beta@Example.test", "csrf_token": owner_csrf})
        assert "beta@example.test" in owner.get("/profile").text

    with TestClient(create_app(settings)) as viewer:
        login(viewer, "beta@example.test")
        viewer_csrf = csrf_for(settings, viewer)
        # cannot view without selecting; sees own (empty) record
        assert "Alpha private result" not in viewer.get("/documents").text
        select = viewer.post(
            "/profile/view",
            data={"owner_user_id": alpha, "csrf_token": viewer_csrf},
            follow_redirects=False,
        )
        assert select.status_code == 303
        listing = viewer.get("/documents")
        assert "Alpha private result" in listing.text
        detail = viewer.get(f"/documents/{alpha_doc}")
        assert detail.status_code == 200
        assert viewer.get(f"/documents/{alpha_doc}/source").status_code == 200
        # writes stay bound to the session user: tagging the owner's document 404s
        assert viewer.post(
            f"/documents/{alpha_doc}/tags",
            data={"name": "intrusion", "csrf_token": viewer_csrf},
        ).status_code == 404

    # revocation ends access even with the viewing cookie still set
    with TestClient(create_app(settings)) as owner:
        login(owner, "alpha@example.test")
        owner_csrf = csrf_for(settings, owner)
        with connect(settings) as connection:
            share_id = connection.execute(
                "SELECT id FROM record_shares WHERE owner_user_id=?", (alpha,)
            ).fetchone()[0]
        owner.post("/profile/shares/remove", data={"share_id": share_id, "csrf_token": owner_csrf})

    with TestClient(create_app(settings)) as viewer:
        login(viewer, "beta@example.test")
        viewer.cookies.set("anamna_record", alpha)
        assert "Alpha private result" not in viewer.get("/documents").text


def seed_blood_observations(settings, user_id: str, patient_id: str, document_id: str):
    from anamna.db import utc_now

    with connect(settings) as connection:
        for concept_id, name, raw, value in (
            ("blood-group", "Blood group", "Група крові", "А(ІІ)"),
            ("rhesus-factor", "Rhesus factor", "Резус-фактор (+)", "позитивний"),
        ):
            connection.execute(
                """INSERT OR IGNORE INTO concepts(id, canonical_name, category, value_type, created_at)
                   VALUES (?, ?, 'unmapped', 'text', ?)""",
                (concept_id, name, utc_now()),
            )
            connection.execute(
                """INSERT INTO observations(
                       id, owner_user_id, patient_id, document_id, page_number, concept_id,
                       raw_name, value_type, value_text, observed_at, verification_status,
                       extraction_method, confidence, evidence_text, parser_version, created_at
                   ) VALUES (?, ?, ?, ?, 1, ?, ?, 'text', ?, '2025-09-16', 'extracted',
                             'test', 0.9, ?, 'test', ?)""",
                (f"obs-{concept_id}", user_id, patient_id, document_id, concept_id,
                 raw, value, f"{raw} {value}", utc_now()),
            )


def test_blood_type_derives_from_lab_results(tmp_path: Path):
    settings = settings_for(tmp_path)
    migrate(settings)
    alpha = create_user(settings, "alpha@example.test", "Alpha", PASSWORD)
    patient = seed_patient(settings, alpha, "Alpha Patient")
    document = seed_document(settings, alpha, patient, "Blood typing", "blood.txt")
    seed_blood_observations(settings, alpha, patient, document)
    with TestClient(create_app(settings)) as client:
        login(client, "alpha@example.test")
        csrf = csrf_for(settings, client)
        page = client.get("/profile").text
        # Derived from the lab result: shown as a static value, not an
        # editable control (no <input> carrying the blood type).
        assert "<dd>A+</dd>" in page
        assert '<input value="A+"' not in page
        assert f"/documents/{document}" in page
        # while lab evidence exists a manual value is never stored
        client.post(
            "/profile",
            data={"full_name": "Alpha", "blood_type": "B-", "csrf_token": csrf},
        )
    with connect(settings) as connection:
        assert connection.execute(
            "SELECT blood_type FROM patients WHERE id=?", (patient,)
        ).fetchone()[0] is None


PROFILE_FORM = {
    "full_name": "Alpha Patient",
    "nickname": "Al",
    "height_cm": "182",
    "weight_kg": "78,5",
    "waist_cm": "84",
    "chest_cm": "102",
    "hip_cm": "97",
    "activity_level": "moderate",
    "skin_type": "II",
    "smoking_status": "never",
    "alcohol_use": "occasional",
}


def seed_device_weight(settings, user_id: str, patient_id: str, kilograms: float, day: str):
    """One day of scale data, as a device import would leave it."""
    from anamna.db import utc_now

    with connect(settings) as connection:
        connection.execute(
            """INSERT OR IGNORE INTO vendors(id, canonical_name, created_at)
               VALUES ('vendor-scale', 'Test Scale', ?)""",
            (utc_now(),),
        )
        connection.execute(
            """INSERT OR IGNORE INTO device_imports(
                   id, owner_user_id, patient_id, vendor_id, adapter_key, source_path,
                   source_fingerprint, source_bytes, imported_at
               ) VALUES ('import-scale', ?, ?, 'vendor-scale', 'apple_health', 'x', 'f', 1, ?)""",
            (user_id, patient_id, utc_now()),
        )
        connection.execute(
            """INSERT INTO device_metric_days(
                   id, owner_user_id, patient_id, import_id, source_name, source_vendor,
                   metric_key, metric_name, category, day, aggregation, unit, value,
                   sample_count, created_at
               ) VALUES (?, ?, ?, 'import-scale', 'Withings', 'Withings', 'body_weight',
                         'Body weight', 'device_body', ?, 'mean', 'kg', ?, 1, ?)""",
            (f"dmd-{day}", user_id, patient_id, day, kilograms, utc_now()),
        )


def test_profile_stores_nickname_measurements_and_context(tmp_path: Path):
    settings = settings_for(tmp_path)
    migrate(settings)
    alpha = create_user(settings, "alpha@example.test", "Alpha", PASSWORD)
    seed_patient(settings, alpha, "Alpha Patient")
    with TestClient(create_app(settings)) as client:
        login(client, "alpha@example.test")
        csrf = csrf_for(settings, client)
        saved = client.post(
            "/profile", data={**PROFILE_FORM, "csrf_token": csrf}, follow_redirects=False
        )
        assert saved.headers["location"] == "/profile?saved=1"
        # The nickname is what the header greets the reader with.
        assert '<span class="account-toggle__name">Al</span>' in client.get("/profile").text
        # An implausible measurement is refused rather than stored.
        assert client.post(
            "/profile",
            data={**PROFILE_FORM, "weight_kg": "780", "csrf_token": csrf},
            follow_redirects=False,
        ).headers["location"] == "/profile?error=profile.error_measurement"
        # So is a value outside the published vocabulary.
        assert client.post(
            "/profile",
            data={**PROFILE_FORM, "skin_type": "VII", "csrf_token": csrf},
            follow_redirects=False,
        ).headers["location"] == "/profile?error=profile.error_choice"
    with connect(settings) as connection:
        patient = connection.execute(
            "SELECT * FROM patients WHERE owner_user_id=?", (alpha,)
        ).fetchone()
        # "78,5" is what a Ukrainian keyboard produces; the column holds a number.
        assert patient["weight_kg"] == 78.5
        assert patient["height_cm"] == 182
        assert (patient["activity_level"], patient["skin_type"]) == ("moderate", "II")
        assert (patient["smoking_status"], patient["alcohol_use"]) == ("never", "occasional")
        assert connection.execute(
            "SELECT nickname FROM users WHERE id=?", (alpha,)
        ).fetchone()[0] == "Al"


def test_measured_weight_displaces_the_typed_one(tmp_path: Path):
    """The same rule the lab-determined blood group follows.

    Two numbers for one quantity drift, and the one a clinician reads has to be
    the one something actually measured.
    """
    settings = settings_for(tmp_path)
    migrate(settings)
    alpha = create_user(settings, "alpha@example.test", "Alpha", PASSWORD)
    patient = seed_patient(settings, alpha, "Alpha Patient")
    seed_device_weight(settings, alpha, patient, 81.4, "2026-05-03")
    with TestClient(create_app(settings)) as client:
        login(client, "alpha@example.test")
        csrf = csrf_for(settings, client)
        page = client.get("/profile").text
        # Shown from the measurement, with the day and a way to the evidence.
        assert "81.4 kg" in page
        assert "/devices/metrics/body_weight" in page
        assert 'name="weight_kg"' not in page
        # Height has no device reading, so it stays an editable field.
        assert 'name="height_cm"' in page
        client.post("/profile", data={**PROFILE_FORM, "csrf_token": csrf})
    with connect(settings) as connection:
        row = connection.execute(
            "SELECT weight_kg, height_cm FROM patients WHERE owner_user_id=?", (alpha,)
        ).fetchone()
        # A submitted weight is discarded while a measurement exists; height stands.
        assert row["weight_kg"] is None
        assert row["height_cm"] == 182


def test_profile_round_trips_sex_at_birth(tmp_path: Path):
    """Sexed reference rules apply only on exact match, so the profile must be
    able to state every value the patients CHECK constraint accepts — and to
    clear it back to NULL."""
    settings = settings_for(tmp_path)
    migrate(settings)
    alpha = create_user(settings, "alpha@example.test", "Alpha", PASSWORD)
    patient = seed_patient(settings, alpha, "Alpha Patient")

    def stored():
        with connect(settings) as connection:
            return connection.execute(
                "SELECT sex_at_birth FROM patients WHERE id=?", (patient,)
            ).fetchone()[0]

    with TestClient(create_app(settings)) as client:
        login(client, "alpha@example.test")
        csrf = csrf_for(settings, client)
        for value in ("female", "male", "intersex", "unknown"):
            response = client.post(
                "/profile",
                data={"full_name": "Alpha", "sex_at_birth": value, "csrf_token": csrf},
                follow_redirects=False,
            )
            assert response.headers["location"] == "/profile?saved=1"
            assert stored() == value
        # Empty means "not stated" and stores NULL, not an empty string.
        client.post("/profile", data={"full_name": "Alpha", "sex_at_birth": "", "csrf_token": csrf})
        assert stored() is None
        # A value outside the vocabulary is refused rather than stored.
        assert client.post(
            "/profile",
            data={"full_name": "Alpha", "sex_at_birth": "attack-helicopter", "csrf_token": csrf},
            follow_redirects=False,
        ).headers["location"] == "/profile?error=profile.error_choice"
        assert stored() is None


def test_forged_view_cookie_is_ignored(tmp_path: Path):
    settings = settings_for(tmp_path)
    migrate(settings)
    alpha = create_user(settings, "alpha@example.test", "Alpha", PASSWORD)
    mallory = create_user(settings, "mallory@example.test", "Mallory", PASSWORD)
    alpha_patient = seed_patient(settings, alpha, "Alpha Patient")
    seed_patient(settings, mallory, "Mallory Patient")
    seed_document(settings, alpha, alpha_patient, "Alpha private result", "alpha.txt")
    with TestClient(create_app(settings)) as client:
        login(client, "mallory@example.test")
        csrf = csrf_for(settings, client)
        # selecting a record that was never shared is refused outright
        assert client.post(
            "/profile/view",
            data={"owner_user_id": alpha, "csrf_token": csrf},
            follow_redirects=False,
        ).status_code == 404
        # and a forged cookie falls back to the intruder's own record
        client.cookies.set("anamna_record", alpha)
        assert "Alpha private result" not in client.get("/documents").text
