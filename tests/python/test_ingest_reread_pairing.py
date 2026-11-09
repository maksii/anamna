"""A re-read pairs its rows with the ones a person already checked.

Shapes are taken from the sandbox audit (2026-11-06), anonymised:
- Esculab urinalysis (n16) and STI PCR (n15): labels the old parser cut short
  («Скупчення лейкоцитів (WBC», «Виявлення ДНК Trichomonas vaginalis») and a
  specimen line filed as three analytes («Приносний матеріал, сеча»);
- Esculab sediment (n70): a sex-split reference cut to its first half;
- Expert urinalysis (n79): labels carrying «, <unit>» that the parser dropped;
- Garmin blood pressure: a category read wrongly on a checked reading.

Every test pins one way the old (page, printed label) rule duplicated a
checked value or let a re-read change it in silence.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import pytest

from anamna.db import connect
from anamna.ingest import pipeline
from anamna.ingest.parsers import ParsedObservation

from test_rescan import build, classification, page, rescanner  # noqa: F401  (fixture)


def parsed(name, value=None, text=None, *, unit=None, page_number=1, reference=None, low=None, high=None,
           observed_at=None) -> ParsedObservation:
    return ParsedObservation(
        raw_name=name, value_numeric=value, value_text=text, comparator=None, unit_raw=unit,
        reference_text=reference, reference_low=low, reference_high=high, page_number=page_number,
        evidence_text=f"{name} {value if value is not None else text}", confidence=0.95,
        observed_at=observed_at,
    )


def stored(settings, user_id, name, value=None, text=None, *, unit=None, page_number=1, status="verified",
           reference=None, observed_at="2022-08-24") -> None:
    with connect(settings) as connection:
        vendor_id = connection.execute("SELECT vendor_id FROM documents WHERE id='doc-1'").fetchone()[0]
        concept_id, _ = pipeline.ensure_concept(
            connection, name, vendor_id, value_type="numeric" if value is not None else "text",
            unit_raw=unit, clinical_type="laboratory",
        )
        connection.execute(
            """INSERT INTO observations(
                   id, owner_user_id, patient_id, document_id, page_number, concept_id, raw_name,
                   value_type, value_numeric, value_text, unit_raw, unit_canonical, observed_at,
                   vendor_reference_text, verification_status, extraction_method, confidence,
                   evidence_text, parser_version, created_at)
               SELECT lower(hex(randomblob(8))), owner_user_id, patient_id, id, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                      ?, ?, 'native_pdf_text_parser', 0.9, ?, '2026.08.04-3', imported_at
                 FROM documents WHERE id='doc-1'""",
            (
                page_number, concept_id, name, "numeric" if value is not None else "text", value, text,
                unit, unit, observed_at, reference, status, f"{name} evidence",
            ),
        )
        connection.commit()


def empty_document(settings) -> None:
    with connect(settings) as connection:
        connection.execute("DELETE FROM observations WHERE document_id='doc-1'")
        connection.commit()


def rows(settings) -> list[dict]:
    with connect(settings) as connection:
        return [
            dict(row)
            for row in connection.execute(
                "SELECT * FROM observations WHERE document_id='doc-1' ORDER BY page_number, rowid"
            )
        ]


def open_task(settings) -> dict:
    with connect(settings) as connection:
        return dict(
            connection.execute(
                "SELECT * FROM review_tasks WHERE entity_id='doc-1' AND state='open' ORDER BY created_at DESC"
            ).fetchone()
        )


def parts_of(task: dict) -> dict[str, dict]:
    return {part["key"]: part["params"] for part in json.loads(task["reason_params_json"])["parts"]}


TWO_PAGES = [page(1), page(2)]


def test_a_label_the_parser_learnt_to_read_does_not_duplicate_a_checked_value(tmp_path: Path, rescanner):
    settings, user_id, _ = build(tmp_path)
    empty_document(settings)
    stored(settings, user_id, "Скупчення лейкоцитів (WBC", 0.4, unit="кл/мкл")
    stored(settings, user_id, "Виявлення ДНК Trichomonas vaginalis", text="не виявлено")
    stored(settings, user_id, "Mycoplasma genitalium (ПЛР) (кількісне", text="не виявлено")
    stored(settings, user_id, "Еритроцити/гемоглобін (C-BLD) - мг/дл Приносний", text="не виявлені")
    # The twin an older re-read already inserted beside the checked row.
    stored(settings, user_id, "Скупчення лейкоцитів (WBC Clumps)", 0.4, unit="кл/мкл", status="extracted")

    rescanner(
        [
            parsed("Скупчення лейкоцитів (WBC Clumps)", 0.4, unit="кл/мкл"),
            parsed("Виявлення ДНК Trichomonas vaginalis (ПЛР) (якісне визначення)", text="не виявлено"),
            parsed("Mycoplasma genitalium (ПЛР) (кількісне визначення)", text="не виявлено", unit="ГЕ/мл"),
            parsed("Еритроцити/гемоглобін (C-BLD)", text="не виявлені", unit="мг/дл",
                   reference="не виявлені (-) 0.03 = +-"),
        ],
        pages=TWO_PAGES,
    )
    result = pipeline.reingest_document(settings, user_id, "doc-1")

    after = rows(settings)
    assert len(after) == 4, [row["raw_name"] for row in after]
    assert {row["verification_status"] for row in after} == {"verified"}
    names = {row["raw_name"] for row in after}
    assert names == {
        "Скупчення лейкоцитів (WBC Clumps)",
        "Виявлення ДНК Trichomonas vaginalis (ПЛР) (якісне визначення)",
        "Mycoplasma genitalium (ПЛР) (кількісне визначення)",
        "Еритроцити/гемоглобін (C-BLD)",
    }
    blood = next(row for row in after if row["raw_name"] == "Еритроцити/гемоглобін (C-BLD)")
    assert blood["vendor_reference_text"] == "не виявлені (-) 0.03 = +-"
    assert result["observations"] == 0 and result["refreshed"] == 4


def test_a_specimen_line_checked_as_an_analyte_is_named_not_kept_silently(tmp_path: Path, rescanner):
    """n16: «Приносний матеріал, сеча» ×3 were the glucose/ketone/bilirubin pads."""
    settings, user_id, _ = build(tmp_path)
    empty_document(settings)
    for value in ("не виявлена", "не виявлені", "не виявлений"):
        stored(settings, user_id, "Приносний матеріал, сеча", text=value)
    rescanner(
        [
            parsed("Глюкоза (C-GLU)", text="не виявлена", unit="мг/дл"),
            parsed("Кетони (C-KET)", text="не виявлені", unit="мг/дл"),
            parsed("Білірубін (C-BIL)", text="не виявлений", unit="мг/дл"),
        ],
        pages=TWO_PAGES,
    )
    pipeline.reingest_document(settings, user_id, "doc-1")

    after = rows(settings)
    # Kept (a person checked them) and the correct readings arrive unchecked.
    assert sorted(row["verification_status"] for row in after) == ["extracted"] * 3 + ["verified"] * 3
    task = open_task(settings)
    orphaned = parts_of(task)["review.reread_orphaned_n"]
    assert orphaned["count"] == 3
    assert {item["label"] for item in orphaned["items"]} == {"Приносний матеріал, сеча"}
    uk = pipeline.review_reason_text(task, "uk")
    en = pipeline.review_reason_text(task, "en")
    assert "3 звірені значення під час повторного зчитування не знайшлися" in uk and "«Приносний матеріал, сеча», с. 1" in uk
    assert "no longer finds 3 checked values" in en and "page 1" in en


def test_a_reference_the_old_parser_cut_in_half_is_refreshed_and_reported(tmp_path: Path, rescanner):
    """n70: «жінки < 100.0» on a man's sediment count; the page prints both halves."""
    settings, user_id, _ = build(tmp_path)
    empty_document(settings)
    stored(settings, user_id, "Бактерії в мкл (BACT)", 130.1, unit="кл/мкл", page_number=2,
           reference="жінки < 100.0")
    rescanner(
        [parsed("Бактерії в мкл (BACT)", 130.1, unit="кл/мкл", page_number=2,
                reference="жінки < 100.0 чоловіки < 26.4")],
        pages=TWO_PAGES,
    )
    pipeline.reingest_document(settings, user_id, "doc-1")

    (row,) = rows(settings)
    assert row["verification_status"] == "verified"
    assert row["vendor_reference_text"] == "жінки < 100.0 чоловіки < 26.4"
    assert row["parser_version"] == pipeline.PARSER_VERSION
    # Recorded, not asked: the value a person checked did not change.
    with connect(settings) as connection:
        details = json.loads(connection.execute(
            "SELECT details_json FROM audit_events WHERE action='observation_reread_refreshed'"
        ).fetchone()[0])
    assert details["references"][0]["old"] == "жінки < 100.0"


def test_a_checked_value_read_differently_is_listed_and_never_applied(tmp_path: Path, rescanner):
    """A Garmin category the old parser misread on a checked reading."""
    settings, user_id, _ = build(tmp_path)
    empty_document(settings)
    stored(settings, user_id, "Blood pressure category", text="Нормальний", observed_at="2024-07-07T15:05:00")
    stored(settings, user_id, "Blood pressure category", text="Нормальний", observed_at="2024-07-07T22:37:00")
    rescanner(
        [
            parsed("Blood pressure category", text="Високий нормальний", observed_at="2024-07-07T15:05:00"),
            parsed("Blood pressure category", text="Нормальний", observed_at="2024-07-07T22:37:00"),
            # A reading whose category the old parser never found.
            parsed("Blood pressure category", text="Ступінь 1", observed_at="2024-07-06T18:39:00"),
        ],
        pages=TWO_PAGES,
    )
    pipeline.reingest_document(settings, user_id, "doc-1")

    after = rows(settings)
    by_moment = {row["observed_at"]: (row["value_text"], row["verification_status"]) for row in after}
    assert by_moment == {
        "2024-07-07T15:05:00": ("Нормальний", "verified"),
        "2024-07-07T22:37:00": ("Нормальний", "verified"),
        "2024-07-06T18:39:00": ("Ступінь 1", "extracted"),
    }
    changed = parts_of(open_task(settings))["review.reread_changed_n"]
    assert changed["count"] == 1
    assert changed["items"][0]["old"]["text"] == "Нормальний"
    assert changed["items"][0]["new"]["text"] == "Високий нормальний"
    uk = pipeline.review_reason_text(open_task(settings), "uk")
    assert "Нормальний > Високий нормальний" in uk


def test_unit_suffixed_labels_pair_with_the_parse_that_drops_the_suffix(tmp_path: Path, rescanner):
    """n79: «Питома вага, г/мл» checked; the current parser prints «Питома вага»."""
    settings, user_id, _ = build(tmp_path)
    empty_document(settings)
    stored(settings, user_id, "Питома вага, г/мл", 1.035, unit="г/мл")
    stored(settings, user_id, "Клітини перехідного епітелію , в п/з", text="не виявлено")
    stored(settings, user_id, "Нейтрофіли, сегментоядерні", 58.0, unit="%")
    stored(settings, user_id, "Нейтрофіли, паличкоядерні", 2.0, unit="%")
    rescanner(
        [
            parsed("Питома вага", 1.035, unit="г/мл"),
            parsed("Клітини перехідного епітелію", text="не виявлено", unit="в п/з"),
            parsed("Нейтрофіли, сегментоядерні", 58.0, unit="%"),
            parsed("Нейтрофіли, паличкоядерні", 2.0, unit="%"),
            parsed("Слиз", text="+", unit="в п/з", reference="(не виявлено)"),
        ],
        pages=TWO_PAGES,
    )
    pipeline.reingest_document(settings, user_id, "doc-1")

    after = rows(settings)
    assert [(row["raw_name"], row["verification_status"]) for row in after] == [
        ("Питома вага", "verified"),
        ("Клітини перехідного епітелію", "verified"),
        ("Нейтрофіли, сегментоядерні", "verified"),
        ("Нейтрофіли, паличкоядерні", "verified"),
        ("Слиз", "extracted"),
    ]


def test_two_equal_counts_with_different_names_keep_their_own_names(tmp_path: Path, rescanner):
    """n16: «Еритроцити в мкл (RBC)» and «Незмінені еритроцити (NL RBC)», both 4.4."""
    settings, user_id, _ = build(tmp_path)
    empty_document(settings)
    stored(settings, user_id, "Еритроцити в мкл (RBC)", 4.4, unit="кл/мкл")
    stored(settings, user_id, "Незмінені еритроцити (NL RBC)", 4.4, unit="кл/мкл")
    rescanner(
        [
            parsed("Незмінені еритроцити (NL RBC)", 4.4, unit="кл/мкл"),
            parsed("Еритроцити в мкл (RBC)", 4.4, unit="кл/мкл"),
        ],
        pages=TWO_PAGES,
    )
    pipeline.reingest_document(settings, user_id, "doc-1")
    assert sorted(row["raw_name"] for row in rows(settings)) == [
        "Еритроцити в мкл (RBC)", "Незмінені еритроцити (NL RBC)"
    ]


def test_a_unit_the_parse_now_prints_on_a_checked_number_is_a_change(tmp_path: Path, rescanner):
    settings, user_id, _ = build(tmp_path)
    empty_document(settings)
    stored(settings, user_id, "Кетони", 0.5, unit=None)
    stored(settings, user_id, "АЛТ", 25.0, unit="од/л")
    rescanner(
        [parsed("Кетони", 0.5, unit="ммоль/л"), parsed("АЛТ", 25.0, unit=None)],
        pages=TWO_PAGES,
    )
    pipeline.reingest_document(settings, user_id, "doc-1")
    after = {row["raw_name"]: row for row in rows(settings)}
    # The checked unit stands where the parse prints none; a unit that appears
    # is shown to a person rather than written over the check.
    assert after["АЛТ"]["unit_raw"] == "од/л" and after["АЛТ"]["verification_status"] == "verified"
    assert after["Кетони"]["unit_raw"] is None and len(after) == 2
    changed = parts_of(open_task(settings))["review.reread_changed_n"]
    assert [item["label"] for item in changed["items"]] == ["Кетони"]


# --- refusing a destructive re-read (DOCC-01) --------------------------------


def test_a_document_that_had_values_and_now_reads_none_is_refused(tmp_path: Path, rescanner):
    settings, user_id, _ = build(tmp_path)
    before = rows(settings)
    rescanner([], pages=[page(number) for number in range(1, 9)])
    with pytest.raises(pipeline.RereadRefused) as refused:
        pipeline.reingest_document(settings, user_id, "doc-1")
    assert refused.value.detail_key == "intake.failed_reread_empty"
    assert [row["id"] for row in rows(settings)] == [row["id"] for row in before]


def test_a_companion_summary_the_parser_recognised_may_empty_the_document(
        tmp_path: Path, rescanner, monkeypatch):
    """A lab's illustrated summary of another report: the parser now knows it
    holds nothing of its own, so its old interleaved rows go."""
    from anamna.ingest.parsers import COMPANION_SUMMARY, ParseIssue

    settings, user_id, _ = build(tmp_path)
    rescanner([], pages=[page(1)])

    def companion(classification_, per_page_, pages_, *, issues=None, **_):
        issues.append(ParseIssue(1, COMPANION_SUMMARY, "", ""))
        return []

    monkeypatch.setattr(pipeline, "parse_pages", companion)
    pipeline.reingest_document(settings, user_id, "doc-1")
    with connect(settings) as connection:
        assert connection.execute("SELECT COUNT(*) FROM observations WHERE document_id='doc-1'").fetchone()[0] == 0
    assert list(parts_of(open_task(settings))) == ["review.companion_summary"]


def test_the_queue_reports_a_refused_reread_with_its_reason(tmp_path: Path, rescanner):
    from anamna.ingest import intake

    settings, user_id, _ = build(tmp_path)
    rescanner([], pages=[page(1)])
    with connect(settings) as connection:
        patient_id = connection.execute("SELECT patient_id FROM documents WHERE id='doc-1'").fetchone()[0]
    intake.enqueue(
        settings, owner_user_id=user_id, patient_id=patient_id, batch_id="b", kind="rescan",
        filename="report.pdf", document_id="doc-1", start=False,
    )
    intake.drain_now(settings)
    with connect(settings) as connection:
        job = connection.execute("SELECT state, detail_key FROM upload_jobs").fetchone()
        assert connection.execute("SELECT COUNT(*) FROM observations WHERE document_id='doc-1'").fetchone()[0] == 8
    assert (job["state"], job["detail_key"]) == ("failed", "intake.failed_reread_empty")


def test_a_kind_no_parser_knows_does_not_empty_the_document(tmp_path: Path, rescanner):
    """«Лабораторний звіт», an AI suggestion stored as a person's ruling."""
    settings, user_id, _ = build(tmp_path)
    with connect(settings) as connection:
        connection.execute(
            "UPDATE documents SET clinical_type='Лабораторний звіт', classified_by='human' WHERE id='doc-1'"
        )
        connection.commit()
    rescanner([parsed("Ferritin", 42.0, unit="ng/mL")], pages=[page(number) for number in range(1, 9)])
    pipeline.reingest_document(settings, user_id, "doc-1")
    with connect(settings) as connection:
        assert connection.execute("SELECT clinical_type FROM documents WHERE id='doc-1'").fetchone()[0] == "laboratory"
    assert [row["raw_name"] for row in rows(settings)] == ["Ferritin"]


def test_a_person_filing_it_as_a_kind_with_nothing_to_parse_may_empty_it(tmp_path: Path, rescanner):
    settings, user_id, _ = build(tmp_path)
    with connect(settings) as connection:
        connection.execute(
            "UPDATE documents SET clinical_type='ultrasound', classified_by='human' WHERE id='doc-1'"
        )
        connection.commit()
    rescanner([], pages=[page(number) for number in range(1, 9)], klass=classification(clinical_type="ultrasound"))
    pipeline.reingest_document(settings, user_id, "doc-1")
    assert rows(settings) == []


# --- dates ---------------------------------------------------------------------


def test_a_report_date_a_person_set_survives_a_reread_that_reads_none(tmp_path: Path, rescanner):
    settings, user_id, _ = build(tmp_path)
    with connect(settings) as connection:
        connection.execute(
            "UPDATE documents SET report_date='2025-02-01', report_date_set_by='human' WHERE id='doc-1'"
        )
        connection.commit()
    rescanner(
        [parsed("Ferritin", 42.0)],
        pages=[page(number) for number in range(1, 9)],
        klass=classification(report_date=None),
    )
    pipeline.reingest_document(settings, user_id, "doc-1")
    with connect(settings) as connection:
        assert connection.execute("SELECT report_date FROM documents WHERE id='doc-1'").fetchone()[0] == "2025-02-01"
    assert rows(settings)[0]["observed_at"] == "2025-02-01"


def test_editing_the_date_records_that_a_person_set_it(tmp_path: Path):
    settings, user_id, client = build(tmp_path)
    with connect(settings) as connection:
        csrf = connection.execute("SELECT csrf_token FROM sessions WHERE user_id=?", (user_id,)).fetchone()[0]
    response = client.post(
        "/documents/doc-1/metadata",
        data={"title": "Lipids", "report_date": "2025-03-01", "csrf_token": csrf},
        follow_redirects=False,
    )
    assert response.status_code == 303
    with connect(settings) as connection:
        assert connection.execute(
            "SELECT report_date_set_by FROM documents WHERE id='doc-1'"
        ).fetchone()[0] == "human"


def test_the_collection_date_dates_new_rows_and_moves_checked_ones(tmp_path: Path, rescanner):
    """ALEX²: drawn on the 28th, printed on the 31st, charted on the 31st."""
    settings, user_id, _ = build(tmp_path)
    empty_document(settings)
    stored(settings, user_id, "Bet v 1", 0.1, unit="kUA/l", observed_at="2025-08-31")
    alex = classification(report_date="2025-08-31", collected_at="2025-08-28")
    rescanner(
        [parsed("Bet v 1", 0.1, unit="kUA/l"), parsed("Der p 1", 0.1, unit="kUA/l")],
        pages=TWO_PAGES, klass=alex,
    )
    pipeline.reingest_document(settings, user_id, "doc-1")
    assert {row["raw_name"]: row["observed_at"] for row in rows(settings)} == {
        "Bet v 1": "2025-08-28", "Der p 1": "2025-08-28"
    }
    with connect(settings) as connection:
        details = json.loads(connection.execute(
            "SELECT details_json FROM audit_events WHERE action='observation_reread_refreshed'"
        ).fetchone()[0])
    assert details["dates"] == [{"old": "2025-08-31", "new": "2025-08-28", "count": 1}]
    with connect(settings) as connection:
        assert connection.execute("SELECT collected_at FROM documents WHERE id='doc-1'").fetchone()[0] == "2025-08-28"


# --- review reasons as keys --------------------------------------------------


def test_reasons_render_from_the_catalogue_in_both_locales(tmp_path: Path):
    settings, user_id, _ = build(tmp_path)
    with connect(settings) as connection:
        for count in (1, 3, 5):
            pipeline.open_review_task(
                connection, user_id, "doc-1", [pipeline.reason_part("review.verify_n", count=count)]
            )
        connection.commit()
        tasks = {
            json.loads(row["reason_params_json"])["parts"][0]["params"]["count"]: dict(row)
            for row in connection.execute("SELECT * FROM review_tasks WHERE reason_key='review.verify_n'")
        }
    assert pipeline.review_reason_text(tasks[1], "en").startswith("Verify 1 extracted observation against")
    assert pipeline.review_reason_text(tasks[3], "en").startswith("Verify 3 extracted observations against")
    assert pipeline.review_reason_text(tasks[3], "uk").startswith("Звірте 3 зчитані значення")
    assert pipeline.review_reason_text(tasks[5], "uk").startswith("Звірте 5 зчитаних значень")
    assert "(s)" not in pipeline.review_reason_text(tasks[5], "en")
    assert ".." not in pipeline.review_reason_text(tasks[5], "uk")
    # The English sentence older readers know is still stored.
    assert tasks[3]["reason"] == "Verify 3 extracted observation(s) against page evidence before marking trusted."


def test_old_reasons_are_read_back_into_keys_on_start(tmp_path: Path):
    settings, user_id, _ = build(tmp_path)
    old = (
        "Re-read with parser 2026.08.04-3: verify 2 observation(s) the earlier parse did not produce. "
        "1 observation(s) the earlier parse produced are not in this one, so check the page to see "
        "whether they are really absent."
    )
    with connect(settings) as connection:
        for task_id, reason in (("old-1", old), ("old-2", "Something a person typed.")):
            connection.execute(
                """INSERT INTO review_tasks(id, owner_user_id, entity_type, entity_id, reason, created_at)
                   VALUES (?, ?, 'document', 'doc-1', ?, '2026-01-01')""",
                (task_id, user_id, reason),
            )
        assert pipeline.backfill_review_reason_keys(connection) >= 2
        assert pipeline.backfill_review_reason_keys(connection) == 0
        connection.commit()
        parsed_row = dict(connection.execute("SELECT * FROM review_tasks WHERE id='old-1'").fetchone())
        opaque = dict(connection.execute("SELECT * FROM review_tasks WHERE id='old-2'").fetchone())
        fixture = dict(connection.execute("SELECT * FROM review_tasks WHERE id='task-1'").fetchone())
    assert parsed_row["reason_key"] == "review.rescanned_n"
    assert [part["key"] for part in json.loads(parsed_row["reason_params_json"])["parts"]] == [
        "review.rescanned_n", "review.vanished_n"
    ]
    uk = pipeline.review_reason_text(parsed_row, "uk")
    assert "звірте 2 значення" in uk and "2026.08.04-3" in uk and "observation" not in uk
    assert opaque["reason_key"] is None
    assert pipeline.review_reason_text(opaque, "en") == "Something a person typed."
    # The fixture's sentence has no final full stop and is still read.
    assert fixture["reason_key"] == "review.verify_n"


# --- stored precision, inclusivity, concept-keyed judgement -----------------


@dataclass(frozen=True)
class Printed(ParsedObservation):
    value_printed: str | None = None


def test_strict_bounds_and_printed_precision_are_stored(tmp_path: Path, rescanner):
    settings, user_id, _ = build(tmp_path)
    empty_document(settings)
    yeast = ParsedObservation(
        raw_name="Дріжджеподібні клітини (YLC)", value_numeric=0.2, value_text=None, comparator=None,
        unit_raw="кл/мкл", reference_text="< 0.2", reference_low=None, reference_high=0.2, page_number=1,
        evidence_text="YLC 0.2", confidence=0.9,
    )
    ph = Printed(
        raw_name="pH", value_numeric=1.8, value_text=None, comparator=None, unit_raw=None,
        reference_text="0.5 - 7.0", reference_low=0.5, reference_high=7.0, page_number=1,
        evidence_text="pH 1,80", confidence=0.9, value_printed="1,80",
    )
    from anamna.ingest.parsers import finalise

    # Every parsed row goes through `finalise`, which reads the printed sign.
    rescanner([finalise(yeast), ph], pages=TWO_PAGES)
    pipeline.reingest_document(settings, user_id, "doc-1")
    after = {row["raw_name"]: row for row in rows(settings)}
    assert (after["Дріжджеподібні клітини (YLC)"]["vendor_reference_low_inclusive"],
            after["Дріжджеподібні клітини (YLC)"]["vendor_reference_high_inclusive"]) == (1, 0)
    assert (after["pH"]["vendor_reference_low_inclusive"], after["pH"]["vendor_reference_high_inclusive"]) == (1, 1)
    assert after["pH"]["value_printed"] == "1,80"

    from anamna.i18n import activate_locale, reset_locale
    from anamna.web.app import format_reading

    for locale, expected in (("en", "1.80"), ("uk", "1,80")):
        token = activate_locale(locale)
        try:
            assert format_reading(after["pH"], None) == expected
        finally:
            reset_locale(token)


def test_reference_inclusivity_reads_the_printed_sign():
    assert pipeline.reference_inclusivity("< 0.2", None, 0.2) == (1, 0)
    assert pipeline.reference_inclusivity("≤ 0.2", None, 0.2) == (1, 1)
    assert pipeline.reference_inclusivity("до 5", None, 5.0) == (1, 1)
    assert pipeline.reference_inclusivity("> 1.0", 1.0, None) == (0, 1)
    assert pipeline.reference_inclusivity("1.0 - 5.0", 1.0, 5.0) == (1, 1)


def test_the_ana_scale_is_judged_by_concept_whatever_the_printed_label():
    ana = ParsedObservation(
        raw_name="Антинуклеарні антитіла (ANA)", value_numeric=0.4, value_text=None, comparator=None,
        unit_raw="index", reference_text="негативний < 1.0; сумнівний 1.0-1.2; позитивний > 1.2",
        reference_low=1.0, reference_high=1.2, page_number=1, evidence_text="ANA 0.4", confidence=0.9,
    )
    assert pipeline.interpretation(ana, "antinuclear-antibodies") == "within_vendor_range"
    assert pipeline.interpretation(replace_value(ana, 1.1), "antinuclear-antibodies") == "borderline"
    assert pipeline.interpretation(replace_value(ana, 2.0), "antinuclear-antibodies") == "positive"


def replace_value(observation: ParsedObservation, value: float) -> ParsedObservation:
    from dataclasses import replace

    return replace(observation, value_numeric=value)


# --- relations and stale detection -------------------------------------------


def _second_document(settings, doc_id: str, **fields) -> None:
    with connect(settings) as connection:
        connection.execute(
            """INSERT INTO documents(id, owner_user_id, patient_id, vendor_id, original_filename, source_path,
                   mime_type, byte_size, sha256, page_count, title, clinical_type, extraction_strategy,
                   classification_confidence, report_date, imported_at, status, order_identifier, report_number)
               SELECT ?, owner_user_id, patient_id, vendor_id, ?, source_path, mime_type, 1, ?, 1, 'Other',
                      ?, extraction_strategy, 1, ?, '2020-01-01T00:00:00+00:00', ?, ?, ?
                 FROM documents WHERE id='doc-1'""",
            (
                doc_id, f"{doc_id}.pdf", f"sha-{doc_id}", fields.get("clinical_type", "laboratory"),
                fields.get("report_date", "2025-02-13"), fields.get("status", "final"),
                fields.get("order_identifier"), fields.get("report_number"),
            ),
        )
        connection.commit()


def relations(settings) -> set[tuple[str, str, str]]:
    with connect(settings) as connection:
        return {
            (row[0], row[1], row[2])
            for row in connection.execute(
                "SELECT source_document_id, target_document_id, relationship FROM document_relations"
            )
        }


def test_relations_are_recorded_for_covers_reports_and_shared_results(tmp_path: Path):
    settings, user_id, _ = build(tmp_path)
    _second_document(settings, "cover", status="result_not_present", order_identifier="3600000001")
    _second_document(settings, "copy", clinical_type="pathology", report_number="№ 10000/25")
    _second_document(settings, "subset")
    _second_document(settings, "reissued", clinical_type="pathology", report_number="№ 10000/25",
                     report_date="2025-02-23")
    with connect(settings) as connection:
        connection.execute(
            """UPDATE documents SET order_identifier='3600000001', report_number='№ 10000/25',
                   collected_at='2025-02-10' WHERE id IN ('doc-1', 'reissued')"""
        )
        # `subset` holds two of doc-1's eight results.
        connection.execute(
            """INSERT INTO observations(id, owner_user_id, patient_id, document_id, page_number, concept_id,
                   raw_name, value_type, value_numeric, value_text, unit_raw, unit_canonical, observed_at,
                   verification_status, extraction_method, confidence, evidence_text, parser_version, created_at)
               SELECT id || '-copy', owner_user_id, patient_id, 'subset', page_number, concept_id, raw_name,
                      value_type, value_numeric, value_text, unit_raw, unit_canonical, observed_at,
                      'extracted', extraction_method, confidence, evidence_text, parser_version, created_at
                 FROM observations WHERE document_id='doc-1' ORDER BY rowid LIMIT 2"""
        )
        pipeline.record_document_relations(connection, user_id, "doc-1")
        connection.commit()
    found = relations(settings)
    assert ("doc-1", "cover", "attachment_of") in found
    assert ("doc-1", "copy", "duplicate") in found
    # Same report number and study, issued on another day.
    assert ("doc-1", "reissued", "reprint") in found
    assert ("doc-1", "subset", "contains") in found
    # Re-recording replaces its own rows rather than adding to them.
    with connect(settings) as connection:
        pipeline.record_document_relations(connection, user_id, "doc-1")
        connection.commit()
    assert relations(settings) == found


def test_a_document_the_classifier_now_reads_differently_is_stale(tmp_path: Path):
    settings, user_id, client = build(tmp_path)
    text = "Консультація сімейного лікаря\nДата візиту: 23/02/2025\n"
    with connect(settings) as connection:
        connection.execute("DELETE FROM observations WHERE document_id='doc-1'")
        connection.execute(
            """INSERT INTO document_pages(document_id, page_number, native_text, extraction_method,
                   native_char_count, image_count, review_status)
               VALUES ('doc-1', 1, ?, 'native_pdf_text', ?, 0, 'not_reviewed')""",
            (text, len(text)),
        )
        connection.execute("UPDATE documents SET content_sha256='drift-test' WHERE id='doc-1'")
        connection.commit()
        pipeline._DRIFT_CACHE.clear()
        assert pipeline.classification_drift_ids(connection, user_id) == ["doc-1"]
        expected, _ = pipeline.classify_pages("report.pdf", "application/pdf", [
            {"page_number": 1, "native_text": text, "ocr_text": None, "native_char_count": len(text),
             "image_count": 0, "extraction_method": "native_pdf_text"}
        ], {})
        connection.execute(
            """UPDATE documents SET title=?, clinical_type=?, report_date=?, order_identifier=?,
                   collected_at=?, issued_at=? WHERE id='doc-1'""",
            (expected.title, expected.clinical_type, expected.report_date, expected.order_identifier,
             expected.collected_at, expected.issued_at),
        )
        connection.commit()
        assert pipeline.classification_drift_ids(connection, user_id) == []
        # A title a person chose is never a reason to re-read.
        connection.execute("UPDATE documents SET title='Mine', title_set_by='human' WHERE id='doc-1'")
        connection.commit()
        assert pipeline.classification_drift_ids(connection, user_id) == []


def test_page_classifications_keep_the_fields_a_page_read_for_itself():
    pages = [
        {"page_number": 1, "native_text": "Сінево\nДата замовлення: 28.08.2025 08:39\nПоказник Результат Од.",
         "ocr_text": "", "native_char_count": 80, "image_count": 0},
        {"page_number": 2, "native_text": "Показник Результат Од.\nГемоглобін 150 г/л 130 - 170",
         "ocr_text": "", "native_char_count": 60, "image_count": 0},
    ]
    per_page = pipeline.page_classifications("report.pdf", "application/pdf", pages, {})
    assert per_page[0].collected_at and per_page[0].collected_at.startswith("2025-08-28")
    assert per_page[1].collected_at == per_page[0].collected_at


# --- F1 parser integration ----------------------------------------------------


def test_a_report_is_parsed_whole_with_the_patients_age_and_sex(monkeypatch):
    """DOCC-36: a reference block crossing a page break is read in one call."""
    calls = []

    def fake(vendor, clinical_type, pages, *, issues=None, age_years=None, sex=None):
        calls.append(([page["page_number"] for page in pages], age_years, sex))
        return []

    monkeypatch.setattr(pipeline, "parse_document", fake)
    lab = classification(report_date="2025-03-10")
    other = classification(report_date="2025-03-20")
    pipeline.parse_pages(lab, [lab, lab, other], [page(1), page(2), page(3)],
                         issues=[], date_of_birth="1990-03-14", sex="male")
    assert calls == [([1, 2], 34, "male"), ([3], 35, "male")]


def test_a_line_the_parser_could_not_read_becomes_a_named_review_reason(tmp_path: Path, rescanner, monkeypatch):
    from anamna.ingest.parsers import ParseIssue

    settings, user_id, _ = build(tmp_path)
    owned = [parsed("Ferritin", 42.0)]
    rescanner(owned, pages=[page(number) for number in range(1, 9)])

    def with_issues(classification_, per_page_, pages_, *, issues=None, **_):
        issues.append(ParseIssue(1, "unparsed_known_analyte", "Гемоглобін", "Гемоглобін ### г/л"))
        issues.append(ParseIssue(1, "unparsed_known_analyte", "Гемоглобін", "Гемоглобін ### г/л"))
        issues.append(ParseIssue(2, "unknown_antibiotic", "ImineHem", "ImineHem R"))
        return [(item, per_page_[item.page_number - 1]) for item in owned]

    monkeypatch.setattr(pipeline, "parse_pages", with_issues)
    pipeline.reingest_document(settings, user_id, "doc-1")
    task = open_task(settings)
    parts = parts_of(task)
    assert parts["review.parse_unread_n"]["count"] == 1
    assert parts["review.parse_antibiotic_n"]["items"][0]["label"] == "ImineHem"
    uk = pipeline.review_reason_text(task, "uk")
    assert "1 надрукований результат програма розпізнала" in uk and "«ImineHem», с. 2" in uk
    assert "1 antibiotic name" in pipeline.review_reason_text(task, "en")


def test_the_parsers_own_reading_and_note_are_stored(tmp_path: Path, rescanner):
    from dataclasses import replace as with_fields

    settings, user_id, _ = build(tmp_path)
    empty_document(settings)
    pad = with_fields(
        parsed("Лейкоцити (C-LEU)", 25.0, unit="кл/мкл", reference="не виявлені 25 = + 75 = ++", high=25.0),
        vendor_interpretation="high", specimen="сеча", note="після навантаження",
    )
    rescanner([pad], pages=TWO_PAGES)
    pipeline.reingest_document(settings, user_id, "doc-1")
    (row,) = rows(settings)
    assert (row["vendor_interpretation"], row["specimen"], row["note"]) == ("high", "сеча", "після навантаження")


def test_a_continuation_page_without_a_kind_joins_the_previous_report():
    """n92: page 2 of an abdominal ultrasound (kidneys, bladder, conclusion)."""
    first = {"page_number": 1, "native_text": "ЕКСПЕРТ\nПРОТОКОЛ\nУЛЬТРАЗВУКОВОГО ДОСЛІДЖЕННЯ ОРГАНІВ ЧЕРЕВНОЇ "
             "ПОРОЖНИНИ\nПечінка збільшена", "ocr_text": "", "native_char_count": 200, "image_count": 0}
    second = {"page_number": 2, "native_text": "Сечовий міхур:\nСтінка потовщена – 4.5 мм.\nВИСНОВОК:\n"
              "Дата дослідження: Іваненко Ольга\nЛікар:\n01.02.2025\nДиректор «Лікарня ЕКСПЕРТ»",
              "ocr_text": "", "native_char_count": 200, "image_count": 0}
    per_page = pipeline.page_classifications("us.pdf", "application/pdf", [first, second], {})
    assert [item.clinical_type for item in per_page] == ["ultrasound", "ultrasound"]
    assert per_page[0].report_date == per_page[1].report_date


def test_a_patients_band_from_a_multi_population_block_is_shown_and_others_hidden():
    from anamna.web.app import _vendor_bounds

    block = "Діти: <1 року: 3.0 - 5.4 1-12 років: 3.9 - 5.3 Дорослі: Чоловіки: 4.0 - 5.0 Жінки: 3.5 - 4.7"
    row = {"vendor_reference_low": 4.0, "vendor_reference_high": 5.0, "vendor_interpretation": "high",
           "vendor_reference_text": block, "value_numeric": 5.06}
    # RBC 5.06 against the laboratory's male 4.0-5.0: the bounds stand.
    assert _vendor_bounds(row, 34, "male") == (4.0, 5.0, "high")
    # The same stored bounds are not this woman's band.
    assert _vendor_bounds(row, 34, "female") == (None, None, None)


def test_renamed_rows_pair_by_their_printed_line_code_or_lone_number(tmp_path: Path, rescanner):
    """St Paraskeva's invented English names, ALEX codes, a vitamin D renamed."""
    settings, user_id, _ = build(tmp_path)
    empty_document(settings)
    stored(settings, user_id, "Erythrocyte sedimentation rate", 10.0, unit="мм/год")
    stored(settings, user_id, "Ani s 1", 0.1, unit="kUA/L")
    stored(settings, user_id, "Total 25-hydroxyvitamin D", 32.122, unit="ng/mL")
    with connect(settings) as connection:
        connection.execute(
            "UPDATE observations SET evidence_text='ШОЕ (SER): мм/год 10 1-10' "
            "WHERE raw_name='Erythrocyte sedimentation rate'"
        )
        connection.commit()
    esr = ParsedObservation(
        raw_name="ШОЕ (SER)", value_numeric=10.0, value_text=None, comparator=None, unit_raw="мм/год",
        reference_text="1-10", reference_low=1.0, reference_high=10.0, page_number=1,
        evidence_text="ШОЕ (SER): мм/год 10 1-10", confidence=0.9,
    )
    rescanner(
        [
            esr,
            parsed("Anisakis simplex Ani s 1 Kunitz Serin Protease Inhibitor", 0.1, unit="kUA/L"),
            parsed("Вітамін D загальний", 32.122, unit="нг/мл"),
        ],
        pages=TWO_PAGES,
    )
    pipeline.reingest_document(settings, user_id, "doc-1")
    after = rows(settings)
    assert len(after) == 3 and {row["verification_status"] for row in after} == {"verified"}
    renamed = next(row for row in after if row["raw_name"] == "ШОЕ (SER)")
    # The checked concept stands, and the printed label is learned for it.
    assert renamed["concept_id"] == "erythrocyte-sedimentation-rate"
