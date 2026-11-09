"""Global chrome: static delivery, transform-proof HTML, skip link, AI opener, sign-in page."""

from __future__ import annotations

import re
from pathlib import Path

from fastapi.testclient import TestClient

from anamna.security import set_open_registration
from anamna.web.app import WEB_DIR, asset, create_app

from test_web_panels import build


def test_a_versioned_asset_is_immutable_and_sets_no_cookie(tmp_path: Path):
    _settings, _user_id, client = build(tmp_path)
    client.cookies.clear()  # an anonymous first visit: no language chosen yet
    response = client.get(asset("app.css"))
    assert response.status_code == 200
    assert response.headers["cache-control"] == "public, max-age=31536000, immutable, no-transform"
    # Cloudflare never caches a response that sets a cookie (PERF-05).
    assert "set-cookie" not in response.headers


def test_an_unversioned_or_stale_asset_gets_a_short_cache(tmp_path: Path):
    _settings, _user_id, client = build(tmp_path)
    for url in ("/static/app.css", "/static/app.css?v=1"):
        response = client.get(url)
        assert response.status_code == 200, url
        assert response.headers["cache-control"] == "public, max-age=300, no-transform", url
        assert "set-cookie" not in response.headers, url
    traversal = client.get("/static/..%2F..%2Fapp.py?v=1")
    assert "immutable" not in traversal.headers.get("cache-control", "")


def test_html_forbids_edge_rewriting(tmp_path: Path):
    """no-transform keeps Cloudflare from injecting its beacon and rewriting
    e-mail addresses (UX-28, OPS-32)."""
    _settings, _user_id, client = build(tmp_path)
    for path in ("/", "/documents", "/profile"):
        assert client.get(path).headers["cache-control"] == "private, no-store, no-transform", path
    client.cookies.clear()
    assert "no-transform" in client.get("/login").headers["cache-control"]


def test_skip_link_lands_focus_inside_main(tmp_path: Path):
    _settings, _user_id, client = build(tmp_path)
    html = client.get("/").text
    assert 'href="#main"' in html
    assert re.search(r'<main id="main" tabindex="-1"', html)


def test_ai_opener_has_a_place_at_every_width_and_keeps_its_verb(tmp_path: Path):
    _settings, _user_id, client = build(tmp_path)
    html = client.get("/").text
    openers = re.findall(r'<button class="ai-opener ([\w-]+)"[^>]*data-ai-open', html)
    assert sorted(openers) == ["account-panel__ai", "ai-header"]
    # Every placement prints the full verb, never the bare "AI" badge.
    labels = re.findall(r'<span class="ai-opener__text">([^<]+)</span>', html)
    assert labels == ["Copy for AI"] * 2
    # Both live in the header; none in <main>, where the wide-screen dock
    # used to cost every page an empty 60px band above its first line.
    header = html[html.index('<header class="topbar">'): html.index("</header>")]
    assert header.count("data-ai-open") == 2
    main = html[html.index('<main id="main"'): html.index("</main>")]
    assert "data-ai-open" not in main and "ai-dock" not in main
    # The header row shows it at every width, a phone included (in the sheet
    # alone it went unfound until the phone was turned sideways); the sheet's
    # copy stays hidden, and on a phone the logo stands for the wordmark.
    css = (WEB_DIR / "static" / "app.css").read_text(encoding="utf-8")
    assert ".topbar .ai-header { display: inline-flex; }" in css
    assert ".account-panel .account-panel__ai { display: none; }" in css
    phone = css[css.index("@media (max-width: 720px) {\n\n  .shell"):]
    phone = phone[: phone.index("\n}\n")]
    assert ".topbar .ai-header { display: none; }" not in phone
    assert ".account-panel__ai { display: flex" not in phone
    assert ".topbar:has(.ai-header) .brand > span:last-child { display: none; }" in phone
    assert ".ai-dock" not in css


def test_account_email_is_shielded_from_obfuscation(tmp_path: Path):
    _settings, _user_id, client = build(tmp_path)
    html = client.get("/").text
    assert "<!--email_off-->panels@example.test<!--/email_off-->" in html


def test_stylesheet_never_capitalises_data_or_fades_state_glyphs():
    css = (WEB_DIR / "static" / "app.css").read_text(encoding="utf-8")
    # "185 См", "Дата Невідома": capitalize corrupts units and Ukrainian (UX-16).
    assert "text-transform: capitalize" not in css
    inactive = re.search(r"\.an-state-slot\.is-inactive \{[^}]*\}", css).group(0)
    assert "opacity" not in inactive  # .62 took the glyph under 3:1 (UX-13)
    # Labels shown wherever the strip is too narrow for them inline: every
    # phone and a three-up desktop card, not only below a viewport width.
    narrow = css[css.index("@container (width < 28rem)"):]
    narrow = narrow[: narrow.index("\n}\n")]
    assert "white-space: normal" in narrow and "clip: auto" in narrow


def _anonymous(tmp_path: Path, open_registration: bool) -> TestClient:
    settings, _user_id, _client = build(tmp_path)
    set_open_registration(settings, open_registration)
    return TestClient(create_app(settings))


def test_sign_in_page_names_the_task_and_points_to_recovery(tmp_path: Path):
    client = _anonymous(tmp_path, open_registration=False)
    for locale, h1, forgot in (("en", "Sign in", "Forgot your password?"), ("uk", "Увійти", "Забули пароль?")):
        client.cookies.set("anamna_lang", locale)
        html = client.get("/login").text
        assert re.findall(r"<h1>([^<]+)</h1>", html) == [h1], locale
        assert forgot in html
        assert 'class="login-story"' not in html  # sign-in is the form alone, no explainer panel
        assert "user-bound" not in html and "прив’язані" not in html  # no developer sentence
    client.cookies.set("anamna_lang", "en")
    closed = client.get("/login?error=closed").text
    assert closed.count("Sign-up is closed on this server") == 1
    # ?error= is a code, never free text printed into the alert.
    assert "Call 0800" not in client.get("/login?error=Call%200800%20now").text


def test_register_page_heading_is_the_task(tmp_path: Path):
    client = _anonymous(tmp_path, open_registration=True)
    client.cookies.set("anamna_lang", "en")
    html = client.get("/register").text
    assert re.findall(r"<h1>([^<]+)</h1>", html) == ["Create your account"]


def test_a_first_visit_is_in_ukrainian_and_only_a_choice_is_remembered(tmp_path: Path, monkeypatch):
    """The audience is Ukrainian: a visitor who never picked a language gets
    «uk», and no cookie pins that default, so it is not mistaken for a choice."""
    from anamna import i18n
    from anamna.web import app as app_module

    assert i18n.VISITOR_LOCALE == "uk"
    monkeypatch.setattr(app_module, "VISITOR_LOCALE", i18n.VISITOR_LOCALE)  # undo conftest's English
    _settings, _user_id, client = build(tmp_path)
    client.cookies.clear()
    first = client.get("/login")
    assert '<html lang="uk"' in first.text
    assert "anamna_lang" not in first.headers.get("set-cookie", "")
    chosen = client.get("/login?lang=en")
    assert '<html lang="en"' in chosen.text
    assert "anamna_lang=en" in chosen.headers["set-cookie"]
    assert '<html lang="en"' in client.get("/login").text, "the choice sticks"
