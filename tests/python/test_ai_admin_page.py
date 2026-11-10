"""PERF-04 and OPS-33 on /admin/ai: the page never waits on a provider, and a
failed call is named by kind -- never by the text the provider or model sent."""
from __future__ import annotations

import html
from pathlib import Path

import pytest

from anamna import ai, drugref
from anamna.db import connect

from test_web_panels import build


@pytest.fixture(autouse=True)
def _no_live_model_lists(monkeypatch):
    monkeypatch.setattr(ai, "_MODEL_CACHE", {})


def test_admin_page_renders_without_calling_any_provider(tmp_path: Path, monkeypatch):
    settings, _, client = build(tmp_path)
    ai.save_ai_settings(settings, {"ai_key_anthropic": "sk-ant-aaaaaa", "ai_key_openai": "sk-oa-bbbbbb"})
    calls: list[str] = []
    monkeypatch.setattr(ai, "_fetch_models", lambda provider, key: calls.append(provider) or [provider + "-model"])
    page = client.get("/admin/ai").text
    assert calls == []  # the render itself made no outbound call
    assert 'data-ai-models-fetch="anthropic"' in page and 'data-ai-models-fetch="openai"' in page
    assert client.get("/admin/ai/models?provider=openai").json()["models"] == ["openai-model"]
    assert client.get("/admin/ai/models?provider=openrouter").status_code == 404
    assert calls == ["openai"]


RAW = {
    "no JSON in reply: {\n  \"summary\": \"Цей документ — загальний аналіз крові пацієнта Іваненка\"": "The reply was not in the expected format",
    "generation stopped with finish_reason=length (output limit 5000 tokens)": "hit the task&#39;s output limit",
    'HTTP 404: {"error":{"message":"No endpoints found that can handle the requested parameters."}}': "does not offer this model",
    "HTTP 401: invalid x-api-key": "refused the key",
    "AuthenticationError: Error code: 401": "refused the key",
    "HTTP 429: rate limited upstream": "rate limit",
    "daily cap for anthropic": "budget was used up",
    "no reply": "No answer was recorded",
    "TimeoutError: The read operation timed out": "timed out",
    "URLError: <urlopen error [Errno 11001] getaddrinfo failed>": "could not be reached",
    "something nobody has seen before": "The provider returned an error.",
}


def test_failures_are_named_by_kind_in_both_languages_without_their_text(tmp_path: Path):
    settings, _, client = build(tmp_path)
    with connect(settings) as db:
        for error in RAW:
            db.execute("""INSERT INTO ai_usage(created_at, feature, provider, model, ok, error)
                          VALUES ('2026-11-05T17:19:59+00:00', 'document_hints_overview', 'openrouter', 'm:free', 0, ?)""", (error,))
    client.cookies.set("anamna_lang", "en")
    page = client.get("/admin/ai").text
    for error, kind in RAW.items():
        assert kind in page, kind
    for leaked in ("Іваненка", "No endpoints found", "invalid x-api-key", "getaddrinfo", "finish_reason", "nobody has seen"):
        assert leaked not in page
    client.cookies.set("anamna_lang", "uk")
    page = client.get("/admin/ai").text
    assert "Відповідь прийшла в неочікуваному форматі" in page and "сягнула ліміту для цього завдання" in page
    assert "aiassist.err_" not in page and "Іваненка" not in page


def test_an_environment_token_is_named_as_such_and_never_shown_even_in_part(tmp_path: Path, monkeypatch):
    settings, _, client = build(tmp_path)
    monkeypatch.setenv("ANAMNA_TABLETKI_TOKEN", "env-secret-9Qx7Lm")
    client.cookies.set("anamna_lang", "en")
    page = html.unescape(client.get("/admin/ai").text)
    assert "Set in the server's environment (ANAMNA_TABLETKI_TOKEN). A token saved here takes its place." in page
    assert "9Qx7Lm" not in page and "env-secret" not in page


def test_a_token_saved_on_the_page_shows_its_tail_and_not_the_environment_text(tmp_path: Path, monkeypatch):
    settings, _, client = build(tmp_path)
    monkeypatch.setenv("ANAMNA_TABLETKI_TOKEN", "env-secret-9Qx7Lm")
    with connect(settings) as db:
        drugref.set_token(db, "saved-token-Kd3Pw8")
        db.commit()
    client.cookies.set("anamna_lang", "en")
    page = client.get("/admin/ai").text
    assert "Set in the server's environment" not in page
    assert "Kd3Pw8" in page and "saved-token" not in page
    assert "9Qx7Lm" not in page
