"""Ingest pipeline audit, round two: re-read pairing that cannot re-label a
checked row, a corrected row's own line, whose report a file is, implausible
report dates, and a narrative that prints a results header.

Every test builds its own temporary record; nothing touches data/ or sources/.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from anamna.db import connect
from anamna.ingest import pipeline
from anamna.ingest.concepts import stable_concept_id

from test_ingest_reread_pairing import empty_document, parsed, rows, stored
from test_rescan import build, classification, page, rescanner  # noqa: F401  (fixture)

TOTAL_BILIRUBIN = stable_concept_id("Total bilirubin")
DIRECT_BILIRUBIN = stable_concept_id("Direct bilirubin")
MONOCYTES = stable_concept_id("Monocytes")
BASOPHILS = stable_concept_id("Basophils")
#: An auto concept: an unnamed label the catalogue never defined.
AUTO = "unmapped-concept-auditpipeline2"
#: The patient the record fixture was built for (test_web_panels.build).
PATIENT_BIRTH_DATE = "1990-03-14"


def shape(name, concept, value, *, unit="µmol/L", line=None, status="verified", page_number=1):
    """A row as `pair_rereading` receives it: the keys `_fresh_rows` and the preserved query give."""
    return {
        "page_number": page_number, "concept_id": concept, "raw_name": name,
        "value_numeric": value, "value_text": None, "comparator": None,
        "unit_raw": unit, "unit_canonical": unit, "observed_at": None,
        "verification_status": status,
        "evidence_text": line if line is not None else f"{name} {value}",
    }


# --- 1. A checked row is paired only with the same analyte --------------------


def test_a_verified_total_bilirubin_is_not_paired_with_a_fresh_direct_bilirubin():
    preserved = [shape("Білірубін", TOTAL_BILIRUBIN, 5.1)]
    fresh = [shape("Білірубін прямий", DIRECT_BILIRUBIN, 5.1, status="extracted")]

    same, changed = pipeline.pair_rereading(preserved, fresh)

    assert same == {} and changed == {}


def test_a_verified_monocyte_row_is_not_paired_with_a_lone_fresh_basophil_of_the_same_value():
    preserved = [shape("Моноцити (MON)", MONOCYTES, 5.0, unit="%", line="Моноцити (MON) 5.0 %")]
    fresh = [shape("Базофіли", BASOPHILS, 5.0, unit="%", line="Базофіли 5.0 %", status="extracted")]

    same, changed = pipeline.pair_rereading(preserved, fresh)

    assert same == {} and changed == {}


def test_a_contained_label_on_the_same_concept_still_pairs():
    preserved = [shape("Білірубін", TOTAL_BILIRUBIN, 5.1)]
    fresh = [shape("Білірубін загальний", TOTAL_BILIRUBIN, 5.1, status="extracted")]

    same, _ = pipeline.pair_rereading(preserved, fresh)

    assert same == {0: 0}


def test_a_checked_row_on_an_auto_concept_still_pairs_by_containment():
    preserved = [shape("Ферритин крові", AUTO, 48.0)]
    fresh = [shape("Ферритин крові сироватка", TOTAL_BILIRUBIN, 48.0, status="extracted")]

    same, _ = pipeline.pair_rereading(preserved, fresh)

    assert same == {0: 0}


def test_a_checked_row_on_an_auto_concept_still_pairs_by_its_printed_line():
    preserved = [shape("Скупчення", AUTO, 0.4, unit="кл/мкл", line="ШОЕ (SER) 0.4 кл/мкл")]
    fresh = [shape("ШОЕ (SER)", TOTAL_BILIRUBIN, 0.4, unit="кл/мкл", line="ШОЕ (SER) 0.4 кл/мкл", status="extracted")]

    same, _ = pipeline.pair_rereading(preserved, fresh)

    assert same == {0: 0}


# --- 2. A corrected row's own line is not inserted beside its correction ------


def test_a_corrected_row_pairs_with_the_fresh_row_on_its_own_printed_line():
    preserved = [shape("Білі кров'яні клітини", AUTO, 7.5, unit="кл/мкл", line="Лейкоцити 5.0 кл/мкл",
                       status="corrected")]
    fresh = [shape("Лейкоцити", TOTAL_BILIRUBIN, 5.0, unit="кл/мкл", line="Лейкоцити 5.0 кл/мкл",
                   status="extracted")]

    same, changed = pipeline.pair_rereading(preserved, fresh)

    assert same == {0: 0} and changed == {}


def test_a_corrected_row_is_not_paired_with_a_fresh_row_on_a_different_line():
    preserved = [shape("Білі кров'яні клітини", AUTO, 7.5, unit="кл/мкл", line="Лейкоцити 5.0 кл/мкл",
                       status="corrected")]
    fresh = [shape("Лейкоцити", TOTAL_BILIRUBIN, 5.0, unit="кл/мкл", line="Лейкоцити 5.1 кл/мкл",
                   status="extracted")]

    same, changed = pipeline.pair_rereading(preserved, fresh)

    assert same == {} and changed == {}


def test_a_reread_keeps_a_corrected_row_untouched_and_does_not_insert_its_parsed_twin(
    tmp_path: Path, rescanner
):
    settings, user_id, _ = build(tmp_path)
    empty_document(settings)
    stored(settings, user_id, "Білі кров'яні клітини", 7.5, unit="кл/мкл", status="corrected")
    with connect(settings) as connection:
        connection.execute("UPDATE observations SET evidence_text='Лейкоцити 5.0' WHERE document_id='doc-1'")
        connection.commit()
    rescanner([parsed("Лейкоцити", 5.0, unit="кл/мкл")], pages=[page(1)])

    result = pipeline.reingest_document(settings, user_id, "doc-1")

    after = rows(settings)
    assert [(row["raw_name"], row["value_numeric"], row["verification_status"]) for row in after] == [
        ("Білі кров'яні клітини", 7.5, "corrected"),
    ]
    assert result["observations"] == 0


# --- 3. Whose report is it: the printed date of birth -------------------------


@pytest.mark.parametrize(
    "text, expected",
    [
        ("Іваненко Іван, 01.01.1990 р.н. 02.03.2025", {"1990-01-01"}),
        ("р.н. 12.03.1980", {"1980-03-12"}),
        ("Дата народження: 17.03.1988", {"1988-03-17"}),
        ("дата народження 17/03/1988", {"1988-03-17"}),
        ("Дата народження: 17-03-1988", {"1988-03-17"}),
        ("Дата нар.: 17.03.1988", {"1988-03-17"}),
        ("17.03.1988 р.н.", {"1988-03-17"}),
        ("17.03.1988 р. н.", {"1988-03-17"}),
        ("р.н.: 17.03.1988", {"1988-03-17"}),
        ("DOB: 1988-03-17", {"1988-03-17"}),
        ("Date of birth: 17.03.1988", {"1988-03-17"}),
        ("Date of birth 17/03/1988", {"1988-03-17"}),
        ("Звіт від 25.02.2025, зразок взято 24.02.2025", set()),
        ("Дата народження: 31.02.1990", set()),
        ("Date of birth: 1990-02-30", set()),
    ],
)
def test_printed_birth_dates_read_only_the_labelled_forms(text, expected):
    assert pipeline.printed_birth_dates(text) == expected


def _review_keys(settings, document_id: str) -> set[str]:
    with connect(settings) as connection:
        task = connection.execute(
            "SELECT reason_params_json FROM review_tasks WHERE entity_id=? AND state='open'",
            (document_id,),
        ).fetchone()
    if task is None or not task["reason_params_json"]:
        return set()
    return {part["key"] for part in json.loads(task["reason_params_json"])["parts"]}


def _ingest(settings, user_id: str, name: str, klass, found=()):
    source = settings.source_dir / f"{name}.pdf"
    source.write_text(name, encoding="utf-8")
    return pipeline.ingest_file(settings, user_id, f"patient-{user_id}", source)


def test_a_report_printing_another_persons_birth_date_asks_whose_it_is(tmp_path: Path, rescanner):
    settings, user_id, _ = build(tmp_path)
    klass = classification(title="Family panel")
    rescanner(
        [parsed("Глюкоза", 5.0, unit="ммоль/л")], klass=klass, per_page=[klass],
        pages=[page(1, "Іваненко Іван, Дата народження: 05.05.1985")],
    )

    result = _ingest(settings, user_id, "family-panel", klass)

    assert "review.person_mismatch" in _review_keys(settings, str(result["document_id"]))
    with connect(settings) as connection:
        stored_row = connection.execute(
            "SELECT 1 FROM observations WHERE document_id=?", (result["document_id"],)
        ).fetchone()
    assert stored_row is not None


def test_a_report_printing_the_patients_own_birth_date_does_not_ask(tmp_path: Path, rescanner):
    settings, user_id, _ = build(tmp_path)
    klass = classification(title="Own panel")
    rescanner(
        [parsed("Глюкоза", 5.0, unit="ммоль/л")], klass=klass, per_page=[klass],
        pages=[page(1, "Дата народження: 14.03.1990")],
    )

    result = _ingest(settings, user_id, "own-panel", klass)

    assert "review.person_mismatch" not in _review_keys(settings, str(result["document_id"]))


def test_a_report_is_not_questioned_when_the_patient_has_no_birth_date(tmp_path: Path, rescanner):
    settings, user_id, _ = build(tmp_path)
    with connect(settings) as connection:
        connection.execute("UPDATE patients SET date_of_birth=NULL WHERE id=?", (f"patient-{user_id}",))
        connection.commit()
    klass = classification(title="Undated owner")
    rescanner(
        [parsed("Глюкоза", 5.0, unit="ммоль/л")], klass=klass, per_page=[klass],
        pages=[page(1, "Дата народження: 05.05.1985")],
    )

    result = _ingest(settings, user_id, "no-owner-birth-date", klass)

    assert "review.person_mismatch" not in _review_keys(settings, str(result["document_id"]))


def test_a_report_printing_no_birth_date_does_not_ask(tmp_path: Path, rescanner):
    settings, user_id, _ = build(tmp_path)
    klass = classification(title="Nothing printed")
    rescanner(
        [parsed("Глюкоза", 5.0, unit="ммоль/л")], klass=klass, per_page=[klass],
        pages=[page(1, "Глюкоза 5.0 ммоль/л, зразок 24.02.2025")],
    )

    result = _ingest(settings, user_id, "nothing-printed", klass)

    assert "review.person_mismatch" not in _review_keys(settings, str(result["document_id"]))


@pytest.mark.parametrize("found", [[], [parsed("Глюкоза", 5.0, unit="ммоль/л")]], ids=["alone", "beside-a-new-row"])
def test_a_reread_keeps_the_person_mismatch_warning(tmp_path: Path, rescanner, found):
    settings, user_id, _ = build(tmp_path)
    empty_document(settings)
    klass = classification(title="Family panel")
    rescanner(found, klass=klass, per_page=[klass], pages=[page(1, "Іваненко Іван, Дата народження: 05.05.1985")])

    pipeline.reingest_document(settings, user_id, "doc-1")

    assert "review.person_mismatch" in _review_keys(settings, "doc-1")


def test_a_reread_does_not_question_a_matching_birth_date(tmp_path: Path, rescanner):
    settings, user_id, _ = build(tmp_path)
    empty_document(settings)
    klass = classification(title="Own panel")
    rescanner([], klass=klass, per_page=[klass], pages=[page(1, "Дата народження: 14.03.1990")])

    pipeline.reingest_document(settings, user_id, "doc-1")

    assert "review.person_mismatch" not in _review_keys(settings, "doc-1")


# --- 4. An implausible report date is filed undated --------------------------


def _stored_report_date(settings, document_id: str):
    with connect(settings) as connection:
        return connection.execute("SELECT report_date FROM documents WHERE id=?", (document_id,)).fetchone()[0]


@pytest.mark.parametrize(
    "report_date",
    [
        "1980-01-01",
        "1990-03-13",
        (datetime.now(timezone.utc).date() + timedelta(days=30)).isoformat(),
    ],
)
def test_a_report_date_the_calendar_rules_out_is_filed_undated(tmp_path: Path, rescanner, report_date):
    settings, user_id, _ = build(tmp_path)
    klass = classification(title="Misdated panel", report_date=report_date)
    rescanner([parsed("Глюкоза", 5.0, unit="ммоль/л")], klass=klass, per_page=[klass])

    result = _ingest(settings, user_id, f"misdated-{report_date}", klass)

    document_id = str(result["document_id"])
    assert _stored_report_date(settings, document_id) is None
    assert "review.no_date" in _review_keys(settings, document_id)


@pytest.mark.parametrize(
    "report_date",
    [
        "1990-03-14",
        "2025-02-13",
        (datetime.now(timezone.utc).date() + timedelta(days=1)).isoformat(),
    ],
)
def test_a_plausible_report_date_is_kept(tmp_path: Path, rescanner, report_date):
    settings, user_id, _ = build(tmp_path)
    klass = classification(title="Dated panel", report_date=report_date)
    rescanner([parsed("Глюкоза", 5.0, unit="ммоль/л")], klass=klass, per_page=[klass])

    result = _ingest(settings, user_id, f"dated-{report_date}", klass)

    document_id = str(result["document_id"])
    assert _stored_report_date(settings, document_id) == report_date
    assert "review.no_date" not in _review_keys(settings, document_id)


def test_a_reread_keeps_a_date_a_person_set_even_when_the_calendar_rules_it_out(tmp_path: Path, rescanner):
    settings, user_id, _ = build(tmp_path)
    empty_document(settings)
    with connect(settings) as connection:
        connection.execute(
            "UPDATE documents SET report_date='2099-01-01', report_date_set_by='human' WHERE id='doc-1'"
        )
        connection.commit()
    klass = classification(report_date="2099-01-01")
    rescanner([parsed("Глюкоза", 5.0, unit="ммоль/л")], klass=klass, per_page=[klass])

    pipeline.reingest_document(settings, user_id, "doc-1")

    assert _stored_report_date(settings, "doc-1") == "2099-01-01"


def test_a_reread_clears_an_implausible_date_the_parser_read(tmp_path: Path, rescanner):
    settings, user_id, _ = build(tmp_path)
    empty_document(settings)
    klass = classification(report_date="2099-01-01")
    rescanner([parsed("Глюкоза", 5.0, unit="ммоль/л")], klass=klass, per_page=[klass])

    pipeline.reingest_document(settings, user_id, "doc-1")

    assert _stored_report_date(settings, "doc-1") is None


# --- 5. A narrative that prints a results header is still a narrative ---------

RESULTS_TABLE = "Показник Результат Од. Референтні значення\nГлюкоза 5.0 ммоль/л 3.3-5.5"


def test_a_consultation_with_a_results_header_still_gets_the_narrative_reason(tmp_path: Path, rescanner):
    settings, user_id, _ = build(tmp_path)
    klass = classification(clinical_type="consultation", title="Consultation with a table")
    rescanner([], klass=klass, per_page=[klass], pages=[page(1, RESULTS_TABLE)])

    result = _ingest(settings, user_id, "consultation-table", klass)

    assert _review_keys(settings, str(result["document_id"])) == {"review.narrative"}


def test_a_laboratory_report_with_no_values_keeps_its_own_reason():
    laboratory = classification(clinical_type="laboratory")

    reason = pipeline._nothing_read_reason(laboratory)

    assert reason["key"] == "review.no_values_found"
