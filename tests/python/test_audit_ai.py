"""Audit regressions in the AI path: grounding, date shape, data retention.

Each test names one failure found in review: a quote the model invented was
accepted because the page image was shown, the original file name went to the
provider, a non-existent date passed as a suggestion, and medical text went to
OpenRouter with no retention constraint.
"""

from __future__ import annotations

from pathlib import Path

from anamna import ai, db, security
from anamna.db import connect, migrate

from test_web_panels import settings_for

MIGRATION_057 = db.MIGRATIONS_DIR / "057_ai_data_collection.sql"


def test_quote_on_a_page_with_text_must_be_found_in_that_text():
    grounding = ai._Grounding(
        valid_pages={1, 2},
        source_by_page={1: ai._match_key("glucose 5.4")},
        images=[b"x"],
    )
    assert grounding.grounded(1, "glucose 5.4", image_ok=True)
    assert not grounding.grounded(1, "invented cholesterol 9.9", image_ok=True)


def test_image_stands_in_for_a_scanned_page_only():
    grounding = ai._Grounding(
        valid_pages={1, 2},
        source_by_page={1: ai._match_key("glucose 5.4")},
        images=[b"x"],
    )
    # Page 2 has no extracted text: it is a scan, and the image the model saw counts.
    assert grounding.grounded(2, "any printed phrase", image_ok=True)
    assert not grounding.grounded(2, "any printed phrase", image_ok=False)


def test_suggested_dates_must_be_real_and_not_in_the_future():
    assert ai._clean_date("2026-02-31") == ""
    assert ai._clean_date("2099-01-01") == ""
    assert ai._clean_date("2020-05-17") == "2020-05-17"
    assert ai._clean_date("17.05.2020") == ""


def test_openrouter_body_always_states_the_retention_policy():
    structured = ai._openrouter_request(
        "anthropic/claude-sonnet-5", [], 100, ai.DOCUMENT_HINTS_RESPONSE_FORMAT
    )
    assert structured["provider"] == {"data_collection": "deny", "require_parameters": True}
    allowed = ai._openrouter_request("anthropic/claude-sonnet-5", [], 100, data_collection="allow")
    assert allowed["provider"] == {"data_collection": "allow"}


def test_retention_is_denied_by_default_and_follows_the_admin_setting(tmp_path: Path):
    settings = settings_for(tmp_path)
    migrate(settings)
    assert ai.ai_settings(settings)["data_collection"] == "deny"
    assert ai.task_route(settings, "default")["data_collection"] == "deny"

    ai.save_ai_settings(settings, {}, data_collection="allow")
    assert ai.ai_settings(settings)["data_collection"] == "allow"
    assert ai.task_route(settings, "default")["data_collection"] == "allow"

    ai.save_ai_settings(settings, {}, data_collection="anything-else")
    assert ai.ai_settings(settings)["data_collection"] == "deny"


def test_complete_passes_an_allowed_retention_policy_only_to_openrouter(tmp_path: Path, monkeypatch):
    settings = settings_for(tmp_path)
    migrate(settings)
    ai.save_ai_settings(settings, {"ai_api_key": "sk-or-test"})
    seen: list[dict] = []

    def recorder(api_key, model, messages, max_tokens, timeout, response_format=None, **kwargs):
        seen.append(kwargs)
        return ai.AIResult(content="ok", model=model, prompt_tokens=1, completion_tokens=1)

    monkeypatch.setitem(ai.PROVIDERS, "openrouter", recorder)
    ai.complete(settings, "default", [{"role": "user", "content": "hi"}])
    ai.save_ai_settings(settings, {}, data_collection="allow")
    ai.complete(settings, "default", [{"role": "user", "content": "hi"}])
    assert "data_collection" not in seen[0]
    assert seen[1]["data_collection"] == "allow"


def test_migration_allows_an_installation_that_already_has_accounts(tmp_path: Path):
    settings = settings_for(tmp_path)
    migrate(settings)
    security.create_user(settings, "a@example.test", "A", "long-enough-password")
    sql = MIGRATION_057.read_text(encoding="utf-8")
    with connect(settings) as connection:
        connection.execute("DELETE FROM app_settings WHERE key = 'ai_openrouter_data_collection'")
    with connect(settings) as connection:
        connection.executescript(sql)
        row = connection.execute(
            "SELECT value FROM app_settings WHERE key = 'ai_openrouter_data_collection'"
        ).fetchone()
    assert row is not None and row[0] == "allow"


def test_migration_leaves_a_fresh_installation_on_the_stricter_default(tmp_path: Path):
    settings = settings_for(tmp_path)
    migrate(settings)
    sql = MIGRATION_057.read_text(encoding="utf-8")
    with connect(settings) as connection:
        connection.execute("DELETE FROM app_settings WHERE key = 'ai_openrouter_data_collection'")
    with connect(settings) as connection:
        connection.executescript(sql)
        rows = connection.execute(
            "SELECT value FROM app_settings WHERE key = 'ai_openrouter_data_collection'"
        ).fetchall()
    assert rows == []
    assert ai.ai_settings(settings)["data_collection"] == "deny"
