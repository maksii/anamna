"""Bearer credentials: what each kind opens, and what it must not.

Every assertion here is about a boundary somebody could cross, so the failing
case is written beside the working one — a test that only proves a token works
would pass just as happily if the token worked on everything.
"""

from datetime import UTC, datetime, timedelta
from pathlib import Path

from fastapi.testclient import TestClient

from anamna.config import Settings
from anamna.db import connect, migrate
from anamna.security import (
    access_token_user,
    create_access_token,
    create_user,
    ensure_seeded_token,
)
from anamna.web.app import create_app

from test_web_security import PASSWORD, seed_document, seed_patient, settings_for
from test_web_profile import csrf_for, login


def in_days(days: int) -> str:
    return (datetime.now(UTC) + timedelta(days=days)).replace(microsecond=0).isoformat()


def owner_with_record(settings: Settings) -> tuple[str, str]:
    user_id = create_user(settings, "alpha@example.test", "Alpha", PASSWORD)
    patient = seed_patient(settings, user_id, "Alpha Patient")
    seed_document(settings, user_id, patient, "Alpha private result", "alpha.txt")
    return user_id, patient


def test_agent_token_opens_the_application_without_the_login_form(tmp_path: Path):
    settings = settings_for(tmp_path)
    migrate(settings)
    user_id, _ = owner_with_record(settings)
    _, secret = create_access_token(settings, user_id, "agent", "deployment check")
    with TestClient(create_app(settings)) as client:
        headers = {"Authorization": f"Bearer {secret}"}
        page = client.get("/", headers=headers)
        assert page.status_code == 200
        # The record itself, not a sign-in page dressed as one.
        assert "Alpha private result" in client.get("/documents", headers=headers).text
        # The same credential also reaches the API surface.
        assert client.get("/api/metrics/search?q=a", headers=headers).status_code == 200
        # X-API-Key is the other spelling of the same thing.
        assert client.get("/", headers={"X-API-Key": secret}).status_code == 200
        # A wrong secret is refused rather than falling back to anonymous.
        refused = client.get(
            "/", headers={"Authorization": "Bearer nope"}, follow_redirects=False
        )
        assert refused.status_code == 303
        assert refused.headers["location"].startswith("/login")


def test_api_key_is_confined_to_the_api(tmp_path: Path):
    settings = settings_for(tmp_path)
    migrate(settings)
    user_id, _ = owner_with_record(settings)
    _, secret = create_access_token(settings, user_id, "api", "integration tests")
    with TestClient(create_app(settings)) as client:
        headers = {"Authorization": f"Bearer {secret}"}
        assert client.get("/api/metrics/search?q=a", headers=headers).status_code == 200
        # Everything outside /api/ is refused, including the pages an agent gets.
        for path in ("/", "/documents", "/upload", "/profile", "/admin/users"):
            assert client.get(path, headers=headers).status_code == 403, path
        # And an API key cannot be upgraded into a browsing session.
        assert client.get(f"/t/{secret}", follow_redirects=False).headers["location"] == (
            "/login?error=token"
        )


def test_guest_link_is_read_only_and_expires(tmp_path: Path):
    settings = settings_for(tmp_path)
    migrate(settings)
    user_id, _ = owner_with_record(settings)
    _, secret = create_access_token(
        settings, user_id, "guest", "Dr Kovalenko", expires_at=in_days(14)
    )
    with TestClient(create_app(settings)) as guest:
        landing = guest.get(f"/t/{secret}", follow_redirects=False)
        assert landing.status_code == 303
        assert landing.headers["location"] == "/"
        page = guest.get("/")
        assert page.status_code == 200
        # The visitor is told whose record this is and that it is read-only.
        assert "read-only" in page.text
        assert "Alpha private result" in guest.get("/documents").text
        # Reading is all they get: the tools are refused, not merely hidden.
        for path in ("/upload", "/review", "/profile", "/admin/users"):
            assert guest.get(path).status_code == 403, path
        assert guest.post("/profile/shares", data={"email": "x@y.test"}).status_code == 403
        # Changing the display language still works — refusing it would leave a
        # visitor unable to read the page they were invited to.
        assert guest.post("/locale", data={"lang": "uk"}, follow_redirects=False).status_code == 303
        # And a doctor who has their own account here can still sign in to it:
        # the form is reachable and is not bounced back to the shared record.
        form = guest.get("/login")
        assert form.status_code == 200
        assert 'name="password"' in form.text
        guest.post(
            "/login",
            data={"email": "alpha@example.test", "password": PASSWORD, "next": "/"},
            follow_redirects=False,
        )
        # Signing in replaces the guest session, tools and all.
        assert guest.get("/upload").status_code == 200

    # A doctor holding invitations from two patients follows the second link
    # without having to work out that they must sign out of the first.
    beta = create_user(settings, "beta@example.test", "Beta", PASSWORD)
    beta_patient = seed_patient(settings, beta, "Beta Patient")
    seed_document(settings, beta, beta_patient, "Beta private result", "beta.txt")
    _, second = create_access_token(
        settings, beta, "guest", "same doctor, other patient", expires_at=in_days(14)
    )
    with TestClient(create_app(settings)) as doctor:
        doctor.get(f"/t/{secret}")
        assert "Alpha private result" in doctor.get("/documents").text
        assert doctor.get(f"/t/{second}", follow_redirects=False).status_code == 303
        listing = doctor.get("/documents").text
        assert "Beta private result" in listing
        assert "Alpha private result" not in listing

    # A wrong link is metered like a wrong password: the endpoint is
    # unauthenticated and reaches the database on every call.
    from anamna.security import LOGIN_ATTEMPT_LIMIT, clear_attempts

    clear_attempts("token:testclient")
    with TestClient(create_app(settings)) as knocking:
        for _ in range(LOGIN_ATTEMPT_LIMIT):
            knocking.get("/t/anamna_guest_wrong", follow_redirects=False)
        assert knocking.get("/t/anamna_guest_wrong", follow_redirects=False).headers[
            "location"
        ] == "/login?error=throttled_token&wait=15"
    clear_attempts("token:testclient")

    # An expired invitation stops working without anyone revoking it.
    _, stale = create_access_token(
        settings, user_id, "guest", "last month", expires_at=in_days(-1)
    )
    assert access_token_user(settings, stale) is None
    with TestClient(create_app(settings)) as late:
        assert late.get(f"/t/{stale}", follow_redirects=False).headers["location"] == (
            "/login?error=token"
        )


def test_revoking_a_credential_signs_out_the_session_it_opened(tmp_path: Path):
    settings = settings_for(tmp_path)
    migrate(settings)
    user_id, _ = owner_with_record(settings)
    token_id, secret = create_access_token(
        settings, user_id, "guest", "Dr Kovalenko", expires_at=in_days(14)
    )
    app = create_app(settings)
    with TestClient(app) as guest:
        guest.get(f"/t/{secret}")
        assert guest.get("/documents").status_code == 200
        with TestClient(app) as owner:
            login(owner, "alpha@example.test")
            owner.post(
                f"/tokens/{token_id}",
                data={"action": "revoke", "csrf_token": csrf_for(settings, owner)},
            )
        # The open tab is signed out, not merely stopped at the next new link.
        assert guest.get("/documents", follow_redirects=False).status_code == 303
    with connect(settings) as connection:
        # The session row is gone rather than orphaned: the foreign key took it
        # with the credential.  The owner's own password session is untouched.
        assert connection.execute(
            "SELECT COUNT(*) FROM sessions WHERE token_id IS NOT NULL"
        ).fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM sessions").fetchone()[0] == 1
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []


def test_owner_provisions_and_edits_their_own_credentials(tmp_path: Path):
    settings = settings_for(tmp_path)
    migrate(settings)
    owner_with_record(settings)
    with TestClient(create_app(settings)) as client:
        login(client, "alpha@example.test")
        csrf = csrf_for(settings, client)
        minted = client.post(
            "/tokens",
            data={
                "kind": "guest",
                "label": "Dr Kovalenko",
                "expires_on": (datetime.now(UTC) + timedelta(days=14)).date().isoformat(),
                "csrf_token": csrf,
            },
        )
        # The secret is answered with the page, never through a URL.
        assert minted.status_code == 200
        assert "anamna_guest_" in minted.text
        assert "/t/anamna_guest_" in minted.text
        secret = minted.text.split("anamna_guest_")[1].split('"')[0]
        assert access_token_user(settings, "anamna_guest_" + secret) is not None

        # A guest link without an expiry is refused: it would never lapse.
        assert "token.error" not in client.post(
            "/tokens", data={"kind": "guest", "label": "forever", "csrf_token": csrf}
        ).text
        with connect(settings) as connection:
            assert connection.execute(
                "SELECT COUNT(*) FROM access_tokens WHERE label='forever'"
            ).fetchone()[0] == 0

        with connect(settings) as connection:
            token_id = connection.execute(
                "SELECT id FROM access_tokens WHERE label='Dr Kovalenko'"
            ).fetchone()[0]
        renamed = client.post(
            f"/tokens/{token_id}",
            data={
                "action": "update",
                "label": "Cardiology follow-up",
                "expires_on": (datetime.now(UTC) + timedelta(days=3)).date().isoformat(),
                "csrf_token": csrf,
            },
            follow_redirects=False,
        )
        assert renamed.headers["location"] == "/profile?saved=token"
        assert "Cardiology follow-up" in client.get("/profile").text


def test_one_owner_cannot_touch_anothers_credential(tmp_path: Path):
    settings = settings_for(tmp_path)
    migrate(settings)
    alpha, _ = owner_with_record(settings)
    create_user(settings, "mallory@example.test", "Mallory", PASSWORD)
    token_id, secret = create_access_token(settings, alpha, "agent", "alpha's own")
    with TestClient(create_app(settings)) as client:
        login(client, "mallory@example.test")
        csrf = csrf_for(settings, client)
        # Revocation is scoped in the WHERE clause, so a guessed id changes nothing.
        refused = client.post(
            f"/tokens/{token_id}", data={"action": "revoke", "csrf_token": csrf},
            follow_redirects=False,
        )
        assert refused.headers["location"] == "/profile?error=token.error_unknown"
        # Naming somebody else as the owner mints against oneself instead.
        client.post(
            "/tokens",
            data={"kind": "api", "label": "sneaky", "owner_user_id": alpha, "csrf_token": csrf},
        )
    with connect(settings) as connection:
        assert access_token_user(settings, secret) is not None
        owner = connection.execute(
            "SELECT owner_user_id FROM access_tokens WHERE label='sneaky'"
        ).fetchone()[0]
        assert owner != alpha


def test_a_credential_sees_only_its_own_owners_record(tmp_path: Path):
    """A token is a new way to become a user, so it is a new way to get that wrong.

    The record scoping it inherits is the same one a password session gets —
    this asserts the inheritance, because "it goes through the same code" is
    the kind of claim that stops being true one refactor later.
    """
    settings = settings_for(tmp_path)
    migrate(settings)
    alpha, _ = owner_with_record(settings)
    beta = create_user(settings, "beta@example.test", "Beta", PASSWORD)
    beta_patient = seed_patient(settings, beta, "Beta Patient")
    beta_doc = seed_document(settings, beta, beta_patient, "Beta private result", "beta.txt")
    _, secret = create_access_token(settings, beta, "agent", "beta's own")
    with TestClient(create_app(settings)) as client:
        headers = {"Authorization": f"Bearer {secret}"}
        listing = client.get("/documents", headers=headers)
        assert "Beta private result" in listing.text
        assert "Alpha private result" not in listing.text
        # Alpha's document is not reachable by id either.
        assert client.get("/documents/doc-alpha.txt", headers=headers).status_code == 404
        assert client.get(f"/documents/{beta_doc}", headers=headers).status_code == 200


def test_admin_provisions_for_another_account(tmp_path: Path):
    settings = settings_for(tmp_path)
    migrate(settings)
    # The first account owns the installation, so this one is the administrator.
    admin = create_user(settings, "root@example.test", "Root", PASSWORD)
    beta = create_user(settings, "beta@example.test", "Beta", PASSWORD)
    seed_patient(settings, beta, "Beta Patient")
    with TestClient(create_app(settings)) as client:
        login(client, "root@example.test")
        csrf = csrf_for(settings, client)
        assert client.get("/admin/tokens").status_code == 200
        minted = client.post(
            "/tokens",
            data={
                "kind": "api",
                "label": "beta integration",
                "owner_user_id": beta,
                "origin": "admin",
                "csrf_token": csrf,
            },
        )
        assert minted.status_code == 200
        assert "anamna_api_" in minted.text
    with connect(settings) as connection:
        row = connection.execute(
            "SELECT owner_user_id, created_by_user_id FROM access_tokens WHERE label='beta integration'"
        ).fetchone()
        assert row["owner_user_id"] == beta
        assert row["created_by_user_id"] == admin


def test_seeded_token_is_pinned_to_the_first_administrator(tmp_path: Path):
    settings = settings_for(tmp_path)
    migrate(settings)
    admin = create_user(settings, "root@example.test", "Root", PASSWORD)
    create_user(settings, "beta@example.test", "Beta", PASSWORD)
    secret = "anamna_agent_pinned-by-the-operator"
    first = ensure_seeded_token(settings, secret)
    # Idempotent: a restart must not mint a second copy of the same credential.
    assert ensure_seeded_token(settings, secret) == first
    with connect(settings) as connection:
        assert connection.execute("SELECT COUNT(*) FROM access_tokens").fetchone()[0] == 1
    row = access_token_user(settings, secret)
    assert row["id"] == admin and row["token_kind"] == "agent"
    # Unset means no credential at all, rather than a guessable default.
    assert ensure_seeded_token(settings, "") is None
    assert ensure_seeded_token(settings, None) is None
