"""Diagnoses a person's documents name, read without a model.

A consultation's diagnosis text (``summary_uk``), the lines of the document's
own text that start with a code («I11.9 - Гіпертензивна хвороба») and its
coded lines («Код МКХ Х: K11.2») print codes the document itself wrote.  The
codes are checked against the catalogue; a code followed by a name must also
share a word stem with its catalogue title, so an ICPC-2 reason-for-encounter
code is not taken for a diagnosis.  The conclusion of a consultation or of a
study (MRI, ultrasound, X-ray, ECG, pathology) is read statement by statement,
word for word, into candidates without a code (method 'text'), unless the AI
reader has read the document.  Those statements come only from the parts of
the document's own text under a conclusion or diagnosis heading: the summary
was written for the page, and read word for word it offered study titles,
measurements, prescriptions and its own remarks as diagnoses.  Candidates wait
for the person: accepting one makes a diagnosis, dismissing one hides it.
Nothing here calls an AI.
"""

from __future__ import annotations

import re
import sqlite3
import uuid
from collections.abc import Collection
from datetime import date

from . import diagnoses, icd10
from .db import utc_now

# Raise when the reading rules change: the job's fingerprint holds it, so every record is read again.
READER_VERSION = 3

# A code is a letter, two digits and an optional decimal part.  Cyrillic
# look-alikes are allowed; icd10.normalize folds them to Latin.
_CODE = r"[A-ZАВЕІКМНОРСТХ][0-9]{2}(?:[.,][0-9]{1,2})?"
_CODE_IN_TEXT = re.compile(rf"(?<![^\W_])({_CODE})(?![^\W_])", re.IGNORECASE)
_CODE_START = re.compile(rf"{_CODE}(?![^\W_])", re.IGNORECASE)
_RANGE = re.compile(rf"{_CODE}\s*[-–]\s*{_CODE}", re.IGNORECASE)
_LABEL = r"(?:(?:Основний|Супутній)(?:\s+діагноз)?|(?:Клінічний|Попередній|Заключний)\s+діагноз|Діагноз)\s*:\s*"
_PIECE = re.compile(rf"^(?:{_LABEL})?({_CODE})(?![^\W_])(.*)$", re.IGNORECASE | re.DOTALL)
# A summary that runs two diagnoses into one line («E09.9 … преддіабет? Клінічний діагноз: I11.9 …»)
# is cut before the second label, so the first name does not swallow the second diagnosis.
_INNER_LABEL = re.compile(r"\s+(?=(?:Клінічний|Попередній|Заключний|Основний|Супутній)\s+діагноз\s*:)", re.IGNORECASE)
# The headings a doctor writes the conclusion or the diagnosis under.  The heading ends the line or
# is followed by a colon, so «Висновок не є остаточним діагнозом» is not one.
_HEADING = re.compile(
    r"^(?:(?:клінічний|попередній|основний|супутній|заключний)\s+діагноз|діагноз|гістологічний\s+висновок|"
    r"висновок|заключення|уз[- ]?ознаки|основний|супутній)\s*(?::|$)\s*",
    re.IGNORECASE,
)
# A line that opens another part of the report ends the conclusion: a recommendation, a signature,
# the next numbered part of a form, or any short label with a colon («Клінічні дані:»).
_SECTION_END = re.compile(
    r"^(?:[0-9]{1,2}\.\s*)?(?:рекоменд|призначен|план(?![^\W_])|до\s+відома|до\s+уваги|результат|дата(?![^\W_])|"
    r"лікар|підпис|консультац|повторн|опис(?![^\W_])|короткий\s+анамнез|анамнез|скарги|огляд|обстеження|"
    r"своїм|лабораторн|дані\s+лабораторн|сторінка|пацієнт|рентгенолаборант|медична\s+сестра|зображень)",
    re.IGNORECASE,
)
_FIELD = re.compile(r"^[^\W\d_]+(?:[\s-]+[^\W\d_]+){0,3}\s*:")
_BULLET = re.compile(r"^[-–—•*]+\s*")
# A diagnosis written as its abbreviation alone («СПК», «ГЕРХ») has no long word, yet is one.
_ABBREVIATION = re.compile(r"[А-ЯІЇЄҐ]{2,6}")
# A label in front of a statement is not part of the condition's name («Супутній: Комбінований геморой»).
_LEAD_LABEL = re.compile(
    r"^(?:(?:основний|супутній|клінічний|попередній|заключний)\s+діагноз|діагноз(?:\s+попередній)?|"
    r"висновок(?:\s+спеціаліста)?|заключення(?:\s+лікаря)?|основний|супутній|ds)\s*:\s*",
    re.IGNORECASE,
)
# OCR reads a Cyrillic letter as its Latin twin («BMK» for «ВМК»); both sides are folded before a check.
_LOOKALIKE = str.maketrans("ABCEHIKMOPTXaceiopxy", "АВСЕНІКМОРТХасеіорху")
# A document whose pages carry at least this much native text is read from its own words; below it
# the words are OCR, which garbles a conclusion, and the summary is the cleaner text.  The same
# threshold decides in health._page_text whether OCR is added to a page.
NATIVE_TEXT_CHARS = 400
_CODED_LABEL = re.compile(r"(?:Код\s+)?МКХ(?:-10|\s?10|\s[ХX])?\s*:", re.IGNORECASE)
_ISO_DAY = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")
_WORD = re.compile(r"[^\W\d_]+")
_SENTENCE_END = re.compile(r"(?<=[.?!])\s+(?=[A-ZА-ЯІЇЄҐ0-9])")
_LIST_NUMBER = re.compile(r"^[0-9]{1,2}[.)]?\s+(?=[^\W\d_])")
_ON_EXAM = re.compile(r"^на момент огляду[:,]?\s*", re.IGNORECASE)
# ponytail: word lists, not understanding.  A descriptor counts as "usual" only as a predicate, at the end of a statement or before a comma («Синуси вільні», «чіткі, рівні»); before a noun it is kept («Вільна рідина»).  The AI reader replaces these candidates when it reads the document.
_NOTHING_FOUND = re.compile(
    r"не виявлен|не визнача|не знайден|без патолог|без особливост|без змін|без негативної|"
    r"без вогнищ|вікові особливості|"
    r"меж(?:ах|і) норми|(?<![^\W_])норм[аі](?![^\W_])|варіант норми|не розширен|не потовщен|"
    r"не збільшен|не змінен|(?<![^\W_])немає(?![^\W_])|відсутн|(?<![^\W_])normal(?![^\W_])|"
    r"unremarkable|no evidence|not detected|no signs",
    re.IGNORECASE,
)
_AS_USUAL = re.compile(r"(?:збережен|звичайн|вільн|чітк|типов|прозор|структурн|задовільн)[^\W\d_]*\s*(?:,|$)", re.IGNORECASE)
_NOT_A_CONDITION = (
    "клінічний діагноз", "основний діагноз", "супутній діагноз", "підтримання здоров", "опис:",
    "рекоменд", "необхідн", "доцільн", "показан", "контроль", "повторн", "консультація", "скарги",
    "огляд", "анамнез", "бакпосів", "копрограма", "антимікотикограма", "антибіотикограма",
    "чутливість до", "автоматична ідентифікація", "recommend", "follow-up", "follow up",
    "досліджуваний матеріал", "призначен", "лікування", "щеплення", "патологоанатом", "файл містить",
    "у висновку", "в описі", "додатковий коментар", "аналіз ", "цитологія", "дії:", "хворіє", "на прийомі",
    "планується", "ступень", "квр ",
)
# A statement that carries a date refers to a study («Копрограма від 18.05.2026»), it does not name a condition.
_DATED = re.compile(r"(?<![0-9])[0-9]{1,2}\.[0-9]{2}\.[0-9]{4}(?![0-9])")


def _is_condition(code: str) -> bool:
    return icd10.entry(code) is not None and icd10.is_condition(code)


def _stems(text: str) -> set[str]:
    """The first five letters of each word of five letters or more, casefolded."""
    words = _WORD.findall(text.replace("'", "").replace("’", "").replace("ʼ", ""))
    return {word.casefold()[:5] for word in words if len(word) >= 5}


def _names_catalogue(name: str, code: str) -> bool:
    """Whether the written name shares a stem with the code's title or its category's."""
    entry = icd10.entry(code)
    titles = [entry["uk"]]
    category = icd10.entry(entry["category"])
    if category is not None:
        titles.append(category["uk"])
    return bool(_stems(name) & _stems(" ".join(titles)))


def _clean_name(rest: str) -> str:
    """The name after a code: the separator removed, the trailing question mark too."""
    return re.sub(r"^\s*[-–:,]?\s*", "", rest).strip().rstrip("?").strip()


def codes_in(text: str) -> set[str]:
    """The normalized catalogue-shaped codes that the text prints."""
    return {icd10.normalize(raw) for raw in _CODE_IN_TEXT.findall(text)} - {""}


def parse_summary(text: str) -> list[dict]:
    """Coded diagnoses in a consultation's diagnosis text.  [] when the text starts with «Скарги»
    (no diagnosis was written).  Split at ';' and line ends.  A piece that starts (after an
    optional «Основний:», «Супутній:», «Клінічний діагноз:» label) with an ICD-10 code followed
    by optional ' - ', ':' or a space and a name gives {code, name, certainty, quote}.
    code: icd10.normalize; kept only when icd10.entry(code) exists and icd10.is_condition(code).
    A range such as 'L20-L30' is skipped.
    Guard against ICPC-2 codes (they look the same: 'A44 вакцинація' is not bartonellosis): the
    written name must share a stem with the catalogue's Ukrainian title of the code or of its
    category.  Stem = the first 5 letters (casefold) of any word of 5 letters or more.
    certainty 'provisional' when the piece holds '?', else 'confirmed'.  name is cut to 200.
    quote is the piece as written, cut to 400.  A piece is also cut before a second diagnosis label
    inside it («… преддіабет? Клінічний діагноз: I11.9 …»)."""
    if text.lstrip().startswith("Скарги"):
        return []
    return coded_lines(text)


def coded_lines(text: str) -> list[dict]:
    """``parse_summary`` without the complaints guard: the pieces of any text that start with a
    code and a name, such as the diagnosis lines of a document («I11.9 - Гіпертензивна …»)."""
    items: list[dict] = []
    pieces = (part for raw in re.split(r"[;\r\n]+", text or "") for part in _INNER_LABEL.split(raw))
    for raw_piece in pieces:
        piece = raw_piece.strip()
        match = _PIECE.match(piece)
        if match is None:
            continue
        code = icd10.normalize(match.group(1))
        name = _clean_name(match.group(2))
        if not name or _CODE_START.match(name) or not _is_condition(code):
            continue
        if not _names_catalogue(name, code):
            continue
        items.append({
            "code": code,
            "name": name[:200],
            "certainty": "provisional" if "?" in piece else "confirmed",
            "quote": piece[:400],
        })
    return items


def parse_coded_line(text: str) -> list[dict]:
    """«Код МКХ Х: K11.2», «МКХ-10: E78.2» lines in a document's full text: the same dict, with
    name '' and the line as the quote.  Same catalogue checks."""
    items: list[dict] = []
    for line in text.splitlines():
        if "ICPC" in line.upper():
            continue
        label = _CODED_LABEL.search(line)
        if label is None:
            continue
        rest = line[label.end():]
        # A range (L20-L30) is not one diagnosis: the line gives none.
        if _RANGE.search(rest):
            continue
        certainty = "provisional" if "?" in line else "confirmed"
        quote = line.strip()[:400]
        for raw in _CODE_IN_TEXT.findall(rest):
            code = icd10.normalize(raw)
            if _is_condition(code):
                items.append({"code": code, "name": "", "certainty": certainty, "quote": quote})
    return items


def _cut(name: str) -> str:
    """A name of at most 200 characters: cut at the last space before 200, with an ellipsis."""
    if len(name) <= 200:
        return name
    stop = name.rfind(" ", 0, 200)
    if stop <= 0:
        stop = 199
    return name[:stop].rstrip() + "…"


def conclusion_text(text: str) -> str:
    """The parts of a document's text under a conclusion or diagnosis heading, '' when it has none.

    A part runs from its heading to the next heading, to a line that opens another part of the
    report (``_SECTION_END``) or to a short label with a colon.  A wrapped line that goes on in a
    small letter or a bracket is joined to the line before it, so a statement cut by the page width
    stays one statement; a line that starts with a capital or a bullet starts a new one.
    """
    lines: list[str] = []
    inside = False
    for raw in (text or "").splitlines():
        line = raw.strip()
        heading = _HEADING.match(line)
        if heading:
            inside = True
            line = line[heading.end():].strip()
            if lines and lines[-1]:
                lines.append("")
        elif inside and (_SECTION_END.match(line) or _FIELD.match(line)):
            inside = False
            continue
        if not inside or not line:
            continue
        if lines and lines[-1] and (line[0].islower() or line[0] in "(,;"):
            lines[-1] = f"{lines[-1]} {line}"
        else:
            lines.append(line)
    return "\n".join(line for line in lines if line)


def parse_conclusion(text: str, skip_codes: Collection[str] = ()) -> list[dict]:
    """The statements of a document's conclusion that read as a condition, word for word.

    [] for a text that starts with «Скарги» or names ICPC-2, and for a piece that starts
    with an ICD-10 code (``parse_summary`` and ``parse_coded_line`` own those).  Pieces split
    at ';' and line ends, statements at a sentence end before a capital or a digit.  A
    statement that says nothing was found, that something is usual, that is a label or an
    instruction, or that names a diagnosis the same document already prints with a code in
    ``skip_codes`` is dropped, and so is a statement that carries a date.  A '?' makes it
    provisional and is removed from the name.
    Each item: {code: '', name, certainty, quote}; quote is the statement, cut to 400.
    """
    text = text or ""
    if text.lstrip().startswith("Скарги") or "ICPC" in text.upper():
        return []
    items: list[dict] = []
    seen: set[str] = set()
    for raw_piece in re.split(r"[;\r\n]+", text):
        piece = raw_piece.strip()
        coded = _PIECE.match(piece)
        # The code reader owns a piece whose code the catalogue knows; a code it does not know
        # (an ICD-10-AM or ICD-10-CM extension) is offered here, as written.
        if coded and icd10.entry(icd10.normalize(coded.group(1))) is not None:
            continue
        for statement in _SENTENCE_END.split(piece):
            sentence = _ON_EXAM.sub("", _LEAD_LABEL.sub("", _LIST_NUMBER.sub("", _BULLET.sub("", statement.strip()))))
            provisional = "?" in sentence
            name = sentence.rstrip(" .;,?!").strip()
            if not (_stems(name) or _ABBREVIATION.fullmatch(name)) or _NOTHING_FOUND.search(name):
                continue
            if _AS_USUAL.search(name):
                continue
            if name.casefold().startswith(_NOT_A_CONDITION):
                continue
            if _DATED.search(name):
                continue
            if any(_names_catalogue(name, code) for code in skip_codes if icd10.entry(code) is not None):
                continue
            name = _cut(name)
            if _fold(name) in seen:
                continue
            seen.add(_fold(name))
            items.append({
                "code": "",
                "name": name,
                "certainty": "provisional" if provisional else "confirmed",
                "quote": sentence[:400],
            })
    return items


def _fold(name: str) -> str:
    return " ".join(name.casefold().split())


def _plain(text: str) -> str:
    """Text folded for a containment check: look-alike letters, case, apostrophes and spacing."""
    text = text.translate(_LOOKALIKE).casefold().replace("’", "'").replace("ʼ", "'")
    return " ".join(text.split())


def in_document(name: str, document_text: str) -> bool:
    """Whether the document's own text says ``name``, as ``_plain`` folds both."""
    plain = _plain(name)
    return bool(plain) and plain in document_text


def key_of(code: str, name_key: str) -> str:
    """The group key: the code when there is one, else 'n:' and the name."""
    return code if code else "n:" + name_key


def _day(value: str | None) -> tuple[str | None, int]:
    """The document's date as (ISO day or None, date_exact)."""
    text = (value or "")[:10]
    if not _ISO_DAY.fullmatch(text):
        return None, 0
    try:
        date.fromisoformat(text)
    except ValueError:
        return None, 0
    return text, 1


def dismissed_keys(connection: sqlite3.Connection, owner_id: str) -> set[str]:
    """The keys the owner has dismissed."""
    rows = connection.execute(
        "SELECT DISTINCT code, name_key FROM diagnosis_candidates WHERE owner_user_id = ? AND state = 'dismissed'",
        (owner_id,),
    ).fetchall()
    return {key_of(row[0], row[1]) for row in rows}


def _insert(
    connection: sqlite3.Connection,
    owner_id: str,
    document_id: str,
    method: str,
    item: dict,
    event_date: str | None,
    date_exact: int,
    state: str,
    now: str,
) -> int:
    """One candidate row.  Returns 1 when inserted, 0 when the UNIQUE key already held it."""
    cursor = connection.execute(
        """INSERT OR IGNORE INTO diagnosis_candidates (
               id, owner_user_id, document_id, method, code, code_printed, name, name_key,
               certainty, timing, event_date, date_exact, quote, state, diagnosis_id, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'now', ?, ?, ?, ?, NULL, ?)""",
        (
            str(uuid.uuid4()), owner_id, document_id, method, item["code"], int(method == "code"),
            item["name"], _fold(item["name"]), item["certainty"], event_date, date_exact,
            item["quote"], state, now,
        ),
    )
    return cursor.rowcount


def collect(connection: sqlite3.Connection, owner_id: str) -> int:
    """Read the owner's documents into candidates: the coded diagnoses of every document, and the
    conclusion statements word for word where the AI reader has not read the document.

    Text candidates that are still 'new' are rebuilt on every call; accepted and dismissed ones
    stay.  Duplicate documents are skipped.  Nothing here calls an AI.  Returns the number of
    candidates inserted.  Does not commit.
    """
    dismissed = dismissed_keys(connection, owner_id)
    connection.execute(
        "DELETE FROM diagnosis_candidates WHERE owner_user_id = ? AND method = 'text' AND state = 'new'",
        (owner_id,),
    )
    rows = connection.execute(
        """SELECT f.document_id, f.summary_uk, f.summary_en, f.original_text, d.report_date,
                  EXISTS(SELECT 1 FROM diagnosis_scans s WHERE s.document_id = d.id) AS ai_read,
                  (SELECT COALESCE(SUM(LENGTH(TRIM(p.native_text))), 0) FROM document_pages p
                    WHERE p.document_id = d.id) AS native_chars
             FROM clinical_findings f
             JOIN documents d ON d.id = f.document_id
            WHERE f.owner_user_id = ?
              AND d.duplicate_of_document_id IS NULL
            ORDER BY f.document_id, f.rowid""",
        (owner_id,),
    ).fetchall()
    by_document: dict[str, list] = {}
    for row in rows:
        by_document.setdefault(row["document_id"], []).append(row)
    now = utc_now()
    inserted = 0
    for document_id, findings in by_document.items():
        event_date, date_exact = _day(findings[0]["report_date"])
        summaries = [row["summary_uk"] or row["summary_en"] or "" for row in findings]
        texts = list(dict.fromkeys(row["original_text"] or "" for row in findings))
        coded: list[dict] = []
        for summary in summaries:
            coded.extend(parse_summary(summary))
        for text in texts:
            coded.extend(coded_lines(text) + parse_coded_line(text))
        for item in coded:
            state = "dismissed" if key_of(item["code"], _fold(item["name"])) in dismissed else "new"
            inserted += _insert(connection, owner_id, document_id, "code", item, event_date, date_exact, state, now)
        if findings[0]["ai_read"]:
            continue
        skip_codes = {item["code"] for item in coded}
        statements = [item for summary in summaries for item in parse_conclusion(summary, skip_codes)]
        if findings[0]["native_chars"] >= NATIVE_TEXT_CHARS:
            # The summary was written for the page: a statement of it is offered only when the
            # document's own text says it too.  The document's own conclusion is offered as written.
            document_text = _plain("\n".join(texts))
            statements = [item for item in statements if in_document(item["name"], document_text)]
            for text in texts:
                statements.extend(parse_conclusion(conclusion_text(text), skip_codes))
        for item in statements:
            state = "dismissed" if key_of("", _fold(item["name"])) in dismissed else "new"
            inserted += _insert(connection, owner_id, document_id, "text", item, event_date, date_exact, state, now)
    return inserted


def _diagnosis_index(connection: sqlite3.Connection, owner_id: str) -> list[tuple[str, str, str]]:
    """(id, code, folded name) of the owner's diagnoses, the active ones first."""
    return [
        (row["id"], row["code"], _fold(row["name"]))
        for row in connection.execute(
            "SELECT id, code, name FROM diagnoses WHERE owner_user_id = ? "
            "ORDER BY (status = 'active') DESC, created_at",
            (owner_id,),
        )
    ]


def _existing_id(index: list[tuple[str, str, str]], code: str, name_key: str) -> str | None:
    for diagnosis_id, diagnosis_code, diagnosis_name in index:
        if code and diagnosis_code == code:
            return diagnosis_id
        if not code and diagnosis_name == name_key:
            return diagnosis_id
    return None


def _group(key: str, members: list[dict], index: list[tuple[str, str, str]], locale: str) -> dict:
    """One group from its mentions, latest first."""
    latest = members[0]
    code = next((member["code"] for member in members if member["code"]), "")
    written = next((member["name"] for member in members if member["name"]), "")
    title = icd10.name(code, locale)
    days = [member["event_date"] for member in members if member["event_date"]]
    dated: dict[str, str] = {}
    for member in members:
        day = member["event_date"] or ""
        dated[member["document_id"]] = max(dated.get(member["document_id"], ""), day)
    documents = sorted(dated.items(), key=lambda pair: pair[1], reverse=True)
    return {
        "key": key,
        "code": code,
        "name": written or title,
        "title": title,
        "certainty": latest["certainty"],
        "mentions": len(dated),
        "first_date": min(days) if days else "",
        "last_date": max(days) if days else "",
        "quote": latest["quote"],
        "methods": sorted({member["method"] for member in members}),
        "code_printed": any(bool(member["code_printed"]) for member in members),
        "documents": [{"id": document_id, "date": day} for document_id, day in documents],
        "existing_id": _existing_id(index, code, latest["name_key"]),
    }


def _offered(connection: sqlite3.Connection, owner_id: str, state: str, *, locale: str) -> list[tuple[dict, list[dict]]]:
    """The groups in ``state`` ('new' or 'dismissed') with their mentions, newest group first.

    A key with a new and a dismissed mention is neither offered nor dismissed.
    """
    rows = [
        dict(row) for row in connection.execute(
            "SELECT * FROM diagnosis_candidates WHERE owner_user_id = ? AND state IN ('new', 'dismissed')",
            (owner_id,),
        )
    ]
    by_key: dict[str, list[dict]] = {}
    for row in rows:
        by_key.setdefault(key_of(row["code"], row["name_key"]), []).append(row)
    other = "dismissed" if state == "new" else "new"
    index = _diagnosis_index(connection, owner_id)
    built: list[tuple[dict, list[dict]]] = []
    for key, found in by_key.items():
        states = {row["state"] for row in found}
        if state not in states or other in states:
            continue
        members = [row for row in found if row["state"] == state]
        # Latest first; an undated mention sorts last.
        members.sort(key=lambda row: (row["event_date"] or "", row["created_at"]), reverse=True)
        built.append((_group(key, members, index, locale), members))
    built.sort(key=lambda pair: pair[0]["name"].casefold())
    built.sort(key=lambda pair: pair[0]["last_date"], reverse=True)
    return built


def groups(connection: sqlite3.Connection, owner_id: str, *, locale: str) -> list[dict]:
    """The 'new' candidates, one group per key, newest last_date first."""
    return [group for group, _members in _offered(connection, owner_id, "new", locale=locale)]


def dismissed(connection: sqlite3.Connection, owner_id: str, *, locale: str) -> list[dict]:
    """The dismissed groups, in the same shape as ``groups``."""
    return [group for group, _members in _offered(connection, owner_id, "dismissed", locale=locale)]


def accept(connection: sqlite3.Connection, owner_id: str, patient_id: str, keys: list[str]) -> list[str]:
    """Link each chosen group to its existing diagnosis, or create one from the document.

    Returns the diagnosis ids touched, each once.  Does not commit.
    """
    offered = {group["key"]: (group, members) for group, members in _offered(connection, owner_id, "new", locale="en")}
    touched: list[str] = []
    for key in dict.fromkeys(keys):
        if key not in offered:
            continue
        group, members = offered[key]
        if group["existing_id"]:
            diagnosis_id = group["existing_id"]
        else:
            latest = members[0]
            diagnosis_id = diagnoses.create(
                connection, owner_id, patient_id,
                {
                    "code": group["code"],
                    "name": next((member["name"] for member in members if member["name"]), ""),
                    "status": "active",
                    "certainty": latest["certainty"],
                    "diagnosed_on": group["first_date"] or None,
                    "resolved_on": None,
                    "dates_approximate": 1,
                    "clinician": "",
                    "document_id": latest["document_id"],
                    "notes": "",
                },
                origin="document",
            )
        connection.executemany(
            "UPDATE diagnosis_candidates SET state='accepted', diagnosis_id=? WHERE id=? AND owner_user_id=?",
            [(diagnosis_id, member["id"], owner_id) for member in members],
        )
        if diagnosis_id not in touched:
            touched.append(diagnosis_id)
    return touched


def _key_match(key: str) -> tuple[str, tuple[str, ...]]:
    """The SQL condition that selects the candidates of one group key."""
    if key.startswith("n:"):
        return "code = '' AND name_key = ?", (key[2:],)
    return "code = ?", (key,)


def _set_state(connection: sqlite3.Connection, owner_id: str, keys: list[str], current: str, target: str) -> int:
    changed = 0
    for key in dict.fromkeys(keys):
        condition, params = _key_match(key)
        cursor = connection.execute(
            f"UPDATE diagnosis_candidates SET state = ? WHERE owner_user_id = ? AND state = ? AND {condition}",
            (target, owner_id, current, *params),
        )
        if cursor.rowcount > 0:
            changed += 1
    return changed


def dismiss(connection: sqlite3.Connection, owner_id: str, keys: list[str]) -> int:
    """Mark the offered candidates of the named groups as not wanted.  Does not commit."""
    return _set_state(connection, owner_id, keys, "new", "dismissed")


def restore(connection: sqlite3.Connection, owner_id: str, keys: list[str]) -> int:
    """Offer the dismissed candidates of the named groups again.  Does not commit."""
    return _set_state(connection, owner_id, keys, "dismissed", "new")


def mentions(connection: sqlite3.Connection, owner_id: str, diagnosis_id: str) -> list[dict]:
    """The accepted candidates of one diagnosis, oldest first."""
    rows = connection.execute(
        "SELECT document_id, event_date, quote, name, certainty, method, created_at "
        "FROM diagnosis_candidates WHERE owner_user_id = ? AND diagnosis_id = ? AND state = 'accepted'",
        (owner_id, diagnosis_id),
    ).fetchall()
    rows = sorted(rows, key=lambda row: (row["event_date"] is None, row["event_date"] or "", row["created_at"]))
    return [
        {
            "document_id": row["document_id"],
            "date": row["event_date"] or "",
            "quote": row["quote"],
            "name": row["name"],
            "certainty": row["certainty"],
            "method": row["method"],
        }
        for row in rows
    ]
