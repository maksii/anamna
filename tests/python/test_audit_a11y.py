"""Accessibility fixes that can be checked from the shipped source text.

Each test names the defect it guards; reverting the fix fails the test. The
behaviour itself (focus, announcements, keyboard walking) is not run here.
"""

from __future__ import annotations

import re

from anamna.i18n import JS_KEYS
from anamna.web.app import WEB_DIR

STATIC = WEB_DIR / "static"
TEMPLATES = WEB_DIR / "templates"


def _text(path) -> str:
    return path.read_text(encoding="utf-8")


def _tag(html: str, marker: str) -> str:
    """The opening tag that contains `marker`, for attribute checks."""
    match = re.search(r"<[a-z]+[^>]*" + re.escape(marker) + r"[^>]*>", html)
    assert match, f"no tag containing {marker!r}"
    return match.group(0)


def _rule(css: str, selector: str) -> str:
    """Declarations of the rule whose selector is exactly `selector`."""
    match = re.search(r"^" + re.escape(selector) + r"\s*\{([^}]*)\}", css, re.M)
    assert match, f"no rule for {selector!r}"
    return match.group(1)


def test_upload_queue_is_not_a_live_region() -> None:
    html = _text(TEMPLATES / "upload.html")
    # The list was re-read in full every poll; the summary line carries the news.
    assert "aria-live" not in _tag(html, 'id="an-queue"')
    assert 'role="status"' in _tag(html, 'id="an-queue-summary"')


def test_upload_progress_has_its_own_status_line() -> None:
    html = _text(TEMPLATES / "upload.html")
    status = _tag(html, 'id="an-upload-status"')
    assert 'role="status"' in status
    assert "visually-hidden" in status
    # The chosen-file line keeps its polite region; progress no longer writes there.
    assert 'aria-live="polite"' in _tag(html, 'id="an-upload-selected"')


def test_health_export_selection_and_empty_search_are_announced() -> None:
    html = _text(TEMPLATES / "health_export.html")
    assert 'role="status"' in _tag(html, "data-selected-count")
    assert 'role="status"' in _tag(html, "data-no-results")


def test_source_viewer_uses_aria_disabled_not_the_disabled_property() -> None:
    js = _text(STATIC / "source-viewer.js")
    assert "aria-disabled" in js
    assert ".disabled =" not in js


def test_source_viewer_announces_the_page_it_turned_to() -> None:
    html = _text(TEMPLATES / "_source_viewer.html")
    assert 'role="status"' in _tag(html, "data-page-status")


def test_viewer_disabled_look_applies_to_aria_disabled() -> None:
    css = _text(STATIC / "app.css")
    assert '.viewer-btn[aria-disabled="true"]' in css


def test_report_modal_textarea_keeps_its_focus_ring() -> None:
    declarations = _rule(_text(STATIC / "app.css"), ".an-report-modal textarea")
    assert "outline: 0" not in declarations
    assert "outline:0" not in declarations


def test_source_controls_meet_the_44px_target() -> None:
    assert "min-height: 44px" in _rule(_text(STATIC / "app.css"), ".an-source-controls button")


def test_index_status_text_is_ink_on_sunken_surface() -> None:
    assert "color: var(--ink)" in _rule(_text(STATIC / "app.css"), ".an-index-disclosure__status span")


def test_scrollable_tables_show_a_focus_ring() -> None:
    css = _text(STATIC / "app.css")
    assert ".table-wrap:focus-visible, .area-result-table-wrap:focus-visible, .an-scroll-x:focus-visible" in css


def test_announcement_strings_reach_the_browser() -> None:
    assert "chat.answer_ready" in JS_KEYS
    assert "upload.announce_done" in JS_KEYS


def test_nav_toggle_is_named_by_its_visible_word() -> None:
    html = _text(TEMPLATES / "base.html")
    # An aria-label replaced the visible "Menu" in the name, so voice control could not say it.
    assert "aria-label" not in _tag(html, 'class="nav-toggle"')
    # The visible word is the only copy of the name: a second one doubled it between 721 and 1100 px.
    summary = re.search(r'<summary class="nav-toggle">.*?</summary>', html, re.S)
    assert summary, "no nav-toggle summary"
    assert summary.group(0).count("{{ t('nav.menu') }}") == 1
    # At phone widths the word must stay in the accessibility tree, so no rule may hide it with display.
    css = _text(STATIC / "app.css")
    rules = [m for m in re.finditer(r"([^{}]*\.nav-toggle__text[^{}]*)\{([^}]*)\}", css)]
    assert rules, "no rule styles .nav-toggle__text"
    for rule in rules:
        assert not re.search(r"display\s*:\s*none", rule.group(2)), rule.group(1).strip()


def test_theme_buttons_are_named_like_their_titles() -> None:
    html = _text(TEMPLATES / "base.html")
    for variant in ("light", "dark", "system"):
        tag = _tag(html, f'name="theme" value="{variant}"')
        label = "{{ t('theme." + variant + "') }}"
        assert 'aria-label="' + label + '"' in tag
        assert 'title="' + label + '"' in tag


def test_language_buttons_declare_their_language_and_name_it() -> None:
    html = _text(TEMPLATES / "base.html")
    for code in ("en", "uk"):
        tag = _tag(html, f'name="lang" value="{code}"')
        assert f'lang="{code}"' in tag
        assert 'aria-label="{{ t(\'lang.' + code + "') }}: {{ t('lang." + code + "_full') }}\"" in tag


def test_auth_form_errors_are_described_by_their_alert() -> None:
    for name, error_id in (
        ("login.html", "login-error"),
        ("register.html", "register-error"),
        ("setup.html", "setup-error"),
    ):
        html = _text(TEMPLATES / name)
        assert f'id="{error_id}"' in html, name
        assert f'aria-describedby="{error_id}"' in html, name
        # Only while an error is shown: the attribute must not point at a missing id.
        assert '{% if error %} aria-describedby="' + error_id + '" aria-invalid="true"{% endif %}' in html, name


# Templates another agent is editing this round; their wrappers are reported by the lead, not checked here.
DEFERRED_TEMPLATES = (
    "chat.html",
    "plan_tests.html",
    "error.html",
    "upload.html",
    "_source_viewer.html",
)
TABLE_WRAPPER_CLASS = re.compile(r'class="[^"]*\b(?:table-wrap|area-result-table-wrap|an-scroll-x)\b[^"]*"')


def test_scrollable_table_wrappers_are_keyboard_reachable() -> None:
    unlabelled: list[str] = []
    for path in sorted(TEMPLATES.glob("*.html")):
        if path.name in DEFERRED_TEMPLATES:
            print(f"skipped (owned by another change): {path.name}")
            continue
        for tag in re.findall(r"<[a-zA-Z][^>]*>", _text(path)):
            if not TABLE_WRAPPER_CLASS.search(tag):
                continue
            missing = [attr for attr in ('tabindex="0"', 'role="region"', 'aria-label="') if attr not in tag]
            if missing:
                unlabelled.append(f"{path.name}: missing {', '.join(missing)} in {tag}")
    assert not unlabelled, "\n".join(unlabelled)


def test_labsync_phone_placeholder_is_translated() -> None:
    html = _text(TEMPLATES / "_labsync_profile.html")
    assert "+380 XX" not in html
    assert "labsync.phone_placeholder" in html
