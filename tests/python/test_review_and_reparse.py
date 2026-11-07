"""What a reviewer can see, correct and re-read.

Three defects live here, each of which reached the page as a confident wrong
answer rather than as an error:

* a `<` in front of a result was never printed and was erased by any
  correction, so an assay that could not detect an analyte published a
  measurement it never made;
* one file appeared in the queue once per review task and every entry resolved
  the first one, so a re-read file showed up three times, two of the entries did
  nothing, and the queue could not reach zero;
* a parser improvement reached stored files only if somebody opened all 85 of
  them one at a time, and nothing said which ones were behind.
"""

from __future__ import annotations

import re
from pathlib import Path

from anamna.db import connect, utc_now
from anamna.ingest.parsers import PARSER_VERSION
from anamna.ingest.pipeline import ensure_vendor

from test_web_panels import build
from test_web_review import add_document, add_task, csrf_for


def observation_ids(settings, document_id: str = "doc-1") -> list[str]:
    with connect(settings) as connection:
        return [
            str(row[0])
            for row in connection.execute(
                "SELECT id FROM observations WHERE document_id=? ORDER BY rowid", (document_id,)
            )
        ]


def observation(settings, observation_id: str) -> dict[str, object]:
    with connect(settings) as connection:
        return dict(
            connection.execute(
                "SELECT * FROM observations WHERE id=?", (observation_id,)
            ).fetchone()
        )


def set_comparator(settings, observation_id: str, comparator: str) -> None:
    with connect(settings) as connection:
        connection.execute(
            "UPDATE observations SET comparator=? WHERE id=?", (comparator, observation_id)
        )
        connection.commit()


# --- the comparator ---------------------------------------------------------


def test_a_result_the_assay_could_not_resolve_keeps_its_sign(tmp_path: Path):
    settings, user_id, client = build(tmp_path)
    target = observation_ids(settings)[0]
    set_comparator(settings, target, "<")

    body = client.get("/documents/doc-1").text
    assert "&lt;4.42" in body or "<4.42" in body

    # The correction form is seeded with the sign, so opening it to fix
    # something else and saving cannot quietly publish a measured 4.42.
    assert 'value="&lt;4.42"' in body or 'value="<4.42"' in body


def test_correcting_the_unit_does_not_erase_the_comparator(tmp_path: Path):
    settings, user_id, client = build(tmp_path)
    target = observation_ids(settings)[0]
    set_comparator(settings, target, "<")
    before = observation(settings, target)

    response = client.post(
        f"/observations/{target}",
        data={
            "csrf_token": csrf_for(settings, user_id),
            "raw_name": before["raw_name"],
            "value_numeric": "<4.42",
            "value_text": "",
            "unit_raw": "mmol/l",
            "vendor_reference_text": before["vendor_reference_text"] or "",
        },
        follow_redirects=False,
    )
    assert response.status_code == 303
    after = observation(settings, target)
    assert after["comparator"] == "<"
    assert after["value_numeric"] == 4.42
    assert after["unit_raw"] == "mmol/l"


def test_deleting_the_sign_is_how_a_reviewer_removes_it(tmp_path: Path):
    settings, user_id, client = build(tmp_path)
    target = observation_ids(settings)[0]
    set_comparator(settings, target, "<")
    before = observation(settings, target)

    client.post(
        f"/observations/{target}",
        data={
            "csrf_token": csrf_for(settings, user_id),
            "raw_name": before["raw_name"],
            "value_numeric": "4.42",
            "value_text": "",
            "unit_raw": before["unit_raw"] or "",
            "vendor_reference_text": before["vendor_reference_text"] or "",
        },
        follow_redirects=False,
    )
    assert observation(settings, target)["comparator"] is None


def test_a_correction_records_what_the_value_used_to_be(tmp_path: Path):
    settings, user_id, client = build(tmp_path)
    target = observation_ids(settings)[0]
    before = observation(settings, target)

    client.post(
        f"/observations/{target}",
        data={
            "csrf_token": csrf_for(settings, user_id),
            "raw_name": before["raw_name"],
            "value_numeric": "9.99",
            "value_text": "",
            "unit_raw": before["unit_raw"] or "",
            "vendor_reference_text": before["vendor_reference_text"] or "",
        },
        follow_redirects=False,
    )
    with connect(settings) as connection:
        details = str(
            connection.execute(
                """SELECT details_json FROM audit_events
                   WHERE action='observation_corrected' AND entity_id=?""",
                (target,),
            ).fetchone()[0]
        )
    # The one question anybody asks of a correction later.
    assert '"previous_value_numeric": 4.42' in details


# --- one queue entry per file ----------------------------------------------


def test_a_file_re_read_twice_is_one_entry_in_the_queue(tmp_path: Path):
    settings, user_id, client = build(tmp_path)
    add_task(settings, user_id, "task-2", "doc-1", "open", utc_now())
    add_task(settings, user_id, "task-3", "doc-1", "open", utc_now())

    body = client.get("/documents?review_state=open").text
    assert body.count('class="document-card"') == 1
    assert "Awaiting review (1)" in body


def test_finishing_a_file_finishes_every_task_on_it(tmp_path: Path):
    settings, user_id, client = build(tmp_path)
    add_task(settings, user_id, "task-2", "doc-1", "open", utc_now())
    add_task(settings, user_id, "task-3", "doc-1", "open", utc_now())
    with connect(settings) as connection:
        newest = str(
            connection.execute(
                """SELECT id FROM review_tasks WHERE entity_id='doc-1' AND state='open'
                   ORDER BY created_at DESC, rowid DESC LIMIT 1"""
            ).fetchone()[0]
        )

    client.post(
        f"/review/{newest}",
        data={"csrf_token": csrf_for(settings, user_id), "action": "verify"},
        follow_redirects=False,
    )
    with connect(settings) as connection:
        states = sorted(
            str(row[0])
            for row in connection.execute(
                "SELECT state FROM review_tasks WHERE entity_id='doc-1'"
            )
        )
    assert states == ["resolved", "resolved", "resolved"]
    # The queue is genuinely empty rather than showing two entries that do nothing.
    assert 'class="document-card"' not in client.get("/documents?review_state=open").text


def test_an_empty_queue_says_which_kind_of_empty_it_is(tmp_path: Path):
    settings, user_id, client = build(tmp_path)
    with connect(settings) as connection:
        connection.execute("DELETE FROM review_tasks")
        connection.commit()

    body = client.get("/documents?review_state=open").text
    assert 'class="document-card"' not in body
    assert "No matching documents" in body
    assert "Awaiting review (0)" in body


# --- re-reading what an older parser produced -------------------------------


def test_the_documents_page_names_the_files_an_older_parser_read(tmp_path: Path):
    settings, user_id, client = build(tmp_path)
    with connect(settings) as connection:
        connection.execute(
            "UPDATE observations SET parser_version='2000.01.01-1' WHERE document_id='doc-1'"
        )
        connection.commit()

    body = client.get("/documents").text
    assert "Older parser" in body
    assert "/documents/rescan-stale" in body


def test_a_file_the_current_parser_read_is_not_offered_for_re_reading(tmp_path: Path):
    settings, user_id, client = build(tmp_path)
    with connect(settings) as connection:
        connection.execute(
            "UPDATE observations SET parser_version=? WHERE document_id='doc-1'",
            (PARSER_VERSION,),
        )
        connection.commit()

    body = client.get("/documents").text
    assert "/documents/rescan-stale" not in body


def test_re_reading_them_all_queues_only_the_stale_ones(tmp_path: Path):
    settings, user_id, client = build(tmp_path)
    add_document(settings, user_id, "doc-2")
    with connect(settings) as connection:
        connection.execute(
            "UPDATE observations SET parser_version='2000.01.01-1' WHERE document_id='doc-1'"
        )
        connection.commit()

    response = client.post(
        "/documents/rescan-stale",
        data={"csrf_token": csrf_for(settings, user_id), "next": "/documents"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    with connect(settings) as connection:
        queued = [
            (str(row["kind"]), str(row["document_id"]))
            for row in connection.execute(
                "SELECT kind, document_id FROM upload_jobs WHERE owner_user_id=?", (user_id,)
            )
        ]
    assert queued == [("rescan", "doc-1")]


def test_re_reading_them_all_needs_the_session_token(tmp_path: Path):
    settings, user_id, client = build(tmp_path)
    response = client.post(
        "/documents/rescan-stale", data={"csrf_token": "wrong"}, follow_redirects=False
    )
    assert response.status_code == 403
    with connect(settings) as connection:
        assert connection.execute("SELECT COUNT(*) FROM upload_jobs").fetchone()[0] == 0


# --- saying what a document actually is -------------------------------------


def test_a_misclassified_report_can_be_named_and_is_re_read(tmp_path: Path):
    settings, user_id, client = build(tmp_path)
    with connect(settings) as connection:
        connection.execute("UPDATE documents SET clinical_type='consultation' WHERE id='doc-1'")
        connection.commit()

    response = client.post(
        "/documents/doc-1/classification",
        data={
            "csrf_token": csrf_for(settings, user_id),
            "clinical_type": "laboratory",
            "vendor": "Synevo",
            "report_date": "2025-02-13",
        },
        follow_redirects=False,
    )
    assert response.status_code == 303
    with connect(settings) as connection:
        row = connection.execute(
            """SELECT d.clinical_type, d.report_date, d.classified_by, v.canonical_name vendor
               FROM documents d JOIN vendors v ON v.id=d.vendor_id WHERE d.id='doc-1'"""
        ).fetchone()
        queued = [
            (str(job["kind"]), str(job["document_id"]))
            for job in connection.execute("SELECT kind, document_id FROM upload_jobs")
        ]
        actions = [
            str(item[0])
            for item in connection.execute(
                "SELECT action FROM audit_events WHERE entity_id='doc-1'"
            )
        ]
    assert row["clinical_type"] == "laboratory"
    assert row["vendor"] == "Synevo"
    assert row["report_date"] == "2025-02-13"
    # A person ruled, so a later re-read must not guess over it.
    assert row["classified_by"] == "human"
    # The answer is worth nothing until the parser has acted on it.
    assert queued == [("rescan", "doc-1")]
    assert "document_reclassified" in actions


def test_title_and_date_are_edited_without_re_reading(tmp_path: Path):
    settings, user_id, client = build(tmp_path)
    response = client.post(
        "/documents/doc-1/metadata",
        data={
            "csrf_token": csrf_for(settings, user_id),
            "title": "Annual lipid panel",
            "report_date": "2025-02-14",
        },
        follow_redirects=False,
    )
    assert response.status_code == 303
    with connect(settings) as connection:
        row = connection.execute(
            "SELECT title, title_set_by, report_date FROM documents WHERE id='doc-1'"
        ).fetchone()
        queued = connection.execute("SELECT COUNT(*) FROM upload_jobs").fetchone()[0]
    assert dict(row) == {
        "title": "Annual lipid panel",
        "title_set_by": "human",
        "report_date": "2025-02-14",
    }
    assert queued == 0


def test_custom_type_provider_and_provider_reset_are_supported(tmp_path: Path):
    settings, user_id, client = build(tmp_path)
    token = csrf_for(settings, user_id)
    response = client.post(
        "/documents/doc-1/classification",
        data={
            "csrf_token": token,
            "clinical_type": "__custom__",
            "clinical_type_custom": "Functional assessment",
            "vendor": "__custom__",
            "vendor_custom": "Community Clinic",
        },
        follow_redirects=False,
    )
    assert response.status_code == 303
    with connect(settings) as connection:
        row = connection.execute(
            """SELECT d.clinical_type, v.canonical_name vendor FROM documents d
               JOIN vendors v ON v.id=d.vendor_id WHERE d.id='doc-1'"""
        ).fetchone()
    assert tuple(row) == ("Functional assessment", "Community Clinic")

    client.post(
        "/documents/doc-1/classification",
        data={"csrf_token": token, "clinical_type": "Functional assessment", "vendor": "__clear__"},
        follow_redirects=False,
    )
    with connect(settings) as connection:
        vendor = connection.execute(
            """SELECT v.canonical_name FROM documents d JOIN vendors v ON v.id=d.vendor_id
               WHERE d.id='doc-1'"""
        ).fetchone()[0]
    assert vendor == "Unknown vendor"


def test_provider_select_shows_all_values_while_one_is_selected(tmp_path: Path):
    settings, _, client = build(tmp_path)
    with connect(settings) as connection:
        ensure_vendor(connection, "Another Clinic", None)
    body = client.get("/documents/doc-1").text
    assert 'value="Test Lab" selected' in body
    assert 'value="Another Clinic"' in body
    assert 'value="__clear__"' in body


def test_a_new_kind_of_report_is_saved_without_re_reading(tmp_path: Path):
    settings, user_id, client = build(tmp_path)
    response = client.post(
        "/documents/doc-1/classification",
        data={"csrf_token": csrf_for(settings, user_id), "clinical_type": "made_up"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    with connect(settings) as connection:
        kind = connection.execute(
            "SELECT clinical_type FROM documents WHERE id='doc-1'"
        ).fetchone()[0]
        assert connection.execute("SELECT COUNT(*) FROM upload_jobs").fetchone()[0] == 0
    assert kind == "made_up"


def test_naming_a_document_needs_the_session_token_and_your_own_file(tmp_path: Path):
    settings, user_id, client = build(tmp_path)
    refused = client.post(
        "/documents/doc-1/classification",
        data={"csrf_token": "wrong", "clinical_type": "laboratory"},
        follow_redirects=False,
    )
    assert refused.status_code == 403
    missing = client.post(
        "/documents/not-mine/classification",
        data={"csrf_token": csrf_for(settings, user_id), "clinical_type": "laboratory"},
        follow_redirects=False,
    )
    assert missing.status_code == 404


def test_a_named_kind_survives_the_re_read_it_triggers(tmp_path: Path):
    """The correction is worthless if the re-read undoes it.

    Naming the kind queues a re-read, and a re-read re-runs the classifier --
    which reaches the same wrong answer it reached the first time.  Without the
    `classified_by` guard the fix appeared to work and had reverted by the time
    the page reloaded, leaving the file permanently unreadable.
    """
    from anamna.ingest.pipeline import _apply_human_classification, Analysis
    from anamna.ingest.classifier import Classification

    settings, user_id, client = build(tmp_path)
    client.post(
        "/documents/doc-1/classification",
        data={
            "csrf_token": csrf_for(settings, user_id),
            "clinical_type": "laboratory",
            "vendor": "Synevo",
            "report_date": "2025-02-13",
        },
        follow_redirects=False,
    )
    with connect(settings) as connection:
        document = connection.execute(
            """SELECT d.*, v.canonical_name vendor_name FROM documents d
               LEFT JOIN vendors v ON v.id=d.vendor_id WHERE d.id='doc-1'"""
        ).fetchone()

    # What the classifier would have said on its own, re-reading the file.
    guessed = Classification(
        vendor="Unknown vendor", website=None, clinical_type="clinical_report",
        title="A report", report_date=None, order_identifier=None, status="final",
        extraction_strategy="native_text", confidence=0.75, notes=None,
    )
    analysis = Analysis(
        pages=[{"page_number": 1}], mime_type="application/pdf", page_count=1,
        content_hash="x", classification=guessed, per_page=[guessed],
    )
    kept = _apply_human_classification(analysis, document)

    assert kept.classification.clinical_type == "laboratory"
    assert kept.classification.vendor == "Synevo"
    assert kept.classification.report_date == "2025-02-13"
    # The page classifications matter most: `parse_pages` dispatches per page,
    # so a document named "laboratory" whose pages still read "clinical_report"
    # would extract exactly as much as before, which is nothing.
    assert kept.per_page[0].clinical_type == "laboratory"
    assert kept.per_page[0].vendor == "Synevo"
    # A document nobody has ruled on is left entirely to the classifier.
    with connect(settings) as connection:
        connection.execute("UPDATE documents SET classified_by=NULL WHERE id='doc-1'")
        connection.commit()
        untouched = connection.execute(
            """SELECT d.*, v.canonical_name vendor_name FROM documents d
               LEFT JOIN vendors v ON v.id=d.vendor_id WHERE d.id='doc-1'"""
        ).fetchone()
    assert _apply_human_classification(analysis, untouched).classification.vendor == "Unknown vendor"


def test_the_form_offers_every_kind(tmp_path: Path):
    settings, user_id, client = build(tmp_path)
    body = client.get("/documents/doc-1").text
    assert "/documents/doc-1/classification" in body
    assert 'value="laboratory"' in body
    assert 'value="ultrasound"' in body
    # The labelled control stands on its own; no help paragraph under it.
    assert "Choose a known report type to re-read the file" not in body
    assert "Add another type" in body


def test_every_kind_the_classifier_can_reach_is_offered_by_the_form():
    """A kind missing here is a wrong answer on the page, not a missing one.

    `DOCUMENT_TYPE_TITLES` is both the option list and the allowlist the POST
    validates against.  With no option matching a document's own kind the
    browser selects the *first* one, so a Kardia ECG recording displayed
    "Allergy report" as its type -- and saving that form, which is the obvious
    response to a field that looks wrong, reclassified the ECG as an allergy
    panel and re-read it under a parser that reads nothing from it.  There was
    no way to set the right value back either, because the same dict rejected
    it.  Four kinds were missing: electrocardiogram, blood_pressure,
    administrative and clinical_report.
    """
    import inspect

    from anamna.ingest import classifier
    from anamna.web.app import DOCUMENT_TYPE_TITLES

    emitted = set(
        re.findall(r'clinical_type = "([a-z_]+)"', inspect.getsource(classifier))
    )
    assert emitted, "the classifier's assignments moved; this guard reads them by shape"
    assert emitted <= set(DOCUMENT_TYPE_TITLES), sorted(emitted - set(DOCUMENT_TYPE_TITLES))
    # And each has a Ukrainian rendering, or the filter prints a bare key.
    from anamna.i18n import set_locale
    from anamna.health import enum_label

    set_locale("uk")
    try:
        untranslated = [kind for kind in sorted(emitted) if enum_label(kind) == kind]
    finally:
        set_locale("en")
    assert not untranslated, untranslated


# --- reaching the rest of the list ------------------------------------------


def test_a_list_longer_than_a_page_offers_the_next_one(tmp_path: Path):
    settings, user_id, client = build(tmp_path)
    for index in range(2, 25):
        add_document(settings, user_id, f"doc-{index}")

    body = client.get("/documents").text
    assert 'rel="next"' in body
    assert "offset=20" in body
    # And the second page can get back.
    assert 'rel="prev"' in client.get("/documents?offset=20").text


# --- finding it again -------------------------------------------------------


def test_a_search_finds_the_same_records_however_it_is_typed():
    """Three spellings of one word returned three different answers.

    On the live record «мрт» found nothing, «МРТ» found nine documents and
    Latin "MRT" found one -- so whether somebody could find their own MRI
    reports depended on having held shift, and on which keyboard layout they
    happened to be in.  SQLite's LIKE folds case for ASCII only, and the two
    scripts are simply different strings to it.
    """
    from anamna.ingest.text import search_key

    assert search_key("мрт") == search_key("МРТ") == search_key("MRT") == "mrt"
    assert search_key("Мрт") == "mrt"
    # «Г» is "h" in the national scheme and "g" to everyone writing an
    # abbreviation, so both reach the same key: «ЕКГ» is typed "EKG".
    assert search_key("ЕКГ") == search_key("екг") == search_key("EKG")
    # A provider's own Latin name is findable by its Cyrillic spelling.
    assert search_key("Синево") == search_key("Synevo")
    # And the fold is not so aggressive that two different words collide.
    assert search_key("креатинін") != search_key("креатин")


def test_the_search_index_carries_the_folded_key_for_every_document(tmp_path: Path):
    from anamna.ingest.pipeline import backfill_search_keys
    from anamna.ingest.text import search_key

    settings, user_id, client = build(tmp_path)
    with connect(settings) as connection:
        connection.execute("UPDATE search_index SET content_folded=NULL")
        connection.commit()
        assert backfill_search_keys(connection) >= 1
        rows = connection.execute("SELECT content, content_folded FROM search_index").fetchall()
    assert rows and all(
        str(row["content_folded"]) == search_key(str(row["content"])) for row in rows
    )
    # A second pass has nothing left to do, so this stays cheap on every start.
    with connect(settings) as connection:
        assert backfill_search_keys(connection) == 0


def test_a_value_is_shown_at_the_precision_the_report_printed(tmp_path: Path):
    """`UNIT_DECIMALS` pins `%` to one decimal, which loses a printed digit.

    An HbA1c the laboratory printed as 5.24 % was stored as 5.24 and displayed
    as 5,2 % -- against thresholds (5.7 %, 6.5 %) written to two decimals.  The
    rounding is right for a device average and wrong for a transcription.
    """
    from anamna.web.app import format_measured, format_quantity, stored_decimals

    assert stored_decimals(5.24) == 2
    assert stored_decimals(77.0) == 0
    assert stored_decimals(None) == 0
    # Capped, so float noise from a conversion is not mistaken for precision.
    assert stored_decimals(1 / 3) == 4
    assert format_measured(5.24, "%") == "5.24"
    # A value with no extra precision is unchanged (trailing zeros are trimmed
    # either way), and device aggregates keep the rounding that suits them.
    assert format_measured(42.0, "%") == format_quantity(42.0, "%") == "42"
    assert format_quantity(76.83333333333333, "bpm") == "77"


def test_the_document_list_can_be_filtered_without_a_page_load(tmp_path: Path):
    """`/metrics` searched as you typed and `/documents` needed a submit.

    Two search fields in one application behaving differently, for no reason a
    reader could see.  The endpoint returns the cards already rendered by the
    macro the page load uses -- not JSON for the browser to rebuild, which is
    what once printed "your result is inside this range" under a chip reading
    "Above range" on the metrics page.
    """
    settings, user_id, client = build(tmp_path)
    page = client.get("/documents").text
    # The form still works without JavaScript: the script only intercepts what
    # the browser would have submitted anyway.
    assert '<form class="filters" method="get">' in page
    assert "/api/documents/search" in page

    payload = client.get("/api/documents/search").json()
    assert payload["total"] >= 1
    assert payload["documents"].count("document-card") >= 1
    # Rendered cards, not a JSON model of them.
    assert "<a class=\"document-card\"" in payload["documents"]

    missing = client.get("/api/documents/search", params={"q": "zzzz-no-such-document"}).json()
    assert missing["total"] == 0 and missing["documents"].strip() == ""

    # And the same rows a full page load would produce, for the same query.
    with connect(settings) as connection:
        title = str(
            connection.execute("SELECT original_filename FROM documents LIMIT 1").fetchone()[0]
        )
    term = title.split(".")[0]
    live = client.get("/api/documents/search", params={"q": term}).json()
    full = client.get("/documents", params={"q": term}).text
    assert live["total"] == full.count('class="document-card"')
