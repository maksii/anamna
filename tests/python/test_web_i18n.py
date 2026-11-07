from __future__ import annotations

import re

from fastapi.testclient import TestClient

from anamna.config import Settings
from anamna.db import migrate
from anamna.security import create_session, create_user
from anamna.web.app import create_app


def _client(tmp_path):
    settings = Settings(tmp_path / "health.sqlite3", tmp_path / "sources", "i18n-test-secret")
    (tmp_path / "sources").mkdir(exist_ok=True)
    migrate(settings)
    try:
        user_id = create_user(settings, "i18n@test.local", "I18N User", "password12345")
    except Exception:
        from anamna.db import connect

        with connect(settings) as connection:
            user_id = connection.execute("SELECT id FROM users LIMIT 1").fetchone()["id"]
    app = create_app(settings)
    client = TestClient(app)
    token, _ = create_session(settings, user_id)
    client.cookies.set("anamna_session", token)
    return client


def test_authenticated_pages_switch_language(tmp_path):
    client = _client(tmp_path)
    client.cookies.set("anamna_lang", "en")
    english = client.get("/").text
    assert "Health record" in english
    assert "Anamna" in english
    assert "Медична картка" not in english

    switched = client.post("/locale", data={"lang": "uk", "next": "/"}, follow_redirects=False)
    assert switched.status_code == 303
    client.cookies.set("anamna_lang", "uk")
    ukrainian = client.get("/").text
    assert "Медична картка" in ukrainian
    assert "Anamna" in ukrainian
    assert ">Home<" not in ukrainian
    assert ">Find results<" not in ukrainian
    assert ">Sign out<" not in ukrainian


def test_login_page_is_fully_localized(tmp_path):
    settings = Settings(tmp_path / "health.sqlite3", tmp_path / "sources", "i18n-test-secret")
    (tmp_path / "sources").mkdir(exist_ok=True)
    migrate(settings)
    # The sign-in page exists once the server is set up; an empty database
    # leads to /setup instead (test_web_setup).
    create_user(settings, "i18n@test.local", "I18N User", "password12345")
    app = create_app(settings)
    client = TestClient(app)
    client.cookies.set("anamna_lang", "uk")
    body = client.get("/login").text
    assert "Увійти" in body
    assert "Anamna" in body
    assert "Open my record" not in body
    assert "Sign in" not in body


def test_body_system_page_is_dedicated_owned_and_localized(tmp_path):
    client = _client(tmp_path)
    client.cookies.set("anamna_lang", "en")
    english = client.get("/areas/spine")
    assert english.status_code == 200
    assert "Bones &amp; spine" in english.text
    assert "Clinical conclusions and assessments" in english.text
    assert client.get("/areas/not-a-real-area").status_code == 404

    client.cookies.set("anamna_lang", "uk")
    ukrainian = client.get("/areas/spine")
    assert ukrainian.status_code == 200
    assert "Кістки та хребет" in ukrainian.text
    assert "Клінічні висновки та оцінки" in ukrainian.text
    assert "Clinical conclusions and assessments" not in ukrainian.text


def _csrf(client) -> str:
    """The token the real form submits, read back out of the rendered page."""
    match = re.search(r'name="csrf_token" value="([^"]+)"', client.get("/").text)
    assert match, "no csrf token on the page"
    return match.group(1)


def test_theme_choice_is_pinned_and_reversible(tmp_path):
    """An explicit theme must win over the operating system preference."""
    client = _client(tmp_path)
    token = _csrf(client)

    # No cookie: follow the system, and let CSS decide from the media query.
    assert 'data-theme="system"' in client.get("/").text

    switched = client.post(
        "/theme", data={"theme": "dark", "next": "/", "csrf_token": token},
        follow_redirects=False,
    )
    assert switched.status_code == 303
    body = client.get("/").text
    assert 'data-theme="dark"' in body
    assert "color-scheme: dark" in body

    client.post(
        "/theme", data={"theme": "light", "next": "/", "csrf_token": token},
        follow_redirects=False,
    )
    assert 'data-theme="light"' in client.get("/").text

    # Back to the system setting clears the pin rather than storing a third value.
    client.post(
        "/theme", data={"theme": "system", "next": "/", "csrf_token": token},
        follow_redirects=False,
    )
    assert 'data-theme="system"' in client.get("/").text


def test_theme_route_is_csrf_protected(tmp_path):
    client = _client(tmp_path)
    refused = client.post(
        "/theme", data={"theme": "dark", "next": "/"}, follow_redirects=False
    )
    assert refused.status_code == 403
    assert 'data-theme="system"' in client.get("/").text


def test_theme_route_rejects_junk_and_offsite_redirects(tmp_path):
    client = _client(tmp_path)
    token = _csrf(client)
    client.post(
        "/theme", data={"theme": "../evil", "next": "/", "csrf_token": token},
        follow_redirects=False,
    )
    assert 'data-theme="system"' in client.get("/").text
    away = client.post(
        "/theme",
        data={"theme": "dark", "next": "https://example.com/", "csrf_token": token},
        follow_redirects=False,
    )
    assert away.headers["location"].startswith("/")
