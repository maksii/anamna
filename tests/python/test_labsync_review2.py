"""Lab connections after the second value-by-value review (2026-11-07): the
printed band decides a lab flag on its own bound, the cross-check pairs with
the order's own document and never a copy, the lab's culture comments reach
the value, the order's sampling time fills a document that prints none, a
bare row name keeps its test, and a report taking an order over never loses
a value the lab's record alone holds.

Synthetic throughout (names, numbers and orders invented); HTTP and the intake
queue are stubbed as in ``test_labsync``.
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path

from anamna import labsync
from anamna.db import connect, utc_now
from anamna.ingest.parsers import ReferenceLimits, parse_document
from anamna.ingest.pipeline import lab_order_collected_at
from anamna.labsync import common
from anamna.reference import canonical_unit

from test_labsync import connect_esculab, esculab_routes, make, order, seed_doc, stub_intake
from test_labsync_crosscheck_fixes import lab_row, observation, set_reference
from test_labsync_nofile import INDICATORS, NOFILE, connected, state, sync


def obs_row(value, low=None, high=None, text=None, low_inclusive=None, high_inclusive=None):
    return {"value_numeric": value, "vendor_reference_low": low, "vendor_reference_high": high,
            "vendor_reference_text": text, "vendor_reference_low_inclusive": low_inclusive,
            "vendor_reference_high_inclusive": high_inclusive}


# --- 1. the printed band decides a flag on its own bound ---------------------------


def test_a_value_on_an_inclusive_printed_bound_is_inside_the_band():
    inside = labsync._inside_printed_band
    assert inside(obs_row(1.0, 0.0, 1.0, "0-1"), {}, 34, "female")            # basophils on «0-1»
    assert inside(obs_row(1.0, 1.0, 5.0, "1-5"), {}, 34, "female")            # eosinophils on «1-5»
    assert inside(obs_row(1.025, 1.005, 1.025, "1.005 - 1.025"), {}, 34, "female")
    assert inside(obs_row(0.0, None, None, "0.0"), {}, 34, "female")          # NRBC against a lone zero
    assert inside(obs_row(9.0, None, None, "Діти до 12 р.: 2-11 Дорослі: 3-9"), {}, 34, "female")
    # A strict bound excludes its value, and a value past the band is outside.
    assert not inside(obs_row(35.0, None, 35.0, "< 35", high_inclusive=0), {}, 34, "female")
    assert not inside(obs_row(10.0, 3.0, 9.0, "3-9"), {}, 34, "female")
    # No interval on the report: the lab's own decides.
    assert inside(obs_row(5.5), {"norm": ["5.5-7.0"]}, None, None)
    assert not inside(obs_row(0.3), {"norm": ["0-0.14"]}, None, None)
    assert labsync._band_limits("Жінки: <35 Чоловіки: <45", 34, "female") == ReferenceLimits(None, 35.0, True, False)


def test_a_lab_record_takes_no_flag_its_own_interval_contradicts():
    on_bound = labsync._record_value(common.lab_row(test="рН", result="5.5", state="critical", norm=["5.5-7.0"]))
    beyond = labsync._record_value(common.lab_row(test="рН", result="8.5", state="critical", norm=["5.5-7.0"]))
    assert on_bound.vendor_interpretation is None and beyond.vendor_interpretation == "high"


def test_an_esculab_flag_on_a_printed_bound_is_taken_back_on_recheck(tmp_path: Path, monkeypatch):
    settings, user_id, _ = make(tmp_path)
    document_id = seed_doc(settings, user_id, vendor="Esculab", order="9810", day="2026-01-10", values=[
        ("Базофіли", 1.0, "%", "within_vendor_range"), ("Моноцити", 9.0, "%", "within_vendor_range")])
    basophils, monocytes = f"{document_id}-0", f"{document_id}-1"
    set_reference(settings, basophils, "0-1", 0.0, 1.0)
    set_reference(settings, monocytes, "Діти до 12 р.: 2-11 Дорослі: 3-9", None, None)
    rows = {"9810": [lab_row("Базофіли", "1", "%", state="critical", norm="{0-1#%}"),
                     lab_row("Моноцити", "9", "%", state="critical", norm="{3-9#%}")]}
    connect_esculab(settings, user_id, monkeypatch, esculab_routes([order(9810, ready=2, total=2)], rows))
    stub_intake(monkeypatch, settings, user_id, {})
    labsync.sync(settings, user_id, "esculab", inline=True)
    with connect(settings) as connection:  # what the earlier version left behind
        connection.execute("UPDATE observations SET vendor_interpretation='high', "
                           "vendor_interpretation_source='lab_record' WHERE id IN (?, ?)", (basophils, monocytes))
    assert labsync.recheck(settings)["flags_undone"] == 2
    for value_id in (basophils, monocytes):
        assert observation(settings, value_id)["vendor_interpretation_source"] is None
    assert observation(settings, basophils)["vendor_interpretation"] == "within_vendor_range"
    assert labsync.recheck(settings)["flags_undone"] == 0


# --- 2. the order's own document, never a copy -------------------------------------


def test_the_cross_check_pairs_with_the_orders_document_and_leaves_copies_out(tmp_path: Path, monkeypatch):
    settings, user_id, _ = make(tmp_path)
    values = [("Кальпротектин", 24.0, "мг/кг", None),
              ("Швидкість осідання еритроцитів (ШОЕ, ESR)", 4.0, "мм/год.", None)]
    own = seed_doc(settings, user_id, vendor="Esculab", order="9820", day="2026-01-10", values=values)
    copies = [seed_doc(settings, user_id, vendor="Esculab", order="9820", day="2026-01-10", values=values)
              for _ in range(2)]
    with connect(settings) as connection:
        for index, copy in enumerate(copies):  # what the pipeline records for a later re-upload
            connection.execute("UPDATE documents SET imported_at=? WHERE id=?", (f"2099-01-0{index + 1}", copy))
            connection.execute(
                """INSERT INTO document_relations(source_document_id, target_document_id, relationship,
                       confidence, notes) VALUES (?, ?, 'duplicate', 0.9, 'auto:shared_results:2')""", (copy, own))
    rows = {"9820": [lab_row("Кальпротектин", "24.0", "мг/кг"),
                     lab_row("Аналіз крові: Швидкість осідання еритроцитів (ШОЕ, ESR)", "4", "мм/год.")]}
    connect_esculab(settings, user_id, monkeypatch, esculab_routes([order(9820, ready=2, total=2)], rows))
    stub_intake(monkeypatch, settings, user_id, {})
    labsync.sync(settings, user_id, "esculab", inline=True)
    with connect(settings) as connection:
        tracked = connection.execute("SELECT * FROM lab_orders WHERE order_id='9820'").fetchone()
        check = labsync.check_order(connection, user_id, tracked)
    assert tracked["document_id"] == own and check["document_ids"] == [own]
    assert check["counts"]["match"] == 2 and check["counts"]["extra"] == check["counts"]["missing"] == 0
    assert {item["obs"]["document_id"] for item in check["items"]} == {own}
    assert json.loads(tracked["crosscheck_json"])["documents"] == [own]

    # A cross-check stored before this fix is refreshed by the repair.
    with connect(settings) as connection:
        connection.execute("UPDATE lab_orders SET crosscheck_json=? WHERE order_id='9820'",
                           (json.dumps({"counts": {"extra": 2}, "documents": [copies[0], own]}),))
    labsync.recheck(settings)
    with connect(settings) as connection:
        stored = json.loads(connection.execute("SELECT crosscheck_json FROM lab_orders").fetchone()[0])
    assert stored["documents"] == [own] and stored["counts"]["extra"] == 0


def test_an_order_linked_to_a_document_later_set_aside_checks_the_kept_one(tmp_path: Path):
    settings, user_id, _ = make(tmp_path)
    kept = seed_doc(settings, user_id, vendor="Esculab", order="9821", day="2026-01-10",
                    values=[("Глюкоза", 5.1, "ммоль/л", None)])
    copy = seed_doc(settings, user_id, vendor="Esculab", order="9821", day="2026-01-10", values=[])
    with connect(settings) as connection:
        connection.execute("UPDATE documents SET duplicate_of_document_id=? WHERE id=?", (kept, copy))
        connection.execute(
            """INSERT INTO lab_orders(owner_user_id, provider, remote_person_id, order_id, first_seen_at,
                   last_synced_at, state, document_id, rows_json)
               VALUES (?, 'esculab', '111', '9821', ?, ?, 'linked', ?, ?)""",
            (user_id, utc_now(), utc_now(), copy, json.dumps([common.lab_row(test="Глюкоза", result="5.1", units="ммоль/л")])))
        tracked = connection.execute("SELECT * FROM lab_orders WHERE order_id='9821'").fetchone()
        check = labsync.check_order(connection, user_id, tracked)
    assert check["document_ids"] == [kept] and check["counts"]["match"] == 1


# --- 3. the lab's comments reach the value -----------------------------------------


URINE = {"comments": ["Ступінь бактеріурії 1,0*10^3 КУО/мл",
                      "Виявлений збудник Lactobacillus spp. є контамінантом зразка."],
         "bacteria_found": [{"bacteria": {"bacteriaId": 1, "bacteriaName": "Lactobacillus spp. ", "defaultComment": None},
                             "concetration": " 1.0 x 10^3 КУО/мл", "normalConcentration": "Не виявлено"}],
         "antibioticograma": []}
STOOL = {"comments": ["Staphylococcus epidermidis природньо резистентний до цефтазидиму. "],
         "bacteria_found": [{"bacteria": {"bacteriaId": 2, "bacteriaName": "Staphylococcus epidermidis",
                                          "defaultComment": "Staphylococcus epidermidis природньо резистентний до цефтазидиму. "},
                             "concetration": "1.0 x 10^7 КУО/г", "normalConcentration": "не більше 10^4"}]}


def culture_row(test, result, material):
    return {**lab_row(test, json.dumps(result, ensure_ascii=False), resulttype="json"), "material": material}


def test_a_culture_comment_is_kept_with_the_organism_it_is_about(tmp_path: Path, monkeypatch):
    settings, user_id, client = make(tmp_path)
    document_id = seed_doc(settings, user_id, vendor="Esculab", order="9830", day="2026-01-10", values=[
        ("Lactobacillus spp.", 1000.0, "КУО/мл", None), ("Ступінь бактеріурії", 1000.0, "КУО/мл", None),
        ("Lactobacillus spp.", 100000.0, "КУО/г", None), ("Staphylococcus epidermidis", 1e7, "КУО/г", None),
        ("Слиз", "відсутній", None, None)])
    urine_lacto, degree, stool_lacto, epidermidis, mucus = (f"{document_id}-{index}" for index in range(5))
    with connect(settings) as connection:
        connection.execute("UPDATE observations SET specimen='сеча' WHERE id IN (?, ?)", (urine_lacto, degree))
        connection.execute("UPDATE observations SET specimen='кал' WHERE id IN (?, ?)", (stool_lacto, epidermidis))
    rows = {"9830": [culture_row("Посів сечі", URINE, "сеча"), culture_row("Дисбактеріоз", STOOL, "кал"),
                     culture_row("Мазок", {"comments": ["Neisseria sicca є нормою слизових оболонок"]}, "зів")]}
    connect_esculab(settings, user_id, monkeypatch, esculab_routes([order(9830, ready=3, total=3)], rows))
    stub_intake(monkeypatch, settings, user_id, {})
    labsync.sync(settings, user_id, "esculab", inline=True)
    notes = {value_id: observation(settings, value_id)["note"]
             for value_id in (urine_lacto, degree, stool_lacto, epidermidis, mucus)}
    assert notes == {urine_lacto: "Виявлений збудник Lactobacillus spp. є контамінантом зразка.",
                     degree: None,  # the comment only restates the value
                     stool_lacto: None,  # another specimen's organism
                     epidermidis: "Staphylococcus epidermidis природньо резистентний до цефтазидиму.",
                     mucus: None}  # «слизових» is not «Слиз»
    assert labsync.recheck(settings)["notes"] == 0  # idempotent: the note already says it

    page = client.get(f"/documents/{document_id}").text
    assert "Note from the laboratory or report" in page and "є контамінантом зразка" in page
    client.cookies.set("anamna_lang", "uk")
    assert "Примітка лабораторії або документа" in client.get(f"/documents/{document_id}").text


# --- 4. the order's sampling time ---------------------------------------------------


def test_the_orders_sampling_time_fills_a_document_that_prints_none(tmp_path: Path, monkeypatch):
    settings, user_id, _ = make(tmp_path)
    bare = seed_doc(settings, user_id, vendor="Esculab", order="9840", day="2026-01-12",
                    values=[("Глюкоза", 5.1, "ммоль/л", None)])
    dated = seed_doc(settings, user_id, vendor="Esculab", order="9841", day="2026-01-12",
                     values=[("Сечовина", 5.5, "ммоль/л", None)])
    with connect(settings) as connection:
        connection.execute("UPDATE documents SET collected_at='2026-01-12T08:30' WHERE id=?", (dated,))
    rows = {"9840": [lab_row("Глюкоза", "5.1", "ммоль/л")], "9841": [lab_row("Сечовина", "5.5", "ммоль/л")]}
    orders = [order(9840, ready=1, total=1, dt="2026-01-09 11:42"), order(9841, ready=1, total=1, dt="2026-01-09 10:00")]
    connect_esculab(settings, user_id, monkeypatch, esculab_routes(orders, rows))
    stub_intake(monkeypatch, settings, user_id, {})
    labsync.sync(settings, user_id, "esculab", inline=True)
    with connect(settings) as connection:
        collected = dict(connection.execute("SELECT id, collected_at FROM documents").fetchall())
        assert lab_order_collected_at(connection, bare) == "2026-01-09T11:42"
        # Never a sampling time after the report's own day.
        connection.execute("UPDATE lab_orders SET ordered_at='2026-02-01 09:00' WHERE order_id='9840'")
        assert lab_order_collected_at(connection, bare) is None
    assert collected == {bare: "2026-01-09T11:42", dated: "2026-01-12T08:30"}  # a printed time stays


# --- 5. a bare row name keeps its test ----------------------------------------------


def test_a_bare_genotype_row_is_named_with_its_test():
    packet = "ПЛР. ВПЛ ВКР (генотипування 16, 18, 31, у/г зішкріб)"
    named = labsync._record_value(common.lab_row(test="16 генотип", result="не виявлено", packet=packet))
    assert named.raw_name == "ПЛР. ВПЛ ВКР, 16 генотип"
    coded = labsync._record_value(common.lab_row(test="18 генотип", result="не виявлено",
                                                 packet="P1234 Генотипування ВПЛ (2 типи)"))
    assert coded.raw_name == "Генотипування ВПЛ, 18 генотип"
    # A name that says what it is on its own is left as the lab wrote it.
    for name in ("1-Метилгістидин", "25-Гідроксивітамін D (Вітамін D загальний)"):
        assert labsync._record_value(common.lab_row(test=name, result="3", packet="P2500 Амінокислоти")).raw_name == name


# --- 6. a takeover never loses a value only the lab's record holds -----------------


HCG = {"id": 2, "name": "β-ХГЛ загальний", "value": "< 0.1", "unit": "мМО/мл",
       "reference_text": "Невагітні жінки: ≤1.0", "is_abnormal": False}


def test_a_report_taking_an_order_over_keeps_the_value_it_did_not_read(tmp_path: Path, monkeypatch):
    settings, user_id, _ = connected(tmp_path, monkeypatch)
    indicators = [*INDICATORS, HCG]
    stub_intake(monkeypatch, settings, user_id, {
        "expert-100169.pdf": {"vendor": "Expert Hospital", "order": "100169", "day": "2025-09-18",
                               "values": [("Антиген SARS-CoV-2", "не виявлено", None, "within_vendor_range")]},
    })
    sync(settings, user_id, monkeypatch, NOFILE, indicators)
    record = state(settings)["order"]["document_id"]
    sync(settings, user_id, monkeypatch, {**NOFILE, "has_file": True}, indicators)
    now = state(settings)
    pdf = now["order"]["document_id"]
    assert pdf != record
    # The PDF holds the antigen; the record stands beside it with only the beta-hCG.
    by_document = {(v["document_id"], v["value_text"]) for v in now["values"]}
    assert (pdf, "не виявлено") in by_document and (record, "не виявлено") not in by_document
    with connect(settings) as connection:
        kept = connection.execute("SELECT raw_name, value_numeric, comparator, unit_raw FROM observations "
                                  "WHERE document_id=?", (record,)).fetchall()
        assert [tuple(row) for row in kept] == [("β-ХГЛ загальний", 0.1, "<", "мМО/мл")]
        assert connection.execute("SELECT duplicate_of_document_id FROM documents WHERE id=?",
                                  (record,)).fetchone()[0] is None
    assert labsync.recheck(settings)["record_kept"] == 0  # idempotent

    # The report is read again and now holds the value: the record is set aside.
    with connect(settings) as connection:
        connection.execute(
            """INSERT INTO observations(id, owner_user_id, patient_id, document_id, page_number, concept_id,
                   raw_name, value_type, value_numeric, comparator, unit_raw, observed_at, verification_status,
                   extraction_method, confidence, evidence_text, parser_version, created_at)
               SELECT ?, owner_user_id, patient_id, ?, 1, concept_id, raw_name, 'numeric', 0.1, '<', unit_raw,
                      observed_at, 'extracted', 'native_pdf_text_parser', 0.9, 'β-ХГЛ загальний < 0.1', 'test', ?
                 FROM observations WHERE document_id=?""", (str(uuid.uuid4()), pdf, utc_now(), record))
    assert labsync.recheck(settings)["record_kept"] == 1
    with connect(settings) as connection:
        assert connection.execute("SELECT COUNT(*) FROM observations WHERE document_id=?", (record,)).fetchone()[0] == 0
        assert connection.execute("SELECT duplicate_of_document_id FROM documents WHERE id=?",
                                  (record,)).fetchone()[0] == pdf


def test_the_reader_knows_milli_iu_per_millilitre_and_folds_it_to_iu_per_litre():
    text = ("Показник Результат Од. Референтний інтервал\n"
            "β-ХГЛ загальний (хоріонічний < 0.1 мМО/мл Невагітні жінки: ≤1.0\n"
            "гонадотропін загальний) Невагітні жінки (постменопауза): ≤7.0\n")
    [value] = parse_document("Synevo", "laboratory", [{"page_number": 1, "text": text, "native_text": text}],
                             age_years=30, sex="female")
    assert (value.raw_name, value.value_numeric, value.comparator, value.unit_raw) == (
        "β-ХГЛ загальний (хоріонічний гонадотропін загальний)", 0.1, "<", "мМО/мл")
    assert canonical_unit("мМО/мл") == canonical_unit("IU/L") == canonical_unit("МО/л")


def test_a_sampling_time_from_the_lab_order_is_not_read_as_classification_drift(tmp_path: Path):
    from anamna.ingest import pipeline

    settings, user_id, _ = make(tmp_path)
    document_id = seed_doc(settings, user_id, vendor="Esculab", order="9842", day="2026-01-12", values=[])
    text = "ЕСКУЛАБ\nДата дослідження: 12.01.2026\nГлюкоза 5.1 ммоль/л 3.3-5.5\n"
    with connect(settings) as connection:
        connection.execute(
            """INSERT INTO document_pages(document_id, page_number, native_text, native_text_sha256,
                   extraction_method, native_char_count, image_count, review_status)
               VALUES (?, 1, ?, 'h', 'native_text', ?, 0, 'not_reviewed')""", (document_id, text, len(text)))
        connection.execute("UPDATE documents SET content_sha256=? WHERE id=?", (uuid.uuid4().hex, document_id))
        row = connection.execute("SELECT * FROM documents WHERE id=?", (document_id,)).fetchone()
        title, kind, day, number, collected, issued = pipeline._expected_classification(connection, row)
        assert collected is None  # the page prints no sampling time
        connection.execute(
            """UPDATE documents SET title=?, clinical_type=?, report_date=?, order_identifier=?, collected_at=?,
                   issued_at=? WHERE id=?""", (title, kind, day, number, "2026-01-09T11:42", issued, document_id))
        connection.execute(
            """INSERT INTO lab_orders(owner_user_id, provider, remote_person_id, order_id, first_seen_at,
                   last_synced_at, state, document_id, ordered_at)
               VALUES (?, 'esculab', '111', '9842', ?, ?, 'linked', ?, '2026-01-09 11:42')""",
            (user_id, utc_now(), utc_now(), document_id))
        assert document_id not in pipeline.classification_drift_ids(connection, user_id)
        connection.execute("DELETE FROM lab_orders")
        assert document_id in pipeline.classification_drift_ids(connection, user_id)
