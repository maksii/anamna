"""An order the lab finished but issued no PDF for: its rows are filed as the
lab&#39;s own record of the order — never a PDF, never verified — once; a later
report takes the order over and the record is set aside, not doubled.

Synthetic throughout: HTTP is stubbed at ``labsync.common._http`` and the
intake queue at ``labsync.intake.enqueue`` (see test_labsync)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from anamna import labsync
from anamna.db import connect
from anamna.ingest.pipeline import RereadRefused, reingest_document
from anamna.labsync import common

from test_labsync import make, router, seed_doc, stub_intake
from test_labsync_expert import FAMILY, PASSWORD, PROFILE, TOKENS

ANTIGEN = "sars-cov-2-antigen"
NOFILE = {"id": 100169, "name": '"Тест на визначення антигену SARS-CoV-2"', "category": "lab",
          "status": "Внесено результати", "status_code": "ResultSubmitted", "date": "2025-09-18T08:36:00",
          "result_date": "2025-09-18T09:10:00", "has_file": False, "has_abnormal_results": False}
INDICATORS = [{"id": 1, "name": "Антиген SARS-CoV-2", "value": "не виявлено", "unit": None,
               "reference_text": "не виявлено", "is_abnormal": False}]


def routes(analysis: dict, indicators=INDICATORS) -> dict:
    return {
        ("GET", "/api/v1/medical/analyses"): {"items": [analysis], "total": 1, "has_more": False},
        ("GET", f"/api/v1/medical/analyses/{analysis['id']}"): {**analysis, "indicators": indicators},
        ("GET", f"/api/v1/medical/analyses/{analysis['id']}/file"): b"%PDF-1.4 synthetic",
    }


def connected(tmp_path: Path, monkeypatch):
    settings, user_id, client = make(tmp_path, enable=("expert",))
    monkeypatch.setattr(common, "_http", router({("POST", "/api/v1/auth/login"): TOKENS,
                                                 ("GET", "/api/v1/profile"): PROFILE,
                                                 ("GET", "/api/v1/profile/family"): FAMILY}))
    labsync.save_credentials(settings, user_id, "expert", {"phone": "0670000001", "password": PASSWORD})
    labsync.check_account(settings, user_id, "expert")
    labsync.link_person(settings, user_id, "expert", "p41", "self", confirmed=False)
    return settings, user_id, client


def sync(settings, user_id, monkeypatch, analysis: dict, indicators=INDICATORS) -> dict:
    monkeypatch.setattr(common, "_http", router(routes(analysis, indicators)))
    return labsync.sync(settings, user_id, "expert", inline=True)


def state(settings) -> dict:
    with connect(settings) as connection:
        order = dict(connection.execute("SELECT * FROM lab_orders WHERE order_id='100169'").fetchone())
        documents = [dict(row) for row in connection.execute(
            "SELECT id, extraction_strategy, mime_type, duplicate_of_document_id, source_path, order_identifier, "
            "report_date FROM documents ORDER BY imported_at, rowid")]
        values = [dict(row) for row in connection.execute(
            "SELECT document_id, concept_id, value_text, observed_at, verification_status, extraction_method, "
            "vendor_interpretation FROM observations WHERE verification_status<>'rejected' ORDER BY rowid")]
    return {"order": order, "documents": documents, "values": values}


def uploads(settings) -> list[Path]:
    return sorted(path for path in Path(settings.source_dir).rglob("*") if path.is_file())


def test_a_finished_order_with_no_pdf_is_filed_once_as_the_labs_record(tmp_path: Path, monkeypatch):
    settings, user_id, _ = connected(tmp_path, monkeypatch)
    calls = stub_intake(monkeypatch, settings, user_id, {})
    summary = sync(settings, user_id, monkeypatch, NOFILE)
    assert calls == []  # no PDF asked for, none invented
    assert (summary["reported"], summary["unavailable"], summary["failed"]) == (1, 0, 0)
    now = state(settings)
    assert now["order"]["state"] == "imported" and now["order"]["error_key"] == "labsync.unavailable_nofile"
    [record] = now["documents"]
    assert now["order"]["document_id"] == record["id"]
    assert (record["extraction_strategy"], record["mime_type"]) == ("lab_api", "application/json")
    assert (record["order_identifier"], record["report_date"]) == ("100169", "2025-09-18")
    # Mapped through the same alias path a PDF row takes; provisional, never verified.
    assert now["values"] == [{"document_id": record["id"], "concept_id": ANTIGEN, "value_text": "не виявлено",
                              "observed_at": "2025-09-18", "verification_status": "extracted",
                              "extraction_method": "lab_api", "vendor_interpretation": "within_vendor_range"}]
    stored = json.loads(Path(record["source_path"]).read_text(encoding="utf-8"))
    assert stored["order_id"] == "100169" and stored["rows"][0]["result"] == "не виявлено"
    assert stored["no_file_reason"] == "labsync.unavailable_nofile"
    with connect(settings) as connection:
        task = connection.execute("SELECT state, reason_key FROM review_tasks WHERE entity_id=?",
                                  (record["id"],)).fetchone()
        tracked = connection.execute("SELECT * FROM lab_orders WHERE order_id='100169'").fetchone()
        # The record IS the lab&#39;s rows: no "matches the lab record" over itself.
        assert labsync.check_order(connection, user_id, tracked) is None
    assert (task["state"], task["reason_key"]) == ("open", "review.verify_n")
    assert labsync.document_check(settings, {"id": user_id}, record["id"]) is None

    # Nothing to re-read: the queue says why instead of parsing JSON as a report.
    with pytest.raises(RereadRefused) as refused:
        reingest_document(settings, user_id, record["id"])
    assert refused.value.detail_key == "intake.failed_reread_lab_record"


def test_a_second_sync_changes_nothing_and_an_amended_record_replaces_the_old(tmp_path: Path, monkeypatch):
    settings, user_id, _ = connected(tmp_path, monkeypatch)
    stub_intake(monkeypatch, settings, user_id, {})
    sync(settings, user_id, monkeypatch, NOFILE)
    before, files = state(settings), uploads(settings)
    again = sync(settings, user_id, monkeypatch, NOFILE)
    assert (again["reported"], again["imported"], again["already"]) == (0, 0, 1)
    after = state(settings)
    assert after["documents"] == before["documents"] and after["values"] == before["values"]
    assert uploads(settings) == files
    assert after["order"]["document_id"] == before["order"]["document_id"]

    # The lab corrects the result: one current record, the old one set aside.
    amended = [{**INDICATORS[0], "value": "виявлено", "is_abnormal": True}]
    changed = sync(settings, user_id, monkeypatch, NOFILE, amended)
    assert changed["reported"] == 1 and changed["changed"] == 1
    now = state(settings)
    old, new = now["documents"]
    assert old["duplicate_of_document_id"] == new["id"] and now["order"]["document_id"] == new["id"]
    assert [(v["document_id"], v["value_text"]) for v in now["values"]] == [(new["id"], "виявлено")]
    assert now["values"][0]["vendor_interpretation"] == "borderline"  # the lab&#39;s flag, never green


def test_a_pdf_the_lab_attaches_later_takes_the_order_over(tmp_path: Path, monkeypatch):
    settings, user_id, _ = connected(tmp_path, monkeypatch)
    calls = stub_intake(monkeypatch, settings, user_id, {
        "expert-100169.pdf": {"vendor": "Expert Hospital", "order": "100169", "day": "2025-09-18",
                               "values": [("Антиген SARS-CoV-2", "не виявлено", None, "within_vendor_range")]},
    })
    sync(settings, user_id, monkeypatch, NOFILE)
    record = state(settings)["order"]["document_id"]
    summary = sync(settings, user_id, monkeypatch, {**NOFILE, "has_file": True})
    assert calls == ["expert-100169.pdf"] and summary["imported"] == 1
    now = state(settings)
    pdf = next(doc for doc in now["documents"] if doc["id"] != record)
    assert now["order"]["state"] == "imported" and now["order"]["document_id"] == pdf["id"]
    assert now["order"]["error_key"] is None
    assert next(doc for doc in now["documents"] if doc["id"] == record)["duplicate_of_document_id"] == pdf["id"]
    # Retired, not doubled: the antigen result now stands once, from the PDF.
    assert [v["document_id"] for v in now["values"]] == [pdf["id"]]
    with connect(settings) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM audit_events WHERE action='labsync_lab_record_retired' AND entity_id=?",
            (record,)).fetchone()[0] == 1
    assert sync(settings, user_id, monkeypatch, {**NOFILE, "has_file": True})["already"] == 1
    assert calls == ["expert-100169.pdf"]


def test_a_report_the_person_uploads_takes_the_order_over_too(tmp_path: Path, monkeypatch):
    settings, user_id, _ = connected(tmp_path, monkeypatch)
    stub_intake(monkeypatch, settings, user_id, {})
    sync(settings, user_id, monkeypatch, NOFILE)
    record = state(settings)["order"]["document_id"]
    uploaded = seed_doc(settings, user_id, vendor="Expert Hospital", order="100169", day="2025-09-18",
                        values=[("Антиген SARS-CoV-2", "не виявлено", None, "within_vendor_range")])
    assert sync(settings, user_id, monkeypatch, NOFILE)["linked"] == 1
    now = state(settings)
    assert (now["order"]["state"], now["order"]["document_id"]) == ("linked", uploaded)
    assert [v["document_id"] for v in now["values"]] == [uploaded]
    assert next(doc for doc in now["documents"] if doc["id"] == record)["duplicate_of_document_id"] == uploaded


def test_any_provider_whose_order_carries_rows_but_no_file_is_filed_the_same_way(tmp_path: Path, monkeypatch):
    """Synevo's in-lab order and its eHealth-locked one have rows and no PDF
    too; the path is the order dict's, not Expert Hospital's."""
    settings, user_id, _ = make(tmp_path, enable=("synevo",))

    class Lab:
        def rows(self, order, person):
            return order["rows"]

        def pdfs(self, order, person):  # pragma: no cover - must not be reached
            raise AssertionError("no PDF is fetched for an order without one")

    order = {"order_id": "7700123", "remote_ref": None, "ordered_at": "2025-03-02 09:00", "dates": ["2025-03-02"],
             "lab_status": "Done", "ready": 1, "total": 1, "complete": True,
             "unavailable": "labsync.unavailable_esoz",
             "rows": [common.lab_row(test="Глюкоза", result="5,1", units="ммоль/л", state="normal",
                                     norm=["3,9 - 5,8"], packet="Глюкоза")]}
    outcome = labsync._sync_order(settings, user_id, user_id, "synevo", f"patient-{user_id}", Lab(),
                                  {"id": "s1"}, order, True)
    assert outcome == ("reported", False)
    with connect(settings) as connection:
        row = connection.execute(
            """SELECT o.value_numeric, o.unit_raw, d.extraction_strategy, v.canonical_name FROM observations o
                 JOIN documents d ON d.id=o.document_id JOIN vendors v ON v.id=d.vendor_id""").fetchone()
        tracked = connection.execute("SELECT state, error_key FROM lab_orders").fetchone()
    assert (row["value_numeric"], row["unit_raw"], row["extraction_strategy"]) == (5.1, "ммоль/л", "lab_api")
    assert row["canonical_name"] == "Synevo"
    assert (tracked["state"], tracked["error_key"]) == ("imported", "labsync.unavailable_esoz")
    # Rows with nothing to file (a heading, an empty result) leave it unavailable, as before.
    empty = {**order, "order_id": "7700124", "rows": [common.lab_row(test="Біохімія", result="", resulttype="none")]}
    assert labsync._sync_order(settings, user_id, user_id, "synevo", f"patient-{user_id}", Lab(),
                               {"id": "s1"}, empty, True) == ("unavailable", False)


@pytest.mark.parametrize("locale, heading, state_text, source_text", [
    ("en", "Reported by the lab&#39;s online service. No PDF issued", "in your record, no PDF",
     "Reported by the lab&#39;s online service · order 100169 · no PDF issued"),
    ("uk", "Результати з онлайн-сервісу лабораторії, без PDF", "у картці, без PDF",
     "Дані онлайн-сервісу лабораторії · замовлення 100169 · PDF не видано"),
])
def test_the_pages_say_where_the_values_came_from(tmp_path: Path, monkeypatch, locale, heading, state_text,
                                                  source_text):
    settings, user_id, client = connected(tmp_path, monkeypatch)
    stub_intake(monkeypatch, settings, user_id, {})
    sync(settings, user_id, monkeypatch, NOFILE)
    record = state(settings)["order"]["document_id"]
    client.cookies.set("anamna_lang", locale)
    page = client.get(f"/documents/{record}").text
    assert heading in page and "100169" in page and 'id="lab-record"' in page
    assert 'data-source-viewer' not in page and f'/documents/{record}/rescan' not in page
    profile = client.get("/profile?tab=connections").text
    card = profile[profile.index('id="lab-expert"'):]
    assert state_text in card and f"/documents/{record}#lab-record" in card
    assert source_text in client.get(f"/metrics/{ANTIGEN}").text
    listing = client.get("/documents").text
    assert ("Lab&#39;s online record, no PDF" if locale == "en" else "Дані лабораторії, без PDF") in listing


def test_method_lines_of_a_lab_record_are_not_its_reference(tmp_path: Path, monkeypatch):
    """«Безціанидовий SLS-метод» under the bands says how, not what is normal."""
    row = {"test": "Гемоглобін (HGB)", "result": "131", "units": "г/л", "resulttype": "", "state": "normal",
           "norm": ["Жінки: 120.0 - 140.0", "Безціанидовий SLS-метод", "Метод ІФА: до 5.0"]}
    parsed = labsync._record_value(row)
    assert parsed.reference_text == "Жінки: 120.0 - 140.0; Метод ІФА: до 5.0"
    settings, user_id, _ = connected(tmp_path, monkeypatch)
    stub_intake(monkeypatch, settings, user_id, {})
    sync(settings, user_id, monkeypatch, NOFILE)
    # A record filed before the rule existed is cleaned by the repair.
    with connect(settings) as connection:
        connection.execute("UPDATE observations SET vendor_reference_text=?",
                           ("Жінки: 120.0 - 140.0; Виконано на аналізаторі VES MATIC CUBE 30",))
    assert labsync.recheck(settings)["references"] == 1
    with connect(settings) as connection:
        assert connection.execute("SELECT vendor_reference_text FROM observations").fetchone()[0] == "Жінки: 120.0 - 140.0"
    assert labsync.recheck(settings)["references"] == 0
