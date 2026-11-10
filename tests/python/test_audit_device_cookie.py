"""The device cookie: a browser that has signed in to an account before is counted
on its own meter, so guessing from elsewhere cannot lock the owner's browser out.
Fixtures follow test_audit_auth.py."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from anamna import security
from anamna.db import migrate
from anamna.security import (
    DEVICE_COOKIE,
    LOGIN_ACCOUNT_LIMIT,
    create_user,
    device_cookie_nonce,
    device_cookie_value,
)
from anamna.web.app import create_app

from test_web_security import PASSWORD, settings_for


_THROTTLED_ACCOUNT = "/login?error=throttled_account&wait=15"
_THROTTLED_DEVICE = "/login?error=throttled_device&wait=15"
_INVALID = "/login?error=invalid"
_EMAIL = "owner@example.test"


@pytest.fixture(autouse=True)
def fresh_meters():
    security._attempts.clear()
    yield
    security._attempts.clear()


def _settings(tmp_path: Path):
    settings = settings_for(tmp_path)
    migrate(settings)
    create_user(settings, _EMAIL, "Owner", PASSWORD)
    return settings


def _login(client: TestClient, email: str, password: str, **headers):
    return client.post(
        "/login",
        data={"email": email, "password": password},
        headers=headers,
        follow_redirects=False,
    )


def _fresh_client(settings) -> TestClient:
    return TestClient(create_app(settings))


def test_device_cookie_accepts_only_its_own_value(tmp_path: Path):
    settings = _settings(tmp_path)
    value = device_cookie_value(settings, _EMAIL)
    nonce = device_cookie_nonce(settings, _EMAIL, value)
    assert nonce is not None
    assert value.startswith(nonce + ".")
    # The address is normalised the way the sign-in form normalises it.
    assert device_cookie_nonce(settings, "  Owner@Example.test ", value) == nonce
    assert device_cookie_nonce(settings, "other@example.test", value) is None
    nonce_part, _, mac = value.partition(".")
    tampered = nonce_part + "." + ("0" if mac[0] != "0" else "1") + mac[1:]
    assert device_cookie_nonce(settings, _EMAIL, tampered) is None
    for garbage in (None, "", "no-dot", "a.b", "x" * 300, "é.é", "....", "abc.def"):
        assert device_cookie_nonce(settings, _EMAIL, garbage) is None


def test_successful_sign_in_sets_an_http_only_device_cookie(tmp_path: Path):
    settings = _settings(tmp_path)
    client = _fresh_client(settings)
    response = _login(client, _EMAIL, PASSWORD)
    assert response.headers["location"] == "/"
    cookies = [
        header for header in response.headers.get_list("set-cookie")
        if header.startswith(DEVICE_COOKIE + "=")
    ]
    assert len(cookies) == 1
    assert "httponly" in cookies[0].lower()
    assert "samesite=lax" in cookies[0].lower()
    assert "max-age=31536000" in cookies[0].lower()
    assert device_cookie_nonce(settings, _EMAIL, client.cookies.get(DEVICE_COOKIE)) is not None


def test_cookie_less_guessing_locks_the_account_but_not_the_owners_browser(tmp_path: Path):
    settings = _settings(tmp_path)
    owner_browser = _fresh_client(settings)
    assert _login(owner_browser, _EMAIL, PASSWORD).headers["location"] == "/"

    attacker = _fresh_client(settings)
    for number in range(LOGIN_ACCOUNT_LIMIT):
        response = _login(
            attacker, _EMAIL, f"wrong-guess-{number}",
            **{"cf-connecting-ip": f"198.51.100.{number + 1}"},
        )
        assert response.headers["location"] == _INVALID

    # A browser with no cookie is refused even with the right password.
    response = _login(
        _fresh_client(settings), _EMAIL, PASSWORD, **{"cf-connecting-ip": "203.0.113.9"},
    )
    assert response.headers["location"] == _THROTTLED_ACCOUNT

    # The owner's browser, holding the cookie from the earlier sign-in, is not.
    assert _login(owner_browser, _EMAIL, PASSWORD).headers["location"] == "/"


def test_guesses_sent_with_a_device_cookie_count_only_on_that_device(tmp_path: Path):
    settings = _settings(tmp_path)
    owner_browser = _fresh_client(settings)
    assert _login(owner_browser, _EMAIL, PASSWORD).headers["location"] == "/"

    guesser = _fresh_client(settings)
    guesser.cookies.set(DEVICE_COOKIE, owner_browser.cookies.get(DEVICE_COOKIE))
    for number in range(LOGIN_ACCOUNT_LIMIT):
        assert _login(guesser, _EMAIL, f"wrong-guess-{number}").headers["location"] == _INVALID
    assert _login(guesser, _EMAIL, PASSWORD).headers["location"] == _THROTTLED_DEVICE

    # Those failures never reached the shared account meter, so a cookie-less
    # browser is still free to try, and to sign in with the right password.
    stranger = _fresh_client(settings)
    assert _login(stranger, _EMAIL, "wrong-guess-stranger").headers["location"] == _INVALID
    assert _login(stranger, _EMAIL, PASSWORD).headers["location"] == "/"


def test_forged_device_cookie_is_treated_as_no_cookie(tmp_path: Path):
    settings = _settings(tmp_path)
    forged = "x" * 22 + "." + "0" * 64
    attacker = _fresh_client(settings)
    attacker.cookies.set(DEVICE_COOKIE, forged)
    # A forged cookie gets no private meter, so its failures count on the shared
    # account meter like any other browser's.
    for number in range(LOGIN_ACCOUNT_LIMIT):
        response = _login(
            attacker, _EMAIL, f"wrong-guess-{number}",
            **{"cf-connecting-ip": f"192.0.2.{number + 1}"},
        )
        assert response.headers["location"] == _INVALID
    response = _login(
        _fresh_client(settings), _EMAIL, PASSWORD, **{"cf-connecting-ip": "203.0.113.9"},
    )
    assert response.headers["location"] == _THROTTLED_ACCOUNT
