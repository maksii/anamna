"""Document page, list, review queue and upload queue (sandbox audit 2026-11-06, F5).

Each test names the finding it guards. They share the miniature record from
test_web_panels and add only the rows the finding needs.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from anamna import ai
from anamna.db import connect, utc_now
from anamna.i18n import activate_locale, reset_locale
from anamna.ingest.pipeline import ensure_concept
from anamna.web import app as web

from test_web_documents import csrf_for
from test_web_panels import build


def add_observation(settings, user_id, obs_id, name, *, numeric=None, text=None, unit=None,
                    document="doc-1", page=1, observed="2025-02-13", evidence=None,
                    bbox=None, status="extracted", reference=None):
    with connect(settings) as connection:
        seed = connection.execute(
            "SELECT patient_id, vendor_id FROM documents WHERE id='doc-1'"
        ).fetchone()
        concept_id, _ = ensure_concept(connection, name, seed["vendor_id"])
        connection.execute(
            """INSERT INTO observations(
                   id, owner_user_id, patient_id, document_id, page_number, concept_id, raw_name,
                   value_type, value_numeric, value_text, unit_raw, observed_at,
                   vendor_reference_text, verification_status, extraction_method, confidence,
                   evidence_text, evidence_bbox_json, parser_version, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'test', 0.9, ?, ?, 'test', ?)""",
            (
                obs_id, user_id, seed["patient_id"], document, page, concept_id, name,
                "numeric" if numeric is not None else "text", numeric, text, unit, observed,
                reference, status, evidence or f"{name} evidence", bbox, utc_now(),
            ),
        )
        return concept_id


def set_document(settings, **fields):
    with connect(settings) as connection:
        for key, value in fields.items():
            connection.execute(f"UPDATE documents SET {key}=? WHERE id='doc-1'", (value,))


def row_html(body: str, obs_id: str) -> str:
    start = body.index(f'id="observation-{obs_id}"')
    return body[start:body.index("</article>", start)]


# --- DOCA-01 / DOCB-01 / DOCC-04, CLIN-30, DOCA-26 ----------------------------

def test_document_rows_are_converted_before_they_are_shown_or_judged(tmp_path: Path):
    settings, user_id, client = build(tmp_path)
    add_observation(settings, user_id, "obs-mchc", "Mean corpuscular hemoglobin concentration",
                    numeric=36.0, unit="g/dL", evidence="МСНС 36 г/дл 32.0 - 36.0")
    row = row_html(client.get("/documents/doc-1").text, "obs-mchc")
    # 36 g/dL is 360 g/L: never "36 g/L", never judged below range.
    assert re.search(r'<span class="result">360(?: |&nbsp;)<small>g/L', row)
    assert 'data-interpretation="low"' not in row


def test_a_word_result_carries_no_unit(tmp_path: Path):
    settings, user_id, client = build(tmp_path)
    add_observation(settings, user_id, "obs-word", "Urine glucose", text="Not detected", unit="mg/dL")
    row = row_html(client.get("/documents/doc-1").text, "obs-word")
    assert re.search(r'<span class="result">Not detected(?: |&nbsp;)<small></small></span>', row)


def test_printed_precision_is_kept():
    assert web.printed_decimals(1.8, "Холестерин ЛПВЩ 1,80 ммоль/л 1.0 - 2.0") == 2
    assert web.printed_decimals(0.4, "Креатинін 0.40 мг/дл") == 2
    assert web.printed_decimals(5.0, "Сечовина 5 ммоль/л 4.0 - 5.0") == 0
    assert web.printed_decimals(7.2, None) == 0


# --- DOCA-21 ------------------------------------------------------------------

def test_ukrainian_reference_numbers_use_the_decimal_comma():
    token = activate_locale("uk")
    try:
        assert web.reference_display("0.5 - 5.0", None, "male") == "0,5-5,0"
    finally:
        reset_locale(token)


# --- DOCA-05 / DOCC-01 / OPS-28 -----------------------------------------------

def test_ai_document_kind_is_an_enum_of_the_parser_kinds(tmp_path: Path):
    assert set(ai.DOCUMENT_KINDS) == set(web.DOCUMENT_TYPE_TITLES)
    schema = ai.OVERVIEW_RESPONSE_FORMAT["json_schema"]["schema"]
    kind = schema["properties"]["suggested_metadata"]["properties"]["clinical_type"]
    assert kind["enum"] == ["", *ai.DOCUMENT_KINDS]

    settings, user_id, client = build(tmp_path)
    csrf = csrf_for(settings, user_id)
    refused = client.post(
        "/documents/doc-1/ai-metadata",
        data={"csrf_token": csrf, "clinical_type": "Результати аналізів", "apply_clinical_type": "1"},
    )
    assert refused.status_code == 400
    with connect(settings) as connection:
        assert connection.execute("SELECT clinical_type FROM documents WHERE id='doc-1'").fetchone()[0] == "laboratory"

    # A round cached before the enum is not offered as a choice.
    hints = {"summary": "s", "section_errors": [], "suggested_metadata": {
        "clinical_type": "Результати аналізів", "vendor": "Lab", "report_date": "", "page": 1, "quote": ""}}
    with connect(settings) as connection:
        connection.execute(
            """INSERT INTO ai_document_hints(document_id, locale, provider, model, content_json, created_at)
               VALUES ('doc-1', 'en', 'openrouter', 'm', ?, ?)""",
            (json.dumps(hints, ensure_ascii=False), utc_now()),
        )
    page = client.get("/documents/doc-1").text
    assert "Результати аналізів" not in page
    hints["suggested_metadata"]["clinical_type"] = "pathology"
    with connect(settings) as connection:
        connection.execute(
            """INSERT INTO ai_document_hints(document_id, locale, provider, model, content_json, created_at)
               VALUES ('doc-1', 'en', 'openrouter', 'm', ?, '2999-01-01T00:00:00+00:00')""",
            (json.dumps(hints, ensure_ascii=False),),
        )
    page = client.get("/documents/doc-1").text
    assert '<select name="clinical_type" required>' in page
    assert '<option value="pathology" selected>' in page


# --- DOCB-10 / UX-10 / DOCC-31 / DOCB-09 / DOCB-24 / DOCC-14 -------------------

def test_titles_are_built_from_the_document_never_from_a_filename(tmp_path: Path):
    token = activate_locale("en")
    try:
        title = web.display_document_title(
            "ЗАГАЛЬНИЙ АНАЛІЗ КРОВІ", "laboratory", "Expert Hospital",
            subjects=["Complete blood count"], date="2025-02-01",
        )
        assert title == "Laboratory report - Complete blood count - 01 Feb 2025"
        assert "Expert Hospital" not in title
        assert web.display_document_title("vact", "immunization_record", filename="vact.pdf") == "Vaccination card"
        assert web.display_document_title("Lipid panel", "laboratory") == "Lipid panel"
    finally:
        reset_locale(token)

    settings, user_id, client = build(tmp_path)
    body = client.get("/documents").text
    # The fixture's title is a filename stem: generated name, no "original title".
    assert "2025-02-13__test-lab__laboratory__result-1</h2>" not in body
    assert "Laboratory report - " in body
    assert ">LA<" not in body  # the two-letter badge is gone
    page = client.get("/documents/doc-1").text
    assert "Original report title" not in page

    set_document(settings, title="Ліпідограма", title_set_by=None)
    assert "Original report title</span> Ліпідограма" in client.get("/documents/doc-1").text
    set_document(settings, title="My lipids", title_set_by="human")
    page = client.get("/documents/doc-1").text
    assert "Original report title" not in page


# --- DOCC-09 / UX-19 ------------------------------------------------------------

def test_a_narrative_report_opens_on_its_conclusion(tmp_path: Path):
    settings, user_id, client = build(tmp_path)
    with connect(settings) as connection:
        connection.execute("DELETE FROM observations WHERE document_id='doc-1'")
        patient = connection.execute("SELECT patient_id FROM documents WHERE id='doc-1'").fetchone()[0]
        for area in ("liver", "digestive"):
            connection.execute(
                """INSERT INTO clinical_findings(id, owner_user_id, patient_id, document_id, page_number,
                       health_area, title, summary_en, original_text, status, created_at)
                   VALUES (?, ?, ?, 'doc-1', 2, ?, 'Ultrasound report', 'Hepatomegaly.', 'Гепатомегалія.',
                           'attention', ?)""",
                (f"f-{area}", user_id, patient, area, utc_now()),
            )
    set_document(settings, clinical_type="ultrasound")
    page = client.get("/documents/doc-1").text
    assert 'class="side-tab is-active" aria-expanded="true" aria-controls="side-panel-conclusion"' in page
    # One card for the sentence filed under two areas, naming both.
    assert page.count('class="an-doc-finding"') == 1
    assert "Liver &amp; pancreas" in page and "Stomach &amp; intestines" in page
    assert "No numeric values" in page and "0 of 0" not in page


# --- DOCB-23 / DOCA-23 / DOCC-32 / UX-29 ---------------------------------------

def test_review_reason_comes_from_the_helper_and_goes_once_nothing_is_pending(tmp_path: Path, monkeypatch):
    settings, user_id, client = build(tmp_path)
    monkeypatch.setattr(web, "review_reason_text", lambda row, locale, **_: f"REASON[{locale}]")
    page = client.get("/documents/doc-1").text
    assert "REASON[en]" in page
    with connect(settings) as connection:
        connection.execute("UPDATE observations SET verification_status='verified' WHERE document_id='doc-1'")
    page = client.get("/documents/doc-1").text
    assert "REASON[en]" not in page
    assert "8 of 8 checked" in page


# --- OPS-27 ----------------------------------------------------------------------

def test_review_queue_says_what_it_is_and_what_each_file_needs(tmp_path: Path):
    settings, user_id, client = build(tmp_path)
    body = client.get("/documents?review_state=open").text
    # The landmark stays for screen readers; on screen the page opens on its files.
    assert '<h1 class="visually-hidden">Review queue</h1>' in body
    assert body.count("<h1") == 1 and 'class="page-head an-page-tools"' in body
    assert "8 values to check" in body
    assert 'class="an-filters-toggle"' in body


# --- OPS-30 ----------------------------------------------------------------------

def test_a_failed_re_read_followed_by_a_success_is_not_counted(tmp_path: Path):
    settings, user_id, client = build(tmp_path)
    with connect(settings) as connection:
        patient = connection.execute("SELECT patient_id FROM documents WHERE id='doc-1'").fetchone()[0]
        for job, state, at in (("j1", "failed", "2026-01-01"), ("j2", "done", "2026-01-02")):
            connection.execute(
                """INSERT INTO upload_jobs(id, owner_user_id, patient_id, batch_id, kind, filename, state,
                       document_id, created_at) VALUES (?, ?, ?, 'b', 'rescan', 'r.pdf', ?, 'doc-1', ?)""",
                (job, user_id, patient, state, at),
            )
        connection.execute("UPDATE observations SET parser_version='old' WHERE document_id='doc-1'")
    body = client.get("/documents").text
    assert "1 file was read by an older parser." in body
    assert "The last re-read of" not in body
    with connect(settings) as connection:
        connection.execute(
            """INSERT INTO upload_jobs(id, owner_user_id, patient_id, batch_id, kind, filename, state,
                   document_id, created_at) VALUES ('j3', ?, ?, 'b', 'rescan', 'r.pdf', 'failed', 'doc-1', '2026-01-03')""",
            (user_id, patient),
        )
    assert "The last re-read of 1 file failed" in client.get("/documents").text


# --- DOCB-22 ---------------------------------------------------------------------

def test_a_partly_placed_page_keeps_the_printed_order(tmp_path: Path):
    settings, user_id, client = build(tmp_path)
    with connect(settings) as connection:
        connection.execute("DELETE FROM observations WHERE document_id='doc-1'")
    add_observation(settings, user_id, "k", "Potassium", numeric=4.1, unit="mmol/L", bbox='{"v":1}')
    add_observation(settings, user_id, "na", "Sodium", numeric=140.0, unit="mmol/L", bbox='{"v":1}')
    add_observation(settings, user_id, "ca", "Ionized calcium", numeric=1.2, unit="mmol/L", bbox='{"v":1,"y":0.81}')
    page = client.get("/documents/doc-1").text
    assert page.index('id="observation-k"') < page.index('id="observation-na"') < page.index('id="observation-ca"')


# --- DOCC-17 / DOCA-25 -----------------------------------------------------------

def test_a_cuff_export_is_one_row_per_reading(tmp_path: Path):
    settings, user_id, client = build(tmp_path)
    with connect(settings) as connection:
        connection.execute("DELETE FROM observations WHERE document_id='doc-1'")
    set_document(settings, clinical_type="blood_pressure")
    for stamp, sys_, dia, pulse in (("2024-07-07T22:37:00", 118, 75, 93), ("2024-07-07T15:05:00", 136, 81, 77)):
        tag = stamp[11:13]
        add_observation(settings, user_id, f"s{tag}", "Systolic blood pressure", numeric=sys_, unit="mmHg", observed=stamp)
        add_observation(settings, user_id, f"d{tag}", "Diastolic blood pressure", numeric=dia, unit="mmHg", observed=stamp)
        add_observation(settings, user_id, f"p{tag}", "Pulse rate", numeric=pulse, unit="bpm", observed=stamp)
    page = client.get("/documents/doc-1").text
    assert page.count('class="an-bp-reading-row"') == 2
    assert "22:37" in page and "118/75" in page
    assert 'id="observation-s22"' not in page  # the three values load on demand
    # The parser wrote the English name: it is not claimed as printed.
    rows = client.get("/documents/doc-1/rows?ids=s22,d22,p22").text
    assert rows.count('class="obs-item an-obs-item"') == 3
    assert "Original source label" not in rows


# --- DOCC-16 / UX-09 -------------------------------------------------------------

def test_an_allergy_panel_folds_its_negatives(tmp_path: Path):
    settings, user_id, client = build(tmp_path)
    set_document(settings, clinical_type="allergy")
    page = client.get("/documents/doc-1").text
    # Judged normal/negative by the engine: folded into one line and a table.
    assert "allergens judged negative" in page
    assert 'id="observation-obs-1"' not in page
    # Judged above range: still a full row to read and check.
    assert 'id="observation-obs-0"' in page


# --- PERF-09 ---------------------------------------------------------------------

def test_checking_a_value_answers_with_the_row_and_keeps_other_memos(tmp_path: Path):
    settings, user_id, client = build(tmp_path)
    web._MEMO[("someone-else", "en", "catalog")] = ((), "kept")
    web._MEMO[(user_id, "en", "catalog")] = ((), "dropped")
    response = client.post(
        "/observations/obs-0/state",
        data={"csrf_token": csrf_for(settings, user_id), "action": "verify"},
        headers={"Accept": "application/json"},
    )
    payload = response.json()
    assert payload["ok"] and 'id="observation-obs-0"' in payload["row"]
    assert 'data-verification="verified"' in payload["row"]
    assert payload["review_line"].startswith("1 of 8 checked")
    assert ("someone-else", "en", "catalog") in web._MEMO
    assert (user_id, "en", "catalog") not in web._MEMO
    web._MEMO.clear()
    # The plain form still works without JavaScript.
    plain = client.post(
        "/observations/obs-1/state",
        data={"csrf_token": csrf_for(settings, user_id), "action": "verify"},
        follow_redirects=False,
    )
    assert plain.status_code == 303


def test_the_concept_picker_is_not_rendered_as_elements(tmp_path: Path):
    settings, user_id, client = build(tmp_path)
    page = client.get("/documents/doc-1").text
    assert '<datalist id="an-concept-list"></datalist>' in page
    assert 'id="an-concept-names"' in page


# --- UX-24 / OPS-29 / PERF-14 ----------------------------------------------------

def test_upload_queue_separates_failures_from_set_aside_members(tmp_path: Path):
    settings, user_id, client = build(tmp_path)
    with connect(settings) as connection:
        patient = connection.execute("SELECT patient_id FROM documents WHERE id='doc-1'").fetchone()[0]
        for job, detail in (("m1", "intake.failed_device_archive_member"), ("f1", "intake.failed_unreadable")):
            connection.execute(
                """INSERT INTO upload_jobs(id, owner_user_id, patient_id, batch_id, kind, filename, state,
                       detail_key, created_at) VALUES (?, ?, ?, 'b', 'document', ?, 'failed', ?, ?)""",
                (job, user_id, patient, f"{job}.png", detail, utc_now()),
            )
    page = client.get("/upload").text
    assert "1 upload failed." in page
    assert 'id="processing" data-upload-disclosure data-queue-active="0" open' in page
    payload = client.get("/api/uploads/queue").json()
    assert payload["failed"] == 1 and payload["set_aside"] == 1
    member = next(job for job in payload["jobs"] if job["id"] == "m1")
    assert member["tone"] == "neutral" and member["state_text"] == "Not imported"
    assert 'href="/documents/doc-1"' in payload["recent_html"]
