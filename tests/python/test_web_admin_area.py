"""The administration area as one place: its front door, its tab strip and the
single account-menu link that leads into it.

Every administration page carries the same strip, and every administration
template must include it, so a page added later without the strip fails here.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from anamna.web.app import create_app

from test_web_admin import sign_in, two_people

ADMIN_PAGES = [
    "/admin/users",
    "/admin/tokens",
    "/admin/ai",
    "/admin/paperless",
    "/admin/openwearables",
    "/admin/telegram",
    "/admin/lab-connections",
]

TEMPLATES = Path(__file__).resolve().parents[2] / "src" / "anamna" / "web" / "templates"
TAB_STRIP_INCLUDE = '{% include "_admin_tabs.html" %}'


def test_admin_home_redirects_to_people(tmp_path: Path):
    settings, _admin, _member = two_people(tmp_path)
    with TestClient(create_app(settings)) as client:
        sign_in(client, "admin@example.test")
        response = client.get("/admin", follow_redirects=False)
        assert response.status_code == 303
        assert response.headers["location"] == "/admin/users"


def test_admin_home_refuses_a_member(tmp_path: Path):
    settings, _admin, _member = two_people(tmp_path)
    with TestClient(create_app(settings)) as client:
        sign_in(client, "member@example.test")
        assert client.get("/admin", follow_redirects=False).status_code == 403


def test_admin_home_sends_a_stranger_to_sign_in(tmp_path: Path):
    settings, _admin, _member = two_people(tmp_path)
    with TestClient(create_app(settings)) as client:
        # Same rule as /admin/users: a stranger is sent to sign in, never shown the area.
        anonymous = client.get("/admin", follow_redirects=False)
        assert anonymous.status_code == 303
        assert anonymous.headers["location"].startswith("/login")


@pytest.mark.parametrize("path", ADMIN_PAGES)
def test_every_admin_page_carries_the_tab_strip(tmp_path: Path, path: str):
    settings, _admin, _member = two_people(tmp_path)
    with TestClient(create_app(settings)) as client:
        sign_in(client, "admin@example.test")
        response = client.get(path)
        assert response.status_code == 200, path
        body = response.text

        strip = re.search(r'<nav class="tabs an-admin-tabs".*?</nav>', body, re.S)
        assert strip is not None, path
        nav = strip.group(0)
        for target in ADMIN_PAGES:
            assert f'href="{target}"' in nav, (path, target)

        current = [
            href
            for href, attributes in re.findall(r'<a href="([^"]+)"([^>]*)>', nav)
            if "aria-current" in attributes
        ]
        assert current == [path], path


def test_account_menu_has_one_administration_link(tmp_path: Path):
    settings, _admin, _member = two_people(tmp_path)
    with TestClient(create_app(settings)) as client:
        sign_in(client, "admin@example.test")
        body = client.get("/").text
    panel = re.search(r'<div class="account-panel">.*?</details>', body, re.S)
    assert panel is not None
    assert panel.group(0).count('href="/admin"') == 1
    assert 'href="/admin/' not in panel.group(0)


def test_account_menu_has_no_administration_link_for_a_member(tmp_path: Path):
    settings, _admin, _member = two_people(tmp_path)
    with TestClient(create_app(settings)) as client:
        sign_in(client, "member@example.test")
        body = client.get("/").text
    panel = re.search(r'<div class="account-panel">.*?</details>', body, re.S)
    assert panel is not None
    assert 'href="/admin' not in panel.group(0)


def test_admin_templates_all_include_the_tab_strip():
    templates = sorted(TEMPLATES.glob("admin_*.html"))
    assert templates, TEMPLATES
    missing = [path.name for path in templates if TAB_STRIP_INCLUDE not in path.read_text(encoding="utf-8")]
    assert missing == []
