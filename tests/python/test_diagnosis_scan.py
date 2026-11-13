"""Reading the documents for diagnoses: what is waiting, what the model's items keep, and the scan's commits.

The provider is faked at the registry seam (as in test_factor_scan.py); the
real ai.complete runs, so the usage rows and the budget path are exercised.
"""

from __future__ import annotations

import functools
import json
import urllib.request
from pathlib import Path

import pytest

from anamna import ai, diagnosis_candidates, diagnosis_scan, factor_scan
from anamna.db import connect, migrate

from test_web_panels import settings_for


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def refuse(*args, **kwargs):
        raise AssertionError("the test reached the network")

    monkeypatch.setattr(urllib.request, "build_opener", refuse)


TEXT = "Клінічний діагноз: Гіпертонічна хвороба, I10. Призначено контроль тиску."
QUOTE = "Клінічний діагноз: Гіпертонічна хвороба, I10."
GOOD_ITEM = {
    "name": "Гіпертонічна хвороба", "code": "I10", "code_printed": True, "certainty": "confirmed",
    "timing": "now", "event_date": "", "quote": QUOTE,
}
DOCUMENT = {"id": "d1", "clinical_type": "consultation", "date": "2026-01-01"}


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
                 report_date: str | None = "2026-01-01", text: str = TEXT) -> None:
    connection.execute(
        """INSERT INTO documents(id, owner_user_id, patient_id, original_filename, source_path,
               mime_type, byte_size, sha256, page_count, title, clinical_type, extraction_strategy,
               classification_confidence, report_date, imported_at, status)
           VALUES (?, ?, ?, ?, ?, 'application/pdf', 1, ?, 1, 'Запис', ?, 'native_text', 1, ?,
                   '2026-03-01T10:00:00+00:00', 'final')""",
        (doc_id, owner, patient, f"{doc_id}.pdf", f"src-{doc_id}", f"sha-{doc_id}", clinical_type, report_date),
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
    """Queue the provider's answers: an exception is raised, an AIResult is returned, a callable
    is given the parsed user payload and answers with the reply text."""
    ai.save_ai_settings(settings, {"ai_api_key": "sk-or-test"})
    calls: list[dict] = []
    queue = list(replies)

    def provider(api_key, model, messages, max_tokens, timeout, response_format=None, **kwargs):
        calls.append({"messages": messages, "timeout": timeout, "response_format": response_format,
                      "max_tokens": max_tokens})
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
        found, _model = diagnosis_scan.read_document(settings, connection, document, locale="uk")
    return found


def sent_payload(calls: list[dict]) -> dict:
    return json.loads(calls[-1]["messages"][1]["content"])


# --- what is waiting ---------------------------------------------------------------

def test_waiting_sees_only_the_owners_scanned_types_that_are_not_duplicates_or_already_scanned(tmp_path: Path):
    settings = seeded(tmp_path)
    with connect(settings) as connection:
        add_owner(connection, "u2", "p2")
        add_document(connection, "d2", "u1", "p1", report_date="2026-02-01")
        add_document(connection, "d3", "u1", "p1", clinical_type="laboratory")
        add_document(connection, "d5", "u2", "p2")
        add_document(connection, "d6", "u1", "p1", report_date="2026-04-01")
        connection.execute(
            "INSERT INTO diagnosis_scans(document_id, owner_user_id, scanned_at, model, found) "
            "VALUES ('d6', 'u1', '2026-04-02T00:00:00+00:00', 'm', 0)"
        )
        connection.execute("UPDATE documents SET duplicate_of_document_id = 'd1' WHERE id = 'd5'")
    with connect(settings) as connection:
        waiting = diagnosis_scan.waiting(connection, "u1")
        assert [(row["id"], row["date"]) for row in waiting] == [("d1", "2026-01-01"), ("d2", "2026-02-01")]
        assert diagnosis_scan.counts(connection, "u1") == {"documents": 3, "waiting": 2}
        assert diagnosis_scan.counts(connection, "u2") == {"documents": 0, "waiting": 0}


# --- what the model's items keep ---------------------------------------------------

def test_a_valid_item_is_kept_with_its_code_and_the_code_is_marked_as_printed(tmp_path: Path, monkeypatch):
    settings = seeded(tmp_path)
    (item,) = read_items(settings, monkeypatch, [GOOD_ITEM])
    assert item["name"] == "Гіпертонічна хвороба"
    assert item["code"] == "I10"
    assert item["code_printed"] is True
    assert item["quote"] == QUOTE


def test_an_item_whose_quote_is_not_in_the_document_is_dropped(tmp_path: Path, monkeypatch):
    settings = seeded(tmp_path)
    items = read_items(settings, monkeypatch, [
        {**GOOD_ITEM, "quote": "Гіпертонічна хвороба, I10 - вирішено повністю"},
        GOOD_ITEM,
        "not an object",
    ])
    assert [item["quote"] for item in items] == [QUOTE]


def test_an_item_whose_code_is_not_in_the_catalogue_is_kept_with_an_empty_code(tmp_path: Path, monkeypatch):
    settings = seeded(tmp_path)
    (item,) = read_items(settings, monkeypatch, [{**GOOD_ITEM, "code": "D99.9", "code_printed": True}])
    assert item["name"] == "Гіпертонічна хвороба"
    assert item["code"] == ""
    assert item["code_printed"] is False


def test_code_printed_is_false_when_the_code_is_not_written_in_the_document(tmp_path: Path, monkeypatch):
    settings = seeded(tmp_path)
    (item,) = read_items(settings, monkeypatch, [{**GOOD_ITEM, "code": "I11", "code_printed": True}])
    assert item["code"] == "I11"
    assert item["code_printed"] is False


def test_a_reason_for_encounter_code_is_emptied(tmp_path: Path, monkeypatch):
    settings = seeded(tmp_path)
    (item,) = read_items(settings, monkeypatch, [{**GOOD_ITEM, "code": "Z34.0", "code_printed": True}])
    assert item["code"] == ""
    assert item["name"] == "Гіпертонічна хвороба"


def test_a_name_that_is_not_in_the_document_is_dropped(tmp_path: Path, monkeypatch):
    settings = seeded(tmp_path)
    assert read_items(settings, monkeypatch, [{**GOOD_ITEM, "name": "Бронхіт", "quote": QUOTE}]) == []


@pytest.mark.parametrize("given, stored, exact", [
    ("2019", "2019-01-01", 0),
    ("2019-03-14", "2019-03-14", 1),
    ("2999-01-01", None, 0),
])
def test_an_event_date_keeps_its_precision_and_a_future_date_of_a_present_item_is_dropped(
    tmp_path: Path, monkeypatch, given, stored, exact,
):
    settings = seeded(tmp_path)
    (item,) = read_items(settings, monkeypatch, [{**GOOD_ITEM, "event_date": given}])
    assert (item["event_date"], item["date_exact"]) == (stored, exact)


def test_the_document_is_sent_with_the_diagnosis_schema_and_its_own_system_text(tmp_path: Path, monkeypatch):
    settings = seeded(tmp_path)
    calls = stub_model(settings, monkeypatch, [reply()])
    with connect(settings) as connection:
        diagnosis_scan.read_document(settings, connection, DOCUMENT, locale="uk")
    assert calls[-1]["messages"][0]["content"] == diagnosis_scan.SYSTEM
    assert calls[-1]["response_format"]["json_schema"]["name"] == "diagnosis_scan"
    item_schema = sent_payload(calls)["output_contract"]["properties"]["items"]["items"]
    assert item_schema["additionalProperties"] is False
    assert set(item_schema["required"]) == set(item_schema["properties"])
    assert item_schema["properties"]["certainty"]["enum"] == ["confirmed", "provisional"]


# --- storing -----------------------------------------------------------------------

def store_item(**overrides) -> dict:
    item = {
        "name": "Гіпертонічна хвороба", "code": "I10", "code_printed": True, "certainty": "confirmed",
        "timing": "now", "event_date": None, "date_exact": 0, "quote": QUOTE,
    }
    item.update(overrides)
    return item


def test_store_writes_the_candidates_and_the_scan_record(tmp_path: Path):
    settings = seeded(tmp_path)
    with connect(settings) as connection:
        assert diagnosis_scan.store(connection, "u1", "d1", "2026-01-01", [store_item()], "test/model") == 1
        connection.commit()
    with connect(settings) as connection:
        row = connection.execute(
            "SELECT method, code, code_printed, name, name_key, state, timing, event_date, date_exact, quote "
            "FROM diagnosis_candidates WHERE document_id = 'd1'"
        ).fetchone()
        assert tuple(row) == (
            "ai", "I10", 1, "Гіпертонічна хвороба", "гіпертонічна хвороба", "new", "now", "2026-01-01", 1, QUOTE,
        )
        scan_row = connection.execute("SELECT model, found FROM diagnosis_scans WHERE document_id = 'd1'").fetchone()
        assert tuple(scan_row) == ("test/model", 1)


def test_store_keeps_a_past_items_missing_date_empty_and_a_present_item_takes_the_document_date(tmp_path: Path):
    settings = seeded(tmp_path)
    with connect(settings) as connection:
        diagnosis_scan.store(connection, "u1", "d1", "2026-01-01", [
            store_item(name="Апендицит", code="", timing="past", event_date=None),
            store_item(name="Бронхіт", code="", timing="now", event_date=None),
            store_item(name="Гастрит", code="", timing="past", event_date="2019-01-01", date_exact=0),
        ], "test/model")
        connection.commit()
    with connect(settings) as connection:
        rows = connection.execute(
            "SELECT name, timing, event_date, date_exact FROM diagnosis_candidates ORDER BY name"
        ).fetchall()
        assert [tuple(row) for row in rows] == [
            ("Апендицит", "past", None, 0),
            ("Бронхіт", "now", "2026-01-01", 1),
            ("Гастрит", "past", "2019-01-01", 0),
        ]


def test_a_key_the_owner_dismissed_before_arrives_dismissed(tmp_path: Path):
    settings = seeded(tmp_path)
    with connect(settings) as connection:
        add_document(connection, "d2", "u1", "p1", report_date="2026-02-01")
        diagnosis_scan.store(connection, "u1", "d1", "2026-01-01", [store_item()], "test/model")
        diagnosis_candidates.dismiss(connection, "u1", ["I10"])
        connection.commit()
    with connect(settings) as connection:
        diagnosis_scan.store(connection, "u1", "d2", "2026-02-01", [store_item()], "test/model")
        connection.commit()
    with connect(settings) as connection:
        states = connection.execute(
            "SELECT document_id, state FROM diagnosis_candidates ORDER BY document_id"
        ).fetchall()
        assert [tuple(row) for row in states] == [("d1", "dismissed"), ("d2", "dismissed")]


# --- the scan ------------------------------------------------------------------------

def test_scan_keeps_the_valid_item_and_a_second_scan_reads_nothing(tmp_path: Path, monkeypatch):
    settings = seeded(tmp_path)
    with connect(settings) as connection:
        add_document(connection, "d2", "u1", "p1", report_date="2026-02-01")
    calls = stub_model(settings, monkeypatch, [reply(GOOD_ITEM), reply(GOOD_ITEM)])
    progress: list[tuple[int, int]] = []
    result = diagnosis_scan.scan(settings, functools.partial(connect, settings), "u1",
                                 locale="uk", report=lambda done, total: progress.append((done, total)))
    assert result == {"read": 2, "found": 2, "failed": 0}
    assert progress == [(0, 2), (1, 2), (2, 2)]
    assert len(calls) == 2
    with connect(settings) as connection:
        assert [tuple(row) for row in connection.execute(
            "SELECT document_id, found FROM diagnosis_scans ORDER BY document_id").fetchall()] == [("d1", 1), ("d2", 1)]
        assert connection.execute("SELECT COUNT(*) FROM diagnosis_candidates").fetchone()[0] == 2

    again = diagnosis_scan.scan(settings, functools.partial(connect, settings), "u1", locale="uk")
    assert again == {"read": 0, "found": 0, "failed": 0}
    assert len(calls) == 2


def test_an_unusable_reply_leaves_its_document_waiting_and_the_scan_goes_on(tmp_path: Path, monkeypatch):
    settings = seeded(tmp_path)
    with connect(settings) as connection:
        add_document(connection, "d2", "u1", "p1", report_date="2026-02-01")
    stub_model(settings, monkeypatch, ["not json at all", reply(GOOD_ITEM)])
    result = diagnosis_scan.scan(settings, functools.partial(connect, settings), "u1", locale="uk")
    assert result == {"read": 1, "found": 1, "failed": 1}
    with connect(settings) as connection:
        assert [row["id"] for row in diagnosis_scan.waiting(connection, "u1")] == ["d1"]
        assert connection.execute("SELECT COUNT(*) FROM diagnosis_candidates WHERE document_id = 'd1'").fetchone()[0] == 0


def test_a_reply_without_an_items_list_is_unusable(tmp_path: Path, monkeypatch):
    settings = seeded(tmp_path)
    stub_model(settings, monkeypatch, [json.dumps({"entries": []})])
    with connect(settings) as connection:
        with pytest.raises(factor_scan.UnreadableReply) as refused:
            diagnosis_scan.read_document(settings, connection, DOCUMENT, locale="uk")
    assert refused.value.reason == "provider_error"


def test_a_budget_failure_ends_the_scan_and_keeps_the_documents_already_read(tmp_path: Path, monkeypatch):
    settings = seeded(tmp_path)
    with connect(settings) as connection:
        add_document(connection, "d2", "u1", "p1", report_date="2026-02-01")
    stub_model(settings, monkeypatch, [reply(GOOD_ITEM), ai.AIUnavailable("budget")])
    with pytest.raises(ai.AIUnavailable) as stopped:
        diagnosis_scan.scan(settings, functools.partial(connect, settings), "u1", locale="uk")
    assert stopped.value.reason == "budget"
    with connect(settings) as connection:
        assert [row[0] for row in connection.execute(
            "SELECT document_id FROM diagnosis_scans ORDER BY document_id").fetchall()] == ["d1"]


def test_with_ai_switched_off_read_document_raises_disabled_before_any_call(tmp_path: Path, monkeypatch):
    settings = seeded(tmp_path)
    calls = stub_model(settings, monkeypatch, [reply(GOOD_ITEM)])
    ai.save_ai_settings(settings, {"ai_enabled": "0"})
    with connect(settings) as connection:
        with pytest.raises(ai.AIUnavailable) as refused:
            diagnosis_scan.read_document(settings, connection, DOCUMENT, locale="uk")
    assert refused.value.reason == "disabled"
    assert calls == []
