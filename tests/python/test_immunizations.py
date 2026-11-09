"""Vaccinations: reading a card, storing doses, and the page in front of them.

The parser's own traps live in `anamna.immunizations.demo()` and run as
`test_module_self_check` below.  What is asserted here is everything that only
shows up once a database and a request are involved: that re-reading a card does
not double or resurrect anything, that a person's ruling outranks the parser's,
that a hand-entered dose is never confused with a parsed one, and that the page
renders in both locales.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from anamna import immunizations
from anamna.db import connect, utc_now
from anamna.immunizations import (
    ParsedDose,
    find_gaps,
    is_vaccination_card,
    parse_immunizations,
    store_document_doses,
)
from anamna.ingest.classifier import classify_document

from test_web_panels import build


#: One page of a form 063/о as OCR actually delivers it: Cyrillic homoglyphs
#: standing in for Latin ones, the «3080» watermark over every second row, a
#: values line that reconstruction placed *above* the name line that anchors it,
#: and one dose printed twice — once in its disease section and once under
#: «Інші щеплення».
CARD_PAGE = {
    "page_number": 1,
    "native_text": "",
    "ocr_text": "\n".join(
        [
            "КАРТА ПРОФІЛАКТИЧНИХ ЩЕПЛЕНЬ",
            "МЕДИЧНА ДОКУМЕНТАЦІЯ ФОРМА N° 063/0",
            "Щеплення проти туберкульозу",
            "Тип Назва препарату Метод No Вік Дата Доза Серія Реакція на щеплення",
            "Щеплення проти гепатиту В",
            "Вакцинація (HepAHepB) Вакцина для профілактики внутрішньом'я 08.01.2026 1,0 mn",
            "гепатиту А та гепатиту В 3080 AHABB490BE",
            "Інші щеплення",
            "внутрішньом'я 1/1 33 23.02.2025 0.5 mn AC37B478AG",
            "Вакцинація (DTaP) Комбінована вакцина для",
            "профілактики дифтерії, правця, кашлюка 3080",
            "Ревакцинація (HepAHepB) Вакцина для профілактики внутрішньом'я 2/3 33 08.01.2026 1.0 mn AHABB490BE",
            "гепатиту А та гепатиту В GlaxoSmithKline",
            "Вакцинація (Рпешто. соп)) Пневмококова внутрішньом'я 08.01.2026 0.5 mn 2011234",
            "кон'югована вакцина Merk Sharp & Dohme B.V. 3080",
        ]
    ),
}


def test_module_self_check():
    """The parser's own assertions, run as part of the suite rather than by hand."""
    immunizations.demo()


def test_a_card_is_recognised_as_one():
    assert is_vaccination_card(CARD_PAGE["ocr_text"])
    assert not is_vaccination_card("Загальний аналіз крові. Показник Результат Норма")
    classification = classify_document(
        "scan.pdf", "application/pdf", [CARD_PAGE], {}
    )
    assert classification.clinical_type == "immunization_record"


def test_every_printed_dose_is_read_once():
    doses = immunizations.merge_doses(parse_immunizations([CARD_PAGE]))
    by_date = {(dose.occurrence_date, dose.lot_number): dose for dose in doses}
    # Three doses, not four: the hepatitis row is printed twice and the second
    # printing is the one carrying "2/3".
    assert len(doses) == 3, [d.product_name for d in doses]
    hepatitis = by_date[("2026-01-08", "AHABB490BE")]
    assert hepatitis.diseases == ("hepatitis_a", "hepatitis_b")
    assert (hepatitis.dose_number, hepatitis.doses_in_series) == (2, 3)
    assert hepatitis.event_kind == "revaccination"
    # The values line printed above its own name line still belongs to it.
    dtap = by_date[("2025-02-23", "AC37B478AG")]
    assert dtap.vaccine_code == "DTaP"
    assert dtap.diseases == ("diphtheria", "tetanus", "pertussis")
    # Identified from the Ukrainian wording after the Cyrillic homoglyphs
    # mangled the code past recognition.
    pneumo = by_date[("2026-01-08", "Z011234")]
    assert pneumo.diseases == ("pneumococcus",)
    # The watermark is not a batch number and the section header is not a dose.
    assert "3080" not in {dose.lot_number for dose in doses}
    assert all(dose.occurrence_date for dose in doses)


def test_a_dose_is_never_verified_by_the_parser():
    for dose in parse_immunizations([CARD_PAGE]):
        assert dose.confidence < 1.0
        assert dose.evidence_text


def seeded(settings, user_id: str, patient_id: str) -> int:
    with connect(settings) as connection:
        written = store_document_doses(
            connection, user_id, patient_id, "doc-1",
            parse_immunizations([CARD_PAGE]), "scanned_page_ocr",
        )
        connection.commit()
    return written


def csrf_for(settings, user_id: str) -> str:
    """The token for the session `build` already put in the client's cookie jar."""
    with connect(settings) as connection:
        return connection.execute(
            "SELECT csrf_token FROM sessions WHERE user_id=? ORDER BY created_at DESC LIMIT 1",
            (user_id,),
        ).fetchone()[0]


def rows(settings, user_id: str) -> list[dict[str, object]]:
    with connect(settings) as connection:
        return [
            dict(row)
            for row in connection.execute(
                "SELECT * FROM immunizations WHERE owner_user_id=? ORDER BY occurrence_date, lot_number",
                (user_id,),
            )
        ]


def test_rereading_a_card_neither_doubles_nor_resurrects(tmp_path: Path):
    settings, user_id, _ = build(tmp_path)
    patient_id = f"patient-{user_id}"
    assert seeded(settings, user_id, patient_id) == 3
    # Re-reading the same document replaces its own unruled rows, so the count
    # written is the same three — and the count on file is still three.
    assert seeded(settings, user_id, patient_id) == 3
    assert len(rows(settings, user_id)) == 3

    # The same card imported again under another filename is the same doses.
    # This is the guarantee that matters: a person who uploads their card twice
    # must not be told they have had twenty-six vaccinations.
    with connect(settings) as connection:
        again = store_document_doses(
            connection, user_id, patient_id, "doc-2",
            parse_immunizations([CARD_PAGE]), "scanned_page_ocr",
        )
        connection.commit()
    assert again == 0
    assert len(rows(settings, user_id)) == 3

    stored = rows(settings, user_id)
    assert {row["entry_source"] for row in stored} == {"document"}
    assert {row["verification_status"] for row in stored} == {"extracted"}

    # A dose set aside by a person must stay set aside: without that, every
    # re-read puts the row they just rejected straight back.
    with connect(settings) as connection:
        connection.execute(
            "UPDATE immunizations SET verification_status='rejected' WHERE lot_number='Z011234'"
        )
        connection.commit()
    seeded(settings, user_id, patient_id)
    after = {row["lot_number"]: row["verification_status"] for row in rows(settings, user_id)}
    assert after["Z011234"] == "rejected"
    assert len(after) == 3


def test_a_persons_correction_survives_a_reread(tmp_path: Path):
    settings, user_id, _ = build(tmp_path)
    patient_id = f"patient-{user_id}"
    seeded(settings, user_id, patient_id)
    with connect(settings) as connection:
        connection.execute(
            """UPDATE immunizations SET verification_status='corrected', product_name='Twinrix'
               WHERE lot_number='AHABB490BE'"""
        )
        connection.commit()
    seeded(settings, user_id, patient_id)
    corrected = [row for row in rows(settings, user_id) if row["lot_number"] == "AHABB490BE"]
    assert len(corrected) == 1
    assert corrected[0]["product_name"] == "Twinrix"
    assert corrected[0]["verification_status"] == "corrected"


def test_the_page_shows_the_card_in_both_locales(tmp_path: Path):
    settings, user_id, client = build(tmp_path)
    seeded(settings, user_id, f"patient-{user_id}")

    english = client.get("/vaccinations")
    assert english.status_code == 200
    assert "Hepatitis B" in english.text
    assert "AHABB490BE" in english.text
    # The gap the card itself declares, and the one a schedule computes.
    assert "dose 2 of 3" in english.text
    assert "2035" in english.text, "the ten-year Td booster date is missing"
    # Every recommendation is attributed, and the disagreement is not averaged.
    assert "zakon.rada.gov.ua" in english.text
    assert "cdc.gov" in english.text and "ecdc.europa.eu" in english.text
    assert "The three schedules differ" in english.text

    client.cookies.set("anamna_lang", "uk")
    ukrainian = client.get("/vaccinations")
    assert ukrainian.status_code == 200
    assert "Гепатит B" in ukrainian.text
    assert "Три календарі розходяться" in ukrainian.text
    # A stray English label on a Ukrainian page is the defect this guards.
    for leaked in ("Doses on file", "Not checked yet", "Entered by you"):
        assert leaked not in ukrainian.text, leaked


def test_a_hand_entered_dose_is_stored_as_the_persons_own(tmp_path: Path):
    settings, user_id, client = build(tmp_path)
    csrf = csrf_for(settings, user_id)

    response = client.post(
        "/vaccinations",
        data={
            "csrf_token": csrf, "occurred_on": "1993-04-15", "vaccine_code": "BCG",
            "event_kind": "vaccination", "product_name": "БЦЖ", "note": "paper booklet",
        },
        follow_redirects=False,
    )
    assert response.status_code == 303
    stored = rows(settings, user_id)
    assert len(stored) == 1
    dose = stored[0]
    assert dose["entry_source"] == "manual"
    assert dose["entered_by_user_id"] == user_id
    assert dose["document_id"] is None
    assert dose["diseases"] == "tuberculosis"
    # Marked with the same vocabulary the one pre-existing hand-entry path used,
    # so nothing downstream has to learn a second one.
    assert dose["extraction_method"] == "human_entered"
    assert dose["verification_status"] == "corrected"

    # The picker is a datalist, so whatever was typed arrives verbatim. A
    # vaccine the dictionary does not know is not an error — it is the reason
    # the free-text escape exists — and it is kept as the product name so the
    # dose is on file even though no code could be resolved for it.
    client.post(
        "/vaccinations",
        data={
            "csrf_token": csrf, "occurred_on": "1994-05-20",
            "vaccine_code": "Some regional vaccine",
        },
        follow_redirects=False,
    )
    unlisted = [row for row in rows(settings, user_id) if row["occurrence_date"] == "1994-05-20"]
    assert len(unlisted) == 1
    assert unlisted[0]["product_name"] == "Some regional vaccine"
    assert unlisted[0]["vaccine_code"] == "" and unlisted[0]["diseases"] == ""

    # A full picker entry resolves back to the code it names, so the modal can
    # pre-fill the field with something a person can read.
    client.post(
        "/vaccinations",
        data={
            "csrf_token": csrf, "occurred_on": "1995-06-21",
            "vaccine_code": "MMR — Measles · Mumps · Rubella",
        },
        follow_redirects=False,
    )
    entry = [row for row in rows(settings, user_id) if row["occurrence_date"] == "1995-06-21"]
    assert entry[0]["vaccine_code"] == "MMR"
    assert entry[0]["diseases"] == "measles,mumps,rubella"

    before = len(rows(settings, user_id))
    # Rejected input comes back as a message, never as a row.
    for bad in (
        {"occurred_on": "2099-01-01", "vaccine_code": "BCG"},
        {"occurred_on": "1993-04-15", "vaccine_code": "", "product_name": ""},
        {"occurred_on": "", "vaccine_code": "BCG"},
        {"occurred_on": "1993-04-15", "vaccine_code": "BCG", "dose_number": "3",
         "doses_in_series": "2"},
    ):
        answer = client.post(
            "/vaccinations", data={"csrf_token": csrf, **bad}, follow_redirects=False
        )
        assert answer.status_code == 303 and "error=" in answer.headers["location"], bad
    assert len(rows(settings, user_id)) == before


def test_an_ai_draft_accepted_beside_a_card_keeps_source_provenance(tmp_path: Path):
    settings, user_id, client = build(tmp_path)
    response = client.post(
        "/vaccinations",
        data={
            "csrf_token": csrf_for(settings, user_id),
            "occurred_on": "2025-02-23",
            "vaccine_code": "DTaP",
            "product_name": "Card product",
            "document_id": "doc-1",
            "page_number": "4",
            "evidence_text": "23.02.2025 DTaP AC37B478AG",
        },
        follow_redirects=False,
    )
    assert response.status_code == 303
    (dose,) = rows(settings, user_id)
    assert dose["entry_source"] == "document"
    assert dose["document_id"] == "doc-1"
    assert dose["page_number"] == 4
    assert dose["entered_by_user_id"] == user_id
    assert dose["verification_status"] == "corrected"
    assert dose["evidence_text"] == "23.02.2025 DTaP AC37B478AG"


def test_removing_a_parsed_dose_sets_it_aside_and_a_typed_one_deletes(tmp_path: Path):
    settings, user_id, client = build(tmp_path)
    seeded(settings, user_id, f"patient-{user_id}")
    csrf = csrf_for(settings, user_id)
    with connect(settings) as connection:
        parsed_id = connection.execute(
            "SELECT id FROM immunizations WHERE lot_number='Z011234'"
        ).fetchone()[0]

    client.post(
        f"/vaccinations/{parsed_id}",
        data={"csrf_token": csrf, "action": "remove"}, follow_redirects=False,
    )
    with connect(settings) as connection:
        assert connection.execute(
            "SELECT verification_status FROM immunizations WHERE id=?", (parsed_id,)
        ).fetchone()[0] == "rejected"

    client.post(
        "/vaccinations",
        data={"csrf_token": csrf, "occurred_on": "1993-04-15", "vaccine_code": "BCG"},
        follow_redirects=False,
    )
    with connect(settings) as connection:
        typed_id = connection.execute(
            "SELECT id FROM immunizations WHERE entry_source='manual'"
        ).fetchone()[0]
    client.post(
        f"/vaccinations/{typed_id}",
        data={"csrf_token": csrf, "action": "remove"}, follow_redirects=False,
    )
    with connect(settings) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM immunizations WHERE id=?", (typed_id,)
        ).fetchone()[0] == 0


def test_confirming_a_dose_takes_it_out_of_the_parsers_reach(tmp_path: Path):
    settings, user_id, client = build(tmp_path)
    seeded(settings, user_id, f"patient-{user_id}")
    csrf = csrf_for(settings, user_id)
    with connect(settings) as connection:
        dose_id = connection.execute(
            "SELECT id FROM immunizations WHERE lot_number='AC37B478AG'"
        ).fetchone()[0]
    client.post(
        f"/vaccinations/{dose_id}",
        data={"csrf_token": csrf, "action": "verify"}, follow_redirects=False,
    )
    with connect(settings) as connection:
        row = connection.execute(
            "SELECT verification_status, entered_by_user_id, entry_source FROM immunizations WHERE id=?",
            (dose_id,),
        ).fetchone()
    assert row["verification_status"] == "verified"
    assert row["entered_by_user_id"] == user_id
    # Confirming is not authoring: the dose still came from the document.
    assert row["entry_source"] == "document"


def test_a_dose_cannot_be_written_without_a_csrf_token(tmp_path: Path):
    settings, user_id, client = build(tmp_path)
    answer = client.post(
        "/vaccinations",
        data={"csrf_token": "wrong", "occurred_on": "1993-04-15", "vaccine_code": "BCG"},
        follow_redirects=False,
    )
    assert answer.status_code == 403
    assert rows(settings, user_id) == []


def test_an_observation_no_longer_needs_a_document(tmp_path: Path):
    """Migration 023's other half: a measurement a person knows and no file holds.

    Asserted here rather than left to the vaccination path, because it is the
    part of the manual-entry model that a later hand-entry form depends on and
    that nothing else currently exercises.
    """
    settings, user_id, _ = build(tmp_path)
    with connect(settings) as connection:
        connection.execute(
            """INSERT INTO observations(
                   id, owner_user_id, patient_id, document_id, page_number, raw_name,
                   value_type, value_numeric, unit_raw, observed_at, verification_status,
                   extraction_method, confidence, evidence_text, parser_version, created_at,
                   entry_source, entered_by_user_id
               ) VALUES ('obs-manual', ?, ?, NULL, 1, 'Blood pressure, systolic', 'numeric',
                         126, 'mmHg', '2026-08-07', 'corrected', 'human_entered', 1.0,
                         'measured at home', 'human', ?, 'manual', ?)""",
            (user_id, f"patient-{user_id}", utc_now(), user_id),
        )
        connection.commit()
        stored = connection.execute(
            "SELECT document_id, entry_source FROM observations WHERE id='obs-manual'"
        ).fetchone()
    assert stored["document_id"] is None and stored["entry_source"] == "manual"

    # And the provenance rule is enforced, not merely documented.
    with connect(settings) as connection:
        with pytest.raises(Exception):
            connection.execute(
                """INSERT INTO observations(
                       id, owner_user_id, patient_id, page_number, raw_name, value_type,
                       value_numeric, verification_status, extraction_method, confidence,
                       evidence_text, parser_version, created_at, entry_source
                   ) VALUES ('obs-bad', ?, ?, 1, 'x', 'numeric', 1, 'corrected', 'human_entered',
                             1.0, '', 'human', ?, 'manual')""",
                (user_id, f"patient-{user_id}", utc_now()),
            )


def test_a_seasonal_gap_points_at_the_next_season_not_the_last(tmp_path: Path):
    """Between seasons, «overdue since last September» is true and useless."""
    given = [{"occurrence_date": "2026-01-08", "diseases": "influenza"}]
    august = {gap.key: gap for gap in find_gaps(given, date(2026, 8, 7))}
    assert august["influenza_season"].due_date == "2026-09-01"
    assert august["influenza_season"].urgency == "soon"
    # Once the season has opened and no dose covers it, it is genuinely due.
    october = {gap.key: gap for gap in find_gaps(given, date(2026, 10, 1))}
    assert october["influenza_season"].urgency == "overdue"
    # A dose given inside the season closes it.
    covered = find_gaps(
        [{"occurrence_date": "2026-10-05", "diseases": "influenza"}], date(2026, 10, 20)
    )
    assert "influenza_season" not in {gap.key for gap in covered}


def test_the_page_offers_the_next_dose_already_filled_in(tmp_path: Path):
    """The add button beside a vaccine says what its next dose looks like.

    A card that printed "2 of 3" has already answered the two questions the
    form would otherwise ask: which vaccine, and which dose of how many. Making
    the person retype both is how a record stops being kept.
    """
    settings, user_id, client = build(tmp_path)
    seeded(settings, user_id, f"patient-{user_id}")
    page = client.get("/vaccinations").text

    # The unfinished hepatitis course: dose 2 of 3 on file, so the next is 3 of
    # 3, and on form 063/о only a first dose is a «Вакцинація».
    assert 'data-vax-dose-number="3"' in page
    assert 'data-vax-doses-in-series="3"' in page
    assert 'data-vax-kind="revaccination"' in page
    # The picker entry, not the bare code, so the field a person sees is legible
    # and still resolves back to HepAHepB.
    assert "HepAHepB - Hepatitis A · Hepatitis B" in page

    # Adding it closes the gap the card itself declared.
    assert "dose 2 of 3" in page
    client.post(
        "/vaccinations",
        data={
            "csrf_token": csrf_for(settings, user_id), "occurred_on": "2026-08-01",
            "vaccine_code": "HepAHepB — Hepatitis A · Hepatitis B",
            "event_kind": "revaccination", "dose_number": "3", "doses_in_series": "3",
        },
        follow_redirects=False,
    )
    assert "dose 2 of 3" not in client.get("/vaccinations").text


def test_the_dose_list_rests_collapsed(tmp_path: Path):
    """Eleven diseases expanded is four screens before the first answer."""
    settings, user_id, client = build(tmp_path)
    seeded(settings, user_id, f"patient-{user_id}")
    page = client.get("/vaccinations").text
    # `<details>` without `open`: every section closed, each summarised by its
    # count and its latest date.
    assert '<details class="an-vax-group"' in page
    assert "an-vax-group__summary" in page
    assert "open>" not in page.split("an-vax-group")[1][:200]
    assert "latest" in page


def test_a_dose_is_confirmed_beside_the_page_it_was_read_from(tmp_path: Path):
    """«This matches the card» was a button on a page with no card on it.

    Confirming an OCR reading is only meaningful next to the image, so the
    control lives in the document review bench — with the page link, the
    evidence line, and a correction form — exactly like an observation.
    """
    settings, user_id, client = build(tmp_path)
    seeded(settings, user_id, f"patient-{user_id}")

    vaccinations = client.get("/vaccinations").text
    assert "This matches the card" not in vaccinations
    # Instead: a route to the evidence.
    assert "Check it against the document" in vaccinations

    document = client.get("/documents/doc-1").text
    assert "vaccinations read from this document" in document
    assert "Confirm this dose" in document
    # The page link the viewer listens to, and the line the parser read.
    assert 'data-page="1"' in document
    assert "AHABB490BE" in document

    # Confirming from the document returns to the document, not to a list the
    # person was not looking at.
    with connect(settings) as connection:
        dose_id = connection.execute(
            "SELECT id FROM immunizations WHERE lot_number='AHABB490BE'"
        ).fetchone()[0]
    answer = client.post(
        f"/vaccinations/{dose_id}",
        data={
            "csrf_token": csrf_for(settings, user_id), "action": "verify",
            "next": "/documents/doc-1",
        },
        follow_redirects=False,
    )
    assert answer.headers["location"].startswith("/documents/doc-1")
    with connect(settings) as connection:
        assert connection.execute(
            "SELECT verification_status FROM immunizations WHERE id=?", (dose_id,)
        ).fetchone()[0] == "verified"

    # And `next` is not an open redirect.
    away = client.post(
        f"/vaccinations/{dose_id}",
        data={
            "csrf_token": csrf_for(settings, user_id), "action": "verify",
            "next": "https://evil.example/steal",
        },
        follow_redirects=False,
    )
    assert away.headers["location"].startswith("/vaccinations")


#: The «Вакцинації» block of a Veselka (Doctor Eleks) visit note, 08.01.2026,
#: as its PDF text layer prints it -- Cyrillic «К» inside a Latin lot included.
VISIT_NOTE = (
    "Огляд лікаря первинка\nДата взаємодії: 08.01.2026 8:32\nВакцинації\n"
    "Назва вакцини HepAHepB ‐ Вакцина для Виробник GlaxoSmithKline\n"
    "профілактики гепатиту А та гепатиту В Серія вакцин AHABB490BE\n"
    "Дата та час вакцинації в системі 08.01.2026 8:38 Термін придатності 31.01.2028\n"
    "Назва вакцини Pneumo_conj ‐ Пневмококова кон'югована вакцина Серія вакцин Z011234\n"
    "Дата та час вакцинації в системі 08.01.2026 8:40\n"
)


def test_a_clinic_visit_note_is_linked_to_the_doses_it_records(tmp_path: Path):
    """The clinic's note of the visit is the second written record of each
    injection: matched by day and vial, shown on /vaccinations and on the note
    itself, and never copied into a second dose row."""
    from test_web_security import seed_document

    settings, user_id, client = build(tmp_path)
    patient_id = f"patient-{user_id}"
    seeded(settings, user_id, patient_id)
    note = seed_document(settings, user_id, patient_id, "Огляд лікаря первинка", "veselka-1000524.pdf")
    with connect(settings) as connection:
        connection.execute("UPDATE documents SET clinical_type='consultation', report_date='2026-01-08' WHERE id=?", (note,))
        connection.execute(
            "INSERT INTO document_pages(document_id,page_number,native_text,extraction_method,review_status) "
            "VALUES (?,1,?,'native','not_reviewed')", (note, VISIT_NOTE))
        # A dose typed in by hand, without a lot, on a day the note does not cover.
        connection.execute(
            "INSERT INTO immunizations(id, owner_user_id, patient_id, occurrence_date, vaccine_code, diseases, "
            "entry_source, entered_by_user_id, verification_status, created_at, updated_at) "
            "VALUES ('typed', ?, ?, '2026-07-18', 'HepAHepB', 'hepatitis_a,hepatitis_b', 'manual', ?, 'verified', ?, ?)",
            (user_id, patient_id, user_id, utc_now(), utc_now()))
        connection.commit()
        doses = immunizations.doses_for(connection, user_id)
        linked = immunizations.visit_notes(connection, user_id, doses)
    by_lot = {dose["lot_number"]: linked.get(dose["id"], []) for dose in doses}
    assert [n["id"] for n in by_lot["AHABB490BE"]] == [note]
    assert [n["id"] for n in by_lot["Z011234"]] == [note]
    assert by_lot["AC37B478AG"] == [], "the 2025 DTaP was not given at this visit"
    assert linked.get("typed") is None, "another day is another visit"
    assert len(rows(settings, user_id)) == 4, "linking copies nothing"

    client.cookies.set("anamna_lang", "uk")
    page = client.get("/vaccinations").text
    assert f'href="/documents/{note}"' in page and "Також згадано в записі про візит" in page
    detail = client.get(f"/documents/{note}").text
    assert "Під час цього візиту зроблено 2 щеплення" in detail and "AHABB490BE" in detail
    client.cookies.set("anamna_lang", "en")
    assert "Also in the clinic&#39;s visit note" in client.get("/vaccinations").text
    assert "2 vaccinations given at this visit" in client.get(f"/documents/{note}").text


#: The «Вакцинації» section of an eHealth visit note, laid out the way the PDF
#: text layer prints it: two columns per line, the protocol table under each
#: dose.  Names and lots are invented.
VISIT_NOTE_DOSES = (
    "Медичний центр ТзОВ «Приклад»\nВакцинації\n"
    "Назва вакцини HepAHepB ‐ Вакцина для Виробник GlaxoSmithKline\n"
    "профілактики гепатиту А та гепатиту В Серія вакцин AHABB123АК\n"
    "Дата та час вакцинації в системі 18.07.2026 14:43 Термін придатності 30.04.2028\n"
    "Лікар, який виконав вакцинацію Іваненко Олена Кількість введеної вакцини 1,0\n"
    "Петрівна ﴾Лікар‐педіатр﴿ Одиниці вимірювання ML ‐ мл\n"
    "Проведено Місце введення дельтоподібний м'яз ﴾ліва рука﴿\n"
    "Причина проведення вакцинації Щеплення за Шлях введення внутрішньом'язово\n"
    "станом здоров’я ﴾планово﴿\nПояснення проведення вакцинації 3 доза\n"
    "№ дози Опис протоколу Автор протоколу Етап Кількість Хвороба\nдоз\n"
    "3 Twinrix Міністерство Охорони 3 3 Гепатит A\nЗдоров'я України\n"
    "Назва вакцини HPV ‐ Вакцина для профілактики Виробник Merk Sharp & Dohme B. V.\n"
    "інфекції, викликаної вірусом папіломи людини Серія вакцин Z000001\n"
    "Дата та час вакцинації в системі 18.07.2026 14:43 Термін придатності 19.10.2027\n"
    "Лікар, який виконав вакцинацію Іваненко Олена Кількість введеної вакцини 0,5\n"
    "Петрівна ﴾Лікар‐педіатр﴿ Одиниці вимірювання ML ‐ мл\n"
    "Проведено Місце введення дельтоподібний м'яз ﴾права рука﴿\n"
    "№ дози Опис протоколу Автор протоколу Етап Кількість Хвороба\nдоз\n"
    "3 Gardasil 9 Міністерство Охорони 3 3 ВПЛ\nЗдоров'я України\n"
    "Рекомендована вакцинація: щорічна вакцинація від грипу\n"
)


def test_a_visit_note_records_every_detail_of_each_dose():
    doses = immunizations.parse_visit_vaccinations([{"page_number": 2, "native_text": VISIT_NOTE_DOSES}])
    assert [(d.vaccine_code, d.lot_number, d.dose_number, d.doses_in_series) for d in doses] == [
        ("HepAHepB", "AHABB123AK", 3, 3),  # the Cyrillic «АК» typed into the lot is the same vial
        ("HPV", "Z000001", 3, 3),
    ]
    hep, hpv = doses
    assert (hep.occurrence_date, hep.dose_quantity, hep.dose_unit, hep.route) == ("2026-07-18", 1.0, "мл", "intramuscular")
    assert hep.site == "дельтоподібний м'яз (ліва рука)" and hpv.site == "дельтоподібний м'яз (права рука)"
    assert hep.clinician == "Іваненко Олена Петрівна"
    assert (hep.trade_name, hpv.trade_name, hep.facility) == ("Twinrix", "Gardasil 9", "ТзОВ Приклад")
    assert "Рекомендована" not in hpv.evidence_text, "the note's advice is not part of the dose"
    assert all(d.confidence < 1.0 for d in doses)


def test_a_document_dose_supersedes_the_one_typed_by_hand(tmp_path: Path):
    """The clinic's record wins over a person's memory of the same injection:
    the typed row is retired, its content audited, and the document's row with
    the lot, site and clinician takes its place.  A typed dose the document
    does not describe is left alone."""
    settings, user_id, _client = build(tmp_path)
    patient_id = f"patient-{user_id}"
    with connect(settings) as connection:
        for typed_id, code, day in (("typed-hep", "HepAHepB", "2026-07-18"), ("typed-flu", "Influenza", "2026-07-18")):
            connection.execute(
                "INSERT INTO immunizations(id, owner_user_id, patient_id, occurrence_date, vaccine_code, diseases, "
                "product_name, dose_number, entry_source, entered_by_user_id, verification_status, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, '', 'Twinrix', 3, 'manual', ?, 'corrected', ?, ?)",
                (typed_id, user_id, patient_id, day, code, user_id, utc_now(), utc_now()))
        connection.execute(
            "INSERT INTO documents(id, owner_user_id, patient_id, original_filename, source_path, mime_type, byte_size, "
            "sha256, page_count, title, clinical_type, extraction_strategy, imported_at) "
            "VALUES ('note', ?, ?, 'n.pdf', 'n.pdf', 'application/pdf', 1, 'x', 2, 'Огляд', 'consultation', 'native_text', ?)",
            (user_id, patient_id, utc_now()))
        doses = immunizations.parse_visit_vaccinations([{"page_number": 2, "native_text": VISIT_NOTE_DOSES}])
        assert store_document_doses(connection, user_id, patient_id, "note", doses, "native_text") == 2
        # Idempotent: a re-read neither doubles the doses nor brings the typed one back.
        assert store_document_doses(connection, user_id, patient_id, "note", doses, "native_text") == 2
        audits = connection.execute(
            "SELECT entity_id, details_json FROM audit_events WHERE action='immunization_superseded_by_document'"
        ).fetchall()
        connection.commit()
    held = {(row["vaccine_code"], row["entry_source"]): row for row in rows(settings, user_id)}
    assert set(held) == {("HepAHepB", "document"), ("HPV", "document"), ("Influenza", "manual")}
    assert held[("HepAHepB", "document")]["site"] == "дельтоподібний м'яз (ліва рука)"
    assert held[("HepAHepB", "document")]["clinician"] == "Іваненко Олена Петрівна"
    assert [row["entity_id"] for row in audits] == ["typed-hep"]
    assert '"product_name": "Twinrix"' in audits[0]["details_json"], "the typed content is kept"


def test_a_visit_note_fills_in_what_the_card_never_records(tmp_path: Path):
    """The card says which vial on which day; the clinic's note of that visit
    also says where it went in and who gave it.  Those fill the card's row --
    nothing is duplicated and nothing the card says is overwritten."""
    settings, user_id, _client = build(tmp_path)
    patient_id = f"patient-{user_id}"
    seeded(settings, user_id, patient_id)
    before = {row["id"]: row for row in rows(settings, user_id)}
    note = VISIT_NOTE_DOSES.replace("18.07.2026", "08.01.2026").replace("AHABB123АК", "AHABB490BE")
    with connect(settings) as connection:
        connection.execute(
            "INSERT INTO documents(id, owner_user_id, patient_id, original_filename, source_path, mime_type, byte_size, "
            "sha256, page_count, title, clinical_type, extraction_strategy, imported_at) "
            "VALUES ('note', ?, ?, 'n.pdf', 'n.pdf', 'application/pdf', 1, 'x', 2, 'Огляд', 'consultation', 'native_text', ?)",
            (user_id, patient_id, utc_now()))
        doses = immunizations.parse_visit_vaccinations([{"page_number": 2, "native_text": note}])
        store_document_doses(connection, user_id, patient_id, "note", doses, "native_text")
        connection.commit()
    after = {row["id"]: row for row in rows(settings, user_id)}
    card_twinrix = next(row for row in after.values() if row["lot_number"] == "AHABB490BE")
    assert card_twinrix["document_id"] == "doc-1", "the card's row is kept"
    assert card_twinrix["site"] == "дельтоподібний м'яз (ліва рука)"
    assert card_twinrix["clinician"] == "Іваненко Олена Петрівна"
    assert card_twinrix["lot_number"] == before[card_twinrix["id"]]["lot_number"]
    assert len([row for row in after.values() if row["lot_number"] == "AHABB490BE"]) == 1
