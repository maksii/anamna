"""Every pause can be released, and a mistyped code never traps anybody.

A meter counts failures per key and says how many minutes until the key frees
itself.  An administrator can lift any pause from the Users page, a new password
set by an administrator lifts that person's sign-in meters, and a registration
form that fails validation does not count at all.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from anamna import security
from anamna.db import connect, migrate
from anamna.security import (
    LOGIN_ACCOUNT_LIMIT,
    LOGIN_ATTEMPT_LIMIT,
    LOGIN_ATTEMPT_WINDOW,
    create_doctor_pin,
    create_user,
    set_open_registration,
)
from anamna.web.app import create_app

from test_web_profile import csrf_for, login
from test_web_security import PASSWORD, seed_document, seed_patient, settings_for


@pytest.fixture(autouse=True)
def fresh_meters():
    """The meters are in-process dicts; no test may inherit another's knocks."""
    security._attempts.clear()
    security._limits.clear()
    yield
    security._attempts.clear()
    security._limits.clear()


@pytest.fixture
def world(tmp_path: Path):
    settings = settings_for(tmp_path)
    migrate(settings)
    owner = create_user(settings, "alpha@example.test", "Alpha", PASSWORD)
    admin = create_user(settings, "admin@example.test", "Admin", PASSWORD, role="admin")
    member = create_user(settings, "member@example.test", "Member", PASSWORD)
    patient = seed_patient(settings, owner, "Alpha Patient")
    seed_document(settings, owner, patient, "Alpha private result", "alpha.txt")
    return settings, owner, admin, member, create_app(settings)


def pause(key: str, limit: int) -> None:
    """Fill a meter to its limit, the way failed attempts would."""
    for _ in range(limit):
        security.record_attempt(key)
    assert security.throttled(key, limit)


def wrong_code(pin: str) -> str:
    return "000000" if pin != "000000" else "111111"


def administrator_browser(app) -> TestClient:
    browser = TestClient(app)
    login(browser, "admin@example.test")
    return browser


def release(browser: TestClient, settings, key: str):
    return browser.post(
        "/admin/throttles/release",
        data={"key": key, "csrf_token": csrf_for(settings, browser)},
        follow_redirects=False,
    )


def test_retry_minutes_is_zero_when_free_and_one_to_fifteen_when_blocked():
    assert security.retry_minutes("token:203.0.113.1") == 0
    pause("token:203.0.113.1", LOGIN_ATTEMPT_LIMIT)
    minutes = security.retry_minutes("token:203.0.113.1")
    assert 1 <= minutes <= 15
    # One stamp is short of the limit, so this key is free.
    security.record_attempt("token:203.0.113.2")
    assert security.throttled("token:203.0.113.2", LOGIN_ATTEMPT_LIMIT) is False
    assert security.retry_minutes("token:203.0.113.2") == 0
    assert security.blocked() == [{"key": "token:203.0.113.1", "minutes": minutes}]


def test_a_pause_frees_itself_when_its_oldest_counted_stamp_leaves_the_window(monkeypatch):
    pause("login:someone@example.test", LOGIN_ACCOUNT_LIMIT)
    assert security.retry_minutes("login:someone@example.test") == 15

    class ThirtySecondsLeft(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime.now(tz) + LOGIN_ATTEMPT_WINDOW - timedelta(seconds=30)

    monkeypatch.setattr(security, "datetime", ThirtySecondsLeft)
    assert security.retry_minutes("login:someone@example.test") == 1
    assert security.blocked() == [{"key": "login:someone@example.test", "minutes": 1}]

    class Expired(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime.now(tz) + LOGIN_ATTEMPT_WINDOW + timedelta(seconds=1)

    monkeypatch.setattr(security, "datetime", Expired)
    assert security.retry_minutes("login:someone@example.test") == 0
    assert security.blocked() == []


def test_clear_attempts_matching_releases_only_the_prefix_and_counts_it():
    pause("login-dev:a@example.test:n1", LOGIN_ACCOUNT_LIMIT)
    pause("login-dev:a@example.test:n2", LOGIN_ACCOUNT_LIMIT)
    pause("login-dev:b@example.test:n1", LOGIN_ACCOUNT_LIMIT)
    assert security.clear_attempts_matching("login-dev:a@example.test:") == 2
    assert [entry["key"] for entry in security.blocked()] == ["login-dev:b@example.test:n1"]


def test_a_doctor_who_mistypes_nine_codes_can_still_enter_the_right_one(world):
    settings, owner, _, _, app = world
    _, pin, _, _ = create_doctor_pin(settings, owner)
    knock = {"CF-Connecting-IP": "203.0.113.20"}
    with TestClient(app) as client:
        for _ in range(security.DOCTOR_PIN_CLIENT_LIMIT - 1):
            assert client.post("/doctor", data={"pin": wrong_code(pin)}, headers=knock).status_code == 400
        opened = client.post("/doctor", data={"pin": pin}, headers=knock, follow_redirects=False)
        assert opened.status_code == 303 and opened.headers["location"] == "/"
    assert security.retry_minutes("doctor-pin:203.0.113.20") == 0


def test_ten_wrong_codes_pause_the_visitor_and_an_administrator_releases_it(world):
    settings, owner, _, _, app = world
    _, pin, _, _ = create_doctor_pin(settings, owner)
    knock = {"CF-Connecting-IP": "203.0.113.30"}
    with TestClient(app) as doctor:
        for _ in range(security.DOCTOR_PIN_CLIENT_LIMIT):
            assert doctor.post("/doctor", data={"pin": wrong_code(pin)}, headers=knock).status_code == 400
        locked = doctor.post("/doctor", data={"pin": pin}, headers=knock, follow_redirects=False)
        assert locked.status_code == 429
        assert "Too many wrong codes" in locked.text
        assert "15 minutes" in locked.text

        administrator = administrator_browser(app)
        response = release(administrator, settings, "doctor-pin:203.0.113.30")
        assert response.headers["location"] == "/admin/users?done=released"

        opened = doctor.post("/doctor", data={"pin": pin}, headers=knock, follow_redirects=False)
        assert opened.status_code == 303 and opened.headers["location"] == "/"


def test_releasing_a_pause_needs_an_administrator_and_a_csrf_token(world):
    settings, _, _, _, app = world
    pause("token:203.0.113.40", LOGIN_ATTEMPT_LIMIT)
    with TestClient(app) as plain:
        login(plain, "member@example.test")
        refused = plain.post(
            "/admin/throttles/release",
            data={"key": "token:203.0.113.40", "csrf_token": csrf_for(settings, plain)},
            follow_redirects=False,
        )
        assert refused.status_code == 403
    assert [entry["key"] for entry in security.blocked()] == ["token:203.0.113.40"]

    administrator = administrator_browser(app)
    no_token = administrator.post(
        "/admin/throttles/release", data={"key": "token:203.0.113.40"}, follow_redirects=False,
    )
    assert no_token.status_code == 403
    wrong_token = administrator.post(
        "/admin/throttles/release",
        data={"key": "token:203.0.113.40", "csrf_token": "not-the-token"},
        follow_redirects=False,
    )
    assert wrong_token.status_code == 403
    assert [entry["key"] for entry in security.blocked()] == ["token:203.0.113.40"]


def test_release_ignores_keys_that_are_not_paused(world):
    settings, _, _, _, app = world
    pause("token:203.0.113.41", LOGIN_ATTEMPT_LIMIT)
    release(administrator_browser(app), settings, "token:198.51.100.99")
    assert [entry["key"] for entry in security.blocked()] == ["token:203.0.113.41"]


def test_star_releases_every_pause_and_the_audit_line_names_no_address(world):
    settings, _, _, _, app = world
    pause("token:203.0.113.50", LOGIN_ATTEMPT_LIMIT)
    pause("register:203.0.113.51", LOGIN_ATTEMPT_LIMIT)
    pause("login:member@example.test", LOGIN_ACCOUNT_LIMIT)
    response = release(administrator_browser(app), settings, "*")
    assert response.headers["location"] == "/admin/users?done=released"
    assert security.blocked() == []
    with connect(settings) as connection:
        details = [
            row["details_json"]
            for row in connection.execute(
                "SELECT details_json FROM audit_events WHERE action = 'throttle.release'"
            )
        ]
    assert details == ['{"released": 3}']
    assert "203.0.113" not in details[0] and "member@" not in details[0]


def test_an_administrator_setting_a_password_releases_that_persons_sign_in_meters(world):
    settings, _, _, member, app = world
    pause("login:member@example.test", LOGIN_ACCOUNT_LIMIT)
    pause("login-dev:member@example.test:devicenonce", LOGIN_ACCOUNT_LIMIT)
    pause("pwchange:" + member, security.PASSWORD_CHANGE_LIMIT)
    with TestClient(app) as guesser:
        blocked = guesser.post(
            "/login", data={"email": "member@example.test", "password": PASSWORD}, follow_redirects=False,
        )
        assert blocked.headers["location"].startswith("/login?error=throttled")

    administrator = administrator_browser(app)
    new_password = "a-fresh-administrator-password"
    response = administrator.post(
        f"/admin/users/{member}/password",
        data={
            "new_password": new_password,
            "confirm_password": new_password,
            "csrf_token": csrf_for(settings, administrator),
        },
        follow_redirects=False,
    )
    assert response.headers["location"] == "/admin/users?done=password_set"
    assert security.blocked() == []

    with TestClient(app) as member_browser:
        signed_in = member_browser.post(
            "/login",
            data={"email": "member@example.test", "password": new_password},
            follow_redirects=False,
        )
        assert signed_in.status_code == 303 and signed_in.headers["location"] == "/"


def test_failed_sign_up_validation_does_not_count_toward_the_limit(world):
    settings, _, _, _, app = world
    set_open_registration(settings, True)
    with TestClient(app) as visitor:
        for index in range(LOGIN_ATTEMPT_LIMIT):
            response = visitor.post(
                "/register",
                data={"email": f"short{index}@example.test", "display_name": "Short", "password": "too-short"},
                follow_redirects=False,
            )
            assert response.headers["location"].startswith("/register?error=register.error_password")
        assert security.blocked() == []
        created = visitor.post(
            "/register",
            data={"email": "valid@example.test", "display_name": "Valid", "password": PASSWORD},
            follow_redirects=False,
        )
        assert created.status_code == 303 and created.headers["location"] == "/"
    with connect(settings) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM users WHERE email = 'valid@example.test'"
        ).fetchone()[0] == 1


def test_the_sign_in_redirect_names_the_account_meter_and_the_page_shows_the_minutes(world):
    settings, _, _, _, app = world
    with TestClient(app) as guesser:
        for number in range(LOGIN_ACCOUNT_LIMIT):
            response = guesser.post(
                "/login",
                data={"email": "member@example.test", "password": f"wrong-guess-{number}"},
                headers={"cf-connecting-ip": f"198.51.100.{number + 1}"},
                follow_redirects=False,
            )
            assert response.headers["location"] == "/login?error=invalid"
        refused = guesser.post(
            "/login",
            data={"email": "member@example.test", "password": PASSWORD},
            headers={"cf-connecting-ip": "203.0.113.60"},
            follow_redirects=False,
        )
        assert refused.headers["location"] == "/login?error=throttled_account&wait=15"
        page = guesser.get(refused.headers["location"])
        assert "Too many failed attempts for this account" in page.text
        assert "15 minutes" in page.text


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("abc", "15 minutes"), ("", "15 minutes"), ("0", "1 minute"), ("99", "15 minutes"), ("7", "7 minutes")],
)
def test_the_wait_query_value_is_clamped_to_one_to_fifteen_minutes(tmp_path: Path, raw, expected):
    settings = settings_for(tmp_path)
    migrate(settings)
    create_user(settings, "alpha@example.test", "Alpha", PASSWORD)
    with TestClient(create_app(settings)) as visitor:
        page = visitor.get(f"/login?error=throttled&wait={raw}")
    assert expected in page.text


def test_the_users_page_lists_pauses_with_release_buttons_and_says_when_there_are_none(world):
    settings, _, _, _, app = world
    administrator = administrator_browser(app)
    empty = administrator.get("/admin/users")
    assert "Nothing is paused right now." in empty.text
    assert "Release all" not in empty.text

    pause("token:203.0.113.70", LOGIN_ATTEMPT_LIMIT)
    one = administrator.get("/admin/users")
    assert "Nothing is paused right now." not in one.text
    assert "Guest links opened from the address 203.0.113.70" in one.text
    assert 'action="/admin/throttles/release"' in one.text
    assert 'name="key" value="token:203.0.113.70"' in one.text
    assert "Release all" not in one.text

    pause("setup-code:203.0.113.71", LOGIN_ATTEMPT_LIMIT)
    two = administrator.get("/admin/users")
    assert "Setup codes from the address 203.0.113.71" in two.text
    assert 'name="key" value="*"' in two.text
    assert "Release all" in two.text
