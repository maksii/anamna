"""A clinic's own words as a PDF the reader can take in.

Expert Hospital keeps a visit's conclusion as structured text in its app
(complaints, anamnesis, examination, diagnosis, recommendations) and issues no
file for most of them; what it does attach is often a Word document (a breath
test report under a gastroenterology consultation).  The pipeline reads PDFs
and images, so both become a PDF here, and from then on they are documents
like any other: classified, read, and queued for the person's review.

Nothing is added to what the clinic wrote but its labels, the clinic's name and
a closing line saying where the text came from.  The rendering is
deterministic (``invariant``), so the same record gives the same bytes.
"""

from __future__ import annotations

import html
import io
import logging
import re
import zipfile
from xml.etree import ElementTree

from .common import LabSyncError

logger = logging.getLogger("anamna.labsync")

#: Largest uncompressed member of a lab-supplied .docx that is read; a zip
#: bomb or an oversized picture is refused as an unreadable document.
MAX_MEMBER_BYTES = 50 * 1024 * 1024

CLINIC = "Лікарня «Експерт» · Expert Hospital"
#: The record's fields in the order a consultation reads, with the labels the
#: clinic's own forms print.
SECTIONS = {
    "conclusions": (
        ("complaints", "Скарги"), ("anamnesis", "Анамнез"), ("examination", "Огляд"),
        ("performed_manipulations", "Виконані маніпуляції"),
        ("endoscopic_examination_results", "Результати ендоскопічного дослідження"),
        ("diagnosis", "Діагноз"), ("diagnosis_codes", "Код діагнозу"), ("text", "Висновок"),
        ("recommendations", "Рекомендації"), ("medications", "Призначення"),
    ),
    "research": (
        ("body_part", "Ділянка обстеження"), ("description", "Опис"), ("conclusion", "Висновок"),
        ("notes", "Примітки"),
    ),
}
_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
_FALLBACK = "{http://schemas.openxmlformats.org/markup-compatibility/2006}Fallback"


def _number(text: object) -> str:
    """«1.0000 саше» as the clinic means it: «1 саше» (its system pads to four places)."""
    return re.sub(r"(\d+)\.(\d*?)0+(?!\d)", lambda m: m[1] + ("." + m[2] if m[2] else ""), str(text or "").strip())


def _medication(item: dict) -> str:
    """One prescription line: «Дексалгін саше: по 1 саше, 3 раз в 1 День (дні),
    01.01.2024–07.01.2024, на курс 21 саше».  The record's own id is not part
    of it; a field this reader does not know is kept as written."""
    known = ("id", "name", "reception_quantity", "reception_frequency", "take_from", "take_to",
             "quantity_in_recipe", "recommendation")
    dose = _number(item.get("reception_quantity"))
    span = "–".join(filter(None, (str(item.get("take_from") or "").strip(), str(item.get("take_to") or "").strip())))
    parts = [f"по {dose}" if dose else "", str(item.get("reception_frequency") or "").strip(), span,
             f"на курс {_number(item.get('quantity_in_recipe'))}" if item.get("quantity_in_recipe") else "",
             str(item.get("recommendation") or "").strip(),
             *(str(value).strip() for key, value in item.items() if key not in known and value not in (None, "", [], {}))]
    name = str(item.get("name") or "").strip()
    rest = ", ".join(part for part in parts if part)
    return f"{name}: {rest}" if name and rest else name or rest


def field_text(value: object) -> str:
    """A field as lines: a list (diagnosis codes, medications) one item a line.
    The clinic's app stores some text HTML-escaped («30 днів--&gt; далі»):
    it is read as the doctor typed it, so the page says «-->», not «&gt;»."""
    if isinstance(value, list):
        return "\n".join(filter(None, (html.unescape(_medication(item)) if isinstance(item, dict)
                                       else field_text(item) for item in value)))
    return html.unescape(str(value or "")).replace("\r\n", "\n").strip()


def _render(blocks: list[tuple[str, str]], title: str, images: list[bytes] = ()) -> bytes:
    """``blocks``: ``(style, text)``, style ``title``, ``label`` or ``body``."""
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.lib.utils import ImageReader
    from reportlab.platypus import Image, Paragraph, SimpleDocTemplate, Spacer

    from ..web.health_export import _register_export_fonts

    regular, bold = _register_export_fonts()
    styles = {
        "title": ParagraphStyle("t", fontName=bold, fontSize=14, leading=18, spaceAfter=4),
        "label": ParagraphStyle("l", fontName=bold, fontSize=10.5, leading=14, spaceBefore=6),
        "body": ParagraphStyle("b", fontName=regular, fontSize=10.5, leading=14),
        "note": ParagraphStyle("n", fontName=regular, fontSize=8.5, leading=11, spaceBefore=6, spaceAfter=6),
    }
    story = []
    for style, text in blocks:
        for line in text.split("\n") or [""]:
            escaped = line.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            story.append(Paragraph(escaped or "&nbsp;", styles[style]))
    width = A4[0] - 40 * mm
    for data in images:
        try:
            reader = ImageReader(io.BytesIO(data))
            w, h = reader.getSize()
        except Exception:  # noqa: BLE001 -- a picture reportlab cannot draw (EMF) is left out
            continue
        scale = min(1.0, width / w, (A4[1] - 60 * mm) / h)
        story += [Spacer(1, 4 * mm), Image(io.BytesIO(data), w * scale, h * scale)]
    out = io.BytesIO()
    SimpleDocTemplate(out, pagesize=A4, leftMargin=20 * mm, rightMargin=20 * mm, topMargin=18 * mm,
                      bottomMargin=18 * mm, invariant=1, title=title[:120]).build(story)
    return out.getvalue()


def record_pdf(kind: str, record: dict, title: str, day: str, ident: str) -> bytes | None:
    """The clinic's record of a conclusion or an examination as a PDF, or None
    when it holds no text at all."""
    sections = [(label, field_text(record.get(key))) for key, label in SECTIONS[kind]]
    sections = [(label, text) for label, text in sections if text]
    if not sections:
        return None
    doctor = " ".join(field_text(record.get(key)) for key in ("doctor_name", "specialist_who_directed") if
                      field_text(record.get(key))).strip()
    speciality = field_text(record.get("speciality") or record.get("doctor_specialization"))
    head = [("title", title), ("body", CLINIC)]
    if day:
        head.append(("body", f"Дата: {day[8:10]}.{day[5:7]}.{day[:4]}"))
    if doctor:
        head.append(("body", f"Лікар: {doctor}" + (f" ({speciality})" if speciality else "")))
    body = [block for label, text in sections for block in (("label", f"{label}:"), ("body", text))]
    what = "висновку" if kind == "conclusions" else "дослідження"
    note = ("note", f"Складено Anamna із запису {what} {ident} в застосунку Лікарні «Експерт»; файлу клініка не "
                    f"видала. / Composed by Anamna from Expert Hospital's in-app record {ident}; the clinic "
                    f"issued no file.")
    # Under the heading, not at the foot: a reader of the last section
    # (recommendations run to the end of the page) would take it as advice.
    return _render([*head, note, *body], title)


def is_docx(data: bytes) -> bool:
    if not data.startswith(b"PK"):
        return False
    try:
        return "word/document.xml" in zipfile.ZipFile(io.BytesIO(data)).namelist()
    except zipfile.BadZipFile:
        return False


def _paragraphs(element) -> list[str]:
    """Each paragraph's text in reading order.  A text box is stored twice
    (the drawing and its legacy fallback); the fallback is skipped."""
    lines: list[str] = []

    def walk(node, inside: list | None):
        if node.tag == _FALLBACK:
            return
        if node.tag == f"{_W}p":
            parts: list[str] = []
            for child in node:
                walk(child, parts)
            lines.append("".join(parts))
            return
        if inside is not None:
            if node.tag == f"{_W}t":
                inside.append(node.text or "")
            elif node.tag == f"{_W}tab":
                inside.append(" ")
            elif node.tag in (f"{_W}br", f"{_W}cr"):
                inside.append("\n")
        for child in node:
            walk(child, inside)

    walk(element, None)
    return lines


def _member(archive: zipfile.ZipFile, name: str) -> bytes:
    """One member's bytes, refused when it declares or decompresses past the limit."""
    if archive.getinfo(name).file_size > MAX_MEMBER_BYTES:
        raise LabSyncError("labsync.error_pdf")
    with archive.open(name) as member:
        # The declared size is the lab's header; the read itself stays bounded.
        data = member.read(MAX_MEMBER_BYTES + 1)
    if len(data) > MAX_MEMBER_BYTES:
        raise LabSyncError("labsync.error_pdf")
    return data


def docx_pdf(data: bytes, name: str) -> bytes:
    """A Word document's text and pictures as a PDF."""
    archive = zipfile.ZipFile(io.BytesIO(data))
    lines = _paragraphs(ElementTree.fromstring(_member(archive, "word/document.xml")))
    text = re.sub(r"\n{3,}", "\n\n", "\n".join(line.rstrip() for line in lines)).strip()
    images = [_member(archive, item) for item in sorted(archive.namelist())
              if item.startswith("word/media/") and item.lower().endswith((".png", ".jpg", ".jpeg"))]
    label = f"«{name}»" if name else ""
    note = ("note", f"Перетворено Anamna з файлу Word {label}, виданого Лікарнею «Експерт». / Converted by Anamna "
                    f"from the Word file {label} Expert Hospital issued.".replace("  ", " "))
    return _render([note, ("body", text)], next((line for line in lines if line.strip()), name), images)
