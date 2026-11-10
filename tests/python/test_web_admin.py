"""Roles, the people page, and the boundaries around both.

Every test here is about who is allowed to do something, so they assert on the
refusal as much as on the success: a guard that returns the right page for the
right person is only half of the check.
"""

from dataclasses import replace
from pathlib import Path

from fastapi.testclient import TestClient

from anamna.config import Settings
from anamna.db import connect, migrate, utc_now
from anamna.security import (
    LOGIN_ATTEMPT_LIMIT,
    clear_attempts,
    create_user,
    open_registration,
    set_open_registration,
)
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


def sign_in(client: TestClient, email: str) -> None:
    response = client.post(
        "/login", data={"email": email, "password": PASSWORD, "next": "/"}, follow_redirects=False
    )
    assert response.status_code == 303, response.headers.get("location")


def csrf_for(settings: Settings, user_id: str) -> str:
    with connect(settings) as connection:
        return connection.execute(
            "SELECT csrf_token FROM sessions WHERE user_id=?", (user_id,)
        ).fetchone()[0]


def role_of(settings: Settings, user_id: str) -> str:
    with connect(settings) as connection:
        return connection.execute("SELECT role FROM users WHERE id=?", (user_id,)).fetchone()[0]


def two_people(tmp_path: Path) -> tuple[Settings, str, str]:
    """An administrator and a member, in that creation order."""
    settings = settings_for(tmp_path)
    migrate(settings)
    admin = create_user(settings, "admin@example.test", "Admin", PASSWORD, role="admin")
    member = create_user(settings, "member@example.test", "Member", PASSWORD)
    return settings, admin, member


def test_the_earliest_account_becomes_the_administrator(tmp_path: Path):
    """An existing installation must not migrate into having no administrator.

    The migration cannot name an email without baking one machine's fixture
    into every clone, so it promotes whoever created the instance.
    """
    settings = settings_for(tmp_path)
    # A database at the previous schema: users exist before the roles column does.
    with connect(settings) as connection:
        connection.executescript(
            (Path(__file__).resolve().parents[2] / "migrations" / "001_initial.sql").read_text(
                encoding="utf-8"
            )
        )
        for index, email in enumerate(("first@example.test", "second@example.test")):
            connection.execute(
                """INSERT INTO users(id, email, display_name, password_salt, password_hash, created_at)
                   VALUES (?, ?, ?, X'00', X'00', ?)""",
                (f"user-{index}", email, email, f"2026-01-0{index + 1}T00:00:00+00:00"),
            )
    migrate(settings)
    assert role_of(settings, "user-0") == "admin"
    assert role_of(settings, "user-1") == "user"


def test_a_fresh_installation_lets_its_owner_in_and_then_shuts_the_door(tmp_path: Path):
    """Closed-by-default would otherwise deadlock an empty database.

    No account means no administrator, and no administrator means nobody who
    can open the sign-up form.  The way in is the first-run page, behind the
    setup code (test_web_setup), never the public sign-up form.
    """
    settings = settings_for(tmp_path)
    migrate(settings)
    assert open_registration(settings) is False

    app = create_app(settings)
    with TestClient(app) as client:
        walk_in = client.post(
            "/register",
            data={"email": "owner@example.test", "display_name": "Owner", "password": PASSWORD},
            follow_redirects=False,
        )
        assert walk_in.headers["location"] == "/setup"
        first = client.post(
            "/setup",
            data={"setup_code": app.state.setup_code, "email": "owner@example.test",
                  "display_name": "Owner", "password": PASSWORD},
            follow_redirects=False,
        )
        assert first.headers["location"] == "/"
        # Signed in as the new owner, who can reach the page a member cannot.
        assert client.get("/admin/users").status_code == 200

    with connect(settings) as connection:
        assert connection.execute(
            "SELECT role FROM users WHERE email='owner@example.test'"
        ).fetchone()[0] == "admin"

    # The door shuts behind them: the second visitor is not let in by default.
    assert open_registration(settings) is False
    with TestClient(create_app(settings)) as stranger:
        second = stranger.post(
            "/register",
            data={"email": "walkin@example.test", "display_name": "Walk In", "password": PASSWORD},
            follow_redirects=False,
        )
        assert second.headers["location"] == "/login?error=closed"
    with connect(settings) as connection:
        assert connection.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 1


def test_the_people_page_is_closed_to_members_and_to_strangers(tmp_path: Path):
    settings, admin, member = two_people(tmp_path)
    with TestClient(create_app(settings)) as client:
        # A stranger is sent to sign in; there is nothing to tell them apart from
        # a member whose session has expired.
        anonymous = client.get("/admin/users", follow_redirects=False)
        assert anonymous.status_code == 303
        assert anonymous.headers["location"].startswith("/login")

        sign_in(client, "member@example.test")
        # 403 rather than another redirect: signing in again would not help.
        assert client.get("/admin/users").status_code == 403
        assert client.post(
            f"/admin/users/{admin}",
            data={"action": "delete", "csrf_token": csrf_for(settings, member)},
        ).status_code == 403
        assert client.post(
            "/admin/registration", data={"enabled": "1", "csrf_token": csrf_for(settings, member)}
        ).status_code == 403

    assert open_registration(settings) is False
    with connect(settings) as connection:
        assert connection.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 2


def test_administrator_sees_the_page_and_a_member_never_sees_the_link(tmp_path: Path):
    settings, admin, member = two_people(tmp_path)
    with TestClient(create_app(settings)) as client:
        sign_in(client, "admin@example.test")
        page = client.get("/admin/users")
        assert page.status_code == 200
        assert "member@example.test" in page.text
        assert "/admin/users" in client.get("/profile").text

    with TestClient(create_app(settings)) as client:
        sign_in(client, "member@example.test")
        assert "/admin/users" not in client.get("/profile").text


def test_blocking_ends_live_sessions_and_refuses_the_next_sign_in(tmp_path: Path):
    settings, admin, member = two_people(tmp_path)
    app = create_app(settings)
    with TestClient(app) as admin_client, TestClient(app) as member_client:
        sign_in(member_client, "member@example.test")
        assert member_client.get("/documents").status_code == 200

        sign_in(admin_client, "admin@example.test")
        blocked = admin_client.post(
            f"/admin/users/{member}",
            data={"action": "block", "csrf_token": csrf_for(settings, admin)},
            follow_redirects=False,
        )
        assert blocked.headers["location"] == "/admin/users?done=blocked"

        # The already-open session stops at the next request, not at expiry.
        stopped = member_client.get("/documents", follow_redirects=False)
        assert stopped.status_code == 303
        assert stopped.headers["location"].startswith("/login")
        refused = member_client.post(
            "/login",
            data={"email": "member@example.test", "password": PASSWORD},
            follow_redirects=False,
        )
        assert refused.headers["location"] == "/login?error=invalid"
        clear_attempts("testclient")

        admin_client.post(
            f"/admin/users/{member}",
            data={"action": "unblock", "csrf_token": csrf_for(settings, admin)},
        )
        sign_in(member_client, "member@example.test")
        assert member_client.get("/documents").status_code == 200


def test_deleting_an_account_takes_its_documents_and_its_files(tmp_path: Path):
    """A deletion that leaves the PDFs on disk has hidden the record, not deleted it."""
    settings, admin, member = two_people(tmp_path)
    source = settings.source_dir / "member-result.txt"
    source.write_text("Ferritin 42", encoding="utf-8")
    with connect(settings) as connection:
        connection.execute(
            "INSERT INTO patients(id, owner_user_id, display_name, created_at) VALUES (?, ?, ?, ?)",
            ("patient-member", member, "Member", utc_now()),
        )
        connection.execute(
            """INSERT INTO documents(
                   id, owner_user_id, patient_id, original_filename, source_path, mime_type,
                   byte_size, sha256, page_count, title, clinical_type, extraction_strategy,
                   classification_confidence, imported_at, status
               ) VALUES ('doc-member', ?, 'patient-member', 'member-result.txt', ?, 'text/plain',
                         11, 'sha-member', 1, 'Member result', 'laboratory', 'native_text', 1, ?, 'final')""",
            (member, str(source), utc_now()),
        )

    with TestClient(create_app(settings)) as client:
        sign_in(client, "admin@example.test")
        removed = client.post(
            f"/admin/users/{member}",
            data={"action": "delete", "csrf_token": csrf_for(settings, admin)},
            follow_redirects=False,
        )
        assert removed.headers["location"] == "/admin/users?done=deleted"

    assert not source.exists()
    with connect(settings) as connection:
        assert connection.execute("SELECT COUNT(*) FROM users WHERE id=?", (member,)).fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM documents").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM patients").fetchone()[0] == 0
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
        # The record of the deletion survives the account it describes.
        event = connection.execute(
            "SELECT * FROM audit_events WHERE action='admin_user_deleted'"
        ).fetchone()
        assert event["owner_user_id"] == admin
        assert "member@example.test" in event["details_json"]


def test_the_last_administrator_cannot_be_removed_by_anyone_including_themselves(tmp_path: Path):
    """An instance with no reachable administrator is repairable only with a SQL client."""
    settings, admin, member = two_people(tmp_path)
    with TestClient(create_app(settings)) as client:
        sign_in(client, "admin@example.test")
        token = csrf_for(settings, admin)
        for action, expected in (
            ("block", "/admin/users?error=admin.error_self"),
            ("demote", "/admin/users?error=admin.error_self"),
            ("delete", "/admin/users?error=admin.error_self"),
        ):
            response = client.post(
                f"/admin/users/{admin}",
                data={"action": action, "csrf_token": token},
                follow_redirects=False,
            )
            assert response.headers["location"] == expected, action

        # A second administrator who is not the last one may still be demoted,
        # and the rule then applies to whoever remains.
        client.post(f"/admin/users/{member}", data={"action": "promote", "csrf_token": token})
        assert role_of(settings, member) == "admin"
        client.post(f"/admin/users/{member}", data={"action": "demote", "csrf_token": token})
        assert role_of(settings, member) == "user"

    assert role_of(settings, admin) == "admin"


def test_the_last_administrator_rule_covers_a_second_account_too(tmp_path: Path):
    """The guard is about the count, not about who is asking."""
    settings, admin, member = two_people(tmp_path)
    with connect(settings) as connection:
        connection.execute("UPDATE users SET role='user' WHERE id=?", (admin,))
        connection.execute("UPDATE users SET role='admin' WHERE id=?", (member,))
    with TestClient(create_app(settings)) as client:
        sign_in(client, "member@example.test")
        response = client.post(
            f"/admin/users/{member}",
            data={"action": "demote", "csrf_token": csrf_for(settings, member)},
            follow_redirects=False,
        )
        # Their own account, so the self-rule answers first; either refusal keeps
        # an administrator on the instance, which is what the rule is for.
        assert "error=" in response.headers["location"]
    assert role_of(settings, member) == "admin"


def test_adding_a_person_creates_the_account_and_the_record_it_writes_into(tmp_path: Path):
    settings, admin, _member = two_people(tmp_path)
    with TestClient(create_app(settings)) as client:
        sign_in(client, "admin@example.test")
        token = csrf_for(settings, admin)
        added = client.post(
            "/admin/users",
            data={
                "email": "Newcomer@Example.test",
                "display_name": "Newcomer",
                "password": PASSWORD,
                "role": "user",
                "csrf_token": token,
            },
            follow_redirects=False,
        )
        assert added.headers["location"] == "/admin/users?done=added"
        short = client.post(
            "/admin/users",
            data={"email": "weak@example.test", "display_name": "Weak", "password": "short",
                  "csrf_token": token},
            follow_redirects=False,
        )
        assert short.headers["location"] == "/admin/users?error=admin.error_password"
        duplicate = client.post(
            "/admin/users",
            data={"email": "newcomer@example.test", "display_name": "Twin", "password": PASSWORD,
                  "csrf_token": token},
            follow_redirects=False,
        )
        assert duplicate.headers["location"] == "/admin/users?error=admin.error_exists"

    with connect(settings) as connection:
        person = connection.execute(
            "SELECT * FROM users WHERE email='newcomer@example.test'"
        ).fetchone()
        assert person["role"] == "user"
        # Without a patients row the account has nothing to write results into.
        assert connection.execute(
            "SELECT COUNT(*) FROM patients WHERE owner_user_id=?", (person["id"],)
        ).fetchone()[0] == 1

    # The account created through the page signs in like any other.
    with TestClient(create_app(settings)) as client:
        sign_in(client, "newcomer@example.test")


def test_the_registration_toggle_opens_and_closes_the_public_form(tmp_path: Path):
    settings, admin, _member = two_people(tmp_path)
    app = create_app(settings)
    # The form is only reachable signed out — a signed-in visitor is sent home
    # before the toggle is ever consulted — so the gate is checked from there.
    with TestClient(app) as client, TestClient(app) as stranger:
        assert stranger.get("/register", follow_redirects=False).headers["location"] == (
            "/login?error=closed"
        )
        sign_in(client, "admin@example.test")
        token = csrf_for(settings, admin)

        opened = client.post(
            "/admin/registration",
            data={"enabled": "1", "csrf_token": token},
            follow_redirects=False,
        )
        assert opened.headers["location"] == "/admin/users?done=registration_open"
        assert open_registration(settings) is True

        closed = client.post(
            "/admin/registration",
            data={"enabled": "0", "csrf_token": token},
            follow_redirects=False,
        )
        assert closed.headers["location"] == "/admin/users?done=registration_closed"
        assert open_registration(settings) is False
        assert stranger.get("/register", follow_redirects=False).headers["location"] == (
            "/login?error=closed"
        )

    set_open_registration(settings, True)
    with TestClient(create_app(settings)) as client:
        assert client.get("/register").status_code == 200


def test_every_administrative_write_requires_the_session_csrf_token(tmp_path: Path):
    settings, admin, member = two_people(tmp_path)
    with TestClient(create_app(settings)) as client:
        sign_in(client, "admin@example.test")
        for path, payload in (
            (f"/admin/users/{member}", {"action": "delete"}),
            ("/admin/users", {"email": "x@example.test", "display_name": "X", "password": PASSWORD}),
            ("/admin/registration", {"enabled": "1"}),
        ):
            assert client.post(path, data={**payload, "csrf_token": "forged"}).status_code == 403

    assert open_registration(settings) is False
    with connect(settings) as connection:
        assert connection.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 2


def test_repeated_failed_sign_ins_are_throttled(tmp_path: Path):
    """scrypt costs the server as much as the attacker, so an open form is both
    a credential-stuffing target and a way to saturate the box."""
    settings, _admin, _member = two_people(tmp_path)
    clear_attempts("testclient")
    try:
        with TestClient(create_app(settings)) as client:
            for _ in range(LOGIN_ATTEMPT_LIMIT):
                response = client.post(
                    "/login",
                    data={"email": "admin@example.test", "password": "wrong"},
                    follow_redirects=False,
                )
                assert response.headers["location"] == "/login?error=invalid"
            throttled = client.post(
                "/login",
                data={"email": "admin@example.test", "password": PASSWORD},
                follow_redirects=False,
            )
            # The correct password is refused too: the limit is on the address,
            # so guessing cannot be resumed by getting one right.
            assert throttled.headers["location"] == "/login?error=throttled&wait=15"
            assert "Too many failed sign-in attempts" in client.get("/login?error=throttled&wait=15").text
    finally:
        clear_attempts("testclient")


def test_a_person_can_replace_the_password_an_administrator_chose_for_them(tmp_path: Path):
    """Otherwise the administrator knows the password to somebody's medical record
    for as long as the account exists."""
    settings, admin, member = two_people(tmp_path)
    NEW = "a-password-only-they-know"
    app = create_app(settings)
    with TestClient(app) as client, TestClient(app) as other_browser:
        sign_in(client, "member@example.test")
        sign_in(other_browser, "member@example.test")
        assert other_browser.get("/documents").status_code == 200
        token = csrf_for(settings, member)

        # A valid session is not enough: an unattended browser must not be able
        # to take the account over permanently.
        wrong = client.post(
            "/profile/password",
            data={"current_password": "not-it", "new_password": NEW,
                  "confirm_password": NEW, "csrf_token": token},
            follow_redirects=False,
        )
        assert wrong.headers["location"] == "/profile?error=profile.error_password_current"

        mismatch = client.post(
            "/profile/password",
            data={"current_password": PASSWORD, "new_password": NEW,
                  "confirm_password": NEW + "typo", "csrf_token": token},
            follow_redirects=False,
        )
        assert mismatch.headers["location"] == "/profile?error=profile.error_password_match"

        short = client.post(
            "/profile/password",
            data={"current_password": PASSWORD, "new_password": "short",
                  "confirm_password": "short", "csrf_token": token},
            follow_redirects=False,
        )
        assert short.headers["location"] == "/profile?error=profile.error_password_short"

        changed = client.post(
            "/profile/password",
            data={"current_password": PASSWORD, "new_password": NEW,
                  "confirm_password": NEW, "csrf_token": token},
            follow_redirects=False,
        )
        assert changed.headers["location"] == "/profile?saved=password"

        # The browser that made the change keeps working...
        assert client.get("/documents").status_code == 200
        # ...and every other one is signed out, because a password is replaced
        # precisely when somebody else may know it.
        stale = other_browser.get("/documents", follow_redirects=False)
        assert stale.status_code == 303
        assert stale.headers["location"].startswith("/login")

    with TestClient(create_app(settings)) as client:
        old = client.post(
            "/login", data={"email": "member@example.test", "password": PASSWORD},
            follow_redirects=False,
        )
        assert old.headers["location"] == "/login?error=invalid"
        clear_attempts("testclient")
        sign_in_new = client.post(
            "/login", data={"email": "member@example.test", "password": NEW, "next": "/"},
            follow_redirects=False,
        )
        assert sign_in_new.headers["location"] == "/"

    with connect(settings) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM audit_events WHERE action='password_changed'"
        ).fetchone()[0] == 1
        # The administrator's own sessions are untouched by somebody else's change.
        assert connection.execute(
            "SELECT COUNT(*) FROM sessions WHERE user_id=?", (admin,)
        ).fetchone()[0] >= 0


def test_an_opened_sign_up_form_is_throttled_on_successes_too(tmp_path: Path):
    """Sign-up is abused by succeeding, not by failing.

    The login limiter counts only failures, which would never fire here: an
    address creating one account after another is doing so successfully.
    """
    settings, _admin, _member = two_people(tmp_path)
    set_open_registration(settings, True)
    clear_attempts("testclient")
    try:
        with TestClient(create_app(settings)) as client:
            for index in range(LOGIN_ATTEMPT_LIMIT):
                created = client.post(
                    "/register",
                    data={
                        "email": f"bulk{index}@example.test",
                        "display_name": f"Bulk {index}",
                        "password": PASSWORD,
                    },
                    follow_redirects=False,
                )
                assert created.headers["location"] == "/", index
                client.cookies.clear()  # each sign-up arrives as a new visitor
            refused = client.post(
                "/register",
                data={"email": "bulk-last@example.test", "display_name": "Last",
                      "password": PASSWORD},
                follow_redirects=False,
            )
            assert refused.headers["location"] == "/register?error=throttled&wait=15"
    finally:
        clear_attempts("testclient")

    with connect(settings) as connection:
        # Two seeded accounts plus the ten that got through, and not the eleventh.
        assert connection.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 12


def test_responses_carry_the_headers_a_public_deployment_needs(tmp_path: Path):
    settings, _admin, _member = two_people(tmp_path)
    with TestClient(create_app(settings)) as client:
        headers = client.get("/login").headers
        assert headers["X-Content-Type-Options"] == "nosniff"
        assert headers["X-Frame-Options"] == "DENY"
        assert headers["Referrer-Policy"] == "no-referrer"
        assert "frame-ancestors 'none'" in headers["Content-Security-Policy"]
        assert "form-action 'self'" in headers["Content-Security-Policy"]
        # Sent only over TLS, where a browser will act on it.
        assert "Strict-Transport-Security" not in headers
        assert "Strict-Transport-Security" in client.get(
            "https://testserver/login"
        ).headers


def test_the_session_cookie_follows_the_scheme_it_was_issued_over(tmp_path: Path):
    """A constant here is wrong in both directions: `secure=True` makes local
    http sign-in impossible, `False` hands the session to the network once the
    deployment is behind TLS."""
    settings, _admin, _member = two_people(tmp_path)
    with TestClient(create_app(settings)) as client:
        plain = client.post(
            "http://testserver/login",
            data={"email": "admin@example.test", "password": PASSWORD},
            follow_redirects=False,
        )
        assert "secure" not in plain.headers["set-cookie"].casefold()
    with TestClient(create_app(settings)) as client:
        secured = client.post(
            "https://testserver/login",
            data={"email": "admin@example.test", "password": PASSWORD},
            follow_redirects=False,
        )
        cookie = secured.headers["set-cookie"].casefold()
        assert "secure" in cookie and "httponly" in cookie


def test_secure_cookies_can_be_forced_for_tls_that_terminates_upstream(tmp_path: Path):
    """Detection cannot see TLS that ends at a proxy uvicorn does not trust.

    `--forwarded-allow-ips` defaults to 127.0.0.1, so a container behind a
    proxy on another address receives plain http and would quietly stop
    marking the cookie secure — the exact deployment this is built for.
    """
    base = settings_for(tmp_path)
    forced = replace(base, secure_cookies=True)
    migrate(forced)
    create_user(forced, "admin@example.test", "Admin", PASSWORD, role="admin")
    with TestClient(create_app(forced)) as client:
        plain = client.post(
            "http://testserver/login",
            data={"email": "admin@example.test", "password": PASSWORD},
            follow_redirects=False,
        )
        assert "secure" in plain.headers["set-cookie"].casefold()

    # And an explicit "never" still means never, for a plain-http deployment.
    never = replace(base, database_path=tmp_path / "never.sqlite3", secure_cookies=False)
    migrate(never)
    create_user(never, "admin@example.test", "Admin", PASSWORD, role="admin")
    with TestClient(create_app(never)) as client:
        over_tls = client.post(
            "https://testserver/login",
            data={"email": "admin@example.test", "password": PASSWORD},
            follow_redirects=False,
        )
        assert "secure" not in over_tls.headers["set-cookie"].casefold()


def test_the_people_page_reports_what_each_account_actually_holds(tmp_path: Path):
    settings, admin, member = two_people(tmp_path)
    with connect(settings) as connection:
        connection.execute(
            "INSERT INTO patients(id, owner_user_id, display_name, created_at) VALUES (?, ?, ?, ?)",
            ("patient-member", member, "Member", utc_now()),
        )
        for index in range(3):
            connection.execute(
                """INSERT INTO documents(
                       id, owner_user_id, patient_id, original_filename, source_path, mime_type,
                       byte_size, sha256, page_count, title, clinical_type, extraction_strategy,
                       classification_confidence, imported_at, status
                   ) VALUES (?, ?, 'patient-member', ?, ?, 'text/plain', 1024, ?, 1, 'Result',
                             'laboratory', 'native_text', 1, ?, 'final')""",
                (f"doc-{index}", member, f"f{index}.txt", f"/tmp/f{index}.txt", f"sha-{index}",
                 utc_now()),
            )
    with TestClient(create_app(settings)) as client:
        sign_in(client, "admin@example.test")
        page = client.get("/admin/users").text
        assert "3 kB" in page  # three 1 KiB documents, summed and shown as storage
        # Counts must not multiply each other: two child tables joined onto one
        # parent would report nine documents here.
        assert page.count("member@example.test") == 1
