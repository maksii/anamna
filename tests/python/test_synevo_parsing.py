"""Synevo layouts the flat-text passes used to cut short or drop.

Synthetic fixtures modelled on the printed layout: the label wraps onto the
line under its own value, and the urinalysis microscopy is a column table
whose values wrap with the reference column in between.  No patient data.
"""

from __future__ import annotations

import pytest

from anamna.ingest.concepts import concept_for_alias
from anamna.ingest.parsers import parse_document, parse_unit_rows

HEADER = "Показник Результат Од. Референтний інтервал\n"


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        # Unclosed bracket: the tail runs to the bracket that closes it.
        (
            "Ліпопротеїди високої щільності (ЛПВЩ, 1.20 ммоль/л Жінки: ≥1.2\nHDL) Чоловіки: ≥1.0\n",
            "Ліпопротеїди високої щільності (ЛПВЩ, HDL)",
        ),
        (
            "Ліпопротеїди низької щільності (ЛПНЩ, 3.10 ммоль/л <3.0 - для груп низького ризику\n"
            "LDL) <2.6 - для груп помірного ризику\n",
            "Ліпопротеїди низької щільності (ЛПНЩ, LDL)",
        ),
        (
            "Незрілі гранулоцити (на 100 0.4 % *Діти: <2 років: ≤0.4\nлейкоцитів) 2-5 років: ≤0.3\n",
            "Незрілі гранулоцити (на 100 лейкоцитів)",
        ),
        (
            "Тестостерон загальний (Т загальний, 15.0 нмоль/л Дорослі:\n"
            "сироватка) Чоловіки (20-49 років): 8.64 - 29.0\n",
            "Тестостерон загальний (Т загальний, сироватка)",
        ),
        # The wrap fell after a hyphen and the tail opens a bracket of its own.
        (
            "Вітамін Д (25-гідроксивітамін D, 25- 31.0 нг/мл Дорослі (від 18 років):\n"
            "(OH)D) Дефіцит: <20.0\n",
            "Вітамін Д (25-гідроксивітамін D, 25-(OH)D)",
        ),
        # Trailing comma: a run of lowercase words, stopping at the reference.
        (
            "Вірус гепатиту B (HBV), HBcorAg, 0.10 Індекс >1.0 - негативний результат\n"
            "антитіла сумарні ≤1.0 - позитивний результат\n",
            "Вірус гепатиту B (HBV), HBcorAg, антитіла сумарні",
        ),
        # Trailing full stop: capitals only, across lines while they end on a comma.
        (
            "Тиреотропний гормон. 2.00 мкМО/мл Діти:\n"
            "ВИСОКОЧУТЛИВИЙ, 0-12 міс.: 1.36 - 8.8\n"
            "БІОТИН-НЕЗАЛЕЖНИЙ 1-6 років: 0.85 - 6.5\n"
            "7-12 років: 0.28 - 4.3\n",
            "Тиреотропний гормон. ВИСОКОЧУТЛИВИЙ, БІОТИН-НЕЗАЛЕЖНИЙ",
        ),
        (
            "Паратгормон (ПТГ 1-84). 40.0 пг/мл 14.9 - 56.9\n"
            "ВИСОКОСПЕЦИФІЧНИЙ. БІОІНТАКТНИЙ Метод: Електрохемілюмінесцентний аналіз\n",
            "Паратгормон (ПТГ 1-84). ВИСОКОСПЕЦИФІЧНИЙ. БІОІНТАКТНИЙ",
        ),
    ],
)
def test_wrapped_synevo_label_takes_its_tail(text: str, expected: str) -> None:
    rows = parse_unit_rows(HEADER + text, 1)
    assert [row.raw_name for row in rows] == [expected]


@pytest.mark.parametrize(
    ("old", "new"),
    [
        ("Ліпопротеїди високої щільності (ЛПВЩ", "Ліпопротеїди високої щільності (ЛПВЩ, HDL)"),
        ("Ліпопротеїди низької щільності (ЛПНЩ", "Ліпопротеїди низької щільності (ЛПНЩ, LDL)"),
        ("Незрілі гранулоцити (на 100", "Незрілі гранулоцити (на 100 лейкоцитів)"),
        ("Тестостерон загальний (Т загальний", "Тестостерон загальний (Т загальний, сироватка)"),
        ("Вітамін Д (25-гідроксивітамін D, 25", "Вітамін Д (25-гідроксивітамін D, 25-(OH)D)"),
        ("Вірус гепатиту B (HBV), HBcorAg", "Вірус гепатиту B (HBV), HBcorAg, антитіла сумарні"),
        ("Тиреотропний гормон", "Тиреотропний гормон. ВИСОКОЧУТЛИВИЙ, БІОТИН-НЕЗАЛЕЖНИЙ"),
        ("Паратгормон (ПТГ 1-84)", "Паратгормон (ПТГ 1-84). ВИСОКОСПЕЦИФІЧНИЙ. БІОІНТАКТНИЙ"),
    ],
)
def test_completed_label_keeps_its_concept(old: str, new: str) -> None:
    """A longer printed name must not split the trend into a second concept."""
    before, after = concept_for_alias(old, "numeric"), concept_for_alias(new, "numeric")
    assert before is not None and after is not None
    assert before["name"] == after["name"]


def test_unclosed_bracket_without_a_closing_line_is_left_alone() -> None:
    rows = parse_unit_rows(HEADER + "Ліпопротеїди високої щільності (ЛПВЩ, 1.20 ммоль/л Жінки: ≥1.2\nЧоловіки: ≥1.0\n", 1)
    assert [row.raw_name for row in rows] == ["Ліпопротеїди високої щільності (ЛПВЩ"]


def test_rdw_tail_discriminator_still_holds() -> None:
    rows = parse_unit_rows(
        HEADER
        + "Ширина розподілення еритроцитів 36.6 фл 35.0 - 46.0\n(RDW-SD)\n"
        + "Ширина розподілення еритроцитів 12.1 % 12.0 - 15.0\n(RDW-CV)\n",
        1,
    )
    assert {row.unit_raw: row.raw_name for row in rows} == {
        "фл": "Ширина розподілення еритроцитів (RDW-SD)",
        "%": "Ширина розподілення еритроцитів (RDW-CV)",
    }


def _page(rows: list[tuple[float, list[tuple[float, str]]]], page_number: int = 1) -> dict:
    """A page as the extractor hands it over: flat text plus word positions."""
    words = []
    for top, cells in rows:
        for x0, text in cells:
            for offset, word in enumerate(text.split()):
                words.append((x0 + offset * 12.0, x0 + offset * 12.0 + 10.0, top, word))
    lines: dict[float, list[tuple[float, str]]] = {}
    for x0, _x1, top, word in words:
        key = next((seen for seen in lines if abs(seen - top) <= 2.0), top)
        lines.setdefault(key, []).append((x0, word))
    native = "\n".join(" ".join(word for _x, word in sorted(lines[top])) for top in sorted(lines))
    return {"page_number": page_number, "native_text": native, "ocr_text": "", "words": words}


HEADER_ROW = (136.0, [(124.0, "Показник"), (274.6, "Результат"), (357.7, "Од."), (442.2, "Референтний інтервал")])


def test_synevo_microscopy_rows_are_read_by_column() -> None:
    page = _page([
        HEADER_ROW,
        (150.0, [(62.0, "Аналіз сечі загальний")]),
        # The dipstick erythrocytes: same printed name and value as the
        # microscopy row below, told apart only by where they are printed.
        (616.0, [(75.0, "Еритроцити"), (269.8, "не виявлені"), (351.7, "Ery/µL")]),
        (617.0, [(391.6, "не виявлені")]),
        (704.0, [(69.0, "Ручна мікроскопія осаду сечі")]),
        (719.0, [(75.0, "Лейкоцити")]),
        (720.0, [(271.8, "до 5.0 в п/з"), (391.6, "не виявлені, до 5.0 в")]),
        (731.0, [(391.6, "п/зору")]),
        (742.0, [(75.0, "Еритроцити"), (391.6, "не виявлені")]),
        (743.0, [(269.9, "не виявлені")]),
        (760.0, [(75.0, "Еритроцити, стан"), (391.6, "незмінені")]),
        (761.0, [(274.6, "незмінені")]),
        (767.0, [(75.0, "Клітини плоского епітелію"), (391.6, "не виявлені, поодинокі")]),
        (768.0, [(269.8, "поодинокі в")]),
        (780.0, [(274.1, "препараті")]),
        (792.0, [(75.0, "Слиз"), (391.6, "не виявлений")]),
        (793.0, [(269.8, "в невеликій")]),
        (805.0, [(274.1, "кількості")]),
        (817.0, [(75.0, "Бактерії"), (269.9, "не виявлені"), (391.6, "не виявлені")]),
        (830.0, [(75.0, "Примітка:")]),
        (840.0, [(62.0, "Результати лабораторних досліджень не є достатньою підставою")]),
    ])
    rows = parse_document("Synevo", "laboratory", [page])
    found = [(row.raw_name, row.value_text, row.reference_text) for row in rows]
    assert ("Лейкоцити", "до 5.0 в п/з", "не виявлені, до 5.0 в п/зору") in found
    assert ("Еритроцити, стан", "незмінені", "незмінені") in found
    assert ("Клітини плоского епітелію", "поодинокі в препараті", "не виявлені, поодинокі") in found
    assert ("Слиз", "в невеликій кількості", "не виявлений") in found
    assert ("Бактерії", "не виявлені", "не виявлені") in found
    # Two «Еритроцити» rows, both «не виявлені», neither collapsed into the other.
    erythrocytes = [row for row in rows if row.raw_name == "Еритроцити"]
    assert len(erythrocytes) == 2
    assert {row.section for row in erythrocytes} == {None, "sediment"}
    # Each microscopy row once; nothing read from the reference column or the footer.
    names = [row.raw_name for row in rows if row.section == "sediment"]
    assert len(names) == len(set(names)) == 6
    assert not any(row.raw_name.startswith(("Примітка", "Результати")) for row in rows)


def test_page_without_microscopy_heading_is_untouched() -> None:
    page = _page([
        HEADER_ROW,
        (616.0, [(75.0, "Еритроцити"), (269.8, "не виявлені"), (391.6, "не виявлені")]),
    ])
    rows = parse_document("Synevo", "laboratory", [page])
    assert [(row.raw_name, row.section) for row in rows] == [("Еритроцити", None)]


def test_dipstick_unit_is_a_unit_not_part_of_the_reference() -> None:
    """«Ery/µL» is the dipstick's unit column; left unparsed it was glued onto
    the reference text, and it folds to the same cells/µL the other urine
    counts use."""
    from anamna.ingest.parsers import parse_categorical_rows
    from anamna.reference import canonical_unit

    rows = parse_categorical_rows(HEADER + "Еритроцити не виявлені Ery/µL не виявлені\n", 1)
    assert [(row.unit_raw, row.reference_text) for row in rows] == [("Ery/µL", "не виявлені")]
    assert canonical_unit("Ery/µL") == canonical_unit("Leu/µL") == canonical_unit("cells/µL")


def test_bare_urine_erythrocytes_are_the_count_not_the_changed_subset() -> None:
    """A urinalysis «Еритроцити» is the red-cell count, as a bare «Лейкоцити»
    is the leukocyte count -- not the dysmorphic «змінені» cells -- while a
    blood «Еритроцити» stays the RBC count."""
    assert concept_for_alias("Еритроцити", "text", category="urinalysis")["name"] == "Urine erythrocytes"
    assert concept_for_alias("Еритроцити змінені, в п/з", "text", category="urinalysis")["name"] == "Urine changed erythrocytes"
    assert concept_for_alias("Еритроцити", "numeric", category="hematology")["name"] == "Red blood cell count"
    assert concept_for_alias("Еритроцити", "numeric")["name"] == "Red blood cell count"
