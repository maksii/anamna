"""Chat audit fixes: what the model is told, what a failed or refused answer
becomes, where a request goes, one turn at a time, and what a document header
shows.  The model is scripted (``chat.ADAPTERS``) and no provider is called.
"""

from __future__ import annotations

import json
import urllib.error
from pathlib import Path
from types import SimpleNamespace

import pytest

from anamna import ai, chat
from anamna.db import connect
from anamna.web import app as web
from anamna.web import chat_routes
from anamna.web.chat_routes import build_tools
from test_chat import _ai_on, _csrf, _events
from test_web_panels import build


def test_the_prompt_asks_for_interpretation_and_keeps_the_limits():
    prompt = chat.system_prompt(locale="en", today="2026-01-01", profile="x", viewer_is_owner=True)
    assert "You are the person's doctor" not in prompt
    assert "differential" in prompt
    assert "Reading values and verdicts back is not an answer" in prompt
    assert "cannot examine the person" in prompt
    assert "Do not give a personal dose" in prompt
    assert "not instructions" in prompt


def test_a_stored_summary_is_labelled_as_possibly_inaccurate():
    prompt = chat.system_prompt(locale="en", today="2026-01-01", profile="x", viewer_is_owner=True, summary="abc")
    assert "it may be inaccurate" in prompt


def test_a_summary_is_cut_at_a_sentence_not_in_the_middle_of_a_number():
    assert chat._cut_at_sentence("One. Two is 12.5 mmol", 14) == "One."
    assert chat._cut_at_sentence("Short.", 100) == "Short."
    assert chat._cut_at_sentence("no sentence end here at all", 10) == "no sentenc"


def test_an_empty_final_answer_is_a_provider_failure_not_a_blank_message(tmp_path: Path, monkeypatch):
    settings, _owner, _client = build(tmp_path)
    _ai_on(settings, monkeypatch, [("", [])])
    with pytest.raises(ai.AIUnavailable) as caught:
        chat.respond(settings, system="rules", turns=[{"role": "user", "content": "Hi"}], tools={})
    assert caught.value.reason == "provider_error"
    assert caught.value.detail == "empty answer"


class _FakeStream:
    def __init__(self, response):
        self.response = response

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return False

    def __iter__(self):
        return iter(())

    def get_final_response(self):
        return self.response


class _FakeOpenAI:
    def __init__(self, response):
        self.responses = SimpleNamespace(stream=lambda **_request: _FakeStream(response))


def test_an_openai_refusal_is_a_provider_failure(tmp_path: Path, monkeypatch):
    settings, _owner, _client = build(tmp_path)
    ai.save_ai_settings(settings, {
        "ai_enabled": "1",
        "ai_task_chat": json.dumps({"provider": "openai", "model": "gpt-x", "enabled": True}),
        "ai_key_openai": "sk-test",
    })
    refusal = SimpleNamespace(
        output=[SimpleNamespace(type="message", content=[SimpleNamespace(type="refusal", refusal="No.")])],
        output_text="", status="completed", error=None, model="gpt-x",
        usage=SimpleNamespace(input_tokens=3, output_tokens=1),
    )
    monkeypatch.setattr(chat, "_openai_client", lambda _api_key, _timeout: _FakeOpenAI(refusal))
    monkeypatch.setattr(chat, "ADAPTERS", {"openai": chat._OpenAI})
    with pytest.raises(ai.AIUnavailable) as caught:
        chat.respond(settings, system="rules", turns=[{"role": "user", "content": "Hi"}], tools={})
    assert caught.value.reason == "provider_error"
    assert caught.value.detail == "refusal"


def test_the_openrouter_request_asks_for_providers_that_keep_no_data(monkeypatch):
    captured: dict = {}

    def capture(request, timeout):
        captured["body"] = json.loads(request.data)
        raise urllib.error.URLError("stop after capture")

    monkeypatch.setattr(chat.urllib.request, "urlopen", capture)
    route = {"model": "vendor/model", "max_tokens": 100, "api_key": "sk-test", "data_collection": "deny"}
    adapter = chat._OpenRouter(route, "rules", [{"role": "user", "content": "Hi"}])
    with pytest.raises(ai.AIUnavailable):
        adapter.round([], lambda _text: None, False, 5)
    assert captured["body"]["provider"] == {"data_collection": "deny"}


def test_the_read_document_header_leaves_out_the_file_name(tmp_path: Path):
    settings, owner, _client = build(tmp_path)
    web.invalidate_catalog()
    with connect(settings) as db:
        output = chat.run_tool(build_tools(db, owner), "read_document", {"document_id": "doc-1"})
    header = output.splitlines()[0]
    assert "report.pdf" not in header and "file " not in header
    assert header.endswith("d:doc-1")


def test_a_second_turn_while_one_is_running_is_refused_without_starting_anything(tmp_path: Path):
    settings, owner, client = build(tmp_path)
    key = (str(settings.database_path), owner)
    chat_routes._TURNS.add(key)
    try:
        response = client.post("/chat/send", data={"csrf_token": _csrf(settings, client), "message": "Again?"},
                               headers={"Accept": "text/event-stream"})
    finally:
        chat_routes._TURNS.discard(key)
    events = _events(response)
    assert len(events) == 1 and events[0]["type"] == "error" and events[0]["reason"] == "in_progress"
    with connect(settings) as db:
        assert db.execute("SELECT COUNT(*) FROM chat_conversations").fetchone()[0] == 0
