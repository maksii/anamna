"""Text-level checks on the templates changed in the first-run and AI-review pass.

They read the template source and compile each template with the app's Jinja
environment. No server or database is needed: an unbalanced ``{% if %}`` fails
at compile time, and a missing message key fails the catalogue check.
"""

from __future__ import annotations

import re
from pathlib import Path

from anamna.i18n import MESSAGES
from anamna.web.app import templates

TEMPLATES = Path(__file__).resolve().parents[2] / "src" / "anamna" / "web" / "templates"

EDITED = [
    "dashboard.html",
    "document_detail.html",
    "_plan_special.html",
    "genetics.html",
    "base.html",
    "_labsync_profile.html",
    "admin_ai.html",
    "profile.html",
    "upload.html",
    "_correlation.html",
]

# Literal keys only. A key built with `~` or `+` (for example
# t('special.' ~ entry)) names no single catalogue entry, so it is skipped.
KEY_PATTERN = re.compile(r"(?<![A-Za-z])(t|t_plural|plural_t)\('([a-z0-9_.\-]+)'(?!\s*[~+])")
PLURAL_FORMS = ("one", "few", "many")

FORM_PATTERN = re.compile(r"<form\b[^>]*>.*?</form>", re.DOTALL)


def _read(name: str) -> str:
    return (TEMPLATES / name).read_text(encoding="utf-8")


def test_ai_suggested_marks_exactly_the_ai_forms() -> None:
    # Three forms carry the flag: the two that store an AI-proposed value and
    # the pre-existing correction form on an observation. The person's own
    # manual-entry forms must not carry it.
    text = _read("document_detail.html")
    flagged = [form for form in FORM_PATTERN.findall(text) if 'name="ai_suggested"' in form]
    actions = {re.search(r'action="([^"]+)"', form).group(1) for form in flagged}
    assert len(flagged) == 3
    assert actions == {
        "/documents/{{ document.id }}/observations",
        "/vaccinations",
        "/observations/{{ item.observation_id }}",
    }


def test_genetics_once_line_is_conditional() -> None:
    lines = _read("genetics.html").splitlines()
    index = next(i for i, line in enumerate(lines) if "genetics.result.once" in line)
    assert any("{% if item.once %}" in lines[j] for j in range(max(0, index - 2), index + 1))


def test_plan_special_uses_lifetime_keys() -> None:
    text = _read("_plan_special.html")
    assert "special.once_note_lifetime" in text
    assert "special.done_once_lifetime" in text


def test_favicon_no_longer_draws_h() -> None:
    assert "M10 8v16M22 8v16M10 16h12" not in _read("base.html")
    assert "M9.5 24 16 8l6.5 16M12 18.5h8" in _read("base.html")


def test_labsync_copy_reports_failure() -> None:
    text = _read("_labsync_profile.html")
    assert "data-failed=" in text
    assert "catch(" in text


def test_admin_ai_has_data_collection_checkbox() -> None:
    assert 'name="data_collection"' in _read("admin_ai.html")


def test_dashboard_first_run_guards() -> None:
    text = _read("dashboard.html")
    assert "record_empty" in text
    assert "dashboard.welcome_heading" in text
    key_at = text.index("dashboard.medical_through")
    assert "{% if counts.latest_result %}" in text[max(0, key_at - 60) : key_at]


def test_dashboard_connect_admin_hint_is_admin_only() -> None:
    lines = _read("dashboard.html").splitlines()
    matching = [line for line in lines if "dashboard.welcome_connect_admin" in line]
    assert len(matching) == 1
    assert "{% if user.role == 'admin' %}" in matching[0]
    assert matching[0].index("{% if user.role == 'admin' %}") < matching[0].index("dashboard.welcome_connect_admin")


def test_every_literal_key_in_edited_templates_is_catalogued() -> None:
    # t_plural stores key_one / key_few / key_many and falls back to the bare
    # key, so a plural call is catalogued by any of those four spellings.
    missing: dict[str, list[str]] = {}
    for name in EDITED:
        for function, key in KEY_PATTERN.findall(_read(name)):
            if function == "t":
                found = key in MESSAGES
            else:
                found = key in MESSAGES or any(f"{key}_{form}" in MESSAGES for form in PLURAL_FORMS)
            if not found:
                missing.setdefault(name, []).append(key)
    assert missing == {}


def test_edited_templates_compile() -> None:
    for name in EDITED:
        templates.env.get_template(name)
