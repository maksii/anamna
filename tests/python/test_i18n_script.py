"""The interface strings reach the browser as one cacheable script per locale.

Before, every page carried them inline (15 KB, rebuilt on each request). Now a
page links `/i18n/<locale>.js?v=<content hash>`: the browser fetches it once,
and a new version of the strings gets a new name.
"""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path

from fastapi.testclient import TestClient

from anamna.i18n import JS_KEYS
from anamna.security import create_access_token
from anamna.web.app import create_app

from test_web_panels import build

IMMUTABLE = "public, max-age=31536000, immutable, no-transform"
BRIEF = "public, max-age=300, no-transform"


def _script_body(client: TestClient, path: str) -> str:
    response = client.get(path)
    assert response.status_code == 200
    return response.text


def test_pages_load_their_strings_from_a_cacheable_script(tmp_path: Path):
    settings, _, client = build(tmp_path)
    page = client.get("/").text
    assert '<script src="/i18n/en.js?v=' in page
    assert "window.__HL_I18N__=" not in page
    src = re.search(r'<script src="(/i18n/en\.js\?v=[0-9a-f]{16})"', page).group(1)
    response = client.get(src)
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/javascript")
    assert response.text.startswith("window.__HL_I18N__={")
    assert '"_formats"' in response.text
    assert 'window.__HL_LOCALE__="en-GB";' in response.text
    assert response.headers["cache-control"] == IMMUTABLE
    assert "set-cookie" not in response.headers


def test_a_stale_or_missing_version_is_cached_briefly(tmp_path: Path):
    settings, _, _ = build(tmp_path)
    anonymous = TestClient(create_app(settings))
    for path in ("/i18n/en.js", "/i18n/en.js?v=old"):
        response = anonymous.get(path)
        assert response.status_code == 200
        assert response.headers["cache-control"] == BRIEF


def test_the_ukrainian_script_is_its_own_file(tmp_path: Path):
    settings, _, _ = build(tmp_path)
    body = _script_body(TestClient(create_app(settings)), "/i18n/uk.js")
    assert 'window.__HL_LOCALE__="uk-UA";' in body
    payload = json.loads(body.split("window.__HL_I18N__=", 1)[1].split(";window.__HL_LOCALE__", 1)[0])
    assert set(payload) == set(JS_KEYS) | {"_formats"}
    assert payload["_formats"]["decimal"] == ","


def test_unknown_names_are_not_found(tmp_path: Path):
    settings, _, _ = build(tmp_path)
    anonymous = TestClient(create_app(settings))
    for path in ("/i18n/xx.js", "/i18n/en", "/i18n/en.css"):
        assert anonymous.get(path).status_code == 404, path


def test_the_script_needs_no_session(tmp_path: Path):
    settings, _, _ = build(tmp_path)
    anonymous = TestClient(create_app(settings))
    assert anonymous.get("/i18n/en.js").status_code == 200
    login = anonymous.get("/login")
    assert login.status_code == 200
    assert '<script src="/i18n/' in login.text


def test_a_guest_link_can_load_the_script(tmp_path: Path):
    settings, owner, _ = build(tmp_path)
    expires = (datetime.now(UTC) + timedelta(days=14)).replace(microsecond=0).isoformat()
    _, secret = create_access_token(settings, owner, kind="guest", label="visitor", expires_at=expires)
    with TestClient(create_app(settings)) as guest:
        opened = guest.get(f"/t/{secret}", follow_redirects=False)
        assert opened.status_code in (302, 303)
        # Before the script joined the guest allowlist this answered 403.
        assert guest.get("/i18n/en.js").status_code == 200
