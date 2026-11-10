"""Account lifecycle: delete your own account, download your record, change your
sign-in address, and the trails that remove and reopen work leave behind.

Each test asserts one rule the lifecycle must keep: a deletion removes exactly
one account and its files and leaves everybody else's; a bearer credential or a
guest link never acts as the account holder; the export is the signed-in
person's own record even while they are viewing a share; a changed address
replaces the old one everywhere it is used; and reopening a file names the
values it moved.
"""

from __future__ import annotations

import html
import json
import zipfile
from datetime import UTC, datetime, timedelta
from io import BytesIO
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from anamna import labsync, security
from anamna.db import connect, migrate, utc_now
from anamna.locales.messages import MESSAGES
from anamna.security import create_access_token, create_user
from anamna.web.app import create_app

from test_web_panels import build
from test_web_profile import csrf_for, login
from test_web_security import PASSWORD, seed_document, seed_patient, settings_for


@pytest.fixture(autouse=True)
def clean_meters():
    """The password and sign-in meters are process-wide; each test starts clean."""
    security._attempts.clear()
    yield
    security._attempts.clear()


def message(key: str) -> str:
    return html.escape(MESSAGES[key]["en"])


def count(settings, sql: str, *args) -> int:
    with connect(settings) as connection:
        return connection.execute(sql, args).fetchone()[0]


def seed_record(settings, user_id: str, filename: str, title: str) -> tuple[str, str]:
    patient_id = seed_patient(settings, user_id, title)
    document_id = seed_document(settings, user_id, patient_id, title, filename)
    return patient_id, document_id


def seed_observation(settings, user_id: str, patient_id: str, document_id: str, observation_id: str) -> None:
    with connect(settings) as connection:
        connection.execute(
            """INSERT INTO observations(
                   id, owner_user_id, patient_id, document_id, page_number, raw_name,
                   value_type, value_numeric, unit_raw, observed_at, verification_status,
                   extraction_method, confidence, evidence_text, parser_version, created_at)
               VALUES (?, ?, ?, ?, 1, 'Glucose', 'numeric', 5.1, 'mmol/L', '2025-02-13', 'extracted',
                       'test', 1.0, 'Glucose 5.1', 'test', ?)""",
            (observation_id, user_id, patient_id, document_id, utc_now()),
        )


def add_share(settings, owner: str, grantee: str, grantee_email: str, share_id: str) -> None:
    with connect(settings) as connection:
        connection.execute(
            """INSERT INTO record_shares(id, owner_user_id, grantee_email, grantee_user_id, created_at, access)
                   VALUES (?, ?, ?, ?, ?, 'read')""",
            (share_id, owner, grantee_email, grantee, utc_now()),
        )


def delete_form(csrf: str, password: str = PASSWORD, email: str = "alpha@example.test") -> dict[str, str]:
    return {"password": password, "email": email, "csrf_token": csrf}


def test_wrong_password_deletes_nothing_and_says_so(tmp_path: Path):
    settings = settings_for(tmp_path)
    migrate(settings)
    create_user(settings, "root@example.test", "Root", PASSWORD)
    alpha = create_user(settings, "alpha@example.test", "Alpha", PASSWORD)
    app = create_app(settings)
    with TestClient(app) as client:
        login(client, "alpha@example.test")
        response = client.post(
            "/profile/delete-account",
            data=delete_form(csrf_for(settings, client), password="not-the-password"),
            follow_redirects=False,
        )
        assert response.headers["location"] == "/profile?error=profile.error_delete_password"
        page = client.get(response.headers["location"])
        assert message("profile.error_delete_password") in page.text
    assert count(settings, "SELECT COUNT(*) FROM users WHERE id=?", alpha) == 1


def test_wrong_address_deletes_nothing_and_says_so(tmp_path: Path):
    settings = settings_for(tmp_path)
    migrate(settings)
    create_user(settings, "root@example.test", "Root", PASSWORD)
    alpha = create_user(settings, "alpha@example.test", "Alpha", PASSWORD)
    app = create_app(settings)
    with TestClient(app) as client:
        login(client, "alpha@example.test")
        response = client.post(
            "/profile/delete-account",
            data=delete_form(csrf_for(settings, client), email="someone@example.test"),
            follow_redirects=False,
        )
        assert response.headers["location"] == "/profile?error=profile.error_delete_email"
        assert message("profile.error_delete_email") in client.get(response.headers["location"]).text
    assert count(settings, "SELECT COUNT(*) FROM users WHERE id=?", alpha) == 1


def test_the_only_administrator_cannot_delete_the_account(tmp_path: Path):
    settings = settings_for(tmp_path)
    migrate(settings)
    root = create_user(settings, "root@example.test", "Root", PASSWORD)
    app = create_app(settings)
    with TestClient(app) as client:
        login(client, "root@example.test")
        response = client.post(
            "/profile/delete-account",
            data=delete_form(csrf_for(settings, client), email="root@example.test"),
            follow_redirects=False,
        )
        assert response.headers["location"] == "/profile?error=profile.error_delete_last_admin"
        assert message("profile.error_delete_last_admin") in client.get(response.headers["location"]).text
    assert count(settings, "SELECT COUNT(*) FROM users WHERE id=?", root) == 1


def test_an_administrator_may_delete_their_own_account_while_another_remains(tmp_path: Path):
    settings = settings_for(tmp_path)
    migrate(settings)
    create_user(settings, "root@example.test", "Root", PASSWORD)
    second = create_user(settings, "second@example.test", "Second", PASSWORD, role="admin")
    app = create_app(settings)
    with TestClient(app) as client:
        login(client, "second@example.test")
        response = client.post(
            "/profile/delete-account",
            data=delete_form(csrf_for(settings, client), email="second@example.test"),
            follow_redirects=False,
        )
    assert response.headers["location"] == "/login?notice=account_deleted"
    assert count(settings, "SELECT COUNT(*) FROM users WHERE id=?", second) == 0


def test_a_person_can_delete_their_account_and_everything_it_holds(tmp_path: Path):
    settings = settings_for(tmp_path)
    migrate(settings)
    create_user(settings, "root@example.test", "Root", PASSWORD)
    alpha = create_user(settings, "alpha@example.test", "Alpha", PASSWORD)
    beta = create_user(settings, "beta@example.test", "Beta", PASSWORD)
    alpha_patient, alpha_doc = seed_record(settings, alpha, "alpha.txt", "Alpha private result")
    beta_patient, beta_doc = seed_record(settings, beta, "beta.txt", "Beta private result")
    seed_observation(settings, alpha, alpha_patient, alpha_doc, "obs-alpha")
    seed_observation(settings, beta, beta_patient, beta_doc, "obs-beta")
    add_share(settings, alpha, beta, "beta@example.test", "share-alpha-beta")
    add_share(settings, beta, alpha, "alpha@example.test", "share-beta-alpha")
    app = create_app(settings)
    with TestClient(app) as client, TestClient(app) as other:
        login(client, "alpha@example.test")
        login(other, "beta@example.test")
        old_session = client.cookies["anamna_session"]
        response = client.post(
            "/profile/delete-account",
            # The address is typed in any case; it is compared casefolded.
            data=delete_form(csrf_for(settings, client), email="  Alpha@Example.test "),
            follow_redirects=False,
        )
        assert response.status_code == 303
        assert response.headers["location"] == "/login?notice=account_deleted"
        assert "anamna_session" not in client.cookies

        # The old session cookie no longer signs anybody in.
        with TestClient(app) as stale:
            stale.cookies.set("anamna_session", old_session)
            stopped = stale.get("/documents", follow_redirects=False)
        assert stopped.status_code == 303
        assert stopped.headers["location"].startswith("/login")

        notice = client.get("/login?notice=account_deleted")
        assert notice.status_code == 200
        assert message("auth.account_deleted") in notice.text
        assert 'role="status"' in notice.text
        # The other account is untouched and still signed in.
        assert other.get("/documents").status_code == 200

    assert count(settings, "SELECT COUNT(*) FROM users WHERE id=?", alpha) == 0
    assert count(settings, "SELECT COUNT(*) FROM documents WHERE owner_user_id=?", alpha) == 0
    assert count(settings, "SELECT COUNT(*) FROM observations WHERE owner_user_id=?", alpha) == 0
    assert count(settings, "SELECT COUNT(*) FROM record_shares WHERE owner_user_id=? OR grantee_user_id=?", alpha, alpha) == 0
    assert count(settings, "SELECT COUNT(*) FROM sessions WHERE user_id=?", alpha) == 0
    assert not (settings.source_dir / "alpha.txt").exists()
    assert (settings.source_dir / "beta.txt").read_text(encoding="utf-8") == "Beta private result"
    assert count(settings, "SELECT COUNT(*) FROM documents WHERE owner_user_id=?", beta) == 1
    assert count(settings, "SELECT COUNT(*) FROM observations WHERE owner_user_id=?", beta) == 1
    with connect(settings) as connection:
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []


def test_a_deleted_person_who_acted_on_anothers_rows_leaves_them_intact(tmp_path: Path):
    settings = settings_for(tmp_path)
    migrate(settings)
    create_user(settings, "root@example.test", "Root", PASSWORD)
    alpha = create_user(settings, "alpha@example.test", "Alpha", PASSWORD)
    beta = create_user(settings, "beta@example.test", "Beta", PASSWORD)
    with connect(settings) as connection:
        connection.execute(
            """INSERT INTO review_tasks(id, owner_user_id, entity_type, entity_id, reason, state,
                                        assigned_user_id, created_at)
               VALUES ('task-beta', ?, 'document', 'doc-beta', 'Check it', 'open', ?, ?)""",
            (beta, alpha, utc_now()),
        )
        connection.execute(
            """INSERT INTO audit_events(owner_user_id, actor_user_id, action, entity_type, entity_id,
                                        details_json, created_at)
               VALUES (?, ?, 'review_verify', 'document', 'doc-beta', '{}', ?)""",
            (beta, alpha, utc_now()),
        )
    app = create_app(settings)
    with TestClient(app) as client:
        login(client, "alpha@example.test")
        response = client.post(
            "/profile/delete-account",
            data=delete_form(csrf_for(settings, client)),
            follow_redirects=False,
        )
    assert response.headers["location"] == "/login?notice=account_deleted"
    assert count(settings, "SELECT COUNT(*) FROM users WHERE id=?", alpha) == 0
    with connect(settings) as connection:
        task = connection.execute("SELECT assigned_user_id FROM review_tasks WHERE id='task-beta'").fetchone()
        event = connection.execute(
            "SELECT actor_user_id, action FROM audit_events WHERE owner_user_id=?", (beta,)
        ).fetchone()
    assert task is not None and task["assigned_user_id"] is None
    assert event is not None and event["actor_user_id"] is None and event["action"] == "review_verify"


def test_a_bearer_credential_cannot_delete_or_re_address_the_account(tmp_path: Path):
    settings = settings_for(tmp_path)
    migrate(settings)
    create_user(settings, "root@example.test", "Root", PASSWORD)
    alpha = create_user(settings, "alpha@example.test", "Alpha", PASSWORD)
    _, secret = create_access_token(settings, alpha, kind="agent", label="agent")
    headers = {"Authorization": f"Bearer {secret}"}
    app = create_app(settings)
    with TestClient(app) as client:
        deleted = client.post(
            "/profile/delete-account", headers=headers,
            data=delete_form(""), follow_redirects=False,
        )
        moved = client.post(
            "/profile/email", headers=headers,
            data={"new_email": "hijack@example.test", "password": PASSWORD, "csrf_token": ""},
            follow_redirects=False,
        )
    assert deleted.status_code == 403
    assert moved.status_code == 403
    assert count(settings, "SELECT COUNT(*) FROM users WHERE id=? AND email='alpha@example.test'", alpha) == 1


def test_the_export_is_a_zip_of_the_signed_in_persons_own_record(tmp_path: Path):
    settings = settings_for(tmp_path)
    migrate(settings)
    create_user(settings, "root@example.test", "Root", PASSWORD)
    alpha = create_user(settings, "alpha@example.test", "Alpha", PASSWORD)
    beta = create_user(settings, "beta@example.test", "Beta", PASSWORD)
    seed_record(settings, alpha, "alpha.txt", "Alpha private result")
    seed_record(settings, beta, "beta.txt", "Beta private result")
    app = create_app(settings)
    with TestClient(app) as client:
        login(client, "alpha@example.test")
        response = client.get("/profile/export.zip")
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/zip"
    disposition = response.headers["content-disposition"]
    assert disposition.startswith('attachment; filename="anamna-export-')
    assert disposition.endswith('.zip"')
    # security_headers rewrites the value to "private, no-store, no-transform";
    # the directive that keeps the archive out of caches is what matters.
    assert "no-store" in response.headers["cache-control"]
    with zipfile.ZipFile(BytesIO(response.content)) as archive:
        names = archive.namelist()
        payload = b"".join(archive.read(name) for name in names)
    assert "manifest.json" in names
    assert any(name.endswith("alpha.txt") for name in names)
    assert b"Alpha private result" in payload
    assert b"Beta private result" not in payload
    assert count(settings, "SELECT COUNT(*) FROM audit_events WHERE action='record_exported' AND owner_user_id=?", alpha) == 1


def test_the_export_stays_my_record_while_i_am_viewing_a_share(tmp_path: Path):
    settings = settings_for(tmp_path)
    migrate(settings)
    create_user(settings, "root@example.test", "Root", PASSWORD)
    alpha = create_user(settings, "alpha@example.test", "Alpha", PASSWORD)
    beta = create_user(settings, "beta@example.test", "Beta", PASSWORD)
    seed_record(settings, alpha, "alpha.txt", "Alpha private result")
    seed_record(settings, beta, "beta.txt", "Beta private result")
    app = create_app(settings)
    with TestClient(app) as owner, TestClient(app) as viewer:
        login(owner, "beta@example.test")
        owner.post(
            "/profile/shares",
            data={"email": "alpha@example.test", "csrf_token": csrf_for(settings, owner)},
        )
        login(viewer, "alpha@example.test")
        selected = viewer.post(
            "/profile/view",
            data={"owner_user_id": beta, "csrf_token": csrf_for(settings, viewer)},
            follow_redirects=False,
        )
        assert selected.status_code == 303
        response = viewer.get("/profile/export.zip")
    assert response.status_code == 200
    with zipfile.ZipFile(BytesIO(response.content)) as archive:
        payload = b"".join(archive.read(name) for name in archive.namelist())
    assert b"Alpha private result" in payload
    assert b"Beta private result" not in payload


def test_a_guest_link_cannot_download_the_record(tmp_path: Path):
    settings = settings_for(tmp_path)
    migrate(settings)
    create_user(settings, "root@example.test", "Root", PASSWORD)
    alpha = create_user(settings, "alpha@example.test", "Alpha", PASSWORD)
    seed_record(settings, alpha, "alpha.txt", "Alpha private result")
    expires = (datetime.now(UTC) + timedelta(days=14)).replace(microsecond=0).isoformat()
    _, secret = create_access_token(settings, alpha, kind="guest", label="visitor", expires_at=expires)
    app = create_app(settings)
    with TestClient(app) as guest:
        opened = guest.get(f"/t/{secret}", follow_redirects=False)
        assert opened.status_code in (302, 303)
        response = guest.get("/profile/export.zip", follow_redirects=False)
    assert response.status_code == 403
    assert response.headers["content-type"] != "application/zip"


def test_an_invalid_address_changes_nothing(tmp_path: Path):
    settings = settings_for(tmp_path)
    migrate(settings)
    create_user(settings, "root@example.test", "Root", PASSWORD)
    alpha = create_user(settings, "alpha@example.test", "Alpha", PASSWORD)
    app = create_app(settings)
    with TestClient(app) as client:
        login(client, "alpha@example.test")
        response = client.post(
            "/profile/email",
            data={"new_email": "not an address", "password": PASSWORD, "csrf_token": csrf_for(settings, client)},
            follow_redirects=False,
        )
        assert response.headers["location"] == "/profile?error=profile.error_email_invalid"
        assert message("profile.error_email_invalid") in client.get(response.headers["location"]).text
    assert count(settings, "SELECT COUNT(*) FROM users WHERE id=? AND email='alpha@example.test'", alpha) == 1


def test_a_wrong_password_changes_no_address(tmp_path: Path):
    settings = settings_for(tmp_path)
    migrate(settings)
    create_user(settings, "root@example.test", "Root", PASSWORD)
    alpha = create_user(settings, "alpha@example.test", "Alpha", PASSWORD)
    app = create_app(settings)
    with TestClient(app) as client:
        login(client, "alpha@example.test")
        response = client.post(
            "/profile/email",
            data={"new_email": "fresh@example.test", "password": "wrong-password-here", "csrf_token": csrf_for(settings, client)},
            follow_redirects=False,
        )
        assert response.headers["location"] == "/profile?error=profile.error_email_password"
        assert message("profile.error_email_password") in client.get(response.headers["location"]).text
    assert count(settings, "SELECT COUNT(*) FROM users WHERE id=? AND email='alpha@example.test'", alpha) == 1


def test_an_address_another_account_uses_is_refused(tmp_path: Path):
    settings = settings_for(tmp_path)
    migrate(settings)
    create_user(settings, "root@example.test", "Root", PASSWORD)
    alpha = create_user(settings, "alpha@example.test", "Alpha", PASSWORD)
    create_user(settings, "beta@example.test", "Beta", PASSWORD)
    app = create_app(settings)
    with TestClient(app) as client:
        login(client, "alpha@example.test")
        response = client.post(
            "/profile/email",
            data={"new_email": "Beta@Example.test", "password": PASSWORD, "csrf_token": csrf_for(settings, client)},
            follow_redirects=False,
        )
        assert response.headers["location"] == "/profile?error=profile.error_email_taken"
        assert message("profile.error_email_taken") in client.get(response.headers["location"]).text
    assert count(settings, "SELECT COUNT(*) FROM users WHERE id=? AND email='alpha@example.test'", alpha) == 1


def test_a_changed_address_replaces_the_old_one_everywhere(tmp_path: Path):
    settings = settings_for(tmp_path)
    migrate(settings)
    create_user(settings, "root@example.test", "Root", PASSWORD)
    alpha = create_user(settings, "alpha@example.test", "Alpha", PASSWORD)
    create_user(settings, "beta@example.test", "Beta", PASSWORD)
    app = create_app(settings)
    with TestClient(app) as owner, TestClient(app) as alpha_client:
        login(owner, "beta@example.test")
        owner.post(
            "/profile/shares",
            data={"email": "alpha@example.test", "csrf_token": csrf_for(settings, owner)},
        )
        login(alpha_client, "alpha@example.test")
        response = alpha_client.post(
            "/profile/email",
            data={
                "new_email": "  Alpha.New@Example.test ",
                "password": PASSWORD,
                "csrf_token": csrf_for(settings, alpha_client),
            },
            follow_redirects=False,
        )
        assert response.status_code == 303
        assert response.headers["location"] == "/profile?saved=email"
        assert any(
            value.startswith("anamna_device=") for value in response.headers.get_list("set-cookie")
        )
        confirmed = alpha_client.get("/profile?saved=email")
        assert message("profile.email_saved") in confirmed.text
        assert message("profile.saved") not in confirmed.text

        # The owner's share list now names the address the account signs in with.
        assert "alpha.new@example.test" in owner.get("/profile").text

    assert count(settings, "SELECT COUNT(*) FROM users WHERE id=? AND email='alpha.new@example.test'", alpha) == 1
    assert count(settings, "SELECT COUNT(*) FROM record_shares WHERE grantee_user_id=? AND grantee_email='alpha.new@example.test'", alpha) == 1

    with TestClient(app) as stranger:
        old = stranger.post(
            "/login", data={"email": "alpha@example.test", "password": PASSWORD, "next": "/"},
            follow_redirects=False,
        )
        assert old.headers["location"] == "/login?error=invalid"
    with TestClient(app) as stranger:
        new = stranger.post(
            "/login", data={"email": "alpha.new@example.test", "password": PASSWORD, "next": "/"},
            follow_redirects=False,
        )
        assert new.headers["location"] == "/"

    with connect(settings) as connection:
        change = connection.execute(
            "SELECT details_json FROM audit_events WHERE action='email_changed' AND owner_user_id=?", (alpha,)
        ).fetchone()
    assert change is not None
    assert json.loads(change["details_json"]) == {}


@pytest.mark.skipif(not hasattr(labsync, "drop_links_between"), reason="labsync.drop_links_between not present")
def test_removing_a_share_drops_the_lab_links_between_the_two_accounts(tmp_path: Path, monkeypatch):
    settings = settings_for(tmp_path)
    migrate(settings)
    create_user(settings, "root@example.test", "Root", PASSWORD)
    alpha = create_user(settings, "alpha@example.test", "Alpha", PASSWORD)
    beta = create_user(settings, "beta@example.test", "Beta", PASSWORD)
    calls: list[tuple[str, str]] = []

    def recorder(_settings, user_a, user_b):
        calls.append((user_a, user_b))
        return 0

    monkeypatch.setattr(labsync, "drop_links_between", recorder)
    app = create_app(settings)
    with TestClient(app) as client:
        login(client, "alpha@example.test")
        csrf = csrf_for(settings, client)
        client.post("/profile/shares", data={"email": "beta@example.test", "csrf_token": csrf})
        with connect(settings) as connection:
            share_id = connection.execute(
                "SELECT id FROM record_shares WHERE owner_user_id=?", (alpha,)
            ).fetchone()["id"]
        removed = client.post(
            "/profile/shares/remove", data={"share_id": share_id, "csrf_token": csrf},
            follow_redirects=False,
        )
    assert removed.status_code == 303
    assert calls == [(alpha, beta)]


def test_reopening_a_file_names_the_values_it_moved_back(tmp_path: Path):
    settings, user_id, client = build(tmp_path)
    token = csrf_for(settings, client)
    client.post("/review/task-1", data={"action": "verify", "csrf_token": token})
    with connect(settings) as connection:
        verified = sorted(
            row["id"]
            for row in connection.execute(
                "SELECT id FROM observations WHERE document_id='doc-1' AND verification_status='verified'"
            )
        )
    assert len(verified) >= 2

    client.post("/review/task-1", data={"action": "reopen", "csrf_token": token})

    with connect(settings) as connection:
        audit = connection.execute(
            """SELECT details_json FROM audit_events
                   WHERE action='review_reopen' AND entity_id='doc-1'
                   ORDER BY id DESC LIMIT 1"""
        ).fetchone()
    assert audit is not None
    assert sorted(json.loads(audit["details_json"])["reopened_observation_ids"]) == verified
