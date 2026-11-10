from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, replace
from datetime import date, datetime
from pathlib import Path

from ..config import local_overrides
from ..immunizations import is_vaccination_card
from .concepts import specimen_family
from .text import collapse_space, combined_page_text


DATE_RE = re.compile(r"\b(\d{2})[./](\d{2})[./](\d{4})\b")
#: «Консультація <specialty>» as a heading.  Nominative only — the genitive
#: «консультації» is the disclaimer at the foot of every laboratory report.
CONSULTATION_HEADING_RE = re.compile(r"консультація\s+[а-яіїєґ]")
#: How far into a document a title can still be a title.
CONSULTATION_HEADING_WINDOW = 120
#: A heading printed on a line of its own above the patient line, however far
#: the letterhead pushes it: form 028/о's «КОНСУЛЬТАЦІЯ ТЕРАПЕВТА» (with the
#: clinic's phone beside it), «ПОВТОРНА КОНСУЛЬТАЦІЯ АЛЕРГОЛОГА», and a
#: gynaecologist's «Консультаційне заключення».  A study the note quotes
#: («УЗД ЩЗ: …», «Polycheck» among the recommended services) sits below.
CONSULTATION_HEADING_LINE_RE = re.compile(
    r"^[ \t]*((?:повторна[ \t]+)?консультація[ \t]+[^\W\d_]{4,}(?:[ \t-]+[^\W\d_]{4,})?|консультаційне[ \t]+заключення"
    # The form's own name, «Консультаційний висновок спеціаліста».
    r"|консультаці[йв]ний[ \t]+висновок(?:[ \t]+спеціаліста)?)"
    r"[ \t]*(?:\+38[\d \t]*[,.]?)?[ \t]*$",
    re.I | re.M,
)
#: The line that names the person; a document's heading is printed above it.
#: Form 028/о numbers it: «2. Прізвище, ім'я, по батькові пацієнта | …».
PATIENT_LABEL_RE = re.compile(
    r"^[^\w\n]{0,3}(?:\d[.\s][ \t]*)?(?:Пацієнт\w*|Клієнт|Прізвище|П[.,]?[ \t]?[ІI1][.,]?[ \t]?Б)(?![^\W\d_])"
    r"[^\n:|]{0,32}[:|][ \t]*",
    re.I | re.M,
)
#: A specialist in the genitive, as a heading names one: «гастроентеролога»,
#: «терапевта», «ортопеда», «хірурга», «педіатра» -- not OCR's «онсул».
_SPECIALIST = r"[а-яіїєґ]{3,}(?:лога|евта|педа|урга|атра)"
#: The name of a consultation form itself, which only a heading prints (never
#: a recommendation): «Консультаційне заключення», «Консультативний висновок
#: (спеціаліста)», read by OCR with a stray token inside («Консультаційне as
#: заключення»).  «… висновок за результатами дихального тесту» is a test's report.
#: A phone photo's OCR splits and garbles the words («Консу: втаційне
#: заключення», «Консультативне заклю слючення», «КОНСУЛЬТАТИВНИЙ BUCHOBOK»
#: with Latin look-alikes); `_form_heading` spells the heading out again.
_FORM_NAME = (
    r"консу(?:льта)?\w{0,6}?(?:[:.]?[ \t]+\w{0,4})?(?:ці[йв]н|тивн)\w*[ \t]+(?:\S{1,3}[ \t]+)?"
    r"(?:висновок|buchobok|заключення|заклю\w*[ \t]+\w*ючення)"
    r"(?:[ \t]+спеціаліста)?(?![ \t]+за[ \t]+результат)"
)
FORM_NAME_RE = re.compile(_FORM_NAME, re.I)
#: The same heading inside a line a photo's OCR padded with debris («І-й
#: КОНСУЛЬТАЦІЯ ГАСТРОЕНТЕРОЛОГА», «ЕКСПЕРТ КОНСУЛЬТАТИВНИЙ ВИСНОВОК es 32 …»,
#: «Е ОГЛЯД ГІНЕКОЛОГА»).
CONSULTATION_HEADING_PHRASE_RE = re.compile(
    rf"((?:повторна[ \t]+)?консультація[ \t]+(?:лікаря(?:-{_SPECIALIST})?|{_SPECIALIST})"
    rf"|{_FORM_NAME}"
    rf"|огляд[ \t]+(?:лікаря(?:-{_SPECIALIST})?|{_SPECIALIST}))(?![а-яіїєґ])",
    re.I,
)
CONSULTATION_HEADING_ALONE_RE = re.compile(
    rf"^[^\w\n]{{0,3}}{CONSULTATION_HEADING_PHRASE_RE.pattern}[^\w\n]{{0,3}}$", re.I | re.M
)
#: A visit note's own sections, each at the start of a line (OCR may leave a
#: few marks before it).  Complaints or history with a second section is a
#: doctor's note, whatever studies its history quotes («УЗД ОЧП від …») or its
#: plan orders («Бакпосів калу …»).
VISIT_SECTION_RES = {
    "complaints": re.compile(r"^[^\w\n]{0,3}\w{0,2}[ \t]?скарг", re.I | re.M),
    "history": re.compile(r"^[^\w\n]{0,3}\w{0,2}[ \t]?(?:\w+[ \t]+)?анамн", re.I | re.M),
    "examination": re.compile(r"^[^\w\n]{0,3}\w{0,2}[ \t]?(?:об['’`ʼ]?єктивн|об-но\b)", re.I | re.M),
    "diagnosis": re.compile(r"^[^\n]{0,20}діагноз", re.I | re.M),
    "plan": re.compile(r"^[^\w\n]{0,3}(?:\d[.)][ \t]*)?(?:рекоменд|призначен)", re.I | re.M),
}


def visit_note_structure(text: str) -> bool:
    found = {name for name, pattern in VISIT_SECTION_RES.items() if pattern.search(text)}
    # A study report may carry a history line and a recommendation; only a
    # visit examines the person or names a diagnosis beside its history.
    return ("complaints" in found and len(found) >= 2) or (
        "history" in found and bool(found & {"examination", "diagnosis"})
    ) or ("plan" in found and bool(DIAGNOSIS_LABEL_RE.search(text)))


#: A doctor's «Діагноз попередній:» opening a line: a note's second page
#: («Діагноз … / Рекомендації: …») carries no complaints or history.  A study
#: names its finding «Висновок»; «Діагноз кольпоскопічний:» is a study's own.
DIAGNOSIS_LABEL_RE = re.compile(
    r"^[^\w\n]{0,3}діагноз(?:[ \t]+(?:попередній|клінічний|основний|заключний))?[ \t]*:", re.I | re.M
)


#: A phone screenshot's own interface, read by OCR with the document in it:
#: the status-bar clock («22:39 2»), the messenger's header («< Ви», «<4
#: Viber») with the day the message was sent («16.07.26»), a viewer's page
#: counter («3 із 8») and toolbar («Відкрити в Книги»).  None of it is the
#: document; the sent date in particular is not the report's date.  A
#: viewer's «17:22:33» acquisition time is part of an image and stays.
SCREEN_CHROME_RE = re.compile(
    r"^[^\w\n]{0,3}(?:\d{1,2}:\d{2}\d?(?![:\d])(?:[ \t]+\S{1,6}){0,3}"
    r"|<[ \t]*\S{0,6}(?:[ \t]+\S{0,6})?|Ви|\d{2}\.\d{2}\.\d{2}|\d{1,2}[ \t]+із[ \t]+\d{1,2})[ \t]*$"
    r"|^[^\n]{0,12}\b(?:Viber|Telegram|WhatsApp|Відкрити в Книги)\b[^\n]{0,20}$",
    re.M,
)


def strip_screen_chrome(text: str) -> str:
    return SCREEN_CHROME_RE.sub("", text)


def consultation_heading(text: str) -> str | None:
    """The consultation heading printed above the patient line, or None."""
    patient = PATIENT_LABEL_RE.search(text)
    if not patient:
        # OCR lost the patient line: only the form's own name still says it,
        # or a heading alone on its line («ОГЛЯД ГІНЕКОЛОГА» over «ацієнта:»).
        named = FORM_NAME_RE.search(text, 0, 1500)
        if named:
            return _heading_as_printed(named.group(0))
        alone = CONSULTATION_HEADING_ALONE_RE.search(text, 0, 1500)
        return _heading_as_printed(alone.group(1)) if alone else None
    match = CONSULTATION_HEADING_LINE_RE.search(text, 0, patient.start()) or CONSULTATION_HEADING_PHRASE_RE.search(
        text, 0, patient.start()
    )
    return _heading_as_printed(match.group(1)) if match else None


def _heading_as_printed(heading: str) -> str:
    if FORM_NAME_RE.fullmatch(collapse_space(heading)):
        return _form_heading(heading)
    return _without_stray_token(heading)


def _form_heading(heading: str) -> str:
    """The form's name spelt out from what OCR kept of it: «Консу: втаційне
    заключення» is «Консультаційне заключення», «КОНСУЛЬТАТИВНИЙ BUCHOBOK» is
    «Консультативний висновок»."""
    folded = heading.casefold()
    adjective = "Консультативн" if "тивн" in folded else "Консультаційн"
    named = adjective + ("ий висновок" if re.search(r"висновок|buchobok", folded) else "е заключення")
    return named + (" спеціаліста" if "спеціаліста" in folded else "")


def _without_stray_token(heading: str) -> str:
    """«Консультаційне as заключення» → «Консультаційне заключення»."""
    return re.sub(r"\s\S{1,3}(?=\s+(?:висновок|заключення))", "", collapse_space(heading), flags=re.I)


#: Every `clinical_type` `classify_document` can emit.  Anything else stored
#: in `documents.clinical_type` was written by somebody other than this module.
KNOWN_CLINICAL_TYPES: frozenset[str] = frozenset({
    "laboratory", "radiology_mri", "radiology_xray", "ultrasound", "pathology",
    "diagnostic_image", "compound_bundle", "consultation", "allergy",
    "microbiology", "electrocardiogram", "blood_pressure", "administrative",
    "clinical_report", "immunization_record", "questionnaire",
})


@dataclass(frozen=True)
class Classification:
    vendor: str
    website: str | None
    clinical_type: str
    title: str
    report_date: str | None
    order_identifier: str | None
    status: str
    extraction_strategy: str
    confidence: float
    notes: str | None = None
    #: When the specimen was taken, as printed: `YYYY-MM-DD` or `YYYY-MM-DDTHH:MM`.
    collected_at: str | None = None
    #: When the laboratory released the report, same format.
    issued_at: str | None = None
    #: The specimen the heading names («сироватка крові», «сеча»), lowercase.
    specimen: str | None = None
    #: A pathology report's own number («№ 40217/24»), which outlives the order.
    report_number: str | None = None


def iso_date(match: re.Match[str] | None) -> str | None:
    if not match:
        return None
    day, month, year = match.groups()
    return valid_date(year, month, day)


def valid_date(year: str | int, month: str | int, day: str | int) -> str | None:
    try:
        return date(int(year), int(month), int(day)).isoformat()
    except ValueError:
        return None


def first_match(patterns: list[str], text: str) -> re.Match[str] | None:
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE | re.MULTILINE)
        if match:
            return match
    return None


#: Where each laboratory prints its order number.  «Замовлення:» must not be
#: preceded by «Дата»: Synevo prints «Дата замовлення: 28.08.2025», and the
#: unanchored pattern stored the day of the month (28, 15, 21…) as the order
#: number of every Synevo report.  Synevo prints its barcode unlabelled after
#: the patient's sex, which is the number its own cabinet calls `Barcode` --
#: ten digits since 2025, eight on the 2015-2018 reports.  An ALEX² export
#: names the same barcode «Ідентифікаційний номер зразка», with a line of
#: unrelated text between the label and the number.
ORDER_PATTERNS = [
    r"Результати дослідження №\s*(\d+)",
    r"(?<!дата )\bЗам\s*овлення:\s*(\d{5,})",
    r"№\s*обстеження:\s*([^\s]+)",
    r"Стать:\s*\S+\s+(\d{8,10})\b",
    r"Ідентифікаційний номер зразка:(?:[^\d\n]*\n){0,2}[^\d\n]*(\d{8,12})\b",
    # Synevo's illustrated companion report: «Штрих-код <barcode>-<suffix>».
    r"Штрих-код\s+(\d{8,12})-\d+\b",
    # The partner clinic's SILAB print: «№ замовл.: <order>», which OCR reads
    # as «Мезамовл.:», «Ne замовл.», «Nesamosn.:».  Its 2026 print gives the
    # barcode beside the client's name instead.
    r"(?:замовл|samosn)[^\s\d]*\s*(\d{8,12})\b",
    r"^Клієнт:[^\n\d]*(\d{10})\b",
    # The SILAB cytology passport: «ШК <barcode>» (штрих-код) beside the
    # client's name, which OCR reads as «WK».
    r"(?<!\w)(?:ШК|WK)\s+(\d{10})\b",
]
#: What OCR leaves around a spoilt heading: marks, and at most one scrap of up to three letters.
_OCR_DEBRIS = r"\W*(?:\w{1,3}\W*)?"
#: BD FocalPoint's cytology passport printed beside a PAP test: micrographs
#: and method text, no result of its own.  Its heading reaches OCR spoilt
#: («ui итологічний паспо ee»); the line naming the images does not.
CYTOLOGY_PASSPORT_RE = re.compile(
    rf"індивідуальні цифрові зображення|^{_OCR_DEBRIS}\w?итологічний\s+паспо\w*{_OCR_DEBRIS}$", re.I | re.M)
#: How lab sync names a laboratory's download: «esculab-<order>.pdf»,
#: «synevo-<barcode>-1.pdf», «expert-<order>.pdf».  The number is the lab's
#: own order id, the one to fall back on when the page prints none.  Files
#: downloaded before the providers' keys took their official spelling
#: (migration 050) are named «eskulab-…» and «ekspert-…» on disk.
LAB_SYNC_FILENAME_RE = re.compile(r"^(?:esculab|eskulab|synevo|expert|ekspert)-(\d{5,})(?:-\d+)?$")


def extract_order_identifier(text: str, filename: str = "") -> str | None:
    match = first_match(ORDER_PATTERNS, text)
    if match:
        return match.group(1)
    named = LAB_SYNC_FILENAME_RE.match(Path(filename).stem)
    return named.group(1) if named else None


def misread_order(order: str, known: set[str] | frozenset[str]) -> bool:
    """Whether `order` is one of `known` with a single digit misread by OCR.

    A photo's OCR reads a barcode's printed number with an 8 as a 6: a number
    of the same length one digit away from an order already on file is that
    order, not another one, and is better not stored at all.
    """
    return any(
        len(other) == len(order) and sum(a != b for a, b in zip(other, order)) == 1 for other in known
    )


def repair_order_identifiers(connection) -> int:
    """Re-read order numbers stored before ORDER_PATTERNS was anchored.

    Only identifiers of one or two characters are touched -- no laboratory
    numbers its orders that way, so each one is a captured day of the month.
    Idempotent: a repaired row no longer matches the filter.
    """
    rows = connection.execute(
        """SELECT d.id, group_concat(coalesce(p.native_text, '') || char(10) || coalesce(p.ocr_text, ''), char(10)) text
             FROM documents d JOIN document_pages p ON p.document_id = d.id
            WHERE d.order_identifier IS NOT NULL AND length(d.order_identifier) <= 2
            GROUP BY d.id"""
    ).fetchall()
    for row in rows:
        connection.execute(
            "UPDATE documents SET order_identifier=? WHERE id=?",
            (extract_order_identifier(row[1] or ""), row[0]),
        )
    return len(rows)


GENITIVE_MONTHS = (
    "січня", "лютого", "березня", "квітня", "травня", "червня",
    "липня", "серпня", "вересня", "жовтня", "листопада", "грудня",
)
#: A labelled date as a phone photo's OCR reads it: the day's dot read as a
#: comma («12,10.2023»), a colon («18:08.2023») or a space («03 08.2025»).
#: Only ever used right after its label, where nothing else is printed.
_LDATE = r"(\d{2})(?:[./]|[,:][ \t]?|[ \t])(\d{2})[./](\d{4})"
#: InMed and Ultramed print the examination day in a column beside its label.
#: A photo's OCR often keeps the value and loses the label, leaving the date
#: alone on a line just under the patient row («ПІБ пацієнта, рік народження
#: …» / «09.05.2024 , р,»), or under Ultramed's birth year («1990» /
#: «14.08.2026»).  «О.М. 12.03.2025» (last period) is labelled, so not alone.
LONE_DATE_UNDER_PATIENT_RE = re.compile(
    r"^(?:[^\n]*ПІБ пацієнта[^\n]*|[^\w\n]{0,3}(?:\S{1,4}[ \t]+)?(?:19|20)\d{2}(?:[ \t]*р\.?)?[^\w\n]{0,3})\n"
    r"(?:[^\n]*\n){0,2}?"
    r"[^\w\n]{0,3}(?:\w[ \t]+)?(\d{2})[./](\d{2})[./](\d{4})(?:[ \t,]+\S{1,3}){0,3}[ \t]*$",
    re.I | re.M,
)
WRITTEN_DATE_RE = re.compile(rf"^[ \t]*(\d{{1,2}})[ \t]+({'|'.join(GENITIVE_MONTHS)})[ \t]+(\d{{4}})[ \t]*(?:року|р\.)", re.I | re.M)


#: Form 027/о's heading, «ВИПИСКА / із медичної карти амбулаторного
#: (стаціонарного) хворого», wrapped or not.
DISCHARGE_027_RE = re.compile(r"виписка\s+із\s+медичної\s+карти\s+амбулаторного\s*\(\s*стаціонарного\s*\)\s+хворого")
DISCHARGE_027_TITLE = "Виписка із медичної карти хворого (форма 027/о)"


def extract_date(text: str, filename: str) -> str | None:
    prioritized = first_match(
        [
            # Form 027/о: the day the stay ended, printed under «виписки або
            # смерті (підкреслити)»; the admission day stands above it.
            r"виписки\s+або\s+смерті[^\n]*\n[^\d\n]{0,3}(\d{2})[./](\d{2})[./](\d{4})",
            r"Дата візиту:\s*(\d{2})[./](\d{2})[./](\d{4})",
            # Form 028/о, beside the patient's name; a photo's OCR splits the
            # word («консульт ації: ії: 08.04. 08.04.2023»).
            r"Дата консульт ?ації:?[^\d\n]{0,8}(?:\d{2}\.\d{2}\.[ \t]+)?(\d{2})[./](\d{2})[./](\d{4})",
            r"Дата звернення:\s*(\d{2})[./](\d{2})[./](\d{4})",
            # An eHealth diagnostic report: «Дата та час формування діагностичного звіту: 09.05.2024 12:06».
            r"Дата та час формування[^\n:]{0,30}:\s*(\d{2})[./](\d{2})[./](\d{4})",
            # The companion report prints the label without its colon; OCR of
            # a partner clinic's print reads the table rule as «|».
            r"Дата замовлення:?[\s|]*(\d{2})[./](\d{2})[./](\d{4})",
            # The same print when OCR lost the label: the order moment opens
            # the line, before the order number («11/08/2021 14:18 №замовл.:»,
            # read as «Nesamosn.», «Мезамовл:»).
            r"^(\d{2})/(\d{2})/(\d{4})(?:[ \t]+\d{1,2}:?\d{2})?[ \t]+[^\n]{0,6}?(?:замовл|samosn)",
            # A Synevo partner's print: «Дата забору матеріалу: 11.08.2021».
            r"Дата забору матеріалу:\s*(\d{2})[./](\d{2})[./](\d{4})",
            r"Зам\s*овлення:\s*\S+\s*/\s*(\d{2})[./](\d{2})[./](\d{4})",
            # InMed prints it without the colon; a photo's OCR reads its table
            # rule as «|» («Дата обстеження | 09.05.2024»).
            rf"Дата обстеження:?[\s|]*{_LDATE}",
            # The same label read below its value: «п 19.03.2025» / «Дата обстеження».
            rf"^[^\w\n]{{0,3}}(?:\w[ \t]+)?{_LDATE}[ \t]*\n[^\w\n]{{0,3}}Дата обстеження[ \t|:]*$",
            # Form 028/о's «Дата консультації:» wrapped after its first word;
            # «Дата наступної / консультації» is the next visit, never this one.
            rf"(?<!наступної\n)^[^\w\n]{{0,3}}консультації:[ \t]*{_LDATE}",
            # Breath tests: «Дата тестування: | 15.08.2026»; «Дата проведення
            # тесту» heads a column whose value ends the line below.
            r"Дата тестування:?[\s|]*(\d{2})[./](\d{2})[./](\d{4})",
            r"Дата проведення тесту[^\n]*\n[^\n]*?(\d{2})[./](\d{2})[./](\d{4})",
            # «Дате:» is OCR's «Дата:».
            rf"^Дат[аеи]:\s*{_LDATE}",
            # Expert's carotid duplex signs off «Лікар: <name> Дата: 13.05.2023».
            r"^Лікар:[^\n]*?\bДата:\s*(\d{2})[./](\d{2})[./](\d{4})",
            # Expert's X-ray: «Комп'ютерна рентгенографія досліджень № 209 / від
            # 31.01.2022»; a photo's OCR reads «№» as «Ne» and adds debris.
            r"досліджен\w*\s+(?:№|N\S{0,2}|Ме)\s*\d+[^\n]{0,12}\n?[\s|/]*від\s+(\d{2})[./](\d{2})[./](\d{4})",
            # A form's sign-off line: «підпис» / «дата 18.08.2023».
            rf"^[ \t]*дата[ \t]*:?[ \t]*{_LDATE}[ \t]*$",
            r"Дата здачі аналізу:\s*(\d{2})[./](\d{2})[./](\d{4})",
            # Expert's «Пацієнт: <name>, 01.01.1990 р.н. 02.03.2025»: the birth date precedes «р.н.»
            # and the order date follows it.  A bare «Пацієнт: ... р.н. 12.03.1980» is the birth date.
            r"Пацієнт:[^\n]*?\d{2}[./]\d{2}[./]\d{4}\s*р\.н\.\s*(\d{2})[./](\d{2})[./](\d{4})",
            # Expert Hospital's ultrasound footer is a two-column table that
            # text extraction reads across: «Дата дослідження: <doctor> /
            # Лікар: / 01.02.2025», and on one layout even «Дата <name> /
            # дослідження: Лікар: <name> / 13.02.2025».  The date sits up to
            # two lines below its label.
            r"Дата(?:[ \t]+\S+)?\s+дослідження:(?:[^\n]*\n){0,2}?[^\n]*?(\d{2})[./](\d{2})[./](\d{4})",
            r"дата інтерпретації\s*(\d{2})[./](\d{2})[./](\d{4})",
            # Expert Hospital's laboratory header: «Пацієнт: <name>, <birth
            # date> <order date>», the second date unlabelled.
            r"^Пацієнт:[^\n]*?\d{2}[./]\d{2}[./]\d{4}[ \t]+(\d{2})[./](\d{2})[./](\d{4})[ \t]*$",
            # A POLYCHECK chip, read on the day of the examination.
            r"^Скануй\s+(\d{2})[./](\d{2})[./](\d{4})",
        ],
        text,
    )
    if prioritized:
        return iso_date(prioritized)
    # An X-ray viewer's overlay: «2022-01-31 1993-12-06 F 28Y» -- the study,
    # then the birth date, sex and age.
    viewer = re.search(r"^(\d{4})-(\d{2})-(\d{2})[ \t]+\d{4}-\d{2}-\d{2}[ \t]+[FM][ \t]+\d{1,3}Y\b", text, re.M)
    if viewer:
        return valid_date(*viewer.groups())
    # A handwritten-form clinic prints the visit with a two-digit year
    # («Дата візиту: 02.08.23»); only this label is trusted with one.
    short = re.search(r"Дата візиту:\s*(\d{2})[./](\d{2})[./](\d{2})(?!\d)", text, re.I)
    if short:
        return valid_date(2000 + int(short.group(3)), short.group(2), short.group(1))
    # A consultation signed off in words: «17 липня 2026 року».
    written = WRITTEN_DATE_RE.search(text)
    if written:
        return valid_date(written.group(3), GENITIVE_MONTHS.index(written.group(2).casefold()) + 1, written.group(1))
    lone = LONE_DATE_UNDER_PATIENT_RE.search(text)
    if lone:
        return iso_date(lone)
    garmin = re.search(
        r"Дані надані програмою Garmin Connect\s+(\d{1,2})\s+"
        r"(січ\.|лют\.|бер\.|квіт\.|трав\.|черв\.|лип\.|серп\.|вер\.|жовт\.|лист\.|груд\.)\s+(\d{4})",
        text,
        re.I,
    )
    if garmin:
        months = {
            "січ.": 1, "лют.": 2, "бер.": 3, "квіт.": 4, "трав.": 5, "черв.": 6,
            "лип.": 7, "серп.": 8, "вер.": 9, "жовт.": 10, "лист.": 11, "груд.": 12,
        }
        return valid_date(garmin.group(3), months[garmin.group(2).casefold()], garmin.group(1))
    kardia = re.search(
        r"Recorded(?:\s+on)?\s*:\s*(?:Heart Rate:\s*)?[A-Z][a-z]+,\s+([A-Z][a-z]+\s+\d{1,2},\s+\d{4})",
        text,
        re.I,
    )
    if kardia:
        try:
            return datetime.strptime(kardia.group(1), "%b %d, %Y").date().isoformat()
        except ValueError:
            pass
    filename_match = DATE_RE.search(filename)
    if filename_match:
        return iso_date(filename_match)
    iso_filename = re.search(r"(?<!\d)(\d{4})-(\d{2})-(\d{2})(?!\d)", filename)
    if iso_filename:
        return valid_date(*iso_filename.groups())
    underscored = re.search(r"(?<!\d)(\d{4})_(\d{2})_(\d{2})(?!\d)", filename)
    return valid_date(*underscored.groups()) if underscored else None


_DMY = r"(\d{2})[./](\d{2})[./](\d{4})"
_HM = r"(?:,?[ \t]+(\d{1,2}):(\d{2}))?"
#: Labelled sample-collection moments, most specific first.
COLLECTED_PATTERNS = [
    # Synevo, which prints the date with dots.  The partner clinic's SILAB
    # form prints the order with slashes («11/08/2021 14:20»), and there the
    # order is not the draw: one smear was taken the day before it was ordered.
    re.compile(r"Дата замовлення:?\s*(\d{2})\.(\d{2})\.(\d{4})" + _HM, re.I),
    re.compile(rf"Дата забору матеріалу:\s*{_DMY}{_HM}", re.I),  # Synevo, a partner clinic's copy
    re.compile(rf"Дата здачі аналізу:\s*{_DMY}{_HM}", re.I),  # St Paraskeva forms
    re.compile(rf"ЗАБІР КРОВІ\s+(?:НАДРУКОВАНИЙ НА\s+)?{_DMY}", re.I),  # ALEX²
    re.compile(rf"Дата операції:?\s*{_DMY}", re.I),  # pathology: when tissue was taken
]
ISSUED_PATTERNS = [
    re.compile(rf"Дата видачі:\s*{_DMY}{_HM}", re.I),  # Esculab
    re.compile(rf"Час виконання:\s*{_DMY}{_HM}", re.I),  # Esculab, older header
    re.compile(rf"Дата виконання:\s*{_DMY}{_HM}", re.I),  # Esculab, 2026 header
    re.compile(rf"Дата видруку:?\s*{_DMY}{_HM}", re.I),  # Synevo companion report
    re.compile(rf"Дата результату:[\s|]*{_DMY}{_HM}", re.I),  # partner clinic's SILAB print, 2025 on
    re.compile(rf"ЗАБІР КРОВІ\s+НАДРУКОВАНИЙ НА\s+{_DMY}\s+{_DMY}", re.I),  # ALEX², two columns
    re.compile(rf"НАДРУКОВАНИЙ НА\s+{_DMY}", re.I),
    # POLYCHECK prints its «Дата видруку» label as a picture; the date stands
    # alone on its line, followed by the Biocheck software version:
    # «18.11.2024 (V. 6.01.21 )».
    re.compile(rf"^{_DMY}\s*\(V\.\s*\d", re.M),
]
ESCULAB_ORDER_DATE_RE = re.compile(rf"Зам\s*овлення:\s*\S+\s*/\s*{_DMY}", re.I)
SAMPLING_TIME_RE = re.compile(r"Час відбору:\s*(\d{1,2}):(\d{2})", re.I)
#: «Патологогістологічне дослідження № 40217/24»; OCR reads «№» as «Ме», «N2».
REPORT_NUMBER_RE = re.compile(
    r"(?:гістологічне|цитологічне)\s+дослідження\s+(?:№\s*|[NМ]\S{0,2}\s+)(\d{3,})\s*/\s*(\d{2})\b",
    re.I,
)


def moment(day: str, month: str, year: str, hour: str | None = None, minute: str | None = None) -> str | None:
    """`YYYY-MM-DD`, or `YYYY-MM-DDTHH:MM` when a valid time was printed."""
    iso = valid_date(year, month, day)
    if iso and hour is not None and int(hour) < 24 and int(minute or 0) < 60:
        return f"{iso}T{int(hour):02d}:{int(minute or 0):02d}"
    return iso


def extract_collected_at(text: str) -> str | None:
    for pattern in COLLECTED_PATTERNS:
        match = pattern.search(text)
        if match:
            return moment(*match.groups())
    # Esculab prints the order date in its header and the sampling time beside
    # every result («Час відбору: 07:40»): together they are the draw.
    order = ESCULAB_ORDER_DATE_RE.search(text)
    if order:
        sampled = SAMPLING_TIME_RE.search(text)
        return moment(*order.groups(), *(sampled.groups() if sampled else ()))
    return None


def extract_issued_at(text: str) -> str | None:
    for pattern in ISSUED_PATTERNS:
        match = pattern.search(text)
        if match:
            groups = match.groups()
            # The two-column ALEX² header carries the draw date first.
            return moment(*(groups[3:6] if len(groups) == 6 and groups[3] else groups))
    return None


def extract_report_number(text: str) -> str | None:
    match = REPORT_NUMBER_RE.search(text)
    return f"№ {match.group(1)}/{match.group(2)}" if match else None


#: Order and turnaround codes Expert Hospital appends to a heading: «(A4001)»,
#: «(B075)», «(O0044)», «(F0508)», «(2 ДНІ)», «(12 ГОДИН)», «(24 ГОД)».
#: Removed together with the spaces before it, by `_sub_with_space_before`.
HEADING_CODE_RE = re.compile(
    r"\((?:[A-ZА-ЯІЇЄҐ]\d{3,5}|\d+\s*(?:дн[іяь]|днів|день|годин[аи]?|год)\.?)\)", re.I
)
#: Synevo's flag column, read into the heading; replaced, with the spaces
#: around it, by one space.
SYNEVO_INDICATOR_RE = re.compile(r"Індикатор зони підвищеної уваги\s*")
SYNEVO_TABLE_HEADER = "Показник Результат Од. Референтний інтервал"
#: The branch city Synevo prints after a section name.
SYNEVO_CITIES = ("Київ", "Львів", "Харків", "Одеса", "Дніпро")
CLOSING_BRACKET_RE = re.compile(r"\)")
MRI_STUDY_NUMBER_RE = re.compile(r"\bMRI\s*\d+\b")
#: Where a report stops being its heading: a title is never a recommendation,
#: a conclusion or a plan («Повторна консультація невролога…, МРТ поперекового»
#: was a cut recommendation line, picked up for its «МРТ»).
TITLE_STOP_RE = re.compile(r"рекоменд|висновок|заключення|план обстеження", re.I)
PATIENT_LINE_RE = re.compile(r"^(?:Пацієнт|Прізвище):")
#: The line above a printed heading: Expert's licence block (the number on
#: the next line), or the approval line of a Ministry form («04.01.2001 р. № 1»).
HEADING_ANCHOR_RE = re.compile(r"^(?:Ліцензія МОЗ України|\d{2}\.\d{2}\.\d{4}\s*р\.\s*№\s*\d+)$")
INVISIBLE_RE = re.compile("[\u200b-\u200d\u2060\ufeff]")
ULTRASOUND_HEADING_RE = re.compile(
    r"^(?:протокол\s+)?(дуплексного\s+)?ультразвуков(?:ого|е)\s+(?:дослідження|обстеження)\b\s*+(.*)$", re.I
)
KEYWORD_TITLE_TOKENS = (
    "БІОПСІЯ", "МРТ ", "МАГНІТНО-РЕЗОНАНС", "КОЛОНОСКОП", "ГАСТРОСКОП", "БАКПОСІВ",
    "КОАГУЛОГРАМА", "ГЛІКОВАНИЙ ГЕМОГЛОБІН", "ЗАГАЛЬНИЙ АНАЛІЗ", "ПАКЕТ ", "ВІТАМІН D",
    "HLA B-27", "АНТИНУКЛЕАРНІ", "АУТОІМУННА", "ДИХАЛЬНИЙ ТЕСТ", "ПРОТОКОЛ КОЛЬПОСКОПІЇ",
)
#: Cyrillic abbreviations that stay upper case when an all-caps heading is
#: sentence-cased.  Latin tokens, tokens with digits and roman numerals are
#: always kept as printed.
KEEP_UPPER = frozenset(
    "ЗАС ЗАК ВІЛ ШОЕ МНВ АЧТЧ ПТЧ ПТІ ДДМ УЗД МРТ КТ ЕКГ ОГК ЛПВЩ ЛПНЩ ЛПДНЩ ІПСШ ПЛР ІФА "
    "ДНК РНК СРБ ТТГ АЛТ АСТ АЛАТ АСАТ ГГТ ЛФ ЛДГ КФК ХС РФ АСЛО ЛОР ШКТ МОЗ ЛШ ПШК".split()
)
#: Single-letter prepositions and conjunctions; any other lone capital («гепатит
#: С», «гепатиту В)», «Х панель») is a name and keeps its case.
LOWER_SINGLE = frozenset("ВУЗІЙАО")
#: Eponyms printed in capitals («ПРОТРОМБІН ПО КВІКУ», «МЕТОД ВЕСТЕРГРЕНА»).
PROPER_NOUNS = frozenset({"КВІКУ", "КВІКОМ", "ВЕСТЕРГРЕНА", "ВЕСТЕРГРЕНОМ"})
WORD_RE = re.compile(r"[^\W\d_]+")
#: Specimens a heading can name, as the laboratory prints them.
SPECIMEN_RE = re.compile(
    r"\(\s*(?:матеріал:\s*)?(?:приносний матеріал,\s*)?"
    r"(сироватка крові|плазма крові|цільна кров|венозна кров|капілярна кров|фекалії|кал|сеча|слина"
    r"|мокротиння|виділення із зіву|виділення з носа)\s*\)"
    r"|\b(сеч[іа])\b",
    re.I,
)


def _sub_with_space_before(pattern: re.Pattern[str], repl: str, value: str) -> str:
    """`pattern.sub(repl, value)` that also drops the whitespace run before each match.

    The same result as a leading «\\s*» in the pattern, without the leading
    quantifier the engine would rescan from every position of a space run.
    `pattern` has no capturing group and starts with a non-space character.
    """
    pieces = pattern.split(value)
    return repl.join([piece.rstrip() for piece in pieces[:-1]] + pieces[-1:])


def _strip_synevo_city(section: str) -> str:
    """«Біохімія Київ» → «Біохімія»: the city must follow a space."""
    for city in SYNEVO_CITIES:
        head = section.removesuffix(city)
        if head != section and head[-1:].isspace():
            return head.rstrip()
    return section


def _strip_truncated_tail(value: str) -> str:
    """Drop a last word cut short with «...» or «…», and the spaces before it."""
    if not value.endswith(("...", "…")):
        return value
    return value[: len(value) - len(value.split()[-1])].rstrip()


def _single_letter_case(token: str, rest: str) -> str:
    if token == "І" and re.match(r"\s+ТА\s+[ІV]+\b", rest):
        return token  # «ВІЛ І ТА ІІ ТИПУ»: roman numerals
    if token in LOWER_SINGLE and re.match(r"\s+[^\W\d_]", rest):
        return token.lower()
    return token


def _sentence_case_word(match: re.Match[str]) -> str:
    """One word of an all-caps heading, lowered unless it is a name or a code."""
    token = match.group(0)
    value = match.string
    if not token.isupper() or re.search(r"[A-Za-z]", token) or token in KEEP_UPPER:
        return token
    if token in PROPER_NOUNS:
        return token.capitalize()
    if any("\u0370" <= char <= "\u03ff" for char in token):
        return token.lower()
    if set(token) <= set("ІVX") and len(token) > 1:
        return token
    if len(token) == 1:
        return _single_letter_case(token, value[match.end():])
    # Glued to a digit («HBA1C», «57.1») is a code, not a word.
    start, end = match.span()
    if (start and value[start - 1].isdigit()) or (end < len(value) and value[end].isdigit()):
        return token
    return token.lower()


def sentence_case(value: str) -> str:
    """«ЗАГАЛЬНИЙ АНАЛІЗ СЕЧІ (ЗАС + …)» → «Загальний аналіз сечі (ЗАС + …)».

    Deterministic and conservative: Latin words (organisms, HLA, IgE), words
    with digits, roman numerals and the abbreviations in KEEP_UPPER are left
    exactly as printed; Greek letters (α-амілаза) are lowered.
    """
    return _capitalise_sentences(WORD_RE.sub(_sentence_case_word, value))


def _capitalise_sentences(lowered: str) -> str:
    """Upper-case the first letter, and the first after an opening quote or «. »."""
    chars = list(lowered)
    capitalise = True
    for index, char in enumerate(chars):
        if char.isalpha():
            if capitalise:
                chars[index] = char.upper()
            capitalise = False
        elif char == '"' and (index == 0 or chars[index - 1] == " "):
            capitalise = True
        elif char == "." and index + 1 < len(chars) and chars[index + 1] == " ":
            capitalise = True
    return "".join(chars)


def _mostly_upper(value: str) -> bool:
    letters = [char for char in value if "\u0400" <= char <= "\u04ff"]
    return len(letters) >= 4 and sum(char.isupper() for char in letters) >= 0.8 * len(letters)


def normalise_heading(value: str) -> str:
    """One printed heading: quotes balanced, order/turnaround codes dropped."""
    value = collapse_space(value)
    previous = None
    while value != previous:
        previous = value
        value = _sub_with_space_before(HEADING_CODE_RE, "", value).strip()
        if len(value) >= 2 and value[0] == value[-1] == '"':
            value = value[1:-1].strip()
    value = value.replace('""', '"')
    if value.count('"') % 2:
        value += '"'  # «ПАКЕТ "ЛІПІДОГРАМА» lost its closing quote to the outer pair
    return value


def clean_title(value: str) -> str:
    # These PDFs print the hyphen as U+00AD («ортопеда\xadтравматолога»).
    value = INVISIBLE_RE.sub("", value.replace("\u00ad", "-"))
    value = _sub_with_space_before(SYNEVO_INDICATOR_RE, " ", value)
    value = re.sub(r"-{2,}", "-", collapse_space(value)).strip(" ;,:")
    # «A · B · ...» says more panels follow; stripping its dots left «A · B ·».
    if not value.endswith(" · ..."):
        value = value.strip(" .;,:")
    value = re.sub(r"\(\s+", "(", _sub_with_space_before(CLOSING_BRACKET_RE, ")", value))
    if _mostly_upper(value):
        value = sentence_case(value)
    return value[:240]


def extract_specimen(title: str) -> str | None:
    """The one specimen a page's title names, or None.  A title joining a
    blood count and a urinalysis («Аналіз крові розгорнутий (ЗАК) · Аналіз
    сечі загальний») names two, though only the urine one is spelled the way
    `SPECIMEN_RE` reads: taken as «сеча», it filed 17 blood rows as urine.
    Each row's own section heading decides there (`pipeline.parse_pages`)."""
    if title.endswith(("…", "...")):
        return None  # a truncated panel list may hide a second specimen
    found = {
        "сеча" if match.group(2) else match.group(1).casefold()
        for match in SPECIMEN_RE.finditer(title)
    }
    families = {specimen_family(part) for part in title.split(" · ")} - {None}
    return found.pop() if len(found) == 1 and len(families) <= 1 else None


#: Room a joined title leaves for « · ...» under `clean_title`'s 240.
JOINED_TITLE_LIMIT = 234


def joined_title(names: list[str]) -> str:
    title = ""
    for name in names:
        candidate = f"{title} · {name}" if title else name
        if len(candidate) > JOINED_TITLE_LIMIT:
            return f"{title} · ..." if title else name
        title = candidate
    return title


#: «2. F2005 Пакет №6. Ліпідограма».  Applied to collapsed lines, which never
#: end in a space, so the possessive «\s++» gives back nothing «(.+)» needs.
ESCULAB_HEADING_RE = re.compile(r"^\d+\.\s+[A-Z]\d{4}\s++(.+)$")


def _with_wrapped_tail(heading: str, following_lines: list[str]) -> str:
    # A long name wraps; its tail starts lower case («…чутливості
    # виділених / мікроорганізмів до антибіотиків (…)»).
    for following in following_lines:
        if not re.match(r"^[а-яіїєґ]", following):
            break
        heading = f"{heading} {following}"
    return heading


#: «1. Кальпротектин <24.0 мг/кг», «1. Хелікобактер пілорі, кал не виявлено»:
#: a single test Esculab prints without a panel code.  Its name ends where
#: the result starts.
ESCULAB_TEST_RE = re.compile(r"^\d+\.\s+(?![A-Z]\d{4}\s)(\S.*)$")
ESCULAB_RESULT_START_RE = re.compile(
    r"(?<!\s)\s\s*+(?:(?:[<>≤≥]\s?)?\d|не виявлено|виявлено|від`ємна|негативний|позитивний)", re.I
)
#: The next line may finish the name: «(СА-125)», «(АМГ, AMH Advanced) сироватка
#: крові …», «трансглютамінази (t-TG), ELiA …» -- a bracket, after at most one
#: lower-case word.  «Діти (ж) ≤ 60 д.» and «плазма крові новонароджені (1
#: день)» are the reference and specimen columns, not the name.
ESCULAB_NAME_TAIL_RE = re.compile(r"^(?:[а-яіїєґa-z][\w-]*\s+)?\([^)]*\)")
#: The rest of a bracket the name left open: «(реакція» / «мікропреципітації)».
ESCULAB_BRACKET_CLOSE_RE = re.compile(r"^[^\d()]*\)")
#: A packet whose result the report does not carry («Даний результат можна
#: отримати лише на пункті забору»): the order names it, the paper does not hold it.
ESCULAB_RESULT_ELSEWHERE_RE = re.compile(r"результат можна отримати лише", re.I)
#: Esculab's older form, attached to an order as an image: «30511 Копрограма»
#: under its table header.
ESCULAB_FORM_HEADER = "Показники Результат Од. виміру"
ESCULAB_FORM_HEADING_RE = re.compile(r"^\d{4,6}\s+([^\d\s].*)$")


def _esculab_test_name(line: str, following: str) -> str | None:
    match = ESCULAB_TEST_RE.match(line)
    result = ESCULAB_RESULT_START_RE.search(match.group(1)) if match else None
    if not result:
        return None
    name = match.group(1)[:result.start()].strip()
    if name.count("(") > name.count(")"):
        closed = ESCULAB_BRACKET_CLOSE_RE.match(following)
        name = f"{name} {closed.group(0)}" if closed else name[:name.rindex("(")].strip()
    else:
        tail = ESCULAB_NAME_TAIL_RE.match(following)
        if tail:
            name = f"{name} {tail.group(0)}"
    return name or None


def _esculab_heading_match(lines: list[str], index: int) -> re.Match[str] | None:
    match = ESCULAB_HEADING_RE.match(lines[index])
    if not match and index and lines[index - 1].startswith(ESCULAB_FORM_HEADER):
        match = ESCULAB_FORM_HEADING_RE.match(lines[index])
    return match


def _esculab_bare_test(line: str, following: list[str], numbered_tests: bool) -> str | None:
    if not numbered_tests:
        return None
    return _esculab_test_name(line, following[0] if following else "")


def _esculab_result_elsewhere(lines: list[str], index: int) -> bool:
    return any(ESCULAB_RESULT_ELSEWHERE_RE.search(item) for item in lines[index + 1:index + 4])


def _esculab_names(headings: list[str], tests: list[str]) -> list[str]:
    names: list[str] = []
    for heading in headings:
        name = re.sub(r"^Пакет\s*№\s*[\d.]+\.?\s*", "", heading).strip(" .")
        if name and name not in names:
            names.append(name)
    return names + [test for test in tests if test not in names]


def _esculab_title(lines: list[str]) -> str | None:
    # An Esculab order prints one coded heading per panel («2. F2005 Пакет №6.
    # Ліпідограма», «1. F5000 Коагулограма»).  The first "Пакет" line named a
    # seven-page order of lipids, liver tests, coagulation and a blood count
    # after its lipid panel alone, and that is the label every list shows.
    # A test ordered on its own prints no code («1. Феритин 26.4 нг/мл»);
    # an order of only such tests was titled by its file name.  Panels come
    # first: each is many results, so a title cut for length keeps them.
    headings: list[str] = []
    tests: list[str] = []
    numbered_tests = any(line.startswith("Результати дослідження №") for line in lines)
    for index, line in enumerate(lines):
        match = _esculab_heading_match(lines, index)
        following = lines[index + 1:index + 3]
        if not match:
            name = _esculab_bare_test(line, following, numbered_tests)
            if name and name not in tests:
                tests.append(name)
            continue
        if _esculab_result_elsewhere(lines, index):
            continue
        heading = _with_wrapped_tail(match.group(1), following)
        if heading not in headings:
            headings.append(heading)
    if len(headings) + len(tests) <= 1:
        return (headings or tests or [None])[0]
    return joined_title(_esculab_names(headings, tests))


def _heading_block_title(lines: list[str]) -> str | None:
    """The heading printed between the letterhead and «Пацієнт:».

    Expert Hospital prints «"ЗАЛІЗО (СИРОВАТКА КРОВІ)"» under its licence
    line and wraps a long one over two lines; the Ministry forms (225/о,
    228/о) print «Загальний аналіз крові» under the form's approval line.
    """
    for index, line in enumerate(lines):
        if not HEADING_ANCHOR_RE.match(line):
            continue
        start = index + 1
        if start < len(lines) and lines[start].startswith("№"):
            start += 1
        block: list[str] = []
        for following in lines[start:start + 4]:
            if PATIENT_LINE_RE.match(following):
                return normalise_heading(" ".join(block)) if block else None
            block.append(following)
    return None


#: Synevo departments whose name says nothing about the test: the test's own
#: heading is the line below («Загальна клініка» / «Копрограма», «ПЛР» / «ПЛР.
#: ВПЛ ВКР (...)»), or the results are printed straight under it («Імунохімія»
#: / «β-ХГЛ загальний ... < 0.1 мМО/мл»), and then the tests are their names.
SYNEVO_DEPARTMENTS = frozenset({
    "Загальна клініка", "Біохімія", "Імунохімія", "Імунологія", "Гематологія", "Серологія", "ПЛР",
    "Мікробіологія", "Алергодіагностика",
})
#: Text a heading never carries: a result's digits, the footer's «Примітка:».
SYNEVO_NOT_HEADING_RE = re.compile(r"\d|^Примітка")
#: How many lines a test heading's bracket may wrap over («ПЛР. ВПЛ ВКР
#: (генотипування 16, 18, 31,» / «33, 35, ...» / «зішкріб, кількісне визначення)»).
SYNEVO_HEADING_LINES = 3


def _synevo_heading(lines: list[str], index: int) -> str:
    """The heading on line `index`, with the lines that close its bracket."""
    heading = _sub_with_space_before(SYNEVO_INDICATOR_RE, " ", lines[index]).strip()
    if heading.count("(") <= heading.count(")"):
        return heading
    tail = lines[index + 1 : index + 1 + SYNEVO_HEADING_LINES]
    for count, following in enumerate(tail, start=1):
        if "(" in following:
            break
        if following.endswith(")"):
            return " ".join([heading, *tail[:count]])
    return heading


def _synevo_test_heading(lines: list[str], index: int) -> str | None:
    """The test heading on line `index`, or None for a result row.

    No digits, or a bracket that closes on a later line: a result row prints
    its value, so its first line never closes on «)» further down.
    """
    heading = _synevo_heading(lines, index)
    if not SYNEVO_NOT_HEADING_RE.search(heading):
        return heading
    first = _sub_with_space_before(SYNEVO_INDICATOR_RE, " ", lines[index]).strip()
    return heading if heading != first and not lines[index].startswith("Примітка") else None


def _synevo_row_names(lines: list[str]) -> list[str]:
    """The names of the results printed with a unit, in order."""
    from .parsers import parse_unit_rows

    return list(dict.fromkeys(row.raw_name for row in parse_unit_rows("\n".join(lines), 1)))


def _synevo_header_section(lines: list[str], index: int) -> tuple[str, list[str] | None, bool]:
    """The section named under the table header on line `index`.

    A department gives the test heading under it instead, and the third item
    says so.  Results printed straight under a department come back as the
    second item, as the names of those results.
    """
    section = _strip_synevo_city(_synevo_heading(lines, index + 1))
    if section in SYNEVO_DEPARTMENTS and index + 2 < len(lines):
        test = _synevo_test_heading(lines, index + 2)
        if test is None:
            # Results straight under the department: the paper holds those
            # tests, and «Імунохімія» named none of them.
            return section, _synevo_row_names(lines[index + 2 :]) or [section], False
        return test, None, True
    return section, None, False


def _synevo_add_section(sections: list[str], section: str) -> None:
    if section and section not in sections:
        sections.append(section)


def _synevo_sections(lines: list[str]) -> list[str]:
    """The section under the first table header, or the tests under a department.

    The section is the line under the table header.  On a continuation page
    that line may be a result row («Глікований гемоглобін (HbA1c) 5.24 % 4.8
    - 5.9») or the footer's «Примітка:», neither of which names anything.
    Under a department, each page's first heading is a test of its own.
    """
    sections: list[str] = []
    department = False
    for index, line in enumerate(lines[:-1]):
        if line != SYNEVO_TABLE_HEADER:
            continue
        first = lines[index + 1]
        if not SYNEVO_INDICATOR_RE.search(first) and SYNEVO_NOT_HEADING_RE.search(first):
            if department:
                continue
            break
        section, rows, under_department = _synevo_header_section(lines, index)
        if rows is not None:
            return rows
        department = department or under_department
        _synevo_add_section(sections, section)
        if not department:
            break
    return sections


def _synevo_title(lines: list[str]) -> str | None:
    if SYNEVO_TABLE_HEADER not in lines:
        return None
    panels: list[tuple[str, str]] = []
    for index, line in enumerate(lines):
        line = _synevo_heading(lines, index)
        match = re.match(r"^Пакет\s*№\s*[\d.]+\s*\((.+)\)$", line)
        if match and line not in [panel for panel, _ in panels]:
            panels.append((line, match.group(1)))
    if len(panels) == 1:
        return panels[0][0]
    if panels:
        return joined_title([name for _, name in panels])
    # The section («Біохімія», «Аналіз крові розгорнутий (ЗАК)») is the line
    # under the table header; a department is replaced by the test under it.
    sections = _synevo_sections(lines)
    return joined_title(sections + [test for test in _synevo_later_tests(lines) if test not in sections]) or None


#: «Аналіз сечі загальний (ЗАС + ручна мікроскопія осаду)»: a test name and
#: its description in brackets, on one line.
SYNEVO_DESCRIBED_TEST_RE = re.compile(r"^(?P<name>[^\d()]+?)\s*\([^()\d]+\)$")


def _synevo_later_tests(lines: list[str]) -> list[str]:
    """Tests that start further down the order, not under a table header.

    Synevo opens each ordered test with its full name and then repeats the
    bare name as the first section heading: «Аналіз сечі загальний (ЗАС +
    ручна мікроскопія осаду)» / «Аналіз сечі загальний».  Only the first
    test sits under the header, so an order of a blood count and a
    urinalysis was titled as the blood count alone.
    """
    return [
        line for line, following in zip(lines, lines[1:])
        if (found := SYNEVO_DESCRIBED_TEST_RE.match(line)) and following == found.group("name")
    ]


#: The footer of Synevo's illustrated companion report: «<patient> / Пакет № 183
#: (Все під контролем для жінок) / 13.05.2023 / стор. 2».  Its cover prints the
#: packet name over three lines, and the first alone («Пакет № 183») was the title.
SYNEVO_COMPANION_FOOTER_RE = re.compile(r"/ (Пакет\s*№\s*[\d.]+\s*\([^)]+\)) / \d{2}\.\d{2}\.\d{4}")


def _synevo_companion_title(text: str) -> str | None:
    match = SYNEVO_COMPANION_FOOTER_RE.search(text)
    return match.group(1) if match else None


#: A POLYCHECK chip prints its panel beside the patient's surname: «<surname>
#: Харчова 20-I».  The labels are images; the panel name is the last two words.
POLYCHECK_PANEL_RE = re.compile(r"(?<!\S)(\S\S*+\s++\d++-[IVX]++)$")
#: Latin letters POLYCHECK's software writes inside Cyrillic words («Харчовa»).
LATIN_HOMOGLYPHS = str.maketrans("aceiopxyABCEHIKMOPTX", "асеіорхуАВСЕНІКМОРТХ")


def _polycheck_title(text: str, lines: list[str]) -> str | None:
    if "polycheck" not in text.casefold() or not lines:
        return None
    panel = POLYCHECK_PANEL_RE.search(lines[0])
    if not panel:
        return "POLYCHECK"
    name, code = panel.group(1).split(maxsplit=1)
    if re.search(r"[а-яіїєґ]", name, re.I):
        name = name.translate(LATIN_HOMOGLYPHS)
    return f"POLYCHECK - {name} {code}"


def _consultation_title(text: str, lines: list[str]) -> str | None:
    heading = consultation_heading(text)
    if heading:
        return heading
    for line in lines[:15]:
        # A service the note orders or recommends («Повторна консультація
        # після дообстеження») is not its heading.
        if re.search(r"рекоменд|послуг", line, re.I):
            continue
        match = re.search(r"(консультативний висновок.*|консультація\s+[^\W\d_].*)$", line, re.I)
        if match:
            # OCR may run the letterhead's phone and name into the heading
            # («КОНСУЛЬТАЦІЯ з 73 22 33 911 Медікал»): it ends at a digit,
            # and the one-letter word left before the digit goes with it.
            words = re.split(r"\d", match.group(1))[0].split()
            while len(words) > 1 and len(words[-1]) <= 2:
                words.pop()
            return _strip_truncated_tail(" ".join(words))
    return None


def _blood_pressure_title(text: str) -> str | None:
    match = re.search(
        r"(Звіт про кров.яний тиск протягом)[ \t]*\n(?:[^\n]*\n){0,3}?[ \t]*(\d+[ \t]+[^\W\d_]+)[ \t]*(?:\n|$)",
        text,
    )
    return f"{match.group(1)} {match.group(2)}" if match else None


def _allergy_title(text: str) -> str | None:
    if "ALEX" not in text:
        return None
    count = re.search(r"Протестовані алергени:[ \t]*(?:\n[ \t]*\d{6,}[ \t]+)?(\d{2,4})\b", text)
    return f"ALEX² - протестовані алергени: {count.group(1)}" if count else "ALEX²"


#: «Локалізація патологічного процесу - м'які тканини».  Applied to collapsed
#: lines, which never end in a space (see ESCULAB_HEADING_RE).
ULTRASOUND_SITE_RE = re.compile(r"^Локалізація патологічного процесу\s*[–-]\s*+(.+)$")
STUDY_AREA_RE = re.compile(r"^(?:Область|Ділянка) дослідження:")
MRI_STUDY_RE = re.compile(r"^(?:Ділянка обстеження:\s*)?(МРТ\s.+)$")
XRAY_HEADING_RE = re.compile(r"^(?:рентгенологічне дослідження|комп.ютерна рентгенографія)$", re.I)
#: «Ділянка тіла: ОГК».  Collapsed lines again, as above.  Expert's X-ray
#: prints «Область Рентгенографія ОГК (одна проекція)», its label's second
#: word «дослідження» wrapped to the next line.
BODY_REGION_RE = re.compile(r"^(?:Ділянка (?:обстеження|тіла):|Область(?= Рентген))\s*+(.+)$")
#: The same line from a phone photo, the label behind debris and its first
#: word garbled («сен Область Pentre: нографія ОГК (дві проекції)»).
XRAY_AREA_RE = re.compile(r"\bОбласть\s++\S{0,8}?:?\s*+нографія\s++(.+)$")


def _without_ocr_echo(value: str) -> str:
    """Drop the words a photo's OCR read twice: «Рентгенографія граф ОГК (дві
    (дві проекції)» is «Рентгенографія ОГК (дві проекції)» -- a word that is
    a piece of the one before it, or a bracket opened twice on one word."""
    kept: list[str] = []
    for word in value.split():
        previous = kept[-1].casefold() if kept else ""
        if len(word) >= 3 and word.casefold() in previous:
            continue
        kept.append(word)
    return " ".join(kept)


#: The clinic's addresses and phone, which Expert's vessel protocol prints in
#: a column beside its heading: «Ультразвукове обстеження вул. Кульпарківська,
#: 64 А» / «гілок дуги аорти Тел: 097 …».
_LETTERHEAD_STREET = r"вул\.\s*+[^,\n]+,\s*\d+(?:\s*[А-ЯA-Z](?![^\W\d_]))?"
_LETTERHEAD_PHONE = r"\bТел\s*:.*$"
LETTERHEAD_COLUMN_RE = re.compile(rf"(?:{_LETTERHEAD_STREET})|(?:{_LETTERHEAD_PHONE})")


def _ultrasound_subject(match: re.Match[str], tail: list[str]) -> str:
    parts = [match.group(2)]
    # An Expert heading wraps, and usually ends at «(дослідження проводилось
    # на …)»; St Paraskeva's is followed by «Протокол 40551».
    for offset, following in enumerate(tail):
        if following.startswith("(дослідження"):
            parts.extend(tail[:offset])
            break
    else:
        # The vessel protocol's heading wraps among the address lines; its
        # tail is the next lower-case remainder («аорти», «гілок дуги аорти»).
        parts = [LETTERHEAD_COLUMN_RE.sub("", parts[0]).strip()]
        for line in tail:
            rest = LETTERHEAD_COLUMN_RE.sub("", line).strip()
            if rest:
                if re.match(r"[а-яіїєґ][^:\d]*$", rest) and len(rest.split()) <= 4:
                    parts.append(rest)
                break
    subject = sentence_case(" ".join(parts).strip()).strip()
    return subject[:1].lower() + subject[1:]


def _ultrasound_area(lines: list[str]) -> str | None:
    return next(
        (re.sub(r"^(?:Область|Ділянка) дослідження:\s*", "", item) for item in lines[:20]
         if STUDY_AREA_RE.match(item)),
        None,
    )


def _ultrasound_site(lines: list[str]) -> str | None:
    for position, item in enumerate(lines[:40]):
        located = ULTRASOUND_SITE_RE.match(item)
        if located:
            site = located.group(1)
            following = lines[position + 1] if position + 1 < len(lines) else ""
            if len(following) <= 25 and not re.search(r"[–:]", following):
                site = f"{site} {following}"
            return site
    return None


def _ultrasound_heading_title(lines: list[str], index: int, match: re.Match[str]) -> str | None:
    subject = _ultrasound_subject(match, lines[index + 1:index + 4])
    prefix = "Дуплексне УЗД" if match.group(1) else "УЗД"
    title = f"{prefix} {subject}".strip()
    detail = _ultrasound_site(lines) or _ultrasound_area(lines)
    if detail:
        return f"{title} - {detail}"
    return title if subject else None


#: InMed's protocol heading, the organ it examined (see ULTRASOUND_PROTOCOL_RE);
#: OCR may add marks after it («Огляд грудних залоз чо Gere -»).
INMED_HEADING_RE = re.compile(
    r"^[^\w]{0,3}((?:обстеження|огляд)\s+(?:органів\s+малого\s+тазу|щитоподібної\s+залози|грудних\s+залоз"
    r"|молочних\s+залоз))(?![^\W\d_])",
    re.I,
)
#: Ultramed's subject line under «Протокол ультразвукового обстеження»:
#: «Обстеження шлунково кишкового тракту (ШКТ)», «Ультрасонографічне
#: обстеження скронево-нижньощелепних суглобів» / «та жувальних м'язів».
#: The subject is the shortest run of at least six letters, spaces and hyphens
#: that leaves only spaces and an optional bracket after it, so a five-letter
#: word keeps the space after it («серця (ЕхоКГ)»).  The text is one heading line.
_STUDY_SUBJECT = r"([а-яіїєґ'’ -]{6,}?)"
STUDY_SUBJECT_RE = re.compile(rf"^(?:ультрасонографічне\s+)?обстеження\s+{_STUDY_SUBJECT}\s*+(?:\(.*)?$", re.I)


def _study_subject_title(lines: list[str]) -> str | None:
    for index, line in enumerate(lines[:30]):
        match = STUDY_SUBJECT_RE.match(line)
        if match and match.group(1)[:1].islower():
            subject = match.group(1)
            if "(" not in line:
                subject = _with_wrapped_tail(subject, lines[index + 1 : index + 2])
            words = subject.split()
            while len(words) > 1 and len(words[-1]) == 1:
                words.pop()  # «та жувальних м'язів i»: a mark read as a letter
            subject = re.sub(r"шлунково\s*(?:-\s*)?кишков", "шлунково-кишков", " ".join(words))
            return f"УЗД {subject}"
    return None


def _ultrasound_title(lines: list[str]) -> str | None:
    for line in lines[:40]:
        heading = INMED_HEADING_RE.match(line)
        if heading:
            return heading.group(1)
    for line in lines[:40]:
        # «УЗД від 19.03.2025р.: …», «УЗД за 06.10.2025» quote an earlier
        # study; a heading names one and carries no date or finding.
        if re.match(r"^УЗД\s+\S", line) and not re.search(r"\b(?:від|за)\s+\d|\d{2}\.\d{2}\.\d{2}|:", line):
            return line
    for index, line in enumerate(lines[:40]):
        match = ULTRASOUND_HEADING_RE.match(line)
        if match and match.group(2):
            return _ultrasound_heading_title(lines, index, match)
        if match:
            # «Протокол ультразвукового обстеження» names no organ; the line
            # that does follows it.
            return _study_subject_title(lines[index + 1 :]) or _ultrasound_heading_title(lines, index, match)
    return _study_subject_title(lines)


def _before_stop(lines: list[str]) -> list[str]:
    """The lines above the first recommendation, conclusion or plan."""
    for index, line in enumerate(lines):
        if TITLE_STOP_RE.search(line):
            return lines[:index]
    return lines


def _mri_title(lines: list[str]) -> str | None:
    for line in lines:
        match = MRI_STUDY_RE.match(line)
        if match:
            return _sub_with_space_before(MRI_STUDY_NUMBER_RE, "", match.group(1))
    return None


def _xray_line_region(line: str) -> str | None:
    match = BODY_REGION_RE.match(line)
    garbled = None if match else XRAY_AREA_RE.search(line)
    if match or garbled:
        return _without_ocr_echo(
            _strip_truncated_tail(match.group(1) if match else f"Рентгенографія {garbled.group(1)}")
        )
    return None


def _xray_title(lines: list[str]) -> str | None:
    heading = None
    for line in lines:
        if XRAY_HEADING_RE.match(line):
            heading = heading or line
        region = _xray_line_region(line)
        if region is not None:
            if "рентген" in region.casefold() or not heading:
                return region
            return f"{heading} - {region}"
    return None


def _labelled_study_title(lines: list[str], clinical_type: str) -> str | None:
    """MRI and X-ray: the study as printed, without its label or study number."""
    lines = _before_stop(lines[:40])
    if clinical_type == "radiology_mri":
        return _mri_title(lines)
    return _xray_title(lines)


#: The tests a SILAB print («Мати та дитина», Synevo's copy of it) heads its
#: sections with, as (what OCR still reads of the heading, the heading as
#: printed).  Scanned, the heading arrives as «Аналіз yir мазка» or broken over
#: two lines, so the printed form is taken from here once its words are seen.
SILAB_HEADINGS = (
    # Synevo's copy names the order «… + ручна мікроскопія …» above the
    # section it prints as «… + мікроскопія …»: one test, one title.
    (re.compile(r"^Аналіз сечі загальний \(ЗАС \+ ручна"), "Аналіз сечі загальний (ЗАС + ручна мікроскопія осаду)"),
    (re.compile(r"^Аналіз сечі загальний \(ЗАС \+ мікроскопія"), "Аналіз сечі загальний (ЗАС + мікроскопія осаду)"),
    (re.compile(r"^Аналіз \S{1,4} мазка на мікрофлору"), "Аналіз у/г мазка на мікрофлору (на склі)"),
    (re.compile(r"^Цитологія на атипові клітини"), "Цитологія на атипові клітини (зішкріб, мазок на склі)"),
    (re.compile(r"^\d+\. Панель цитологічних досліджень$"), None),
    (re.compile(r"^ПЛР\. ВПЛ \S{3} \(генотипування, якісне"), "ПЛР. ВПЛ ВКР (генотипування, якісне визначення)"),
    (
        re.compile(r"^ПЛР\. ВПЛ \S{3} \(генотипування 16, 18"),
        "ПЛР. ВПЛ ВКР (генотипування 16, 18, 31, 33, 35, 39, 45, 51, 52, 56, 58, 59, 66, 68, у/г зішкріб, "
        "кількісне визначення)",
    ),
    (re.compile(r"^ПАП\S{0,2}тест методом рідинної цитології"), "ПАП-тест методом рідинної цитології"),
    (
        re.compile(r"^Бакпосів на мікрофлору \(урогенітальний\) \+ антибіотикограма"),
        "Бакпосів на мікрофлору (урогенітальний) + антибіотикограма (у разі виявлення умовно-патогенної та "
        "патогенної мікрофлори)",
    ),
)
SILAB_PRINT_RE = re.compile(r"silab|mdclinics|неомед|neomed", re.I)


def _silab_title(text: str, lines: list[str]) -> str | None:
    if not SILAB_PRINT_RE.search(text):
        return None
    found: list[str] = []
    for line in lines:
        for pattern, heading in SILAB_HEADINGS:
            name = (heading or line) if pattern.search(line) else None
            if name and name not in found and not (name.startswith("Аналіз сечі") and any(
                item.startswith("Аналіз сечі") for item in found
            )):
                found.append(name)
    return joined_title(found) or None


def _keyword_title(lines: list[str]) -> str | None:
    for line in lines:
        if TITLE_STOP_RE.search(line):
            return None
        if len(line) <= 240 and any(token in line.upper() for token in KEYWORD_TITLE_TOKENS):
            return normalise_heading(re.sub(r"^Ділянка обстеження:\s*", "", line))
    return None


#: A clinic document fetched by lab sync is saved as «<clinic>-<document id>
#: <YYYY-MM-DD> <the clinic's own name for it>.pdf» (labsync.doctoreleks).
#: Expert Hospital's visit documents carry a letter before the id
#: («expert-c812 …» a conclusion, «expert-r77 …» an examination).
#: «Висновок ЕЕГ»: a study's conclusion as a heading, named by its abbreviation.
STUDY_CONCLUSION_RE = re.compile(r"^Висновок\s+[А-ЯІЇЄҐA-Z][А-ЯІЇЄҐA-Zа-яіїєґa-z]*[А-ЯІЇЄҐA-Z]$")
CLINIC_FILENAME_RE = re.compile(
    r"^(?P<clinic>[a-z]+)-[a-z]?\d+(?:-\d+)?\s+(?P<day>\d{4}-\d{2}-\d{2})\s+(?P<title>\S.*)$")


#: The lab-sync key of a clinic → the vendor its own documents are filed under.
CLINIC_VENDORS = {
    "veselka": ("Veselka", "https://veselka.clinic"),
    "paraskeva": ("St. Paraskeva Medical Center", None),
    "expert": ("Expert Hospital", "https://experthospital.com.ua"),
}


#: Form 045/о's name, which a photo's OCR keeps only in pieces.
RABIES_CARD_TITLE = "Карта звернення за антирабічною допомогою"
CONSENT_TITLE_RE = re.compile(
    r"інформована\s+добровільна\s+згода(?:\s+пацієнта)?|згода\s+на\s+обробку\s+персональних\s+даних", re.I
)
#: GastroLife's breath tests.  The H. pylori report heads itself over two
#: lines («Консультативний висновок за результатами дихального тесту на» /
#: «визначення бактерії Helicobacter pylori»); the SIBO sheet prints its name
#: in a column OCR interleaves with the logo («Синдром надмірного» / «Gastr
#: бактерійного росту в» / «тонкому кишківнику»), often cut at the margin.
BREATH_REPORT_HEADING_RE = re.compile(r"^Консультативний висновок за результатами дихального тесту\b.*$", re.I)
SIBO_RE = re.compile(r"надмірного\s+(?:\S{1,6}\s+){0,2}бактерійного\s+росту", re.I)
SIBO_TITLE = "Дихальний тест на визначення надмірного бактерійного росту у кишківнику"
#: An eHealth diagnostic report: «ДІАГНОСТИЧНИЙ ЗВІТ за послугою» over the service.
SERVICE_REPORT_RE = re.compile(r"^діагностичний звіт за послугою:?\s*+(.*)$", re.I)


def _breath_test_title(text: str, lines: list[str]) -> str | None:
    for index, line in enumerate(lines[:20]):
        if BREATH_REPORT_HEADING_RE.match(line):
            heading = _with_wrapped_tail(line, lines[index + 1 : index + 2])
            # «тесту Ha» is «на» read in Latin letters.
            return re.sub(r"(?<!\s)\s\s*+Ha(?=\s)", " на", heading).rstrip(" .")
    return SIBO_TITLE if SIBO_RE.search(text) else None


def _service_report_title(lines: list[str]) -> str | None:
    for index, line in enumerate(lines[:20]):
        match = SERVICE_REPORT_RE.match(line)
        if match:
            service = match.group(1) or (lines[index + 1] if index + 1 < len(lines) else "")
            return f"Діагностичний звіт: {service}" if service else "Діагностичний звіт"
    return None


def _questionnaire_title(text: str, lines: list[str]) -> str | None:
    """The scale by its own name: OCR reads the quoted «NICHQ» as «ХІСНО»."""
    folded = text.casefold()
    if "vanderbilt" in folded:
        form = re.search(r"vanderbilt\W{0,4}\s*(?:-\s*)?форма\s+([AАBВ])\b", text, re.I)
        return "Опитувальник NICHQ Vanderbilt" + (f" (форма {form.group(1)})" if form else "")
    if re.search(r"\basrs\b", folded):
        return "Опитувальник ASRS"
    return next((line for line in lines[:10] if re.match(r"опитувальник\b", line, re.I)), None)


def _immunization_title(text: str) -> str | None:
    if re.search(r"карта профілактичних щеплень", text, re.I):
        return "Карта профілактичних щеплень"
    return RABIES_CARD_TITLE if _is_rabies_card(text.casefold()) else None


def _report_title(text: str, lines: list[str]) -> str | None:
    if DISCHARGE_027_RE.search(text.casefold()):
        return DISCHARGE_027_TITLE
    return _breath_test_title(text, lines) or _service_report_title(lines)


def _typed_title(text: str, lines: list[str], clinical_type: str) -> str | None:
    """The heading only one kind of document prints."""
    if clinical_type == "consultation":
        return _consultation_title(text, lines)
    if clinical_type == "blood_pressure":
        return _blood_pressure_title(text)
    if clinical_type == "allergy":
        return _allergy_title(text)
    if clinical_type == "immunization_record":
        return _immunization_title(text)
    if clinical_type == "questionnaire":
        return _questionnaire_title(text, lines)
    if clinical_type == "administrative":
        consent = CONSENT_TITLE_RE.search(text)
        return consent.group(0) if consent else None
    if clinical_type == "clinical_report":
        return _report_title(text, lines)
    if clinical_type == "ultrasound":
        return _ultrasound_title(lines)
    if clinical_type in {"radiology_mri", "radiology_xray"}:
        return _labelled_study_title(lines, clinical_type)
    return None


def _clinic_title(text: str, clinic: re.Match[str]) -> str:
    # The clinic's own name for the document outranks a heading guessed
    # from its text («Консультація лікаря-кардіолога», not the first
    # finding line of the ultrasound it quotes) -- except a study the
    # report prints at its head: the clinic filed an EEG as «Огляд лікаря».
    study = next((line for line in text.splitlines()[:5] if STUDY_CONCLUSION_RE.match(line.strip())), None)
    return clean_title(study) if study else clinic["title"][:240]


def _named_title(text: str, filename: str, clinical_type: str) -> str | None:
    """The title that the file name or the kind of document settles before any heading is read."""
    clinic = CLINIC_FILENAME_RE.match(Path(filename).stem)
    if clinic:
        return _clinic_title(text, clinic)
    if clinical_type == "diagnostic_image":
        # A photo of a results print the reader leaves as an image still
        # names its tests («ПАП-тест методом рідинної цитології»).
        named = _silab_title(text, [line for line in (collapse_space(raw) for raw in text.splitlines()) if line])
        return clean_title(named) if named else "Diagnostic image"
    if clinical_type == "electrocardiogram":
        return "Kardia 6-lead ECG recording" if "6l recording" in text.casefold() else "Kardia ECG recording"
    if clinical_type == "pathology" and CYTOLOGY_PASSPORT_RE.search(text):
        return "Цитологічний паспорт"
    return None


def extract_title(text: str, filename: str, clinical_type: str) -> str:
    named = _named_title(text, filename, clinical_type)
    if named is not None:
        return named
    lines = [line for line in (collapse_space(raw) for raw in text.splitlines()) if line]
    candidates = (
        lambda: _esculab_title(lines),
        lambda: _heading_block_title(lines),
        # Before Synevo's own reader: a scan whose table header OCR read clean
        # would otherwise be titled by the heading under it as OCR spelt it.
        lambda: _silab_title(text, lines),
        lambda: _synevo_title(lines),
        lambda: _synevo_companion_title(text),
        # A consultation names the panel it recommends; only a chip is one.
        lambda: _polycheck_title(text, lines) if clinical_type == "allergy" else None,
        lambda: _typed_title(text, lines, clinical_type),
        lambda: _keyword_title(lines),
    )
    for candidate in candidates:
        found = candidate()
        title = clean_title(found) if found else ""
        if title:
            return title
    # Nothing printed is usable; the app recognises a filename-shaped title.
    return _without_patient_name(Path(filename).stem, text)[:240]


def _without_patient_name(stem: str, text: str) -> str:
    """The file name without the person's name the page prints on its patient line.

    A clinic names its downloads «<surname>_<name>_<patronymic>_<test>»; a
    title is shown in every list and must not carry who the record is about.
    """
    # A file name saved on a Mac spells «ї» as «і» plus a combining diaeresis.
    text = unicodedata.normalize("NFC", text)
    names = {
        word.casefold()
        for match in PATIENT_LABEL_RE.finditer(text)
        for word in re.findall(r"[^\W\d_]{3,}", text[match.end():].split("\n", 1)[0])[:3]
    }
    words = re.split(r"[_\s]+", unicodedata.normalize("NFC", stem))
    kept = [word for word in words if word.casefold() not in names]
    return " ".join(kept) if kept and len(kept) < len(words) else stem


UNKNOWN_VENDOR = "Unknown vendor"
_SILAB_SYSTEM = "інформаційної системи silab"

#: (text tokens, filename tokens, PDF producer tokens, vendor, website), in
#: order: the first rule any token of which is present names the vendor.
_VENDOR_RULES: tuple[tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...], str, str | None], ...] = (
    (("kardia", "alivecor"), (), (), "Kardia", "https://www.alivecor.com/"),
    (("garmin connect",), (), (), "Garmin Connect", "https://connect.garmin.com"),
    # «synevo-<order>.pdf» is how lab sync names a Synevo download; the
    # illustrated companion report it fetches prints no lab name at all.
    # A Synevo report printed for a partner clinic («Мати та дитина») drops
    # the «Сінево (Synevo)» line and carries the clinic's logo; what stays is
    # the laboratory's own system: the flag column «Індикатор зони підвищеної
    # уваги» of its result table, and the footer naming its information
    # system, SILAB, on the printouts that print one.
    (
        ("сінево", "synevo", "індикатор зони підвищеної уваги", _SILAB_SYSTEM),
        ("__synevo__", "synevo-"), (), "Synevo", "https://www.synevo.ua",
    ),
    (("esculab.com", "елаб"), ("__eskulab__", "esculab-", "eskulab-"), ("Apache FOP",), "Esculab", "https://esculab.com"),
    # Medical centre «Veselka», operated by ТзОВ «Повноділ»; its
    # vaccination card prints only the operator's name.
    (("повноділ", "veselka.clinic"), (), (), "Veselka", "https://veselka.clinic"),
    (("3d діагностики",), (), (), "Center of Medical 3D Diagnostics", None),
    (("оксфорд медікал", "oxford.lviv"), (), (), "Oxford Medical Lviv", "https://lviv.oxford-med.com.ua"),
    # Medical centre «Мати та дитина», trade mark of ТОВ «НЕОМЕД 2007».  Before
    # Expert: its cytology reports name «лабораторного експерта».
    (("mdclinics", "неомед 2007", "мати та дитина"), (), (), "MD Clinics", "https://mdclinics.com.ua"),
    # «22 33 911» is Expert's phone block, all of its letterhead a photo's OCR
    # may keep («КОНСУЛЬТАЦІЯ з 73 22 33 911 Медікал»).
    (
        ("експерт", "experthospital", "expert hospital", "22 33 911", "2233911"), (), (),
        "Expert Hospital", "https://experthospital.com.ua",
    ),
    # Clinics read from their printed headers (photo triage 2026-11-07).
    # Addresses where OCR of a phone photo keeps the address and loses the
    # logo; never a bare street name another clinic shares («Хімічна»).
    # InMed's logo reads «їн Мед» or «пн Мед»; its three phones stay legible.
    (
        ("інмед", "inmed", "мазепи, 25", "лемківська, 28", "їн мед", "пн мед", "068 688 06 69", "068 207 47 87",
         "096 48 49 909"), (), (), "InMed", None,
    ),
    (("ultramed", "ультрамед"), (), (), "Ultramed", None),
    (("клініка лоно", "lono.clinic"), (), (), "LONO Clinic", None),
    (("medicover", "медікавер"), (), (), "Medicover", None),
    (("parens", "паренс"), (), (), "Parens", None),
    # Its e-mail domain as OCR reads it («ivivmedicaicenter.com»), and the
    # company's registry code (ЄДРПОУ), printed on every form.
    (
        ("львів медікал центр", "lviv medical center", "ivmedicalcenter", "ivmedicaicenter", "44237940"), (), (),
        "Lviv Medical Center", None,
    ),
    (("обласний клінічний перинатальний центр",), (), (), "Lviv Regional Clinical Perinatal Center", None),
    # Its logo, read «Gastray», and «КЛІНІКА ГАСТРОЕНТЕРОЛОГІЇ» under it.
    (
        ("gastrolife", "скнилівський провулок", "gastray", "клініка гастроентероло"), (), (),
        "GastroLife", "https://gastrolife.ua",
    ),
    # Lviv's municipal territorial medical associations, by name or registry
    # code (ЄДРПОУ): «Друге клінічне ТМО», the «Львівське ТМО» and «1 ТМО»
    # with its St. Luke's hospital («КНП ІТМО ВП лікарня святого …»).
    (("друге клінічне", "44625774"), (), (), "Second Clinical Territorial Medical Association of Lviv", None),
    (
        ("святого луки", "кнп ітмо", "кнп 1тмо", "кнп 1 тмо", "44496574"), (), (),
        "First Clinical Territorial Medical Association of Lviv, St. Luke's Hospital", None,
    ),
    (("львівське територіальне медичне",), (), (), "Lviv Territorial Medical Association", None),
    (("медцентр св. параскеви", "святої параскеви"), ("st-paraskeva",), (), "St. Paraskeva Medical Center", None),
)
#: «Антибіотики/Антимікотики <organism>» heads an antibiogram, and is all an
#: Esculab culture's second page prints of it: typed as a laboratory page, that
#: page was read as a report of its own and its rows lost the specimen the
#: first page names.
MICROBIOLOGY_TOKENS = ("антибіотикограм", "бакпосів", "мікробіологічне", "мікроорганізм", "антибіотики/антимікотики")
LABORATORY_TOKENS = (
    "показник результат",
    "результат норма",
    "результати дослідження",
    "електроліти крові",
    "носійства гену hla",
    "аутоімунна стандартна",
    # The partner clinic «Мати та дитина» prints its results out of SILAB, its
    # laboratory information system, which every page's footer names; read
    # from a scan, the heading and the table header are often lost to OCR.
    _SILAB_SYSTEM,
    "видача результатів аналізів",
    "референтний інтервал",
)
#: Text that only a report carrying result values prints.
RESULT_PRESENT_TOKENS = (
    "показник результат", "результат норма", "назва дослідження результат",
    "результат дослідження", "мікроорганізм", "kual/l", "kua/l",
    "загальний ige:", "ige <", "росту аеробної", "антигени діапазон",
    "ro/ss-a 52", "показники одиниці результати", "форма № 225/о", "форма № 228/о",
    # POLYCHECK's class legend, printed under the allergen rows.
    "антитіла відсутні",
    # A SILAB print's table header, a smear's closing grade, and the footer
    # of a print that is the results themselves.
    "референтний інтервал", "ступінь чистоти", _SILAB_SYSTEM,
)
RESULT_TYPES = frozenset({"laboratory", "microbiology", "allergy"})


def _any_in(text: str, tokens: tuple[str, ...]) -> bool:
    return any(token in text for token in tokens)


#: A private practice that names itself on its form: «ФОП Коваленко Петро
#: Іванович» is «ФОП Коваленко П. І.» (OCR garbles the given names more
#: often than their first letters).
SOLE_PROPRIETOR_RE = re.compile(r"\bФОП\s+([А-ЯІЇЄҐ][а-яіїєґ'’]+)\s+([А-ЯІЇЄҐ])[а-яіїєґ'’]+(?:\s+([А-ЯІЇЄҐ])[а-яіїєґ'’]+)?")


def _vendor(filename: str, text: str, producer: str) -> tuple[str, str | None]:
    clinic = CLINIC_FILENAME_RE.match(Path(filename).stem)
    if clinic and clinic["clinic"] in CLINIC_VENDORS:
        # The clinic itself sent this file (lab sync): its text may name
        # another lab whose results it quotes («аналізи Synevo від …»).
        return CLINIC_VENDORS[clinic["clinic"]]
    name = filename.casefold()
    folded = text.casefold()
    # Rule order, not position on the page: a photo that catches the edge of
    # another clinic's sheet above its own letterhead (Lviv Medical Center's
    # header over an MD Clinics consultation) would be filed under the edge.
    for text_tokens, name_tokens, producer_tokens, vendor, website in _VENDOR_RULES:
        if _any_in(folded, text_tokens) or _any_in(name, name_tokens) or _any_in(producer, producer_tokens):
            return vendor, website
    practice = SOLE_PROPRIETOR_RE.search(text)
    if practice:
        initials = " ".join(f"{letter}." for letter in practice.groups()[1:] if letter)
        return f"ФОП {practice.group(1)} {initials}", None
    return UNKNOWN_VENDOR, None


def _is_consultation(filename: str, folded: str) -> bool:
    # A screenshot headed «Консультація сімейного лікаря» was filed as a
    # diagnostic image: a picture of nothing, with a doctor's note in it.
    # Generalising the specialty is safe only where the phrase is the
    # document's *title*, and the corpus says why — in every other report
    # here it is a recommendation in the conclusion («рекомендовано:
    # консультація гастроентеролога», «повторна консультація невролога»),
    # sitting 582 to 2916 characters in.  Searching the whole text refiled
    # five imaging reports as consultations; the genitive «консультації»,
    # which is the footer of every Expert Hospital laboratory report
    # («потребують консультації лікаря»), refiled fifty-five more.  The two
    # literals stay because those documents are named by their conclusion,
    # not their heading, and the window would drop them.
    return bool(
        CONSULTATION_HEADING_RE.search(folded[:CONSULTATION_HEADING_WINDOW])
        or consultation_heading(folded)
        or "консультація невролога" in folded
        or "консультація ортопеда" in folded
        or "orthopedic-traumatology-consultation" in filename.casefold()
        # A clinic's own name for the document (lab sync), e.g. «Консультація
        # лікаря-кардіолога», «Огляд лікаря первинка».
        or re.search(r"\s(?:консультаці|огляд лікаря)", Path(filename).stem.casefold())
        and CLINIC_FILENAME_RE.match(Path(filename).stem)
    )


def _is_ultrasound(filename: str, folded: str) -> bool:
    name = filename.casefold()
    return bool(
        # A report headed «УЗД органів черевної порожнини» (Veselka) is an
        # ultrasound whatever the file is called.
        re.search(r"^\s*узд\s", folded[:1500], re.MULTILINE)
        or "ультразвуков" in folded
        or "узд" in name
        or "ultrasound" in name
        or "echocardiogram" in name
        or ULTRASOUND_PROTOCOL_RE.search(folded)
        or len(ORGAN_SECTION_RE.findall(folded)) >= 2
    )


#: A protocol that never says «ультразвукове»: InMed heads its sheets with the
#: organ («Обстеження органів малого тазу», «Огляд щитоподібної залози»,
#: «Огляд грудних залоз»), and a photo's OCR may keep only the description
#: under it («Матка розташована в anteflexio …»).  A doctor's note that says
#: the same is a consultation, decided before this.
ULTRASOUND_PROTOCOL_RE = re.compile(
    r"^[^\w\n]{0,3}(?:(?:обстеження|огляд)[ \t]+(?:органів[ \t]+малого[ \t]+тазу|щитоподібної[ \t]+залози"
    r"|грудних[ \t]+залоз|молочних[ \t]+залоз)"
    r"|(?:матка|щитоподібна[ \t]+залоза)[ \t]+розташован|грудні[ \t]+залози[ \t]+симетричн)",
    re.M,
)
#: Ultramed's protocols: one organ heading per section, each on a line of its
#: own («ПЕЧІНКА.», «НИРКИ.»; «Стравохід», «Тонкий кишечник»).  A laboratory
#: groups its biochemistry under «Печінка» / «Нирки» too, never with the stop.
ORGAN_SECTION_RE = re.compile(
    r"^[ \t]*(?:(?:печінка|жовчний[ \t]+міхур|підшлункова[ \t]+залоза|селезінка|нирки)\."
    r"|стравохід|шлунок\.?|тонкий[ \t]+кишечник|товстий[ \t]+кишечник)[ \t]*$",
    re.M,
)
#: A questionnaire someone filled in: the screening scale's own heading or name.
QUESTIONNAIRE_RE = re.compile(r"vanderbilt|^[^\w\n]{0,3}опитувальник\b|\basrs\b", re.M)
#: Consent forms («Згода на обробку персональних даних», form 003-6/о
#: «Інформована добровільна згода пацієнта»): paperwork, not a finding.
CONSENT_RE = re.compile(
    r"інформована[ \t]+добровільна[ \t]+згода|згода[ \t]+на[ \t]+обробку[ \t]+персональних[ \t]+даних"
)
#: Vaccination records besides form 063/о: a clinic's vaccination booklet
#: («Тип щеплення | Препарат | Дата | Серія», «Проти поліомієліту»), and form
#: 045/о, the rabies card «Карта звернення за антирабічною допомогою».
#: Form 063/о's later sheet (its dose table alone) is left an image: the card
#: reader takes that table's OCR for doses it does not hold.
VACCINATION_BOOKLET_RE = re.compile(r"(?:препарат|mpenapar)[ \t|]+дата\b")
RABIES_FORM_RE = re.compile(r"\b045/[оo0]\b")


def _is_rabies_card(folded: str) -> bool:
    return "рабічн" in folded and bool(RABIES_FORM_RE.search(folded))


def _is_other_vaccination_record(folded: str) -> bool:
    booklet = VACCINATION_BOOKLET_RE.search(folded) and re.search(r"щепл|поліомієліт", folded)
    return bool((booklet and "серія" in folded) or _is_rabies_card(folded))


#: Units of length (and the volume an echo report prints beside its
#: dimensions): a table mostly of these is a measurement table, not results.
MEASUREMENT_UNITS = frozenset({"мм", "см", "мл", "см3", "см.куб", "mm", "cm", "ml"})
#: Result rows a page needs before its results header outweighs a mention of
#: another kind of document.
RESULT_TABLE_MIN_ROWS = 4


def _is_results_table(text: str) -> bool:
    """A laboratory results table that also mentions a consultation or a scan.

    The rows are counted by the parser that will read them, so the rule
    cannot drift from what gets extracted.  The header check is what protects
    an ultrasound without one: a «УЗД ... рекомендовано» note is a laboratory
    report only when the table is there too.
    """
    # Imported here, as `_synevo_row_names` does, so classifier never depends
    # on parsers at import time.
    from .parsers import has_result_header, parse_unit_rows

    if not has_result_header(text):
        return False
    rows = parse_unit_rows(text, 1)
    if len(rows) < RESULT_TABLE_MIN_ROWS:
        return False
    measured = sum(1 for row in rows if (row.unit_raw or "").casefold() in MEASUREMENT_UNITS)
    return measured * 2 <= len(rows)


def _clinical_type(filename: str, mime_type: str, text: str, folded: str) -> str:
    if "kardia advanced determination" in folded:
        clinical_type = "electrocardiogram"
    elif "alex2-order-cover" in filename.casefold():
        clinical_type = "administrative"
    elif DISCHARGE_027_RE.search(folded):
        # Form 027/о, the discharge summary a hospital stay ends with: a
        # report, however the clinic named the Word file it came in
        # («Консультація 1748171.docx»).
        clinical_type = "clinical_report"
    elif _is_results_table(text):
        # A results table that names a consultation, a biopsy or an MRI in its
        # note is a laboratory report.  Those kinds are never parsed for values,
        # so the whole page used to vanish.
        clinical_type = "laboratory"
    elif _is_consultation(filename, folded):
        clinical_type = "consultation"
    elif "звіт про кров’яний тиск" in folded and "garmin connect" in folded:
        clinical_type = "blood_pressure"
    elif is_vaccination_card(text) or _is_other_vaccination_record(folded):
        # Form 063/о, «Карта профілактичних щеплень».
        clinical_type = "immunization_record"
    elif visit_note_structure(folded):
        clinical_type = "consultation"
    elif CYTOLOGY_PASSPORT_RE.search(folded):
        clinical_type = "pathology"
    # «… не замінить ендоскопію з біопсією» is an ultrasound's disclaimer.
    elif re.search(r"(?<!з )біопсі|гістолог", folded):
        clinical_type = "pathology"
    elif "магнітно-резонанс" in folded or re.search(r"\bмрт\b", folded):
        clinical_type = "radiology_mri"
    else:
        clinical_type = _content_type(filename, mime_type, folded)
    return clinical_type


_BREATH_TEST = r"дихальн\w*\s+(?:\w{1,3}\s+)?(?:уреазн\w*\s+)?тест"
_TEST_DATE = r"дата\s+проведення\s+тесту"
_BREATH_TEST_RE = re.compile(rf"{_BREATH_TEST}|{_TEST_DATE}")


def _content_type(filename: str, mime_type: str, folded: str) -> str:
    if QUESTIONNAIRE_RE.search(folded):
        clinical_type = "questionnaire"
    elif _any_in(folded, ("рентгенологічне дослідження", "рентгенограф")):
        clinical_type = "radiology_xray"
    elif _is_ultrasound(filename, folded):
        clinical_type = "ultrasound"
    # POLYCHECK (Biocheck) specific-IgE chips, as Esculab issues them, are an
    # allergy panel like ALEX²: the same reader and the same review.
    elif _any_in(folded, ("alex2", "алергодіагност", "алерген", "polycheck")):
        clinical_type = "allergy"
    elif re.search(r"форма\s*№\s*(?:210|225|228)/о", folded):
        clinical_type = "laboratory"
    elif _any_in(folded, MICROBIOLOGY_TOKENS):
        clinical_type = "microbiology"
    elif re.search(r"гастродуоденоскоп|панендоскоп|колоноскоп|кольпоскоп", folded):
        # An endoscopy protocol prints «Результати дослідження:» over its
        # description; it carries no laboratory values.
        clinical_type = "clinical_report"
    elif _any_in(folded, LABORATORY_TOKENS):
        clinical_type = "laboratory"
    elif _BREATH_TEST_RE.search(folded):
        # A breath test's written result, photographed or not (a visit note
        # quoting one was taken as a consultation above).
        clinical_type = "clinical_report"
    elif CONSENT_RE.search(folded):
        clinical_type = "administrative"
    elif mime_type.startswith("image/"):
        # Last, not first.  «This is a picture» is a fact about the container,
        # and it used to outrank every fact about the contents: a photograph of
        # a family doctor's note, a scan of an X-ray *report*, a screenshot of a
        # discharge summary all became `diagnostic_image` — a kind that means
        # "images with no written interpretation", and that therefore promised
        # a radiology reading nobody would ever find in them.  Now that a scan
        # is genuinely read (extract.ocr_pdf_page), the text is there to decide
        # on, and only an image whose text says nothing recognisable falls
        # through to here — which is exactly what the kind is supposed to mean.
        clinical_type = "diagnostic_image"
    else:
        clinical_type = "clinical_report"
    return clinical_type


def _extraction_strategy(
    mime_type: str, scanned: bool, has_embedded_ocr: bool, meaningful_chars: int, image_pages: int
) -> str:
    if mime_type.startswith("image/"):
        return "ocr_image_metadata"
    if scanned:
        # A whole page read as one image, because there was nothing else on it.
        # Distinct from `embedded_image_ocr`, which is a table lifted out of a
        # page whose text layer carried the rest: on a scan there is no text
        # layer, so nothing here has a second source to be checked against.
        return "scanned_page_ocr"
    if has_embedded_ocr:
        return "native_text_plus_embedded_image_ocr" if meaningful_chars else "embedded_image_ocr"
    if meaningful_chars < 80:
        return "ocr_required" if image_pages else "visual_or_vector_review"
    return "native_text_plus_visual_attachments" if image_pages else "native_text"


def _status(clinical_type: str, folded: str, filename: str = "") -> tuple[str, str | None]:
    if clinical_type == "administrative" and "alex2-order-cover" not in filename.casefold():
        return "supporting_record", None  # a consent form, not an order cover
    if clinical_type == "administrative":
        return (
            "supporting_record",
            "Order cover retained for provenance; the result values are stored in the linked attachment export.",
        )
    if "ваш результат готовий і знаходиться в додатковому pdf файлі" in folded:
        return "result_not_present", "This cover export points to a separate PDF attachment that contains the result values."
    if clinical_type in RESULT_TYPES and not _any_in(folded, RESULT_PRESENT_TOKENS):
        return "result_not_present", "The export identifies the ordered test but contains no result value."
    return "final", None


def classify_document(
    filename: str,
    mime_type: str,
    pages: list[dict[str, object]],
    metadata: dict[str, str] | None = None,
) -> Classification:
    metadata = metadata or {}
    # Only OCR can have read a screenshot's interface; a native text layer
    # is the document's own.
    text = "\n".join(
        combined_page_text({**page, "ocr_text": strip_screen_chrome(str(page.get("ocr_text") or ""))})
        for page in pages
    )
    folded = text.casefold()
    vendor, website = _vendor(filename, text, metadata.get("Producer", ""))
    clinical_type = _clinical_type(filename, mime_type, text, folded)

    meaningful_chars = sum(int(page.get("native_char_count") or 0) for page in pages)
    image_pages = sum(1 for page in pages if int(page.get("image_count") or 0) > 0)
    has_embedded_ocr = any(str(page.get("ocr_text") or "").strip() for page in pages)
    scanned = any("page_image_ocr" in str(page.get("extraction_method") or "") for page in pages)
    strategy = _extraction_strategy(mime_type, scanned, has_embedded_ocr, meaningful_chars, image_pages)

    status, notes = _status(clinical_type, folded, filename)
    if meaningful_chars < 80 and not has_embedded_ocr and mime_type == "application/pdf":
        status = "attachment_only"

    order_identifier = extract_order_identifier(text, filename)
    title = extract_title(text, filename, clinical_type)
    confidence = 0.98 if vendor != UNKNOWN_VENDOR and clinical_type != "clinical_report" else 0.75
    if status in {"attachment_only", "result_not_present"}:
        confidence = min(confidence, 0.9)
    result = Classification(
        vendor=vendor,
        website=website,
        clinical_type=clinical_type,
        title=title,
        report_date=extract_date(text, filename),
        order_identifier=order_identifier,
        status=status,
        extraction_strategy=strategy,
        confidence=confidence,
        notes=notes,
        collected_at=extract_collected_at(text),
        issued_at=extract_issued_at(text),
        specimen=extract_specimen(title) if clinical_type in RESULT_TYPES else None,
        report_number=extract_report_number(text),
    )
    # Per-file corrections reviewed by a person (an image-only scan's vendor and
    # date, a printed discrepancy worth a note) name one person's documents, so
    # they live in the installation's own data, never here.
    name = filename.casefold()
    for override in local_overrides().get("classifier", ()):
        if any(pattern.casefold() in name for pattern in override["filename_contains"]):
            result = replace(result, **override["set"])
    return result
