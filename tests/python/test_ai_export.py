"""The AI hand-off prompt.

Every assertion here guards a way the export could be confidently wrong rather
than merely ugly: a rounded value that contradicts the interval printed beside
it, a name leaked to a third-party assistant that nobody asked to send, a cap
that trims the record without saying so, and forty thousand wearable rows
arriving whole.
"""

from __future__ import annotations

import re
from pathlib import Path

from anamna.db import connect, utc_now
from anamna.devices.queries import device_history_summary
from anamna.web import ai_export

from test_web_panels import build


def _seed_devices(settings, user_id: str, days: int = 900) -> None:
    """One wearable metric with a long daily history, in the real table."""
    from datetime import date, timedelta

    start = date(2023, 1, 1)
    with connect(settings) as connection:
        vendor_id = connection.execute("SELECT id FROM vendors LIMIT 1").fetchone()["id"]
        connection.execute(
            """INSERT INTO device_imports(
                   id, owner_user_id, patient_id, vendor_id, adapter_key, source_path,
                   source_fingerprint, source_bytes, raw_record_count, status,
                   metadata_json, imported_at)
               VALUES ('imp-1', ?, ?, ?, 'apple_health', 'export.zip', 'sha-d', 10, ?,
                       'complete', '{}', ?)""",
            (user_id, f"patient-{user_id}", vendor_id, days, utc_now()),
        )
        for index in range(days):
            day = start + timedelta(days=index)
            connection.execute(
                """INSERT INTO device_metric_days(
                       id, owner_user_id, patient_id, import_id, source_name, source_vendor,
                       metric_key, metric_name, category, day, aggregation, unit,
                       value, value_min, value_max, sample_count, created_at)
                   VALUES (?, ?, ?, 'imp-1', 'Watch', 'Apple Health', 'steps', 'Daily steps',
                           'device_activity', ?, 'sum', 'steps', ?, 1, 400, 30, ?)""",
                (f"dm-{index}", user_id, f"patient-{user_id}", day.isoformat(),
                 5000 + index, utc_now()),
            )


def _prompt(
    client,
    include: set[str] | None = None,
    locale: str = "en",
    scope: str | None = None,
    path: str | None = None,
) -> str:
    """The prompt as the browser receives it, sections and locale included.

    Driven through the endpoint rather than ``build_prompt`` directly: the
    section parsing, the locale middleware and the catalogue assembly are all
    part of what could go wrong, and none of them are exercised by calling the
    builder with hand-made arguments.
    """
    from anamna.web import app as web

    web.invalidate_catalog()
    client.cookies.set("anamna_lang", locale)
    params: dict[str, str] = {}
    if include is not None:
        params["include"] = ",".join(sorted(include))
    if scope is not None:
        params["scope"] = scope
    if path is not None:
        params["path"] = path
    response = client.get("/api/ai-export", params=params)
    assert response.status_code == 200, response.text[:200]
    return response.text


def test_numbers_keep_the_precision_the_interval_is_written_in():
    """1.035 must not print as "1.03" beside a 1.010-1.030 interval.

    Rounding to a fixed number of decimals put a flagged urine specific
    gravity visibly *inside* the range it had been flagged for, which reads to
    an assistant as a bug in the record rather than a result to explain.
    """
    assert ai_export._num(1.035) == "1.035"
    assert ai_export._num(0.0083333333) == "0.00833333"
    # Never scientific notation: a step count is not 6.93e+03.
    assert ai_export._num(6930.0) == "6930"
    assert ai_export._num(58083) == "58083"
    assert ai_export._num(95.95238095238095, 4) == "95.95"
    assert ai_export._num(None) == "-"
    assert ai_export._num(0) == "0"
    assert ai_export._num(-1.5) == "-1.5"


def test_wearable_history_is_summarised_not_truncated(tmp_path: Path):
    settings, user_id, _ = build(tmp_path)
    _seed_devices(settings, user_id, days=900)
    with connect(settings) as connection:
        summaries = device_history_summary(connection, user_id)
    steps = next(item for item in summaries if item["metric_key"] == "steps")
    # Nine hundred days become twelve months plus a line per earlier year...
    assert steps["day_count"] == 900
    assert len(steps["months"]) == 12
    assert steps["years"], "days older than the monthly window need a yearly line"
    assert len(steps["months"]) + len(steps["years"]) < 20
    # ...and the compression is visible rather than implied.
    assert steps["row_count"] == 900
    assert steps["first_day"] == "2023-01-01"
    # A month's range comes from the daily values, never from value_min/max:
    # on a summed metric those describe one sample, so the month of a walker
    # would report its step range as "1-400".
    assert min(bucket["min"] for bucket in steps["months"]) > 400


def test_the_prompt_leads_with_instructions_a_legend_and_the_flagged_results(tmp_path: Path):
    _settings, _user_id, client = build(tmp_path)
    text = _prompt(client)
    # Order matters: an assistant reads top-down and must know the task and the
    # notation before it reaches a number.
    task = text.index("What I would like from you")
    legend = text.index("How to read this record")
    attention = text.index("Needs attention")
    results = text.index("Current results")
    assert task < legend < attention < results
    assert "- LDL cholesterol: 4.42 mmol/L @2025-02-13 ↑ (" in text
    # The flagged value carries its interval and the body that published it,
    # because "high" without either is not something to act on.  The body is
    # an alias, named once in the legend.
    ldl = next(line for line in text.splitlines() if line.startswith("- LDL cholesterol:"))
    alias = re.search(r"\(<3 (S\d+)", ldl).group(1)
    legend = next(line for line in text.splitlines() if line.startswith("- Sources: "))
    assert f"{alias} " in legend
    assert text.index(legend) < text.index("Needs attention")
    # And the gaps are declared rather than left for the assistant to assume.
    assert "does NOT contain" in text
    assert "is not in the list of my entries above" in text
    assert "Medication I take" not in text


def test_the_name_is_withheld_unless_it_is_asked_for(tmp_path: Path):
    """The whole point of this text is to be pasted somewhere else."""
    _settings, _user_id, client = build(tmp_path)
    default = _prompt(client)
    assert "Test Patient" not in default
    assert "1990-03-14" not in default
    assert "deliberately left out" in default
    # Age and sex stay, because a reference interval depends on them.
    assert "Sex at birth: Male" in default
    assert re.search(r"- Age: \d+", default)

    opted_in = _prompt(client, include={"identity"})
    assert "Test Patient" in opted_in
    assert "1990-03-14" in opted_in


def test_excluded_sections_are_named_rather_than_silently_missing(tmp_path: Path):
    _settings, _user_id, client = build(tmp_path)
    text = _prompt(client, include=set())
    assert "Trends over time - not included" in text
    assert "Watch and device measurements - not included" in text
    # The core is never optional: results and their verdicts always travel.
    assert "LDL cholesterol" in text


def test_a_cap_states_what_it_left_out(tmp_path: Path, monkeypatch):
    _settings, _user_id, client = build(tmp_path)
    monkeypatch.setattr(ai_export, "MAX_ATTENTION", 1)
    text = _prompt(client)
    assert "further flagged results were not listed" in text


def test_the_prompt_is_written_in_the_readers_language(tmp_path: Path):
    _settings, _user_id, client = build(tmp_path)
    text = _prompt(client, locale="uk")
    assert "Про що я прошу" in text
    assert "Відповідайте українською" in text
    assert "What I would like from you" not in text
    # Prose and units follow the locale; the numbers do not, and the legend
    # says so. "4,42" inside a data table is two numbers to a parser.
    assert "ммоль/л" in text
    assert "десятковий роздільник крапка" in text
    ldl = next(line for line in text.splitlines() if line.startswith("- Холестерин ЛПНЩ:"))
    assert "4.42" in ldl and "4,42" not in ldl
    # Critically, the value and the interval printed beside it must use the
    # same convention: one line carrying "4.42" and "≤ 1,4" is how a reader
    # gets told the threshold is fourteen. (The interval is the EAS/EFLM
    # population cut-point: this record holds no risk category, so no
    # risk-stratified goal such as 1.4 may be printed as "the" reference.)
    assert "<3 " in ldl and not re.search(r"\d,\d", ldl)
    assert "1.4" not in ldl


def test_the_endpoint_needs_a_session_and_serves_plain_text(tmp_path: Path):
    _settings, _user_id, client = build(tmp_path)
    response = client.get("/api/ai-export")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")
    assert "What I would like from you" in response.text

    client.cookies.clear()
    assert client.get("/api/ai-export").status_code == 401


def test_the_button_appears_on_result_pages_and_not_on_the_others(tmp_path: Path):
    _settings, _user_id, client = build(tmp_path)
    for path in ("/", "/results", "/documents", "/devices"):
        assert "data-ai-open" in client.get(path).text, path
    for path in ("/upload", "/profile"):
        assert "data-ai-open" not in client.get(path).text, path
    assert client.get("/about").status_code == 404


def test_a_metric_page_scope_is_an_excerpt_about_that_metric(tmp_path: Path):
    """On a metric page the default export is the subject, not the record.

    The whole-record prompt from a metric page is 140k characters of everything,
    which is how the one value being asked about drowns.  The excerpt carries
    the metric in full, its panel as context, and one line per flag elsewhere —
    and every unrelated normal result stays home.
    """
    _settings, _user_id, client = build(tmp_path)
    text = _prompt(client, scope="page", path="/metrics/ldl-cholesterol")
    assert "An excerpt from my personal health record" in text
    assert "LDL cholesterol: my results in full" in text
    # The value still carries its verdict, interval and publisher.
    assert "- LDL cholesterol: 4.42 mmol/L @2025-02-13 ↑ (<3 S1" in text
    # The rest of the lipid panel travels as context...
    assert "HDL cholesterol" in text
    # ...but an unrelated normal analyte does not.
    assert "Creatinine" not in text
    # The excerpt says what it is and how to get the rest.
    assert "This message is an excerpt about LDL cholesterol" in text
    assert "Flagged elsewhere in my record" in text
    # The record-wide sections stay home: no every-analyte dump, no documents.
    assert "Current results" not in text
    assert "Documents these results came from" not in text


def test_page_scope_on_a_list_page_falls_back_to_the_whole_record(tmp_path: Path):
    """A path that names no subject must yield more, never less."""
    _settings, _user_id, client = build(tmp_path)
    text = _prompt(client, scope="page", path="/results")
    assert "My personal health record" in text
    assert "Current results" in text


def test_a_document_page_scope_lists_what_that_document_said(tmp_path: Path):
    _settings, _user_id, client = build(tmp_path)
    text = _prompt(client, scope="page", path="/documents/doc-1")
    assert "An excerpt from my personal health record" in text
    assert "Document:" in text and "Test Lab" in text
    # Every extracted value of the document, judged like the pages judge it.
    for name in ("LDL cholesterol", "HDL cholesterol", "Creatinine", "Hemoglobin"):
        assert name in text, name
    # A document another user owns is not a subject; the record is the fallback.
    other = _prompt(client, scope="page", path="/documents/doc-nobody")
    assert "Current results" in other


def test_a_comparator_result_is_never_exported_as_a_measured_number(tmp_path: Path):
    """"<0.1" is a limit of detection, not a reading of 0.1.

    Dropping the sign hands the assistant a measurement that was never made,
    and an allergen reported below the detection limit reads as a small
    positive instead of an absence.
    """
    settings, _user_id, client = build(tmp_path)
    with connect(settings) as connection:
        connection.execute(
            "UPDATE observations SET comparator='<', value_numeric=0.1 WHERE id='obs-0'"
        )
        name = connection.execute(
            "SELECT raw_name FROM observations WHERE id='obs-0'"
        ).fetchone()["raw_name"]
    text = _prompt(client, scope="page", path="/documents/doc-1")
    line = next(line for line in text.splitlines() if name in line)
    assert "<0.1" in line, line
    assert not re.search(r"(?<![<>≤≥])\b0\.1\b", line), line


def test_a_set_aside_row_stays_out_of_the_documents_excerpt(tmp_path: Path):
    """The page marks a rejected row "Set aside"; the prompt has no such chip,
    so an exported one reads exactly like a genuine result."""
    settings, _user_id, client = build(tmp_path)
    with connect(settings) as connection:
        name = connection.execute(
            "SELECT raw_name FROM observations WHERE id='obs-1'"
        ).fetchone()["raw_name"]
        connection.execute(
            "UPDATE observations SET verification_status='rejected' WHERE id='obs-1'"
        )
    text = _prompt(client, scope="page", path="/documents/doc-1")
    assert name not in text, f"{name} was set aside but still exported"


def test_the_scope_choice_appears_only_on_detail_pages(tmp_path: Path):
    _settings, _user_id, client = build(tmp_path)
    detail = client.get("/metrics/ldl-cholesterol").text
    assert "data-ai-scope" in detail
    assert "LDL cholesterol" in detail
    for path in ("/", "/results", "/documents"):
        assert "data-ai-scope" not in client.get(path).text, path


def test_the_excerpt_is_written_in_the_readers_language(tmp_path: Path):
    _settings, _user_id, client = build(tmp_path)
    text = _prompt(client, locale="uk", scope="page", path="/metrics/ldl-cholesterol")
    assert "Витяг із моєї медичної картки" in text
    assert "усі мої результати" in text
    assert "What I would like from you" not in text
    # Data-table numbers keep the dot convention even in Ukrainian prose.
    ldl = next(line for line in text.splitlines() if line.startswith("- Холестерин ЛПНЩ:"))
    assert "4.42" in ldl and "4,42" not in ldl


# --- sandbox audit 2026-11-06 (CLIN-03, CLIN-15, CLIN-16) ---------------------


def _card(name, value, interpretation, *, panel="allergy", value_text=None, verdict=None, date="2025-08-31"):
    return {
        "id": name, "name": name, "unit": "kUA/L", "value_numeric": value,
        "value_text": value_text or str(value), "latest_date": date, "panel_id": panel,
        "area_name": "Allergy", "verification_status": "verified",
        "verdict": {"interpretation": interpretation, "label": interpretation, **(verdict or {})},
    }


def test_a_catalog_card_keeps_the_comparator_printed_in_its_value():
    # Catalog cards carry the sign only inside the formatted value.
    card = _card("Aca m 2", 0.1, "negative", value_text="<0,1")
    assert ai_export._value_text(card) == "<0.1 kUA/L"
    assert ai_export._value_text(_card("Bet v 1", 0.32, "positive")) == "0.32 kUA/L"


def test_exclusive_bounds_print_their_own_comparator():
    assert ai_export._interval(None, 0.35, "kUA/L", True, False) == "< 0.35 kUA/L"
    assert ai_export._interval(0, None, None, False, True) == "> 0"
    assert ai_export._interval(None, 3.8, "mmol/L") == "≤ 3.8 mmol/L"


def test_an_all_negative_allergen_panel_collapses_to_one_line():
    negatives = [_card(f"Allergen {index}", 0.1, "negative") for index in range(30)]
    positive = _card("Cyn d 1", 0.42, "positive")
    total = _card("Total immunoglobulin E", 39, "normal")
    kept, line = ai_export._collapse_negative_allergens([positive, total, *negatives])
    assert kept == [positive, total]
    assert line.startswith("- 30 ") and "Allergen 29" in line and "2025-08-31" in line
    few, none = ai_export._collapse_negative_allergens(negatives[:3])
    assert none is None and len(few) == 3


def test_body_systems_with_flags_come_first():
    calm = [_card("A", 1, "normal", panel=None)]
    flagged = [_card("B", 9, "critical_high", panel=None), _card("C", 1, "normal", panel=None)]
    assert ai_export._area_rank(flagged) < ai_export._area_rank(calm)


def test_the_printed_target_is_cited_to_the_body_that_published_it():
    card = _card("Non-HDL cholesterol", 3.29, "normal", panel=None, verdict={
        "authority": "curated", "source_id": "esc-eas-2019",
        "target_low": None, "target_high": 3.8, "target_high_inclusive": False,
        "target_source_id": "eas-eflm-2016",
    })
    names = {"esc-eas-2019": "ESC/EAS", "eas-eflm-2016": "EAS/EFLM"}

    class Named:
        def ref(self, source_id, fallback=""):
            return names.get(source_id, fallback)

    text = ai_export.judged(card["verdict"], Named())
    assert text == " (<3.8 EAS/EFLM)"


# --- compact notation (2026-11-09) ---------------------------------------------


def test_a_flagged_result_is_printed_once(tmp_path: Path):
    """"Needs attention" carries the full line; the results section does not
    print it a second time (every flagged row used to appear twice)."""
    _settings, _user_id, client = build(tmp_path)
    text = _prompt(client)
    assert sum(line.startswith("- LDL cholesterol:") for line in text.splitlines()) == 1
    assert "HDL cholesterol" in text.split("## Current results", 1)[1]


def test_only_unchecked_values_are_marked():
    """Most of the record is checked against its page; saying so on every line
    was the largest single phrase in the export.  The exceptions are marked."""
    checked = _card("Bet v 1", 0.32, "positive")
    unchecked = {**checked, "verification_status": "extracted"}
    device = {**checked, "verification_status": "device_measurement"}

    class Nobody:
        def ref(self, source_id, fallback=""):
            return ""

    assert "unverified" not in ai_export._result_line(checked, Nobody())
    assert ai_export._result_line(unchecked, Nobody()).endswith(" unverified")
    assert "unverified" not in ai_export._result_line(device, Nobody())
    assert ai_export._result_line(checked, Nobody()) == "- Bet v 1: 0.32 kUA/L @2025-08-31 +"


def test_a_conclusion_without_an_english_summary_still_travels():
    """42 of 43 conclusions had no English summary and went out as a bare title,
    taking the diagnoses a cardiologist wrote with them."""
    item = {"finding_date": "2026-08-09", "title": "Cardiology consultation", "vendor": "Clinic",
            "summary_en": None, "summary_text": "E78.2 Змішана\nгіперліпідемія"}
    line = ai_export._finding_line(item)
    assert line == "- 2026-08-09 Cardiology consultation (Clinic): E78.2 Змішана гіперліпідемія"
    # The same conclusion extracted three times is one line.
    kept, over = ai_export._finding_lines([item, item, {**item, "summary_text": "I11.9"}])
    assert len(kept) == 2 and over == 0


def test_publishers_are_numbered_in_order_of_use():
    class Fake(ai_export.Sources):
        def __init__(self):
            self.by_source = {"a": "Zeta Society", "b": "Alpha Board"}
            self.alias, self.by_use = {}, True

    sources = Fake()
    text = f"x {sources.ref('a')} y {sources.ref('b')} z {sources.ref('a')}\nSLOT"
    assert sources.render(text, label="- Sources", at="SLOT") == (
        "x S1 y S2 z S1\n- Sources: S1 Zeta Society; S2 Alpha Board"
    )
    # One body spelled with two apostrophes is still one body.
    sources = Fake()
    sources.by_source = {"a": "Міністерство охорони здоров'я", "b": "Міністерство охорони здоров’я"}
    assert sources.render(f"{sources.ref('a')} {sources.ref('b')}") == (
        "S1 S1\nSources: S1 Міністерство охорони здоров’я"
    )
