"""Which product a dose was, the card's own lot shapes, and keeping the record true.

Covers DOCC-23 / OPS-26 (trade name, maker, facility, lot repairs, the
correction pass for doses already ruled on), OPS-25 (the card's review task
follows its doses) and the vaccination search contract.  The card text is
synthetic but shaped exactly like the OCR of a real form 063/о: Cyrillic
homoglyphs, the «3080» stamp, values pushed onto other lines, a «Z» read as
«2», a dropped «Q», and an «A» where a «4» belongs.
"""

from __future__ import annotations

import json
from pathlib import Path

from anamna.db import connect, utc_now
from anamna.immunizations import (
    PRODUCTS_BY_KEY,
    anchor_kind,
    apply_card_transcription,
    card_facility,
    lot_key,
    match_product,
    merge_doses,
    normalise_lot,
    parse_immunizations,
    refresh_card_review,
    search_entries,
    store_document_doses,
)

from test_web_panels import build


CARD = {
    "page_number": 1,
    "native_text": "",
    "ocr_text": "\n".join([
        "(якої) належить заклад охорони здоров'я МЕДИЧНА ДОКУМЕНТАЦІЯ",
        "T30B Тестовий Центр",
        "адреса) ФОРМА N° 063/0",
        "KAPTA ПРОФІЛАКТИЧНИХ ЩЕПЛЕНЬ",
        "Ва кцинація (HepAHepB) Вакцина Загальна Місцева",
        "renatury ANA профілактики внутрішньом'я 1, 05.01.2026",
        "А ra гепатиту В 3080 1,0 mn AHABBA11XY",
        "x GlaxoSmithKline",
        "Вакцинація (HepAHepB) Вакцина ana профілактики внутрішньом'я 05.01.2026 1.0 AHABB411XY",
        "гепатиту A ta гепатиту В GlaxoSmithKline 3080",
        "Вакцинація (Рпешто. соп)) Пневмококова внутрішньом'я 05.01.2026 0.5 2123456",
        "mn",
        "кон'югована вакцина Merk Sharp & Dohme 3080",
        "BV.",
        "Вакцинація (Men_ACWY_135) Кон'югована внутрішньом'я. 1/1 05.01.2026 0.5™n LB1234",
        "полісахаридна вакцина проти 30B0",
        "менінгококів Ceporpyn A, С, W-135 Ta Y",
        "Pfizer",
        "Вакцинаці я (Influenza) Вакцина ana профілактики внутрішньом'я 1/1 33 05.01.2026 0.5 mn 12345678",
        "rpuny GC Biopharma Corp. eee",
        "Ревакцинація (SarsCov2_mRNA) Вакцина Big",
        "коронавірусної хвороби 01.12.2021 0.3 ma FAO123",
        "Ha платформі",
        "MPHK BioNTech Manufacturing GmbH",
    ]),
}


def test_lot_repairs_follow_the_makers_shape_and_nothing_else():
    assert normalise_lot("2007422", PRODUCTS_BY_KEY["gardasil9"].lot_templates) == "Z007422"
    assert normalise_lot("20010299", PRODUCTS_BY_KEY["gardasil9"].lot_templates) == "Z0010299"
    assert normalise_lot("AHABBA90BE", PRODUCTS_BY_KEY["twinrix"].lot_templates) == "AHABB490BE"
    assert normalise_lot("60225011", PRODUCTS_BY_KEY["gcflu"].lot_templates) == "Q60225011"
    assert normalise_lot("FKO592", PRODUCTS_BY_KEY["comirnaty"].lot_templates) == "FK0592"
    # A lot that already fits, or that no single-glyph repair fits, is kept.
    assert normalise_lot("FM4289", PRODUCTS_BY_KEY["comirnaty"].lot_templates) == "FM4289"
    assert normalise_lot("TOTALLYODD99", PRODUCTS_BY_KEY["comirnaty"].lot_templates) == "TOTALLYODD99"
    assert normalise_lot("ABXF48AC", PRODUCTS_BY_KEY["bexsero"].lot_templates) == "ABXF48AC"
    assert lot_key("Z011234") == lot_key("2011234")
    assert lot_key("Q60225011") == lot_key("60225011")


def test_a_product_is_named_only_when_the_card_settles_it():
    assert match_product("HepAHepB", "Вакцина … GlaxoSmithKline").trade_name == "Twinrix"
    assert match_product("Pneumo_conj", "кон'югована вакцина Merk Sharp & Dohme").trade_name == "Vaxneuvance"
    # Pfizer makes two conjugate pneumococcal vaccines: its name alone is not enough.
    assert match_product("Pneumo_conj", "Пневмококова кон'югована вакцина Pfizer") is None
    assert match_product("Pneumo_conj", "Prevenar 20").trade_name == "Prevenar 20"
    # GSK's DTaP-family vaccine is Boostrix only on Boostrix's lot prefix.
    assert match_product("DTaP", "GlaxoSmithKline Biologicals", "AC37B111AA").trade_name == "Boostrix"
    assert match_product("DTaP", "GlaxoSmithKline Biologicals", "A21CB111AA") is None
    # A trade name typed by hand is recognised without a code.
    assert match_product("", "Twinrix").key == "twinrix"
    assert PRODUCTS_BY_KEY["gardasil9"].alternatives == ("Gardasil",)
    for product in PRODUCTS_BY_KEY.values():
        assert product.sources, product.key
        assert all(source["url"].startswith("https://") for source in product.sources)


def test_a_row_opens_only_on_its_first_column():
    assert anchor_kind("Ва кцинація (HPV) Вакцина") == "vaccination"
    assert anchor_kind("Вакцинаці: я (MenB)") == "vaccination"
    assert anchor_kind("Ревакцинація (HPV)") == "revaccination"
    # «вакцина» in a continuation line used to open a row and cut the maker off.
    assert anchor_kind("кон'югована вакцина Merk Sharp & Dohme 3080") is None
    assert anchor_kind("полісахаридна вакцина проти 30B0") is None


def test_the_card_is_read_to_trade_name_maker_facility_and_lot():
    assert card_facility([CARD]) == "ТзОВ Тестовий Центр"
    doses = {(dose.occurrence_date, dose.vaccine_code): dose for dose in merge_doses(parse_immunizations([CARD]))}
    assert len(doses) == 5, sorted(doses)

    twinrix = doses[("2026-01-05", "HepAHepB")]
    # Printed twice, once with «A» for «4»: one dose, with the corrected lot.
    assert twinrix.lot_number == "AHABB411XY"
    assert (twinrix.trade_name, twinrix.manufacturer) == ("Twinrix", "GlaxoSmithKline Biologicals S.A.")
    assert twinrix.product_name == "Вакцина для профілактики гепатиту А та гепатиту В GlaxoSmithKline"
    assert twinrix.facility == "ТзОВ Тестовий Центр"

    pneumo = doses[("2026-01-05", "Pneumo_conj")]
    assert (pneumo.trade_name, pneumo.lot_number) == ("Vaxneuvance", "Z123456")
    assert pneumo.dose_quantity == 0.5, "the dose column beside the date, its «мл» on another line"

    men = doses[("2026-01-05", "Men_ACWY_135")]
    assert men.trade_name == "Nimenrix" and men.product_name.endswith("W-135 та Y Pfizer")
    assert (men.dose_number, men.doses_in_series) == (1, 1)

    flu = doses[("2026-01-05", "Influenza")]
    assert (flu.trade_name, flu.lot_number) == ("GC FLU", "Q12345678")

    covid = doses[("2021-12-01", "SarsCov2_mRNA")]
    assert (covid.trade_name, covid.lot_number, covid.event_kind) == ("Comirnaty", "FA0123", "revaccination")


def _card_document(settings, user_id: str, *, extracted: bool = True) -> None:
    patient_id = f"patient-{user_id}"
    with connect(settings) as connection:
        connection.execute(
            """INSERT INTO documents(
                   id, owner_user_id, patient_id, original_filename, source_path, mime_type,
                   byte_size, sha256, page_count, title, clinical_type, extraction_strategy,
                   classification_confidence, imported_at, status
               ) VALUES ('card-1', ?, ?, 'card.pdf', 'card.pdf', 'application/pdf', 10, 'sha-card', 1,
                         'card', 'immunization_record', 'scanned_page_ocr', 1, ?, 'final')""",
            (user_id, patient_id, utc_now()),
        )
        store_document_doses(connection, user_id, patient_id, "card-1", parse_immunizations([CARD]), "scanned_page_ocr")
        connection.execute(
            """INSERT INTO review_tasks(id, owner_user_id, entity_type, entity_id, reason, state, created_at)
               VALUES ('task-card', ?, 'document', 'card-1', ?, 'open', ?)""",
            (user_id, "Check 5 vaccination(s) read from this card against the page, particularly dates, "
             "dose numbers and lot numbers.", utc_now()),
        )
        if not extracted:
            connection.execute("UPDATE immunizations SET verification_status='verified' WHERE document_id='card-1'")
        connection.commit()


def _task(settings) -> dict:
    with connect(settings) as connection:
        return dict(connection.execute("SELECT * FROM review_tasks WHERE id='task-card'").fetchone())


def test_the_review_task_follows_the_doses_and_closes_when_none_wait(tmp_path: Path):
    """OPS-25: a card whose every dose was decided sat in the queue for months."""
    settings, user_id, client = build(tmp_path)
    _card_document(settings, user_id)
    with connect(settings) as connection:
        ids = [row[0] for row in connection.execute(
            "SELECT id FROM immunizations WHERE document_id='card-1' ORDER BY occurrence_date"
        )]
        csrf = connection.execute(
            "SELECT csrf_token FROM sessions WHERE user_id=? ORDER BY created_at DESC LIMIT 1", (user_id,)
        ).fetchone()[0]
    # Setting one aside: the count falls and a set-aside dose never counts.
    client.post(f"/vaccinations/{ids[0]}", data={"csrf_token": csrf, "action": "remove"})
    assert _task(settings)["reason"].startswith("Check 4 vaccination(s)")
    assert _task(settings)["state"] == "open"
    for dose_id in ids[1:]:
        client.post(f"/vaccinations/{dose_id}", data={"csrf_token": csrf, "action": "verify"})
    task = _task(settings)
    assert task["state"] == "resolved" and task["resolution"] == "verify"
    assert task["assigned_user_id"] == user_id
    with connect(settings) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM audit_events WHERE action='review_resolved_all_doses_decided' AND entity_id='card-1'"
        ).fetchone()[0] == 1
        # Nothing left to do: a second call changes nothing.
        assert refresh_card_review(connection, user_id, "card-1", user_id) == "unchanged"


def test_a_document_with_values_still_waiting_keeps_its_task(tmp_path: Path):
    settings, user_id, _ = build(tmp_path)
    with connect(settings) as connection:
        store_document_doses(connection, user_id, f"patient-{user_id}", "doc-1",
                             parse_immunizations([CARD]), "scanned_page_ocr")
        connection.execute("UPDATE immunizations SET verification_status='verified'")
        # doc-1 also carries eight extracted observations nobody has checked.
        assert refresh_card_review(connection, user_id, "doc-1", user_id) == "unchanged"
        assert connection.execute("SELECT state FROM review_tasks WHERE id='task-1'").fetchone()[0] == "open"


TRANSCRIPTION = {
    "document_sha256": "sha-card",
    "facility": "ТзОВ Тестовий Центр",
    "doses": [
        {"page": 1, "date": "2026-01-05", "code": "HepAHepB", "kind": "vaccination", "dose": "1/3",
         "quantity": 1.0, "route": "intramuscular", "lot": "AHABB411XY",
         "printed": "Вакцина для профілактики гепатиту А та гепатиту В GlaxoSmithKline"},
        {"page": 1, "date": "2026-01-05", "code": "Pneumo_conj", "kind": "vaccination", "dose": "1/1",
         "quantity": 0.5, "route": "intramuscular", "lot": "Z123456",
         "printed": "Пневмококова кон'югована вакцина Merk Sharp & Dohme B. V."},
        {"page": 1, "date": "2021-12-01", "code": "SarsCov2_mRNA", "kind": "revaccination", "dose": "2/2",
         "quantity": 0.3, "route": "intramuscular", "lot": "FA0123",
         "printed": "Вакцина від коронавірусної хвороби на платформі мРНК BioNTech Manufacturing GmbH"},
        {"page": 1, "date": "2030-01-01", "code": "MenB", "kind": "vaccination", "dose": "1/2",
         "quantity": 0.5, "route": "intramuscular", "lot": "NOPE1", "printed": ""},
    ],
}


def test_the_correction_pass_makes_ruled_doses_equal_the_card_and_audits_it(tmp_path: Path):
    """OPS-26: verified doses whose lot, dose number and kind disagreed with the card."""
    settings, user_id, _ = build(tmp_path)
    _card_document(settings, user_id, extracted=False)
    with connect(settings) as connection:
        # What a person confirmed from the old parse: the OCR lot, no dose
        # number, the wrong kind, no trade name.
        connection.execute(
            """UPDATE immunizations SET lot_number='2123456', dose_number=NULL, doses_in_series=NULL,
                      trade_name='', manufacturer='', product_name='Пневмококова', vaccine_code='',
                      diseases='pneumococcus'
               WHERE lot_number='Z123456'"""
        )
        connection.execute(
            "UPDATE immunizations SET event_kind='vaccination', route='' WHERE vaccine_code='SarsCov2_mRNA'"
        )
        connection.commit()

        preview = apply_card_transcription(connection, TRANSCRIPTION, apply=False)
        assert connection.execute(
            "SELECT lot_number FROM immunizations WHERE diseases='pneumococcus'"
        ).fetchone()[0] == "2123456", "a dry run writes nothing"

        report = apply_card_transcription(connection, TRANSCRIPTION, actor_user_id=user_id, apply=True)
        connection.commit()
        assert [entry.get("problem") for entry in report] == [entry.get("problem") for entry in preview]
        missing = [entry for entry in report if entry.get("problem")]
        assert missing == [{"document_id": "card-1", "date": "2030-01-01", "code": "MenB", "problem": "missing"}]

        pneumo = dict(connection.execute(
            "SELECT * FROM immunizations WHERE diseases='pneumococcus'"
        ).fetchone())
        assert (pneumo["lot_number"], pneumo["vaccine_code"], pneumo["trade_name"]) == ("Z123456", "Pneumo_conj", "Vaxneuvance")
        assert (pneumo["dose_number"], pneumo["doses_in_series"]) == (1, 1)
        assert pneumo["product_name"] == "Пневмококова кон'югована вакцина Merk Sharp & Dohme B. V."
        assert pneumo["facility"] == "ТзОВ Тестовий Центр"
        assert pneumo["verification_status"] == "verified", "a correction keeps the ruling"
        covid = dict(connection.execute("SELECT * FROM immunizations WHERE vaccine_code='SarsCov2_mRNA'").fetchone())
        assert (covid["event_kind"], covid["dose_number"], covid["route"]) == ("revaccination", 2, "intramuscular")

        audit = json.loads(connection.execute(
            "SELECT details_json FROM audit_events WHERE action='immunization_corrected_to_card' AND entity_id=?",
            (pneumo["id"],),
        ).fetchone()[0])
        assert audit["changes"]["lot_number"] == ["2123456", "Z123456"]
        assert audit["status_kept"] == "verified"

        # Idempotent: the second run finds nothing to change and audits nothing.
        before = connection.execute("SELECT COUNT(*) FROM audit_events").fetchone()[0]
        again = apply_card_transcription(connection, TRANSCRIPTION, actor_user_id=user_id, apply=True)
        assert [entry for entry in again if not entry.get("problem")] == []
        assert connection.execute("SELECT COUNT(*) FROM audit_events").fetchone()[0] == before


def test_a_reread_after_correction_neither_duplicates_nor_resurrects(tmp_path: Path):
    """A better lot reading of a confirmed dose is the same dose, and so is a lotless copy."""
    settings, user_id, _ = build(tmp_path)
    _card_document(settings, user_id, extracted=False)
    with connect(settings) as connection:
        connection.execute("UPDATE immunizations SET lot_number='2123456' WHERE lot_number='Z123456'")
        connection.execute("UPDATE immunizations SET lot_number='' WHERE vaccine_code='Influenza'")
        connection.commit()
        written = store_document_doses(connection, user_id, f"patient-{user_id}", "card-1",
                                       parse_immunizations([CARD]), "scanned_page_ocr")
        assert written == 0
        assert connection.execute("SELECT COUNT(*) FROM immunizations").fetchone()[0] == 5


def test_search_entries_carry_every_name_a_vaccine_goes_by(tmp_path: Path):
    settings, user_id, _ = build(tmp_path)
    _card_document(settings, user_id)
    with connect(settings) as connection:
        english = search_entries(connection, user_id, "en")
        ukrainian = search_entries(connection, user_id, "uk")
    by_title = {entry["title"]: entry for entry in english}
    twinrix = by_title["Twinrix (HepAHepB)"]
    assert set(twinrix) == {"kind", "title", "subtitle", "url", "terms"}
    assert twinrix["kind"] == "vaccination"
    assert twinrix["url"] == "/vaccinations?q=Twinrix"
    for term in ("HepAHepB", "Twinrix", "GlaxoSmithKline Biologicals S.A.", "GSK", "Hepatitis A",
                 "Гепатит A", "щеплення", "вакцина", "прививка", "vaccination", "AHABB411XY"):
        assert term in twinrix["terms"], term
    assert "Hepatitis A" in twinrix["subtitle"]
    assert "Gardasil" not in twinrix["terms"]
    uk_twinrix = {entry["title"]: entry for entry in ukrainian}["Twinrix (HepAHepB)"]
    assert "Гепатит A" in uk_twinrix["subtitle"] and "1 доза" in uk_twinrix["subtitle"]
    assert {entry["title"] for entry in english} >= {"Vaxneuvance (Pneumo_conj)", "GC FLU (Influenza)"}
