"""Error pages for browsers, JSON for everything else, the Content-Security-Policy
nonce, and the access log staying off in the entry point.  Fixtures follow
test_audit_auth.py."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from anamna import security
from anamna.db import migrate
from anamna.locales.messages import MESSAGES
from anamna.security import create_user
from anamna.web import app as app_module
from anamna.web.app import _content_security_policy, create_app

from test_web_security import PASSWORD, settings_for


#: The policy as it was sent before the nonce work; only script-src may change.
_POLICY_BEFORE_NONCE = (
    "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data:; connect-src 'self'; form-action 'self'; base-uri 'self'; "
    "frame-ancestors 'none'"
)


@pytest.fixture(autouse=True)
def fresh_meters():
    security._attempts.clear()
    yield
    security._attempts.clear()


def _settings(tmp_path: Path):
    settings = settings_for(tmp_path)
    migrate(settings)
    create_user(settings, "owner@example.test", "Owner", PASSWORD)
    create_user(settings, "member@example.test", "Member", PASSWORD)
    return settings


def _signed_in(settings, email: str) -> TestClient:
    client = TestClient(create_app(settings))
    response = client.post(
        "/login", data={"email": email, "password": PASSWORD}, follow_redirects=False,
    )
    assert response.status_code == 303
    client.cookies.set("anamna_lang", "en")
    return client


def _directives(policy: str) -> dict[str, str]:
    parts = [part.strip() for part in policy.split(";") if part.strip()]
    return {part.split()[0]: part for part in parts}


def test_browser_404_gets_an_html_error_page(tmp_path: Path):
    client = _signed_in(_settings(tmp_path), "owner@example.test")
    response = client.get("/no-such-page", headers={"Accept": "text/html"})
    assert response.status_code == 404
    assert response.headers["content-type"].startswith("text/html")
    assert MESSAGES["error.404"]["en"] in response.text
    assert 'href="/"' in response.text


def test_json_request_keeps_the_json_body(tmp_path: Path):
    client = _signed_in(_settings(tmp_path), "owner@example.test")
    response = client.get("/no-such-page", headers={"Accept": "application/json"})
    assert response.status_code == 404
    assert response.json() == {"detail": "Not Found"}


def test_api_path_gets_json_even_when_asked_for_html(tmp_path: Path):
    client = _signed_in(_settings(tmp_path), "owner@example.test")
    response = client.get("/api/no-such-thing", headers={"Accept": "text/html"})
    assert response.status_code == 404
    assert response.headers["content-type"].startswith("application/json")
    assert response.json() == {"detail": "Not Found"}


def test_script_request_with_html_accept_gets_json(tmp_path: Path):
    client = _signed_in(_settings(tmp_path), "owner@example.test")
    response = client.get(
        "/no-such-page", headers={"Accept": "text/html", "X-Requested-With": "fetch"},
    )
    assert response.status_code == 404
    assert response.json() == {"detail": "Not Found"}


def test_signed_out_browser_gets_the_error_page_too(tmp_path: Path):
    client = TestClient(create_app(_settings(tmp_path)))
    client.cookies.set("anamna_lang", "en")
    response = client.get("/no-such-page", headers={"Accept": "text/html"})
    assert response.status_code == 404
    assert MESSAGES["error.404"]["en"] in response.text
    assert 'href="/"' in response.text


def test_translated_403_detail_is_shown_on_the_page(tmp_path: Path):
    client = _signed_in(_settings(tmp_path), "member@example.test")
    response = client.get("/admin/tokens", headers={"Accept": "text/html"})
    assert response.status_code == 403
    assert MESSAGES["admin.forbidden"]["en"] in response.text


def test_403_for_a_script_stays_json(tmp_path: Path):
    client = _signed_in(_settings(tmp_path), "member@example.test")
    response = client.get("/admin/tokens", headers={"Accept": "application/json"})
    assert response.status_code == 403
    assert response.json() == {"detail": MESSAGES["admin.forbidden"]["en"]}


def test_401_still_redirects_a_signed_out_browser_to_sign_in(tmp_path: Path):
    client = TestClient(create_app(_settings(tmp_path)))
    response = client.get("/profile", headers={"Accept": "text/html"}, follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/login?next=/profile"


def test_content_security_policy_is_unchanged_until_strict_mode():
    assert _content_security_policy("abc", False) == _POLICY_BEFORE_NONCE


def test_strict_policy_swaps_unsafe_inline_for_the_nonce_only_in_script_src():
    strict = _directives(_content_security_policy("abc", True))
    before = _directives(_POLICY_BEFORE_NONCE)
    assert "'nonce-abc'" in strict["script-src"]
    assert "'unsafe-inline'" not in strict["script-src"]
    assert strict["style-src"] == before["style-src"]
    assert {k: v for k, v in strict.items() if k != "script-src"} == {
        k: v for k, v in before.items() if k != "script-src"
    }


def test_each_request_gets_its_own_nonce_in_strict_mode(tmp_path: Path, monkeypatch):
    settings = _settings(tmp_path)
    client = TestClient(create_app(settings))
    monkeypatch.setattr(app_module, "CSP_STRICT_SCRIPTS", False)
    assert "'nonce-" not in client.get("/login").headers["Content-Security-Policy"]
    monkeypatch.setattr(app_module, "CSP_STRICT_SCRIPTS", True)
    nonces = []
    for _ in range(2):
        policy = client.get("/login").headers["Content-Security-Policy"]
        match = re.search(r"'nonce-([A-Za-z0-9_-]+)'", policy)
        assert match is not None
        nonces.append(match.group(1))
    assert nonces[0] != nonces[1]


def test_entry_point_keeps_the_access_log_off(monkeypatch):
    calls = {}
    monkeypatch.setattr(app_module.uvicorn, "run", lambda *args, **kwargs: calls.update(kwargs))
    app_module.run()
    assert calls["access_log"] is False
