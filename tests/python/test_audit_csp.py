"""Inline scripts carry the per-request nonce and no template carries an inline
event-handler attribute, so the strict policy (`script-src 'self' 'nonce-...'`,
see `CSP_STRICT_SCRIPTS` in web/app.py) can be switched on.

Static: every template.  Rendered: the pages listed below, under the policy
the switch sets (strict by default).  Fixtures follow test_audit_error_pages.py.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from anamna import security
from anamna.db import connect, migrate
from anamna.ingest.pipeline import ensure_concept
from anamna.security import create_user
from anamna.web import app as app_module
from anamna.web.app import create_app

from test_audit_sample_facts import add_observation
from test_web_panels import build
from test_web_security import PASSWORD, settings_for

TEMPLATES = Path(app_module.__file__).parent / "templates"

NONCE_ATTR = 'nonce="{{ csp_nonce }}"'
SCRIPT_TAG = re.compile(r"<script\b[^>]*>", re.IGNORECASE)
SCRIPT_BODY = re.compile(r"(<script\b[^>]*>)(.*?)(</script>)", re.IGNORECASE | re.DOTALL)
JINJA_COMMENT = re.compile(r"\{#.*?#\}", re.DOTALL)
TAG = re.compile(r"<[a-zA-Z][^>]*>")
HANDLER = re.compile(r"\son[a-z]+\s*=", re.IGNORECASE)
SRC = re.compile(r"\ssrc\s*=", re.IGNORECASE)
NONCE_IN_POLICY = re.compile(r"'nonce-([A-Za-z0-9_-]+)'")

#: (path, signed-in account) for pages whose markup this test checks.
PAGES = [
    ("/login", None),
    ("/", "owner@example.test"),
    ("/metrics", "owner@example.test"),
    ("/documents", "owner@example.test"),
    ("/upload", "owner@example.test"),
    ("/chat", "owner@example.test"),
    ("/plan-tests", "owner@example.test"),
    ("/vaccinations", "owner@example.test"),
    ("/devices", "owner@example.test"),
    ("/changes", "owner@example.test"),
    ("/admin/users", "owner@example.test"),
    ("/admin/ai", "owner@example.test"),
    ("/admin/tokens", "owner@example.test"),
    ("/profile", "owner@example.test"),
]


@pytest.fixture(autouse=True)
def fresh_meters():
    security._attempts.clear()
    yield
    security._attempts.clear()


def _settings(tmp_path: Path):
    settings = settings_for(tmp_path)
    migrate(settings)
    # The first account on an empty database is the administrator.
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


def _without_script_bodies(markup: str) -> str:
    """The markup with Jinja comments and script bodies removed, so only tags
    and their attributes are searched for handlers."""
    markup = JINJA_COMMENT.sub("", markup)
    return SCRIPT_BODY.sub(lambda m: m.group(1) + m.group(3), markup)


def _inline_handlers(markup: str) -> list[str]:
    return [tag for tag in TAG.findall(_without_script_bodies(markup)) if HANDLER.search(tag)]


def _template_files() -> list[Path]:
    return sorted(TEMPLATES.rglob("*.html"))


@pytest.mark.parametrize("path", _template_files(), ids=lambda p: p.name)
def test_inline_script_in_template_carries_the_nonce(path: Path):
    text = path.read_text(encoding="utf-8")
    for tag in SCRIPT_TAG.findall(text):
        if SRC.search(tag):
            continue
        assert NONCE_ATTR in tag, f"{path.name}: {tag}"


@pytest.mark.parametrize("path", _template_files(), ids=lambda p: p.name)
def test_template_has_no_inline_event_handler_attribute(path: Path):
    found = _inline_handlers(path.read_text(encoding="utf-8"))
    assert found == [], f"{path.name}: {found}"


def test_handler_scan_ignores_words_in_text_and_script_bodies():
    markup = (
        "<p>one once onboarding</p>"
        "<script>el.onclick = go; var one = 1;</script>"
        '<button data-x="1" onclick="go()">x</button>'
    )
    assert [HANDLER.search(t).group(0).strip() for t in _inline_handlers(markup)] == ["onclick="]


@pytest.mark.parametrize("path, email", PAGES, ids=lambda item: str(item))
def _assert_page_is_strict(response, path: str) -> None:
    policy = response.headers["Content-Security-Policy"]
    script_src = next(part for part in policy.split(";") if part.strip().startswith("script-src"))
    match = NONCE_IN_POLICY.search(script_src)
    assert match is not None, script_src
    assert "'unsafe-inline'" not in script_src
    nonce = match.group(1)

    body = response.text
    violations = []
    for tag in SCRIPT_TAG.findall(body):
        if SRC.search(tag):
            continue
        if f'nonce="{nonce}"' not in tag:
            violations.append(tag)
    violations += _inline_handlers(body)
    assert violations == [], f"{path}: {violations[:5]}"


@pytest.mark.parametrize("path, email", PAGES, ids=lambda item: str(item))
def test_rendered_page_under_strict_policy(tmp_path: Path, path, email):
    settings = _settings(tmp_path)
    client = TestClient(create_app(settings)) if email is None else _signed_in(settings, email)
    response = client.get(path, headers={"Accept": "text/html"})
    if response.status_code != 200 or not response.headers["content-type"].startswith("text/html"):
        pytest.skip(f"{path}: {response.status_code}, not a page")
    _assert_page_is_strict(response, path)


def test_rendered_metric_page_under_strict_policy(tmp_path: Path):
    # The metric page with a chart: two readings of one concept, so the chart
    # data and band scripts are rendered as well.
    settings, user_id, client = build(tmp_path)
    with connect(settings) as connection:
        concept_id, _ = ensure_concept(connection, "Blood glucose", None)
    add_observation(settings, user_id, concept_id, 5.0, "2024-06-01", "csp-glu-1")
    add_observation(settings, user_id, concept_id, 5.4, "2025-06-01", "csp-glu-2")
    response = client.get(f"/metrics/{concept_id}", headers={"Accept": "text/html"})
    assert response.status_code == 200
    assert 'id="chart-data"' in response.text
    _assert_page_is_strict(response, f"/metrics/{concept_id}")
