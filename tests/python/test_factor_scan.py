"""Reading the documents for factors: what is waiting, what the model's items keep, and the scan's commits.

The provider is faked at the registry seam (as in test_factor_research.py); the
real ai.complete runs, so the usage rows and the budget path are exercised.
"""

from __future__ import annotations

import datetime
import functools
import json
import urllib.request
from pathlib import Path

import pytest

from anamna import ai, factor_scan
from anamna.db import connect, migrate

from test_web_panels import settings_for


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def refuse(*args, **kwargs):
        raise AssertionError("the test reached the network")

    monkeypatch.setattr(urllib.request, "build_opener", refuse)


TEXT = (
    "Консультація терапевта. Призначено: Діокор 80 мг, по 1 таблетці один раз на добу. "
    "Амлодипін у дозі не змінюємо."
)
QUOTE = "Призначено: Діокор 80 мг, по 1 таблетці один раз на добу."
GOOD_ITEM = {
    "kind": "medicine", "name": "Діокор", "substance": "валсартан", "strength": "80 мг",
    "dose_amount": 1, "dose_unit": "tablet", "repeat": "daily", "every": 1, "per_day": 1,
    "how_written": "по 1 таблетці один раз на добу", "duration_days": 0, "long_term": True,
    "stopped": False, "timing": "now", "times": [], "meal": "", "event_date": "", "reason": "тиск", "quote": QUOTE,
}
DOCUMENT = {"id": "d1", "clinical_type": "consultation", "date": "2026-01-01"}
PLAIN_SCHEDULE = {"repeat": "daily", "every": 1, "weekdays": [], "per_day": 1, "times": [], "clock": [], "meal": ""}


def add_owner(connection, user_id: str, patient_id: str) -> None:
    connection.execute(
        "INSERT INTO users(id, email, display_name, password_salt, password_hash, created_at) "
        "VALUES (?, ?, 'Тест', x'00', x'11', '2026-01-01T00:00:00+00:00')",
        (user_id, f"{user_id}@example.test"),
    )
    connection.execute(
        "INSERT INTO patients(id, owner_user_id, display_name, date_of_birth, sex_at_birth, created_at) "
        "VALUES (?, ?, 'Пацієнт', '1990-01-02', 'female', '2026-01-01T00:00:00+00:00')",
        (patient_id, user_id),
    )


def add_document(connection, doc_id: str, owner: str, patient: str, *, clinical_type: str = "consultation",
                 report_date: str | None = "2026-01-01", imported_at: str = "2026-03-01T10:00:00+00:00",
                 text: str = TEXT, duplicate_of: str | None = None) -> None:
    connection.execute(
        """INSERT INTO documents(id, owner_user_id, patient_id, original_filename, source_path,
               mime_type, byte_size, sha256, page_count, title, clinical_type, extraction_strategy,
               classification_confidence, report_date, imported_at, status, duplicate_of_document_id)
           VALUES (?, ?, ?, ?, ?, 'application/pdf', 1, ?, 1, 'Запис', ?, 'native_text', 1, ?, ?, 'final', ?)""",
        (doc_id, owner, patient, f"{doc_id}.pdf", f"src-{doc_id}", f"sha-{doc_id}",
         clinical_type, report_date, imported_at, duplicate_of),
    )
    connection.execute(
        "INSERT INTO document_pages(document_id, page_number, native_text, extraction_method) "
        "VALUES (?, 1, ?, 'native')",
        (doc_id, text),
    )


def seeded(tmp_path: Path, *, text: str = TEXT) -> dict:
    settings = settings_for(tmp_path)
    migrate(settings)
    with connect(settings) as connection:
        add_owner(connection, "u1", "p1")
        add_document(connection, "d1", "u1", "p1", text=text)
    return settings


def stub_model(settings, monkeypatch, replies: list) -> list[dict]:
    """Queue the provider's answers.

    An exception is raised, an AIResult is returned as it is, and a callable is
    given the parsed user payload and answers with the reply text.
    """
    ai.save_ai_settings(settings, {"ai_api_key": "sk-or-test"})
    calls: list[dict] = []
    queue = list(replies)

    def provider(api_key, model, messages, max_tokens, timeout, response_format=None, **kwargs):
        calls.append({"messages": messages, "timeout": timeout, "response_format": response_format})
        answer = queue.pop(0) if queue else json.dumps({"items": []})
        if callable(answer):
            answer = answer(json.loads(messages[1]["content"]))
        if isinstance(answer, BaseException):
            raise answer
        if isinstance(answer, ai.AIResult):
            return answer
        return ai.AIResult(content=answer, model="test/model", prompt_tokens=10, completion_tokens=5)

    monkeypatch.setitem(ai.PROVIDERS, "openrouter", provider)
    return calls


def reply(*items) -> str:
    return json.dumps({"items": list(items)}, ensure_ascii=False)


def read_items(settings, monkeypatch, items: list, *, document: dict = DOCUMENT) -> list[dict]:
    stub_model(settings, monkeypatch, [reply(*items)])
    with connect(settings) as connection:
        found, _model = factor_scan.read_document(settings, connection, document, locale="uk")
    return found


def sent_payload(calls: list[dict]) -> dict:
    return json.loads(calls[-1]["messages"][1]["content"])


# --- what is waiting -----------------------------------------------------------

def test_waiting_and_counts_see_only_the_owners_scanned_types_that_are_not_duplicates_or_scanned(tmp_path: Path):
    settings = seeded(tmp_path)
    with connect(settings) as connection:
        add_owner(connection, "u2", "p2")
        add_document(connection, "d2", "u1", "p1", report_date="2026-02-01")
        add_document(connection, "d3", "u1", "p1", clinical_type="laboratory")
        add_document(connection, "d4", "u1", "p1", duplicate_of="d1")
        add_document(connection, "d5", "u2", "p2")
        add_document(connection, "d6", "u1", "p1", report_date="2026-04-01")
        connection.execute(
            "INSERT INTO factor_scans(document_id, owner_user_id, scanned_at, model, found) "
            "VALUES ('d6', 'u1', '2026-04-02T00:00:00+00:00', 'm', 0)"
        )
        connection.execute(
            "UPDATE documents SET report_date = NULL, imported_at = '2026-05-01T09:00:00+00:00' WHERE id = 'd2'"
        )
    with connect(settings) as connection:
        waiting = factor_scan.waiting(connection, "u1")
        assert [(row["id"], row["date"]) for row in waiting] == [("d1", "2026-01-01"), ("d2", "2026-05-01")]
        assert factor_scan.counts(connection, "u1") == {"documents": 3, "waiting": 2}
        assert factor_scan.counts(connection, "u2") == {"documents": 1, "waiting": 1}


def test_waiting_is_oldest_first_then_by_insertion(tmp_path: Path):
    settings = seeded(tmp_path)
    with connect(settings) as connection:
        add_document(connection, "d0", "u1", "p1", report_date="2025-12-31")
        add_document(connection, "d9", "u1", "p1", report_date="2026-01-01")
    with connect(settings) as connection:
        assert [row["id"] for row in factor_scan.waiting(connection, "u1")] == ["d0", "d1", "d9"]


# --- what the model's items keep -----------------------------------------------

def test_an_item_whose_quote_and_name_are_in_the_text_is_kept_and_others_are_dropped(tmp_path: Path, monkeypatch):
    settings = seeded(tmp_path)
    items = read_items(settings, monkeypatch, [
        GOOD_ITEM,
        {**GOOD_ITEM, "name": "Амлодипін", "quote": "Амлодипін 5 мг щодня протягом місяця"},
        {**GOOD_ITEM, "name": "Аспірин"},
        {**GOOD_ITEM, "name": "Діокор", "kind": "other"},
        {**GOOD_ITEM, "name": "діокор"},
        "not an object",
    ])
    assert [item["name"] for item in items] == ["Діокор"]
    assert items[0]["quote"] == QUOTE


def test_an_item_whose_name_is_in_the_text_only_under_another_case_is_kept(tmp_path: Path, monkeypatch):
    settings = seeded(tmp_path)
    items = read_items(settings, monkeypatch, [{**GOOD_ITEM, "name": "ДІОКОР"}])
    assert [item["name"] for item in items] == ["ДІОКОР"]


# --- regimen ----------------------------------------------------------------------

def test_a_plain_medicine_regimen_is_kept_with_its_schedule(tmp_path: Path, monkeypatch):
    settings = seeded(tmp_path)
    (item,) = read_items(settings, monkeypatch, [GOOD_ITEM])
    assert item["dose_amount"] == 1.0
    assert item["dose_unit"] == "tablet"
    assert item["schedule_json"] == json.dumps(PLAIN_SCHEDULE, separators=(",", ":"))


def test_a_supplement_keeps_its_regimen_too(tmp_path: Path, monkeypatch):
    settings = seeded(tmp_path)
    (item,) = read_items(settings, monkeypatch, [{**GOOD_ITEM, "kind": "supplement"}])
    assert item["dose_amount"] == 1.0 and item["schedule_json"]


@pytest.mark.parametrize("overrides", [
    {"dose_amount": 0},
    {"dose_amount": True},
    {"dose_unit": "bottle"},
    {"repeat": ""},
    {"kind": "procedure"},
    {"kind": "illness"},
])
def test_the_regimen_is_blanked_when_it_is_not_plain_or_not_a_medicine(tmp_path: Path, monkeypatch, overrides):
    settings = seeded(tmp_path)
    (item,) = read_items(settings, monkeypatch, [{**GOOD_ITEM, **overrides}])
    assert item["dose_amount"] is None
    assert item["dose_unit"] == ""
    assert item["schedule_json"] == ""


def test_days_of_one_becomes_daily_and_per_day_is_clamped_to_twenty_four(tmp_path: Path, monkeypatch):
    settings = seeded(tmp_path)
    (item,) = read_items(settings, monkeypatch, [{**GOOD_ITEM, "repeat": "days", "every": 1, "per_day": 30}])
    assert json.loads(item["schedule_json"]) == {**PLAIN_SCHEDULE, "per_day": 24}


def test_named_times_of_day_are_ordered_distinct_and_raise_per_day(tmp_path: Path, monkeypatch):
    settings = seeded(tmp_path)
    (item,) = read_items(settings, monkeypatch, [
        {**GOOD_ITEM, "times": ["evening", "morning", "evening", "bogus"], "per_day": 1, "meal": "after"},
    ])
    assert json.loads(item["schedule_json"]) == {
        **PLAIN_SCHEDULE, "times": ["morning", "evening"], "per_day": 2, "meal": "after",
    }
    assert '"times":["morning","evening"]' in item["schedule_json"]
    assert '"per_day":2' in item["schedule_json"]


def test_an_unknown_meal_becomes_empty_and_times_do_not_lower_per_day(tmp_path: Path, monkeypatch):
    settings = seeded(tmp_path)
    (item,) = read_items(settings, monkeypatch, [
        {**GOOD_ITEM, "times": ["night"], "per_day": 3, "meal": "bogus"},
    ])
    assert json.loads(item["schedule_json"]) == {**PLAIN_SCHEDULE, "times": ["night"], "per_day": 3}


def test_times_and_meal_are_not_kept_when_the_regimen_is_not(tmp_path: Path, monkeypatch):
    settings = seeded(tmp_path)
    (item,) = read_items(settings, monkeypatch, [{**GOOD_ITEM, "dose_amount": 0, "times": ["morning"], "meal": "after"}])
    assert item["schedule_json"] == ""


# --- dates and durations ---------------------------------------------------------

@pytest.mark.parametrize("given, stored, exact", [
    ("2019", "2019-01-01", 0),
    ("2019-03", "2019-03-01", 0),
    ("2019-03-14", "2019-03-14", 1),
    ("2019-13", None, 0),
    ("19", None, 0),
    ("14.03.2019", None, 0),
    ("1800", None, 0),
    ("2019-02-30", None, 0),
    ("не дата", None, 0),
    ("", None, 0),
    (True, None, 0),
])
def test_an_event_date_keeps_its_precision_and_unusable_shapes_are_dropped(tmp_path: Path, monkeypatch, given, stored, exact):
    settings = seeded(tmp_path)
    (item,) = read_items(settings, monkeypatch, [{**GOOD_ITEM, "event_date": given}])
    assert (item["event_date"], item["date_exact"]) == (stored, exact)


@pytest.mark.parametrize("timing, kept", [("planned", True), ("now", False), ("past", False)])
def test_a_future_event_date_is_kept_only_for_a_planned_item(tmp_path: Path, monkeypatch, timing, kept):
    settings = seeded(tmp_path)
    ahead = (datetime.date.today() + datetime.timedelta(days=30)).isoformat()
    (item,) = read_items(settings, monkeypatch, [{**GOOD_ITEM, "timing": timing, "event_date": ahead}])
    assert item["event_date"] == (ahead if kept else None)


@pytest.mark.parametrize("given, stored", [("past", "past"), ("planned", "planned"), ("someday", "now"), (None, "now")])
def test_timing_is_kept_when_known_and_otherwise_is_now(tmp_path: Path, monkeypatch, given, stored):
    settings = seeded(tmp_path)
    (item,) = read_items(settings, monkeypatch, [{**GOOD_ITEM, "timing": given}])
    assert item["timing"] == stored


@pytest.mark.parametrize("given, stored", [(4000, 0), (True, 0), (0, 0), (14, 14)])
def test_a_duration_outside_one_to_3650_days_or_a_bool_becomes_zero(tmp_path: Path, monkeypatch, given, stored):
    settings = seeded(tmp_path)
    (item,) = read_items(settings, monkeypatch, [{**GOOD_ITEM, "duration_days": given}])
    assert item["duration_days"] == stored


# --- no text, redaction and the length sent --------------------------------------

def test_a_document_without_text_returns_nothing_and_makes_no_model_call(tmp_path: Path, monkeypatch):
    settings = seeded(tmp_path, text="   ")
    calls = stub_model(settings, monkeypatch, [])
    with connect(settings) as connection:
        assert factor_scan.read_document(settings, connection, DOCUMENT, locale="uk") == ([], "")
    assert calls == []


def test_the_text_sent_is_redacted_first_and_cut_to_the_limit(tmp_path: Path, monkeypatch):
    settings = seeded(tmp_path, text=QUOTE * 300)
    monkeypatch.setattr(ai, "redact_document_text", lambda text: "MARK " + text)
    calls = stub_model(settings, monkeypatch, [reply()])
    with connect(settings) as connection:
        factor_scan.read_document(settings, connection, DOCUMENT, locale="en")
    # The text is longer than one part, so the first part carries the redacted start.
    first = json.loads(calls[0]["messages"][1]["content"])
    assert first["document"]["text"].startswith("MARK ")
    assert len(first["document"]["text"]) == factor_scan.TEXT_CHARS
    assert first["language"] == "English"
    assert calls[-1]["response_format"]["json_schema"]["name"] == "factor_scan"


def test_the_system_text_and_the_schema_match_the_contract(tmp_path: Path, monkeypatch):
    settings = seeded(tmp_path)
    calls = stub_model(settings, monkeypatch, [reply()])
    with connect(settings) as connection:
        factor_scan.read_document(settings, connection, DOCUMENT, locale="uk")
    assert calls[-1]["messages"][0]["content"] == factor_scan.SYSTEM
    schema = sent_payload(calls)["output_contract"]
    assert set(schema["required"]) == {"items"}
    item_schema = schema["properties"]["items"]["items"]
    assert item_schema["additionalProperties"] is False
    assert set(item_schema["required"]) == set(item_schema["properties"])
    assert item_schema["properties"]["kind"]["enum"] == list(factor_scan.SCAN_KINDS)


def test_a_reply_without_an_items_list_is_unusable_and_settled_as_failed(tmp_path: Path, monkeypatch):
    settings = seeded(tmp_path)
    stub_model(settings, monkeypatch, [json.dumps({"entries": []})])
    with connect(settings) as connection:
        with pytest.raises(factor_scan.UnreadableReply) as refused:
            factor_scan.read_document(settings, connection, DOCUMENT, locale="uk")
    assert refused.value.reason == "provider_error"
    with connect(settings) as connection:
        assert connection.execute("SELECT COUNT(*) FROM ai_usage WHERE ok = 0").fetchone()[0] == 1


# --- storing ----------------------------------------------------------------------

def test_store_writes_the_candidates_and_the_scan_record_with_the_count(tmp_path: Path):
    settings = seeded(tmp_path)
    item = {
        "kind": "medicine", "name": "Діокор", "substance": "валсартан", "strength": "80 мг",
        "dose_amount": 1.0, "dose_unit": "tablet", "schedule_json": json.dumps(PLAIN_SCHEDULE, separators=(",", ":")),
        "how_written": "по 1 таблетці", "timing": "now", "event_date": None, "date_exact": 0,
        "duration_days": 0, "long_term": True, "stopped": False, "reason": "тиск", "quote": QUOTE,
    }
    with connect(settings) as connection:
        assert factor_scan.store(connection, "u1", "d1", [item], "test/model") == 1
        connection.commit()
    with connect(settings) as connection:
        row = connection.execute(
            "SELECT kind, name, name_key, state, long_term, stopped, dose_amount, quote FROM factor_candidates "
            "WHERE document_id = 'd1'"
        ).fetchone()
        assert tuple(row) == ("medicine", "Діокор", "діокор", "new", 1, 0, 1.0, QUOTE)
        scan_row = connection.execute("SELECT model, found FROM factor_scans WHERE document_id = 'd1'").fetchone()
        assert tuple(scan_row) == ("test/model", 1)


def test_store_writes_timing_and_date_exact_as_given(tmp_path: Path):
    settings = seeded(tmp_path)
    item = {
        "kind": "procedure", "name": "апендектомія", "substance": "", "strength": "",
        "dose_amount": None, "dose_unit": "", "schedule_json": "", "how_written": "",
        "timing": "past", "event_date": "2019-01-01", "date_exact": 0, "duration_days": 0,
        "long_term": False, "stopped": False, "reason": "", "quote": "апендектомія",
    }
    with connect(settings) as connection:
        factor_scan.store(connection, "u1", "d1", [item], "test/model")
        connection.commit()
    with connect(settings) as connection:
        row = connection.execute(
            "SELECT timing, event_date, date_exact FROM factor_candidates WHERE document_id = 'd1'"
        ).fetchone()
        assert tuple(row) == ("past", "2019-01-01", 0)


def test_the_schema_lists_timing_times_and_meal_among_the_required_item_properties():
    item_schema = factor_scan.RESPONSE_FORMAT["json_schema"]["schema"]["properties"]["items"]["items"]
    assert {"timing", "times", "meal"} <= set(item_schema["required"])
    assert item_schema["properties"]["timing"]["enum"] == ["now", "past", "planned"]
    assert item_schema["properties"]["times"]["items"]["enum"] == list(factor_scan.factors.DAY_PARTS)
    assert item_schema["properties"]["meal"]["enum"] == [*factor_scan.factors.MEALS, ""]


# --- the scan ---------------------------------------------------------------------

def test_scan_reads_each_waiting_document_commits_each_and_reports_progress(tmp_path: Path, monkeypatch):
    settings = seeded(tmp_path)
    with connect(settings) as connection:
        add_document(connection, "d2", "u1", "p1", report_date="2026-02-01")
        add_document(connection, "d3", "u1", "p1", report_date=None, imported_at="2026-03-01T10:00:00+00:00")
    calls = stub_model(settings, monkeypatch, [reply(GOOD_ITEM), reply(GOOD_ITEM), reply(GOOD_ITEM)])
    progress: list[tuple[int, int]] = []
    result = factor_scan.scan(settings, functools.partial(connect, settings), "u1",
                              locale="uk", report=lambda done, total: progress.append((done, total)))
    assert result == {"read": 3, "found": 3, "failed": 0}
    assert progress == [(0, 3), (1, 3), (2, 3), (3, 3)]
    assert len(calls) == 3
    with connect(settings) as connection:
        scanned = connection.execute("SELECT document_id, found FROM factor_scans ORDER BY document_id").fetchall()
        assert [tuple(row) for row in scanned] == [("d1", 1), ("d2", 1), ("d3", 1)]
        assert connection.execute("SELECT COUNT(*) FROM factor_candidates").fetchone()[0] == 3

    again: list[tuple[int, int]] = []
    second = factor_scan.scan(settings, functools.partial(connect, settings), "u1",
                              locale="uk", report=lambda done, total: again.append((done, total)))
    assert second == {"read": 0, "found": 0, "failed": 0}
    assert again == [(0, 0)]
    assert len(calls) == 3


def test_a_budget_failure_ends_the_scan_and_keeps_the_documents_already_read(tmp_path: Path, monkeypatch):
    settings = seeded(tmp_path)
    with connect(settings) as connection:
        add_document(connection, "d2", "u1", "p1", report_date="2026-02-01")
    stub_model(settings, monkeypatch, [reply(GOOD_ITEM), ai.AIUnavailable("budget")])
    with pytest.raises(ai.AIUnavailable) as stopped:
        factor_scan.scan(settings, functools.partial(connect, settings), "u1", locale="uk")
    assert stopped.value.reason == "budget"
    with connect(settings) as connection:
        assert [row[0] for row in connection.execute(
            "SELECT document_id FROM factor_scans ORDER BY document_id").fetchall()] == ["d1"]
        assert [row[0] for row in connection.execute(
            "SELECT document_id FROM factor_candidates").fetchall()] == ["d1"]


# --- switched off and the connection -----------------------------------------------

def test_with_ai_switched_off_read_document_raises_disabled_before_any_call(tmp_path: Path, monkeypatch):
    settings = seeded(tmp_path)
    calls = stub_model(settings, monkeypatch, [reply(GOOD_ITEM)])
    ai.save_ai_settings(settings, {"ai_enabled": "0"})
    with connect(settings) as connection:
        with pytest.raises(ai.AIUnavailable) as refused:
            factor_scan.read_document(settings, connection, DOCUMENT, locale="uk")
    assert refused.value.reason == "disabled"
    assert calls == []


def test_the_model_call_runs_with_no_write_open_on_the_callers_connection(tmp_path: Path, monkeypatch):
    """The real ai.complete records usage on its own connection with BEGIN IMMEDIATE.

    An uncommitted write on the caller's connection would hold the lock and the
    usage row would fail with "database is locked".  read_document commits first.
    """
    settings = seeded(tmp_path)
    stub_model(settings, monkeypatch, [reply(GOOD_ITEM)])
    with connect(settings) as connection:
        add_document(connection, "d2", "u1", "p1")
        items, _model = factor_scan.read_document(settings, connection, DOCUMENT, locale="uk")
    assert [item["name"] for item in items] == ["Діокор"]
    with connect(settings) as connection:
        assert connection.execute("SELECT COUNT(*) FROM documents WHERE id = 'd2'").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM ai_usage WHERE ok = 1").fetchone()[0] == 1


# --- long documents -----------------------------------------------------------------

FILLER = "Рядок опису без особливостей, стан задовільний.\n"


def test_chunks_of_a_short_text_is_the_text_itself():
    assert factor_scan._chunks(TEXT) == [TEXT]


def test_chunks_cut_at_line_ends_and_keep_the_whole_text():
    text = ("a" * 4999 + "\n") * 3
    pieces = factor_scan._chunks(text)
    assert len(pieces) == 2
    assert all(piece.endswith("\n") for piece in pieces)
    assert "".join(pieces) == text


def test_chunks_cut_a_line_longer_than_a_piece_into_slices():
    pieces = factor_scan._chunks("x" * 30000)
    assert len(pieces) == 3
    assert all(len(piece) <= factor_scan.TEXT_CHARS for piece in pieces)
    assert "".join(pieces) == "x" * 30000


def test_chunks_stop_at_the_cap():
    pieces = factor_scan._chunks("x" * (factor_scan.MAX_CHUNKS * factor_scan.TEXT_CHARS + 5000))
    assert len(pieces) == factor_scan.MAX_CHUNKS


def test_long_document_is_read_to_the_end(tmp_path: Path, monkeypatch):
    settings = seeded(tmp_path, text=FILLER * 260 + QUOTE + "\n")

    def names_it(payload):
        return reply(GOOD_ITEM) if "Діокор" in payload["document"]["text"] else reply()

    calls = stub_model(settings, monkeypatch, [names_it, names_it])
    with connect(settings) as connection:
        items, _model = factor_scan.read_document(settings, connection, DOCUMENT, locale="uk")
    assert len(calls) == 2
    parts = [json.loads(call["messages"][1]["content"])["document"]["part"] for call in calls]
    assert parts == ["1 of 2", "2 of 2"]
    assert [item["name"] for item in items] == ["Діокор"]


def test_short_document_sends_no_part(tmp_path: Path, monkeypatch):
    settings = seeded(tmp_path)
    calls = stub_model(settings, monkeypatch, [reply()])
    with connect(settings) as connection:
        factor_scan.read_document(settings, connection, DOCUMENT, locale="uk")
    assert len(calls) == 1
    assert "part" not in sent_payload(calls)["document"]


def test_same_item_in_two_parts_is_listed_once(tmp_path: Path, monkeypatch):
    settings = seeded(tmp_path, text=QUOTE + "\n" + FILLER * 260 + QUOTE + "\n")
    calls = stub_model(settings, monkeypatch, [reply(GOOD_ITEM), reply(GOOD_ITEM)])
    with connect(settings) as connection:
        items, _model = factor_scan.read_document(settings, connection, DOCUMENT, locale="uk")
    assert len(calls) == 2
    assert [item["name"] for item in items] == ["Діокор"]


# --- unusable replies ---------------------------------------------------------------

def test_unparseable_reply_settles_usage_as_failed(tmp_path: Path, monkeypatch):
    settings = seeded(tmp_path)
    stub_model(settings, monkeypatch, ["not json at all"])
    with connect(settings) as connection:
        with pytest.raises(factor_scan.UnreadableReply) as refused:
            factor_scan.read_document(settings, connection, DOCUMENT, locale="uk")
    assert refused.value.reason == "provider_error"
    with connect(settings) as connection:
        assert connection.execute("SELECT COUNT(*) FROM ai_usage WHERE ok = 0").fetchone()[0] == 1


def test_unusable_reply_does_not_stop_the_scan(tmp_path: Path, monkeypatch):
    settings = seeded(tmp_path)
    with connect(settings) as connection:
        add_document(connection, "d2", "u1", "p1", report_date="2026-02-01")
    stub_model(settings, monkeypatch, ["not json at all", reply(GOOD_ITEM)])
    progress: list[tuple[int, int]] = []
    result = factor_scan.scan(settings, functools.partial(connect, settings), "u1",
                              locale="uk", report=lambda done, total: progress.append((done, total)))
    assert result == {"read": 1, "found": 1, "failed": 1}
    assert progress[-1] == (2, 2)
    with connect(settings) as connection:
        assert [row["id"] for row in factor_scan.waiting(connection, "u1")] == ["d1"]
        assert connection.execute("SELECT COUNT(*) FROM factor_scans WHERE document_id = 'd1'").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM factor_scans WHERE document_id = 'd2'").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM factor_candidates WHERE document_id = 'd2'").fetchone()[0] == 1


def test_truncated_reply_raises_unreadable_with_reason_truncated(tmp_path: Path, monkeypatch):
    settings = seeded(tmp_path)
    cut_short = ai.AIResult(content='{"items": [', model="test/model", prompt_tokens=10,
                            completion_tokens=5, finish_reason="length")
    stub_model(settings, monkeypatch, [cut_short])
    with connect(settings) as connection:
        with pytest.raises(factor_scan.UnreadableReply) as refused:
            factor_scan.read_document(settings, connection, DOCUMENT, locale="uk")
    assert refused.value.reason == "truncated"


def test_truncated_reply_is_unusable_not_fatal(tmp_path: Path, monkeypatch):
    settings = seeded(tmp_path)
    with connect(settings) as connection:
        add_document(connection, "d2", "u1", "p1", report_date="2026-02-01")
    cut_short = ai.AIResult(content='{"items": [', model="test/model", prompt_tokens=10,
                            completion_tokens=5, finish_reason="length")
    stub_model(settings, monkeypatch, [cut_short, reply(GOOD_ITEM)])
    result = factor_scan.scan(settings, functools.partial(connect, settings), "u1", locale="uk")
    assert result == {"read": 1, "found": 1, "failed": 1}


def test_budget_error_on_the_first_document_still_ends_the_scan(tmp_path: Path, monkeypatch):
    settings = seeded(tmp_path)
    with connect(settings) as connection:
        add_document(connection, "d2", "u1", "p1", report_date="2026-02-01")
    stub_model(settings, monkeypatch, [ai.AIUnavailable("budget")])
    with pytest.raises(ai.AIUnavailable) as stopped:
        factor_scan.scan(settings, functools.partial(connect, settings), "u1", locale="uk")
    assert stopped.value.reason == "budget"
    assert not isinstance(stopped.value, factor_scan.UnreadableReply)
