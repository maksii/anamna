"""Sign-in meters, cross-site form posts, upload and webhook body limits, and
the response-level settings: OpenAPI off, compression on, HSTS when TLS is
declared upstream.  Fixtures follow test_web_security.py."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from anamna import security
from anamna.config import Settings
from anamna.db import migrate
from anamna.security import LOGIN_ACCOUNT_LIMIT, LOGIN_ATTEMPT_LIMIT, create_user
from anamna.web import app as app_module
from anamna.web.app import create_app

from test_web_security import PASSWORD, settings_for


_THROTTLED = "/login?error=throttled&wait=15"
_THROTTLED_ACCOUNT = "/login?error=throttled_account&wait=15"


@pytest.fixture(autouse=True)
def fresh_meters():
    security._attempts.clear()
    yield
    security._attempts.clear()


def _login(client: TestClient, email: str, password: str, **headers):
    return client.post(
        "/login",
        data={"email": email, "password": password},
        headers=headers,
        follow_redirects=False,
    )


def _signed_in_client(settings: Settings, email: str) -> TestClient:
    client = TestClient(create_app(settings))
    response = _login(client, email, PASSWORD)
    assert response.status_code == 303
    return client


def test_account_meter_holds_when_guesses_come_from_many_addresses(tmp_path: Path):
    settings = settings_for(tmp_path)
    migrate(settings)
    create_user(settings, "victim@example.test", "Victim", PASSWORD)
    with TestClient(create_app(settings)) as client:
        for number in range(LOGIN_ACCOUNT_LIMIT):
            response = _login(
                client, "victim@example.test", f"wrong-guess-{number}",
                **{"cf-connecting-ip": f"198.51.100.{number + 1}"},
            )
            assert response.headers["location"] == "/login?error=invalid"
        response = _login(
            client, "victim@example.test", PASSWORD, **{"cf-connecting-ip": "203.0.113.9"},
        )
        assert response.status_code == 303
        assert response.headers["location"] == _THROTTLED_ACCOUNT


def test_successful_sign_in_to_another_account_does_not_reset_the_address_meter(tmp_path: Path):
    settings = settings_for(tmp_path)
    migrate(settings)
    create_user(settings, "target@example.test", "Target", PASSWORD)
    create_user(settings, "other@example.test", "Other", PASSWORD)
    address = {"cf-connecting-ip": "192.0.2.50"}
    with TestClient(create_app(settings)) as client:
        for number in range(LOGIN_ATTEMPT_LIMIT - 1):
            response = _login(client, "target@example.test", f"wrong-guess-{number}", **address)
            assert response.headers["location"] == "/login?error=invalid"
        response = _login(client, "other@example.test", PASSWORD, **address)
        assert response.headers["location"] == "/"
        response = _login(client, "target@example.test", "wrong-guess-last", **address)
        assert response.headers["location"] == "/login?error=invalid"
        response = _login(client, "target@example.test", "wrong-guess-after", **address)
        assert response.headers["location"] == _THROTTLED


def test_webhook_failures_do_not_lock_sign_in(tmp_path: Path):
    settings = settings_for(tmp_path)
    migrate(settings)
    create_user(settings, "owner@example.test", "Owner", PASSWORD)
    with TestClient(create_app(settings)) as client:
        for _ in range(12):
            client.get("/integrations/oura/webhook?verification_token=wrong")
        response = _login(client, "owner@example.test", PASSWORD)
        assert response.status_code == 303
        assert response.headers["location"] == "/"


def test_cross_site_post_to_a_pre_auth_form_is_refused(tmp_path: Path):
    settings = settings_for(tmp_path)
    migrate(settings)
    create_user(settings, "owner@example.test", "Owner", PASSWORD)
    with TestClient(create_app(settings)) as client:
        refused = _login(
            client, "owner@example.test", PASSWORD, **{"sec-fetch-site": "cross-site"},
        )
        assert refused.status_code == 403
        accepted = _login(
            client, "owner@example.test", PASSWORD, **{"sec-fetch-site": "same-origin"},
        )
        assert accepted.status_code == 303
        assert accepted.headers["location"] == "/"


def test_anonymous_upload_is_redirected_before_the_body_is_read(tmp_path: Path):
    settings = settings_for(tmp_path)
    migrate(settings)
    create_user(settings, "owner@example.test", "Owner", PASSWORD)
    with TestClient(create_app(settings)) as client:
        response = client.post(
            "/upload",
            files={"file": ("note.txt", b"anonymous", "text/plain")},
            follow_redirects=False,
        )
    assert response.status_code == 303
    assert response.headers["location"].startswith("/login")
    assert not any(settings.source_dir.rglob("*"))


def test_signed_in_upload_declaring_more_than_the_limit_is_refused(tmp_path: Path):
    settings = settings_for(tmp_path)
    migrate(settings)
    create_user(settings, "owner@example.test", "Owner", PASSWORD)
    with _signed_in_client(settings, "owner@example.test") as client:
        response = client.post(
            "/upload",
            content=b"x",
            headers={
                "content-length": str(app_module.MAX_ARCHIVE_UPLOAD_BYTES + 2 * 1024 * 1024),
                "content-type": "multipart/form-data; boundary=x",
            },
        )
    assert response.status_code == 413


def test_oversized_refuses_a_missing_or_unbounded_declared_length():
    class FakeRequest:
        def __init__(self, headers: dict[str, str]):
            self.headers = headers

    assert app_module._oversized(FakeRequest({}), 5) is True
    assert app_module._oversized(FakeRequest({"content-length": "abc"}), 5) is True
    assert app_module._oversized(FakeRequest({"content-length": "10"}), 5) is True
    assert app_module._oversized(FakeRequest({"content-length": "5"}), 5) is False


def test_openapi_document_is_not_published(tmp_path: Path):
    settings = settings_for(tmp_path)
    migrate(settings)
    create_user(settings, "owner@example.test", "Owner", PASSWORD)
    with TestClient(create_app(settings)) as client:
        assert client.get("/openapi.json").status_code == 404


def test_signed_in_pages_are_compressed_when_the_client_accepts_gzip(tmp_path: Path):
    settings = settings_for(tmp_path)
    migrate(settings)
    create_user(settings, "owner@example.test", "Owner", PASSWORD)
    with _signed_in_client(settings, "owner@example.test") as client:
        response = client.get("/", headers={"accept-encoding": "gzip"})
    assert response.status_code == 200
    assert response.headers["content-encoding"] == "gzip"


def test_hsts_follows_tls_declared_upstream(tmp_path: Path):
    sources = tmp_path / "sources"
    sources.mkdir()
    settings = Settings(
        database_path=tmp_path / "health.sqlite3",
        source_dir=sources,
        secret_key="test-secret",
        session_days=1,
        secure_cookies=True,
    )
    migrate(settings)
    create_user(settings, "owner@example.test", "Owner", PASSWORD)
    with TestClient(create_app(settings)) as client:
        response = client.get("/login")
    assert "strict-transport-security" in response.headers


def test_hsts_is_not_sent_over_plain_http_without_declared_tls(tmp_path: Path):
    settings = settings_for(tmp_path)
    migrate(settings)
    create_user(settings, "owner@example.test", "Owner", PASSWORD)
    with TestClient(create_app(settings)) as client:
        response = client.get("/login")
    assert "strict-transport-security" not in response.headers
