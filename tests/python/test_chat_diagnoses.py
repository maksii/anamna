"""What the assistant and the AI export read about diagnoses.

The record's diagnoses and the possible ones the results suggest reach the
model through the ``get_diagnoses`` tool, and through the AI export's
diagnoses section.  Both run against a temporary record; the model is not called.
"""

from __future__ import annotations

import csv
import io
import json
import zipfile
from datetime import date
from pathlib import Path

from anamna import chat, diagnoses, diagnosis_matrix
from anamna.db import connect, utc_now
from anamna.export import write_record_archive
from anamna.web.chat_routes import build_tools

from test_ai_export import _prompt
from test_chat import _other_person
from test_web_panels import build

GAP_RECORDED = "- Diagnoses that are not in the list of my diagnoses above"
GAP_UNRECORDED = "- Diagnoses I already have, unless a document above states them"
NONE_EN = "Diagnoses: none recorded."


def _add(settings, owner: str, **fields) -> str:
    """A diagnosis for ``owner`` created through the record's own validation."""
    values, errors = diagnoses.clean({"status": "active", "certainty": "confirmed", **fields}, today=date.today())
    assert errors == [], errors
    with connect(settings) as db:
        return diagnoses.create(db, owner, f"patient-{owner}", values)


def _suspicion(settings, owner: str, rule_id: str, code: str, state: str, *,
               metric: str = "LDL cholesterol", metric_id: str = "ldl-cholesterol",
               band: str = "above the target") -> None:
    """A possible diagnosis row with one piece of evidence, as the matrix stores it."""
    evidence = [{
        "metric": metric, "metric_id": metric_id, "url": f"/metrics/{metric_id}",
        "value": "4.5", "unit": "mmol/L", "date": "2026-03-14", "band": band,
        "source_id": "src-1", "source_name": "Guideline", "source_url": "https://example.test/guideline",
    }]
    now = utc_now()
    with connect(settings) as db:
        db.execute(
            """INSERT INTO diagnosis_suspicions(id, owner_user_id, rule_id, code, state, evidence_json,
                   first_seen_at, last_seen_at, state_changed_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (f"s-{owner}-{rule_id}", owner, rule_id, code, state, json.dumps(evidence), now, now, now),
        )


def _run(settings, owner: str) -> str:
    with connect(settings) as db:
        return chat.run_tool(build_tools(db, owner), "get_diagnoses", {})


# --- the tool ------------------------------------------------------------------------


def test_get_diagnoses_is_one_of_the_tools_offered_to_the_model(tmp_path: Path):
    settings, owner, _client = build(tmp_path)
    with connect(settings) as db:
        assert "get_diagnoses" in build_tools(db, owner)


def test_get_diagnoses_says_none_for_an_empty_record(tmp_path: Path):
    settings, owner, _client = build(tmp_path)
    text = _run(settings, owner)
    assert NONE_EN in text
    assert "Possible diagnoses: none." in text
    assert text.endswith("Possible diagnoses the person hid are not listed.")


def test_a_coded_diagnosis_gives_its_code_english_title_status_and_since(tmp_path: Path):
    settings, owner, _client = build(tmp_path)
    _add(settings, owner, code="e78.2", diagnosed_on="2025-03-01")
    text = _run(settings, owner)
    assert "Diagnoses:\n- E78.2 Mixed hyperlipidaemia; status: active; certainty: confirmed; since 2025-03-01" in text


def test_the_written_name_is_shown_only_when_it_differs_from_the_title(tmp_path: Path):
    settings, owner, _client = build(tmp_path)
    _add(settings, owner, code="E78.2", name="Mixed hyperlipidaemia")
    _add(settings, owner, code="E78.2", name="Змішана гіперліпідемія")
    _add(settings, owner, name="Old note without a code")
    text = _run(settings, owner)
    assert "- E78.2 Mixed hyperlipidaemia; status:" in text
    assert "- E78.2 Mixed hyperlipidaemia (written as: Змішана гіперліпідемія); status:" in text
    assert "- Old note without a code; status:" in text
    assert text.count("written as") == 1


def test_an_approximate_date_resolution_and_clinician_are_printed(tmp_path: Path):
    settings, owner, _client = build(tmp_path)
    _add(settings, owner, code="E78.2", status="resolved", diagnosed_on="2024-01-10",
         resolved_on="2025-02-01", dates_approximate="1", clinician="Dr Hale", notes="after diet change")
    text = _run(settings, owner)
    assert ("- E78.2 Mixed hyperlipidaemia; status: resolved; certainty: confirmed; since 2024-01-10 (approximate); "
            "until 2025-02-01; clinician: Dr Hale; notes: after diet change") in text


def test_an_open_possible_diagnosis_is_listed_with_its_evidence(tmp_path: Path):
    settings, owner, _client = build(tmp_path)
    _suspicion(settings, owner, "lipid_mixed", "E78.2", "open")
    text = _run(settings, owner)
    assert "Possible diagnoses (found by the application in the results, not confirmed by a doctor):" in text
    assert "- E78.2 Mixed hyperlipidaemia: LDL cholesterol 4.5 mmol/L on 2026-03-14 (above the target)" in text
    assert "Possible diagnoses: none." not in text


def test_a_muted_possible_diagnosis_is_not_listed(tmp_path: Path):
    settings, owner, _client = build(tmp_path)
    _suspicion(settings, owner, "hypothyroid", "E03.9", "muted")
    text = _run(settings, owner)
    assert "E03.9" not in text
    assert "Possible diagnoses: none." in text


def test_another_persons_diagnoses_and_possible_diagnoses_never_appear(tmp_path: Path):
    settings, owner, _client = build(tmp_path)
    other = _other_person(settings)
    _add(settings, other, name="Secret entry of the other person", code="E78.2")
    _suspicion(settings, other, "hypothyroid", "E03.9", "open")
    text = _run(settings, owner)
    assert NONE_EN in text
    assert "Secret entry" not in text
    assert "E03.9" not in text


def _medicine(settings, owner: str, name: str, atc: str) -> None:
    """A current medicine of ``owner`` on the Medicines page, inserted as the page would store it."""
    now = utc_now()
    with connect(settings) as db:
        db.execute(
            "INSERT INTO factors(id, owner_user_id, patient_id, kind, name, atc_code, status, created_at, updated_at) "
            "VALUES (?, ?, ?, 'medicine', ?, ?, 'current', ?, ?)",
            (f"f-{name}-{owner}", owner, f"patient-{owner}", name, atc, now, now),
        )


def test_the_tool_names_a_current_medicine_beside_the_diagnosis_it_treats(tmp_path: Path):
    settings, owner, _client = build(tmp_path)
    _add(settings, owner, code="I11.9")
    _medicine(settings, owner, "Valsartan", "C09CA03")
    lines = _run(settings, owner).splitlines()
    (line,) = [line for line in lines if line.startswith("- I11.9 ")]
    assert line.endswith("; treated with: Valsartan")


# --- the account archive ----------------------------------------------------------


def test_the_account_archive_carries_the_diagnosis_tables_of_its_owner(tmp_path: Path):
    settings, owner, _client = build(tmp_path)
    other = _other_person(settings)
    _add(settings, owner, code="E78.2")
    _add(settings, other, name="Other person's entry")
    _suspicion(settings, owner, "lipid_mixed", "E78.2", "open")
    buffer = io.BytesIO()
    counts = write_record_archive(settings, owner, buffer)
    archive = zipfile.ZipFile(io.BytesIO(buffer.getvalue()))
    diagnosis_rows = list(csv.DictReader(io.StringIO(archive.read("diagnoses.csv").decode("utf-8"))))
    suspicion_rows = list(csv.DictReader(io.StringIO(archive.read("diagnosis_suspicions.csv").decode("utf-8"))))
    assert [row["code"] for row in diagnosis_rows] == ["E78.2"]
    assert [row["rule_id"] for row in suspicion_rows] == ["lipid_mixed"]
    assert "diagnosis_candidates.csv" in archive.namelist()
    assert (counts["diagnoses"], counts["diagnosis_suspicions"]) == (1, 1)


# --- the AI export -----------------------------------------------------------------


def test_the_export_lists_recorded_diagnoses_and_stops_calling_them_missing(tmp_path: Path):
    settings, owner, client = build(tmp_path)
    _add(settings, owner, code="E78.2", diagnosed_on="2025-03-01")
    text = _prompt(client, locale="en")
    assert "## Diagnoses on my record" in text
    assert ("- E78.2 Mixed hyperlipidaemia; status: Current; certainty: Confirmed by a doctor; since 2025-03-01"
            in text)
    assert GAP_RECORDED in text
    assert GAP_UNRECORDED not in text


def test_the_export_lists_recorded_diagnoses_in_ukrainian(tmp_path: Path):
    settings, owner, client = build(tmp_path)
    _add(settings, owner, code="E78.2", diagnosed_on="2025-03-01")
    text = _prompt(client, locale="uk")
    assert "## Діагнози в моїй картці" in text
    assert "- E78.2 Змішана гіперліпідемія; статус: " in text
    assert "Діагнози, яких немає в переліку моїх діагнозів вище" in text
    assert "Діагнози, які вже встановлено" not in text


def test_the_export_names_the_current_medicine_of_a_recorded_diagnosis(tmp_path: Path):
    settings, owner, client = build(tmp_path)
    _add(settings, owner, code="I11.9")
    _medicine(settings, owner, "Valsartan", "C09CA03")
    text = _prompt(client, locale="en")
    assert any(line.startswith("- I11.9 ") and line.endswith("; treated with: Valsartan") for line in text.splitlines())


def test_the_export_without_diagnoses_keeps_the_old_gap_line(tmp_path: Path):
    _settings, _owner, client = build(tmp_path)
    text = _prompt(client, locale="en")
    assert "## Diagnoses on my record" in text
    assert "None recorded. Ask me what I have been diagnosed with." in text
    assert GAP_UNRECORDED in text
    assert GAP_RECORDED not in text


def test_the_export_gives_possible_diagnoses_their_own_sentence_and_evidence(tmp_path: Path):
    settings, owner, client = build(tmp_path)
    _suspicion(settings, owner, "lipid_mixed", "E78.2", "open")
    text = _prompt(client, locale="en")
    assert "These were found by the application in my results, and no doctor has confirmed them:" in text
    assert "- E78.2 Mixed hyperlipidaemia: LDL cholesterol 4.5 mmol/L on 2026-03-14 (above the target)" in text
    # Possible diagnoses are not diagnoses: with none recorded the gap line stands.
    assert GAP_UNRECORDED in text


def test_the_ukrainian_export_gives_a_possible_band_its_ukrainian_label(tmp_path: Path):
    settings, owner, client = build(tmp_path)
    _suspicion(settings, owner, "obesity", "E66", "open", metric="Body mass index", metric_id="body-mass-index",
               band="Obesity class I")
    with connect(settings) as db:
        expected = diagnosis_matrix.band_text(db, "Body mass index", "Obesity class I", "uk")
    text = _prompt(client, locale="uk")
    assert expected != "Obesity class I"
    assert f"({expected})" in text
    assert "(Obesity class I)" not in text


def test_the_export_says_when_no_possible_diagnosis_was_found(tmp_path: Path):
    _settings, _owner, client = build(tmp_path)
    text = _prompt(client, locale="en")
    assert "No possible diagnoses were found in my results." in text
