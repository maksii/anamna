"""The record chat (/chat): who it may read, what it stores, what it tells the model.

The model is scripted (``chat.ADAPTERS``), so every assertion is about the
application: that a tool reads exactly the record the request may read, that
a shared viewer's conversation is theirs, that a guest reaches nothing, that a
budget or provider failure reaches the page as a sentence, and that nothing a
tool does writes to the record.
"""

from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from anamna import ai, chat
from anamna.db import connect, utc_now
from anamna.i18n import activate_locale, reset_locale
from anamna.security import create_access_token, create_session, create_user
from anamna.web import app as web
from anamna.web.app import create_app
from anamna.web.chat_routes import build_tools, profile_summary, render_markdown

from test_web_panels import PASSWORD, build


class Scripted:
    """A model that follows a script: each round emits text and asks for tools."""

    script: list[tuple[str, list[tuple[str, dict]]]] = []
    seen: list[list[tuple[str, str, str]]] = []
    systems: list[str] = []
    turns: list[list[dict]] = []

    def __init__(self, route, system, turns):
        Scripted.systems.append(system)
        Scripted.turns.append([dict(turn) for turn in turns])
        self.rounds = list(Scripted.script)

    def round(self, tools, emit, final, timeout):
        text, calls = self.rounds.pop(0) if self.rounds else ("", [])
        if text:
            emit(text)
        return chat._Round(
            text=text, calls=[] if final else [(f"call-{i}", name, args) for i, (name, args) in enumerate(calls)],
            model="scripted-1", prompt_tokens=10, completion_tokens=5, finish="stop",
        )

    def add_results(self, results):
        Scripted.seen.append(results)


def _ai_on(settings, monkeypatch, script):
    ai.save_ai_settings(settings, {"ai_enabled": "1", "ai_api_key": "sk-test", "ai_provider": "openrouter"})
    monkeypatch.setattr(chat, "ADAPTERS", dict.fromkeys(ai.PROVIDER_NAMES, Scripted))
    Scripted.script, Scripted.seen, Scripted.systems, Scripted.turns = script, [], [], []


def _csrf(settings, client) -> str:
    import hashlib

    digest = hashlib.sha256(client.cookies["anamna_session"].encode()).hexdigest()
    with connect(settings) as db:
        return db.execute("SELECT csrf_token FROM sessions WHERE token_hash=?", (digest,)).fetchone()[0]


def _other_person(settings) -> str:
    """A second account with one document and one result of its own."""
    other = create_user(settings, "other@example.test", "Other", PASSWORD)
    with connect(settings) as db:
        db.execute(
            """INSERT INTO patients(id, owner_user_id, display_name, date_of_birth, sex_at_birth, created_at)
               VALUES (?, ?, 'Other Person', '1980-01-01', 'female', ?)""",
            (f"patient-{other}", other, utc_now()),
        )
        vendor = db.execute("SELECT id FROM vendors LIMIT 1").fetchone()[0]
        db.execute(
            """INSERT INTO documents(id, owner_user_id, patient_id, vendor_id, original_filename, source_path,
                   mime_type, byte_size, sha256, page_count, title, clinical_type, extraction_strategy,
                   classification_confidence, report_date, imported_at, status)
               VALUES ('doc-other', ?, ?, ?, 'secret.pdf', 'x', 'application/pdf', 1, 'sha-o', 1,
                       'Other person report', 'laboratory', 'native_text', 1, '2025-01-01', ?, 'final')""",
            (other, f"patient-{other}", vendor, utc_now()),
        )
        db.execute(
            """INSERT INTO document_pages(document_id, page_number, native_text, extraction_method)
               VALUES ('doc-other', 1, 'Prolactin 999 SECRET-MARKER', 'native')"""
        )
        concept = db.execute("SELECT id FROM concepts WHERE id='ldl-cholesterol'").fetchone()[0]
        db.execute(
            """INSERT INTO observations(id, owner_user_id, patient_id, document_id, page_number, concept_id,
                   raw_name, value_type, value_numeric, unit_raw, observed_at, verification_status,
                   extraction_method, confidence, evidence_text, parser_version, created_at)
               VALUES ('obs-other', ?, ?, 'doc-other', 1, ?, 'LDL', 'numeric', 9.99, 'mmol/L', '2025-01-01',
                       'extracted', 'test', 0.9, 'LDL 9.99', 'test', ?)""",
            (other, f"patient-{other}", concept, utc_now()),
        )
    return other


def _events(response) -> list[dict]:
    return [json.loads(chunk[5:]) for chunk in response.text.split("\n\n") if chunk.startswith("data:")]


# --- access scope ---------------------------------------------------------------


def test_every_tool_reads_only_the_record_it_was_bound_to(tmp_path: Path):
    settings, owner, _client = build(tmp_path)
    _other_person(settings)
    web.invalidate_catalog()
    with connect(settings) as db:
        tools = build_tools(db, owner)
        assert "No document" in chat.run_tool(tools, "read_document", {"document_id": "doc-other"})
        assert "SECRET-MARKER" not in chat.run_tool(tools, "read_document", {"document_id": "doc-other", "page": 1})
        history = chat.run_tool(tools, "get_metric", {"metric_id": "ldl-cholesterol"})
        assert "4.42" in history and "9.99" not in history and "doc-other" not in history
        assert "doc-other" not in chat.run_tool(tools, "list_documents", {})
        assert "9.99" not in chat.run_tool(tools, "search_record", {"query": "LDL"})
        # A model cannot widen its reach through an argument nobody declared.
        assert "doc-other" not in chat.run_tool(tools, "list_documents", {"owner_user_id": "x", "query": "report"})
        before = db.total_changes
        for name in tools:
            chat.run_tool(tools, name, {})
        chat.run_tool(tools, "read_document", {"document_id": "doc-1"})
        assert db.total_changes == before, "a chat tool wrote to the database"


def test_a_shared_viewer_reads_the_owners_record_and_owns_the_conversation(tmp_path: Path, monkeypatch):
    settings, owner, owner_client = build(tmp_path)
    viewer = _other_person(settings)
    with connect(settings) as db:
        db.execute("INSERT INTO record_shares(id, owner_user_id, grantee_email, grantee_user_id, created_at) VALUES ('s1', ?, ?, ?, ?)",
                   (owner, "other@example.test", viewer, utc_now()))
    _ai_on(settings, monkeypatch, [("", [("read_document", {"document_id": "doc-1"}),
                                         ("read_document", {"document_id": "doc-other"})]),
                                   ("Your LDL was 4.42 mmol/L on 2025-02-13.", [])])
    client = TestClient(create_app(settings))
    token, _ = create_session(settings, viewer)
    client.cookies.update({"anamna_session": token, "anamna_lang": "en", "anamna_record": owner})
    response = client.post("/chat/send", data={"csrf_token": _csrf(settings, client), "message": "My LDL?"},
                           follow_redirects=False)
    assert response.status_code == 303
    (own_doc, foreign_doc), = [[content for _id, _name, content in results] for results in Scripted.seen]
    # Bound to the owner of the shared record, not to the viewer's own one.
    assert "results (" in own_doc and "No document" in foreign_doc
    assert "someone the owner of this record has shared it with" in Scripted.systems[0]
    with connect(settings) as db:
        row = db.execute("SELECT user_id, record_user_id FROM chat_conversations").fetchone()
    assert (row["user_id"], row["record_user_id"]) == (viewer, owner)
    page = client.get(response.headers["location"])
    assert page.status_code == 200 and "Your LDL was 4.42" in page.text
    # The owner never sees what a viewer asked.
    assert "My LDL?" not in owner_client.get("/chat").text
    assert owner_client.get(response.headers["location"]).status_code == 404
    # Back on their own record, the viewer's conversation about the owner is out of view.
    client.cookies.delete("anamna_record")
    assert client.get(response.headers["location"]).status_code == 404


def test_a_guest_link_and_an_api_credential_reach_no_chat(tmp_path: Path, monkeypatch):
    settings, owner, _client = build(tmp_path)
    _ai_on(settings, monkeypatch, [("hello", [])])
    _, guest = create_access_token(settings, owner, "guest", "doctor", expires_at="2999-01-01T00:00:00+00:00")
    _, api = create_access_token(settings, owner, "api", "integration")
    _, agent = create_access_token(settings, owner, "agent", "check")
    with TestClient(create_app(settings)) as anonymous:
        for secret in (guest, api):
            headers = {"Authorization": f"Bearer {secret}"}
            assert anonymous.get("/chat", headers=headers).status_code == 403
            assert anonymous.post("/chat/send", data={"message": "hi"}, headers=headers).status_code == 403
        # The guest's own navigation does not offer it either.
        assert 'href="/chat"' not in anonymous.get("/results", headers={"Authorization": f"Bearer {guest}"}).text
        assert anonymous.get("/chat", headers={"Authorization": f"Bearer {agent}"}).status_code == 200
        assert anonymous.get("/chat", follow_redirects=False).headers["location"].startswith("/login")
    with connect(settings) as db:
        assert db.execute("SELECT COUNT(*) FROM chat_conversations").fetchone()[0] == 0
        assert db.execute("SELECT COUNT(*) FROM ai_usage").fetchone()[0] == 0


# --- conversations -------------------------------------------------------------------


def test_conversations_are_stored_per_person_and_deleted_on_request(tmp_path: Path):
    settings, owner, client = build(tmp_path)
    other = _other_person(settings)
    first = chat.create_conversation(settings, owner, owner, "What about my  LDL " + "x" * 200)
    chat.add_message(settings, first, "user", "What about my LDL")
    chat.add_message(settings, first, "assistant", "It was high.", tools=[{"name": "get_metric", "detail": ""}],
                     model="m")
    second = chat.create_conversation(settings, owner, owner, "Second")
    listed = chat.conversations(settings, owner, owner)
    assert [item["id"] for item in listed] == [second, first]
    assert len(listed[1]["title"]) <= chat.TITLE_CHARS and "  " not in listed[1]["title"]
    stored = chat.conversation(settings, first, owner, owner)
    assert [m["role"] for m in stored["messages"]] == ["user", "assistant"]
    assert stored["messages"][1]["tools"] == [{"name": "get_metric", "detail": ""}]
    assert chat.conversation(settings, first, other, owner) is None
    assert not chat.delete_conversation(settings, first, other)

    csrf = _csrf(settings, client)
    assert client.post(f"/chat/{first}/delete", data={"csrf_token": "wrong"}).status_code == 403
    response = client.post(f"/chat/{first}/delete", data={"csrf_token": csrf}, follow_redirects=False)
    assert response.status_code == 303
    assert chat.conversation(settings, first, owner, owner) is None
    with connect(settings) as db:
        assert db.execute("SELECT COUNT(*) FROM chat_messages").fetchone()[0] == 0  # cascaded
    client.post("/chat/delete-all", data={"csrf_token": csrf})
    assert chat.conversations(settings, owner, owner) == []


def test_history_replays_text_only_and_never_two_turns_of_one_role():
    turns = chat.history([
        {"role": "assistant", "content": "orphan"},
        {"role": "user", "content": "first"},
        {"role": "assistant", "content": ""},  # a failed answer with nothing written
        {"role": "user", "content": "again"},
        {"role": "assistant", "content": "answer"},
    ])
    assert turns == [{"role": "user", "content": "first\n\nagain"}, {"role": "assistant", "content": "answer"}]


def test_the_answer_streams_and_every_round_is_budgeted(tmp_path: Path, monkeypatch):
    settings, owner, client = build(tmp_path)
    _ai_on(settings, monkeypatch, [("Let me look. ", [("search_record", {"query": "LDL"})]),
                                   ("LDL **4.42** mmol/L (2025-02-13).", [])])
    response = client.post("/chat/send", data={"csrf_token": _csrf(settings, client), "message": "LDL?"},
                           headers={"Accept": "text/event-stream"})
    assert response.headers["content-type"].startswith("text/event-stream")
    events = _events(response)
    assert [event["type"] for event in events][:2] == ["conversation", "text"]
    assert {"type": "tool", "label": "Searched the record for “LDL”"} in events
    done = events[-1]
    assert done["type"] == "done" and "<strong>4.42</strong>" in done["html"]
    assert done["tools_summary"] == "Looked at 1 part of the record"
    stored = chat.conversation(settings, events[0]["id"], owner, owner)
    assert [m["role"] for m in stored["messages"]] == ["user", "assistant"]
    assert "LDL **4.42** mmol/L" in stored["messages"][1]["content"]
    with connect(settings) as db:
        usage = db.execute("SELECT feature, provider, ok FROM ai_usage ORDER BY id").fetchall()
    assert [tuple(row) for row in usage] == [("chat", "openrouter", 1)] * 2
    # The next question replays the conversation so far.
    client.post("/chat/send", data={"csrf_token": _csrf(settings, client), "message": "And HDL?",
                                    "conversation_id": events[0]["id"]})
    assert [turn["role"] for turn in Scripted.turns[-1]] == ["user", "assistant", "user"]


def test_a_missing_provider_or_a_spent_budget_is_a_sentence_not_a_500(tmp_path: Path, monkeypatch):
    settings, owner, client = build(tmp_path)
    ai.save_ai_settings(settings, {"ai_enabled": "0", "ai_api_key": ""})
    page = client.get("/chat").text
    assert "The assistant is not available" in page and 'name="message" rows' not in page
    events = _events(client.post("/chat/send", data={"csrf_token": _csrf(settings, client), "message": "Hi"},
                                 headers={"Accept": "text/event-stream"}))
    assert events[-1]["type"] == "error" and events[-1]["reason"] == "disabled"
    assert "AI provider" in events[-1]["message"]

    _ai_on(settings, monkeypatch, [("hi", [])])
    ai.save_ai_settings(settings, {"ai_task_chat": json.dumps({"provider": "anthropic", "model": "m", "enabled": True}),
                                   "ai_key_anthropic": "sk-a", "ai_daily_cap_anthropic": "0"})
    error = _events(client.post("/chat/send", data={"csrf_token": _csrf(settings, client), "message": "Hi"},
                                headers={"Accept": "text/event-stream"}))[-1]
    assert error["reason"] == "budget" and "limit" in error["message"]

    def broken(*_args):
        raise RuntimeError("upstream exploded")

    monkeypatch.setattr(Scripted, "round", lambda self, *args: broken())
    ai.save_ai_settings(settings, {"ai_task_chat": json.dumps({"provider": "openrouter", "model": "m", "enabled": True})})
    response = client.post("/chat/send", data={"csrf_token": _csrf(settings, client), "message": "Hi"},
                           follow_redirects=False)
    page = client.get(response.headers["location"]).text
    assert "did not answer" in page and "Hi" in page
    with connect(settings) as db:
        failed = db.execute("SELECT ok, error FROM ai_usage ORDER BY id DESC").fetchone()
    assert failed["ok"] == 0 and "upstream exploded" in failed["error"]


# --- what the model is told -------------------------------------------------------------


def test_the_system_prompt_carries_the_rules_and_a_compact_english_profile(tmp_path: Path):
    settings, owner, _client = build(tmp_path)
    web.invalidate_catalog()
    token = activate_locale("uk")
    try:
        with connect(settings) as db:
            profile = profile_summary(db, owner)
    finally:
        reset_locale(token)
    prompt = chat.system_prompt(locale="uk", today="2026-11-09", profile=profile, viewer_is_owner=True)
    for rule in ("Cite what you used", "say so plainly", "Never call a value verified",
                 "say so first and plainly", "Answer in Ukrainian", "Today is 2026-11-09"):
        assert rule in prompt, rule
    # Age and sex travel; the name and date of birth do not.
    assert "Test Patient" not in prompt and "1990-03-14" not in prompt
    # The record travels in English on a Ukrainian page too (fewer tokens);
    # the model is told to answer in Ukrainian.
    assert "sex at birth male" in profile and "Стать" not in profile
    assert "- LDL cholesterol: 4.42 mmol/L @2025-02-13 high #ldl-cholesterol" in prompt
    assert "S1, S2... are publishers" in prompt
    english = chat.system_prompt(locale="en", today="2026-11-09", profile="", viewer_is_owner=True)
    assert "Answer in English" in english and "the person whose record this is" in english


def test_assistant_markdown_is_escaped_before_it_is_rendered():
    html = str(render_markdown("**High** LDL\n\n- one <script>alert(1)</script>\n- two\n\n## Next\n`code`"))
    assert "<script>" not in html and "&lt;script&gt;" in html
    assert "<strong>High</strong>" in html and html.count("<li>") == 2 and "<code>code</code>" in html


def test_the_chat_page_is_in_navigation_and_in_both_languages(tmp_path: Path, monkeypatch):
    settings, _owner, client = build(tmp_path)
    _ai_on(settings, monkeypatch, [])
    english = client.get("/chat").text
    assert 'href="/chat"' in english and "Your question" in english and "openrouter.ai" in english
    client.cookies.set("anamna_lang", "uk")
    ukrainian = client.get("/chat").text
    assert "Ваше запитання" in ukrainian and "Надіслати" in ukrainian
    assert "Your question" not in ukrainian


# --- compaction and request size -------------------------------------------------


def _long_conversation(settings, owner, exchanges: int = 8, size: int = 1200) -> str:
    conversation_id = chat.create_conversation(settings, owner, owner, "Long one")
    for index in range(exchanges):
        chat.add_message(settings, conversation_id, "user", f"Question {index}")
        chat.add_message(settings, conversation_id, "assistant", f"Answer {index} " + "x" * size)
    return conversation_id


def test_a_long_conversation_is_folded_into_one_stored_summary(tmp_path: Path, monkeypatch):
    settings, owner, client = build(tmp_path)
    _ai_on(settings, monkeypatch, [("Short answer.", [])])
    asked: list[list[dict]] = []

    def summariser(api_key, model, messages, max_tokens, timeout, response_format=None, *, effort=""):
        asked.append(messages)
        return ai.AIResult(content="SUMMARY: LDL 4.42 mmol/L on 2025-02-13 was discussed.", model="s",
                           prompt_tokens=1, completion_tokens=1, finish_reason="stop")

    monkeypatch.setitem(ai.PROVIDERS, "openrouter", summariser)
    conversation_id = _long_conversation(settings, owner, exchanges=12)
    stored = chat.conversation(settings, conversation_id, owner, owner)
    older = chat.pending_compaction(stored["messages"], 0)
    assert len(older) == len(stored["messages"]) - chat.KEEP_RECENT

    events = _events(client.post("/chat/send", data={"csrf_token": _csrf(settings, client), "message": "Next?",
                                                     "conversation_id": conversation_id},
                                 headers={"Accept": "text/event-stream"}))
    compacted = next(event for event in events if event["type"] == "compacted")
    assert compacted["after_id"] == older[-1]["id"]
    # The summary was asked for in the page language and covered exactly the older messages.
    assert "Question 0" in asked[0][1]["content"] and "Question 10" not in asked[0][1]["content"]
    with connect(settings) as db:
        assert db.execute("SELECT feature FROM ai_usage WHERE feature='chat_compact'").fetchone()
    stored = chat.conversation(settings, conversation_id, owner, owner)
    assert stored["summary"].startswith("SUMMARY") and stored["summary_through"] == older[-1]["id"]
    # What was sent: the summary in the system prompt, then only the recent turns.
    assert "SUMMARY: LDL 4.42" in Scripted.systems[-1]
    sent = Scripted.turns[-1]
    assert "Question 0" not in json.dumps(sent) and sent[-1] == {"role": "user", "content": "Next?"}
    assert sum(len(turn["content"]) for turn in sent) < chat.COMPACT_AT_CHARS
    # The thread shows where it happened.
    page = client.get(f"/chat/{conversation_id}").text
    assert "summarised for the assistant" in page
    # A short follow-up does not compact again.
    asked.clear()
    client.post("/chat/send", data={"csrf_token": _csrf(settings, client), "message": "And?",
                                    "conversation_id": conversation_id})
    assert asked == []


def test_a_failed_summary_still_bounds_what_is_sent(tmp_path: Path, monkeypatch):
    settings, owner, client = build(tmp_path)
    _ai_on(settings, monkeypatch, [("ok", [])])

    def down(*_args, **_kwargs):
        raise ai.AIUnavailable("provider_error", "down")

    monkeypatch.setitem(ai.PROVIDERS, "openrouter", down)
    conversation_id = _long_conversation(settings, owner, exchanges=30, size=2000)
    client.post("/chat/send", data={"csrf_token": _csrf(settings, client), "message": "Next?",
                                    "conversation_id": conversation_id})
    sent = Scripted.turns[-1]
    assert sum(len(turn["content"]) for turn in sent) <= chat.HISTORY_CHAR_CAP + len("Next?")
    assert sent[0]["role"] == "user" and sent[-1]["content"] == "Next?"
    assert chat.conversation(settings, conversation_id, owner, owner)["summary"] == ""


def test_one_answer_makes_at_most_the_allowed_lookups(tmp_path: Path, monkeypatch):
    settings, owner, client = build(tmp_path)
    greedy = [("search_record", {"query": f"q{index}"}) for index in range(chat.MAX_LOOKUPS + 3)]
    _ai_on(settings, monkeypatch, [("", greedy), ("Done.", [])])
    events = _events(client.post("/chat/send", data={"csrf_token": _csrf(settings, client), "message": "All?"},
                                 headers={"Accept": "text/event-stream"}))
    assert sum(event["type"] == "tool" for event in events) == chat.MAX_LOOKUPS
    results = [content for _id, _name, content in Scripted.seen[0]]
    assert results[-1].startswith("Not run") and not results[0].startswith("Not run")
    # The next round was the last one, sent with tools off.
    assert len(Scripted.seen) == 1 and events[-1]["type"] == "done"


def test_tool_output_is_trimmed_before_it_reaches_the_model(tmp_path: Path):
    settings, owner, _client = build(tmp_path)
    web.invalidate_catalog()
    with connect(settings) as db:
        db.execute(
            """INSERT INTO document_pages(document_id, page_number, native_text, extraction_method)
               VALUES ('doc-1', 1, 'LDL cholesterol 4.42 mmol/L PAGE-TEXT-MARKER', 'native')""")
        tools = build_tools(db, owner)
        summary = chat.run_tool(tools, "read_document", {"document_id": "doc-1"})
        # Results first; the page text only on request.
        assert "results (" in summary and "PAGE-TEXT-MARKER" not in summary
        assert "page=1" in summary
        # The short id it prints is accepted back.
        assert "PAGE-TEXT-MARKER" in chat.run_tool(tools, "read_document", {"document_id": "d:doc-1", "page": 1})
        # Rows on the document's own date leave the date out.
        assert "- LDL cholesterol: 4.42 mmol/L high (" in summary
        token = activate_locale("uk")
        try:
            heart = chat.run_tool(tools, "list_results", {"area_id": "area:heart"})
        finally:
            reset_locale(token)
    # One line per result, English on a Ukrainian page, verdict as the engine's code,
    # publishers as aliases with a legend under the text.
    ldl = next(line for line in heart.splitlines() if "#ldl-cholesterol" in line)
    assert ldl.startswith("- LDL cholesterol: 4.42 mmol/L @2025-02-13 high (")
    assert "VERIFIED" not in heart and "the interval the laboratory itself printed" not in heart
    alias = ldl.split("(", 1)[1].split()[1].rstrip(";)")
    assert alias.startswith("S") and "Sources: " in heart and f"{alias} " in heart.split("Sources: ", 1)[1]
    huge = chat.Tool(name="huge", description="", parameters={}, run=lambda _args: "y" * 50000)
    assert len(chat.run_tool({"huge": huge}, "huge", {})) < chat.MAX_TOOL_CHARS + 200


def test_each_conversation_can_be_deleted_from_the_list(tmp_path: Path):
    settings, owner, client = build(tmp_path)
    first = chat.create_conversation(settings, owner, owner, "First")
    second = chat.create_conversation(settings, owner, owner, "Second")
    page = client.get(f"/chat/{second}").text
    assert page.count('class="an-chat-side__delete"') == 2
    assert 'aria-label="Delete conversation “First”"' in page
    csrf = _csrf(settings, client)
    # Deleting another one keeps the open conversation open.
    response = client.post(f"/chat/{first}/delete", data={"csrf_token": csrf, "back": second},
                           follow_redirects=False)
    assert response.headers["location"] == f"/chat/{second}?deleted=1"
    # `back` is only ever an id: anything else lands on /chat.
    response = client.post(f"/chat/{second}/delete", data={"csrf_token": csrf, "back": "//evil.example"},
                           follow_redirects=False)
    assert response.headers["location"] == "/chat?deleted=1"
    assert chat.conversations(settings, owner, owner) == []


# --- model choice, the admin's list and the context figures ---------------------


def test_the_admin_list_decides_which_models_a_person_may_pick(tmp_path: Path, monkeypatch):
    settings, owner, client = build(tmp_path)
    _ai_on(settings, monkeypatch, [("ok", [])])
    assert ai.parse_chat_models("anthropic:claude-sonnet-5-5\nopenrouter:google/gemma-4:free") == [
        {"provider": "anthropic", "model": "claude-sonnet-5-5"},
        {"provider": "openrouter", "model": "google/gemma-4:free"},
    ]
    assert ai.parse_chat_models("mistral:large") is None
    assert ai.parse_chat_models("anthropic:two words") is None
    ai.save_ai_settings(settings, {
        ai.CHAT_MODELS_SETTING: json.dumps([{"provider": "anthropic", "model": "claude-sonnet-5-5"},
                                            {"provider": "openai", "model": "gpt-6"}]),
        "ai_key_anthropic": "sk-a", "ai_key_openai": "",
    })
    keys = [item["key"] for item in chat.choices(settings)]
    # The chat route's own model first; a provider without a key is not offered.
    assert keys == ["openrouter:openrouter/free", "anthropic:claude-sonnet-5-5"]
    page = client.get("/chat").text
    assert 'name="model"' in page and "claude-sonnet-5-5 · api.anthropic.com" in page and "gpt-6" not in page

    routes: list[dict] = []
    original = Scripted.__init__

    def remember(self, route, system, turns):
        routes.append(route)
        original(self, route, system, turns)

    monkeypatch.setattr(Scripted, "__init__", remember)
    csrf = _csrf(settings, client)
    response = client.post("/chat/send", data={"csrf_token": csrf, "message": "Hi",
                                               "model": "anthropic:claude-sonnet-5-5"}, follow_redirects=False)
    assert (routes[-1]["provider"], routes[-1]["model"], routes[-1]["api_key"]) == ("anthropic", "claude-sonnet-5-5", "sk-a")
    conversation_id = response.headers["location"].rsplit("/", 1)[1]
    assert 'value="anthropic:claude-sonnet-5-5" selected' in client.get(f"/chat/{conversation_id}").text
    # A model the admin does not offer answers on the default.
    client.post("/chat/send", data={"csrf_token": csrf, "message": "Hi", "model": "openai:gpt-6",
                                    "conversation_id": conversation_id})
    assert routes[-1]["provider"] == "openrouter"
    with connect(settings) as db:
        assert db.execute("SELECT provider FROM ai_usage ORDER BY id").fetchall()[0][0] == "anthropic"


def test_each_answer_records_its_tokens_and_the_page_shows_the_context(tmp_path: Path, monkeypatch):
    settings, owner, client = build(tmp_path)
    _ai_on(settings, monkeypatch, [("", [("search_record", {"query": "LDL"})]), ("Done.", [])])
    events = _events(client.post("/chat/send", data={"csrf_token": _csrf(settings, client), "message": "LDL?"},
                                 headers={"Accept": "text/event-stream"}))
    done = events[-1]
    # Scripted rounds report 10 input and 5 output tokens each.
    assert done["context"]["tokens"] == 10 and done["context"]["text"] == "10 tokens"
    conversation_id = events[0]["id"]
    with connect(settings) as db:
        row = db.execute("SELECT input_tokens, output_tokens, context_tokens FROM chat_messages "
                         "WHERE role='assistant'").fetchone()
    assert tuple(row) == (20, 10, 10)
    page = client.get(f"/chat/{conversation_id}").text
    assert "The last answer read 10 tokens" in page
    client.cookies.set("anamna_lang", "uk")
    assert "Для останньої відповіді прочитано 10 токенів" in client.get(f"/chat/{conversation_id}").text


def test_the_admin_form_saves_the_ticked_chat_models_or_names_the_error():
    from starlette.datastructures import FormData

    base = [("enabled", "1"), *[(f"task_{task}_provider", "openrouter") for task in ai.TASKS]]
    ticked = [("chat_models_present", "1"), ("chat_model", "anthropic:claude-sonnet-5-5"), ("chat_model", "openai:gpt-6")]
    values, _audit = ai.parse_admin_form(FormData(base + ticked))
    assert json.loads(values[ai.CHAT_MODELS_SETTING]) == [
        {"provider": "anthropic", "model": "claude-sonnet-5-5"}, {"provider": "openai", "model": "gpt-6"}]
    # Nothing ticked clears the list; a provider nobody configures is refused.
    assert ai.parse_admin_form(FormData(base + [("chat_models_present", "1")]))[0][ai.CHAT_MODELS_SETTING] == "[]"
    assert ai.parse_admin_form(FormData(base + [("chat_models_present", "1"), ("chat_model", "gemini:pro")])) \
        == "aiassist.error_chat_models"
    # A form without the field (an older page) leaves the stored list alone.
    assert ai.CHAT_MODELS_SETTING not in ai.parse_admin_form(FormData(base))[0]


def test_the_admin_page_offers_the_chat_models_as_checkboxes(tmp_path: Path):
    settings, _owner, client = build(tmp_path)
    with connect(settings) as db:
        db.execute("UPDATE users SET role='admin'")
    ai.save_ai_settings(settings, {"ai_api_key": "sk-test", "ai_key_anthropic": "",
                                   ai.CHAT_MODELS_SETTING: json.dumps([{"provider": "anthropic", "model": "claude-x"}])})
    page = client.get("/admin/ai").text
    assert 'name="chat_model" value="openrouter:openrouter/free"' in page
    # A saved choice stays on the page, ticked and marked, after its key went.
    assert 'value="anthropic:claude-x" checked' in page and "no key: not offered" in page
    assert "1 model chosen" in page
