"""The scan's candidates as the person reviews them: grouping, suggested status, existing entries,
accepting into factors, dismissing, and the owner boundary.

Candidates are inserted directly; no AI is called.  The database is a temporary one.
"""

from __future__ import annotations

import itertools
import json
import uuid
from datetime import date
from types import SimpleNamespace

import pytest

from anamna import factor_candidates, factors
from anamna.db import connect, migrate
from anamna.security import create_user
from test_web_security import PASSWORD, seed_document, seed_patient, settings_for

TODAY = date(2025, 6, 1)

# key: (title, filename, report date).  A None date and an empty imported_at give a document with no date.
DOCUMENTS = {
    "d2023": ("Consult 2023", "consult-2023.txt", "2023-01-01"),
    "d2024": ("Consult 2024", "consult-2024.txt", "2024-01-10"),
    "jan": ("Consult January", "consult-jan.txt", "2025-01-10"),
    "mar": ("Consult March", "consult-mar.txt", "2025-03-05"),
    "may1": ("Consult May 1", "consult-may1.txt", "2025-05-01"),
    "may20": ("Consult May 20", "consult-may20.txt", "2025-05-20"),
    "undated": ("", "undated.txt", None),
}

_clock = itertools.count(1)


@pytest.fixture
def db(tmp_path):
    settings = settings_for(tmp_path)
    migrate(settings)
    alpha = create_user(settings, "alpha@example.test", "Alpha", PASSWORD)
    beta = create_user(settings, "beta@example.test", "Beta", PASSWORD)
    alpha_patient = seed_patient(settings, alpha, "Alpha")
    beta_patient = seed_patient(settings, beta, "Beta")
    docs = {
        key: seed_document(settings, alpha, alpha_patient, title, filename)
        for key, (title, filename, _report) in DOCUMENTS.items()
    }
    beta_doc = seed_document(settings, beta, beta_patient, "Beta result", "beta-consult.txt")
    connection = connect(settings)
    for key, (_title, _filename, report) in DOCUMENTS.items():
        connection.execute(
            "UPDATE documents SET report_date=?, imported_at='' WHERE id=?", (report, docs[key])
        )
    yield SimpleNamespace(
        connection=connection, alpha=alpha, beta=beta, alpha_patient=alpha_patient,
        docs=docs, beta_doc=beta_doc,
    )
    connection.close()


def key(kind: str, name: str) -> str:
    return f"{kind}:{' '.join(name.split()).casefold()}"


def add(db, document_id: str, *, name: str = "Diacor", kind: str = "medicine", owner=None, **fields) -> str:
    row = {
        "id": str(uuid.uuid4()), "owner_user_id": owner or db.alpha, "document_id": document_id,
        "kind": kind, "name": name, "name_key": " ".join(name.split()).casefold(),
        "quote": f"quote {name}", "state": "new",
        "timing": "now", "event_date": None, "date_exact": 0,
        "created_at": f"2025-06-01T00:00:{next(_clock):05d}",
    }
    row.update(fields)
    columns = ", ".join(row)
    marks = ", ".join("?" for _ in row)
    db.connection.execute(f"INSERT INTO factor_candidates ({columns}) VALUES ({marks})", tuple(row.values()))
    return row["id"]


def entry(db, **fields) -> str:
    values, error = factors.clean({"status": "current", **fields}, today=TODAY)
    assert error is None, error
    return factors.create(db.connection, db.alpha, db.alpha_patient, values)


def offered(db, owner=None) -> dict:
    found = factor_candidates.groups(db.connection, owner or db.alpha, today=TODAY, locale="en")
    return {group["key"]: group for group in found}


def state(db, candidate_id: str) -> tuple:
    return tuple(db.connection.execute(
        "SELECT state, factor_id FROM factor_candidates WHERE id=?", (candidate_id,)
    ).fetchone())


def accept(db, keys, statuses=None, owner=None):
    return factor_candidates.accept(
        db.connection, owner or db.alpha, db.alpha_patient, keys, statuses or {}, today=TODAY,
    )


def test_one_medicine_in_three_documents_is_one_group(db):
    d = db.docs
    add(db, d["jan"], name="Diacor", substance="bisoprolol", reason="high pressure", quote="jan quote")
    add(db, d["mar"], name="Diacor", reason="", quote="mar quote")
    add(db, d["may20"], name="DIACOR", reason="pressure control", quote="may quote")

    [group] = factor_candidates.groups(db.connection, db.alpha, today=TODAY, locale="en")

    assert group["key"] == "medicine:diacor"
    assert group["mentions"] == 3
    assert group["first_date"] == "2025-01-10"
    assert group["last_date"] == "2025-05-20"
    assert group["name"] == "DIACOR"
    assert group["quote"] == "may quote"
    assert group["reason"] == "pressure control"
    assert group["substance"] == "bisoprolol"
    assert group["documents"] == [
        {"id": d["may20"], "title": "Consult May 20", "date": "2025-05-20"},
        {"id": d["mar"], "title": "Consult March", "date": "2025-03-05"},
        {"id": d["jan"], "title": "Consult January", "date": "2025-01-10"},
    ]


def test_how_uses_the_regimen_as_data_and_otherwise_the_written_words(db):
    d = db.docs
    add(db, d["jan"], name="Amlodipine", dose_amount=1, dose_unit="tablet",
        schedule_json=json.dumps({"repeat": "daily", "every": 1, "per_day": 2}))
    add(db, d["mar"], name="Amlodipine", how_written="twice a day with food")
    add(db, d["jan"], name="Compress", kind="other", how_written="apply to the knee")

    offered_groups = offered(db)

    amlodipine = offered_groups["medicine:amlodipine"]
    assert amlodipine["how"] == "1 tablet · 2 times a day"
    assert amlodipine["how_written"] == "twice a day with food"
    assert offered_groups["other:compress"]["how"] == "apply to the knee"


def test_a_stopped_medicine_shows_no_regimen_text_even_with_a_written_instruction(db):
    add(db, db.docs["may1"], name="Ibuprofen", stopped=1, how_written="stop taking ibuprofen")

    group = offered(db)["medicine:ibuprofen"]

    assert group["how"] == ""
    assert group["how_written"] == "stop taking ibuprofen"


@pytest.mark.parametrize(
    ("document", "fields", "exact"),
    [
        # The document's own date stands for a day it says is present now.
        ("mar", {}, True),
        # An event date the document gave in full.
        ("may1", {"timing": "past", "event_date": "2025-02-02", "date_exact": 1}, True),
        # An event date the document gave only by its year.
        ("may1", {"timing": "past", "event_date": "2019-01-01", "date_exact": 0}, False),
        # No date at all.
        ("undated", {}, True),
    ],
)
def test_first_and_last_exact_say_whether_the_day_was_written_in_full(db, document, fields, exact):
    add(db, db.docs[document], name="Case", **fields)

    [group] = factor_candidates.groups(db.connection, db.alpha, today=TODAY, locale="en")

    assert group["first_exact"] is exact
    assert group["last_exact"] is exact


def test_first_and_last_exact_follow_their_own_mention(db):
    d = db.docs
    add(db, d["jan"], name="Diacor", timing="past", event_date="2019-01-01", date_exact=0)
    add(db, d["mar"], name="Diacor")

    group = offered(db)["medicine:diacor"]

    assert group["first_date"] == "2019-01-01"
    assert group["first_exact"] is False
    assert group["last_date"] == "2025-03-05"
    assert group["last_exact"] is True


@pytest.mark.parametrize(
    ("kind", "document", "fields", "status", "started", "ended"),
    [
        # A point kind: one date, past or planned.
        ("procedure", "may1", {"event_date": "2025-02-02"}, "past", "2025-02-02", ""),
        # Past: the start is the earliest dated mention, no end.
        ("medicine", "may1", {"timing": "past", "event_date": "2024-03-01"}, "past", "2024-03-01", ""),
        # Planned: prescribed, starting on its date.
        ("medicine", "may1", {"timing": "planned", "event_date": "2025-07-01"}, "prescribed", "2025-07-01", ""),
        # Stopped: the stop date ends it, and there is no start to name.
        ("medicine", "may1", {"stopped": 1}, "past", "", "2025-05-01"),
        # A course: the start plus its duration.
        ("medicine", "may1", {"duration_days": 14}, "past", "2025-05-01", "2025-05-15"),
        ("medicine", "may20", {"duration_days": 60}, "current", "2025-05-20", "2025-07-19"),
        # Long term: current from the earliest date.
        ("medicine", "d2023", {"long_term": 1}, "current", "2023-01-01", ""),
        # Otherwise: current when the latest mention is recent, past when it is not.
        ("medicine", "may20", {}, "current", "2025-05-20", ""),
        ("medicine", "d2024", {}, "past", "2024-01-10", ""),
        ("medicine", "undated", {}, "past", "", ""),
    ],
)
def test_suggested_status_start_and_end(db, kind, document, fields, status, started, ended):
    add(db, db.docs[document], name="Case", kind=kind, **fields)

    [group] = factor_candidates.groups(db.connection, db.alpha, today=TODAY, locale="en")

    assert group["suggested_status"] == status
    assert group["started_on"] == started
    assert group["ended_on"] == ended


def test_first_and_last_date_ignore_mentions_without_a_date(db):
    d = db.docs
    add(db, d["undated"], name="Diacor")
    add(db, d["jan"], name="Diacor", timing="past")
    add(db, d["mar"], name="Diacor")
    add(db, d["undated"], name="Nothing dated")

    groups_by_key = offered(db)

    assert groups_by_key["medicine:diacor"]["first_date"] == "2025-03-05"
    assert groups_by_key["medicine:diacor"]["last_date"] == "2025-03-05"
    assert groups_by_key["medicine:nothing dated"]["first_date"] == ""
    assert groups_by_key["medicine:nothing dated"]["last_date"] == ""


def test_an_entry_already_in_the_record_marks_the_group_existing(db):
    d = db.docs
    entry(db, kind="medicine", name="Diacor")
    entry(db, kind="medicine", name="Діокор соло 160")
    entry(db, kind="medicine", name="Bisoprolol", substance="Bisoprolol")
    entry(db, kind="supplement", name="Magnesium")
    add(db, d["jan"], name="Diacor")
    add(db, d["jan"], name="Діокор соло")
    add(db, d["jan"], name="Bisoprolol-Teva", substance="bisoprolol")
    add(db, d["jan"], name="Magnesium")

    flags = {group["key"]: group["existing"] for group in factor_candidates.groups(
        db.connection, db.alpha, today=TODAY, locale="en")}

    assert flags == {
        "medicine:diacor": True,
        "medicine:діокор соло": True,
        "medicine:bisoprolol-teva": True,
        "medicine:magnesium": False,
    }


def test_groups_are_ordered_and_count_leaves_out_existing(db):
    d = db.docs
    entry(db, kind="medicine", name="Known")
    add(db, d["may20"], name="Known")
    add(db, d["may20"], name="Beta")
    add(db, d["may20"], name="Alpha")
    add(db, d["mar"], name="Gamma")
    add(db, d["may1"], name="Surgery", kind="procedure")
    add(db, d["may1"], name="Flu", kind="illness")

    names = [group["name"] for group in factor_candidates.groups(db.connection, db.alpha, today=TODAY, locale="en")]

    assert names == ["Alpha", "Beta", "Gamma", "Surgery", "Flu", "Known"]
    assert factor_candidates.count(db.connection, db.alpha) == 5
    assert factor_candidates.count(db.connection, db.beta) == 0


def test_accept_creates_the_entry_and_marks_its_candidates(db):
    d = db.docs
    diacor_jan = add(db, d["jan"], name="Diacor", dose_amount=1, dose_unit="tablet",
                     schedule_json=json.dumps({"repeat": "daily", "every": 1, "per_day": 2}),
                     reason="high pressure", how_written="one tablet in the morning")
    diacor_may = add(db, d["may20"], name="Diacor", reason="pressure control", how_written="twice a day")
    warfarin = add(db, d["may1"], name="Warfarin", how_written="as directed")
    course = add(db, d["may1"], name="Course", duration_days=14)
    known = add(db, d["may20"], name="Known")
    entry(db, kind="medicine", name="Known")
    beta_diacor = add(db, db.beta_doc, name="Diacor", owner=db.beta)

    ids = accept(
        db,
        [key("medicine", "Diacor"), key("medicine", "Warfarin"), key("medicine", "Course"),
         key("medicine", "Known"), "nonsense:key"],
        {key("medicine", "Diacor"): "prescribed"},
    )

    assert len(ids) == 3
    diacor, warf, ended_course = (factors.get(db.connection, db.alpha, factor_id, today=TODAY) for factor_id in ids)
    assert diacor["name"] == "Diacor"
    assert diacor["status"] == "prescribed"
    assert diacor["started_on"] == "2025-01-10"
    assert diacor["ended_on"] is None
    assert diacor["dates_approximate"] == 1
    assert diacor["reason"] == "pressure control"
    assert diacor["schedule"] == ""
    assert diacor["dose_amount"] == 1
    assert diacor["dose_unit"] == "tablet"
    assert diacor["regimen"]["repeat"] == "daily"
    assert diacor["regimen"]["per_day"] == 2
    assert diacor["document_id"] == d["jan"]

    assert warf["status"] == "current"
    assert warf["started_on"] == "2025-05-01"
    assert warf["schedule"] == "as directed"
    assert warf["regimen"] is None
    assert warf["document_id"] == d["may1"]

    assert ended_course["status"] == "past"
    assert ended_course["started_on"] == "2025-05-01"
    assert ended_course["ended_on"] == "2025-05-15"

    assert state(db, diacor_jan) == ("accepted", ids[0])
    assert state(db, diacor_may) == ("accepted", ids[0])
    assert state(db, warfarin) == ("accepted", ids[1])
    assert state(db, course) == ("accepted", ids[2])
    assert state(db, known) == ("new", None)
    assert state(db, beta_diacor) == ("new", None)
    assert "medicine:diacor" not in offered(db)
    assert "medicine:warfarin" not in offered(db)
    assert offered(db)["medicine:known"]["existing"] is True


def test_prescriber_comes_from_the_earliest_document(db, monkeypatch):
    d = db.docs
    fake = SimpleNamespace(doctor_in=lambda text: "Dr. Petrenko" if "Петренко" in text else "")
    monkeypatch.setattr(factor_candidates, "factor_documents", fake)
    db.connection.execute(
        "INSERT INTO document_pages(document_id, page_number, native_text, extraction_method) "
        "VALUES (?, 1, ?, 'native')",
        (d["jan"], "Лікар: Петренко"),
    )
    add(db, d["jan"], name="Diacor", how_written="daily")
    add(db, d["may20"], name="Diacor", how_written="twice a day")

    [factor_id] = accept(db, [key("medicine", "Diacor")])

    created = factors.get(db.connection, db.alpha, factor_id, today=TODAY)
    assert created["prescriber"] == "Dr. Petrenko, Test Lab"
    assert created["document_id"] == d["jan"]


def test_a_procedure_keeps_its_own_date(db):
    add(db, db.docs["may1"], name="Appendectomy", kind="procedure", event_date="2025-02-02", date_exact=1)

    [factor_id] = accept(db, [key("procedure", "Appendectomy")])

    created = factors.get(db.connection, db.alpha, factor_id, today=TODAY)
    assert created["started_on"] == "2025-02-02"
    assert created["dates_approximate"] == 0
    assert created["status"] == "past"


def test_a_past_procedure_without_a_date_gets_no_start_and_never_the_document_date(db):
    add(db, db.docs["may1"], name="Appendectomy", kind="procedure", timing="past")

    group = offered(db)["procedure:appendectomy"]
    [factor_id] = accept(db, [key("procedure", "Appendectomy")])

    assert group["started_on"] == ""
    assert group["suggested_status"] == "past"
    created = factors.get(db.connection, db.alpha, factor_id, today=TODAY)
    assert created["started_on"] is None
    assert created["status"] == "past"


@pytest.mark.parametrize(("exact", "approximate"), [(0, 1), (1, 0)])
def test_a_procedure_date_is_approximate_unless_the_document_gave_it_in_full(db, exact, approximate):
    add(db, db.docs["may1"], name="Appendectomy", kind="procedure", timing="past",
        event_date="2019-01-01", date_exact=exact)

    [factor_id] = accept(db, [key("procedure", "Appendectomy")])

    created = factors.get(db.connection, db.alpha, factor_id, today=TODAY)
    assert created["started_on"] == "2019-01-01"
    assert created["dates_approximate"] == approximate


def test_a_planned_procedure_is_prescribed_and_stays_so(db):
    add(db, db.docs["may1"], name="Scan", kind="procedure", timing="planned", event_date="2025-07-01")

    assert offered(db)["procedure:scan"]["suggested_status"] == "prescribed"
    [factor_id] = accept(db, [key("procedure", "Scan")])

    created = factors.get(db.connection, db.alpha, factor_id, today=TODAY)
    assert created["status"] == "prescribed"
    assert created["started_on"] == "2025-07-01"


def test_a_past_illness_without_a_date_is_past_with_no_start(db):
    add(db, db.docs["may1"], name="Flu", kind="illness", timing="past")

    group = offered(db)["illness:flu"]
    [factor_id] = accept(db, [key("illness", "Flu")])

    assert group["suggested_status"] == "past"
    assert group["started_on"] == ""
    created = factors.get(db.connection, db.alpha, factor_id, today=TODAY)
    assert created["status"] == "past"
    assert created["started_on"] is None


def test_a_stopped_medicine_ends_on_its_document_date_with_no_schedule(db):
    add(db, db.docs["may1"], name="Ramipril", stopped=1, how_written="stop taking")

    group = offered(db)["medicine:ramipril"]
    [factor_id] = accept(db, [key("medicine", "Ramipril")])

    assert group["started_on"] == ""
    assert group["ended_on"] == "2025-05-01"
    created = factors.get(db.connection, db.alpha, factor_id, today=TODAY)
    assert created["status"] == "past"
    assert created["started_on"] is None
    assert created["ended_on"] == "2025-05-01"
    assert created["schedule"] == ""


def test_a_stopped_medicine_mentioned_earlier_starts_on_the_earlier_date(db):
    d = db.docs
    add(db, d["d2024"], name="Ramipril", how_written="one capsule daily")
    add(db, d["may1"], name="Ramipril", stopped=1, how_written="stop taking")

    group = offered(db)["medicine:ramipril"]
    [factor_id] = accept(db, [key("medicine", "Ramipril")])

    assert group["started_on"] == "2024-01-10"
    assert group["ended_on"] == "2025-05-01"
    created = factors.get(db.connection, db.alpha, factor_id, today=TODAY)
    assert created["started_on"] == "2024-01-10"
    assert created["ended_on"] == "2025-05-01"
    assert created["schedule"] == ""


def test_the_stored_parts_of_day_and_meal_reach_the_entry(db):
    schedule = {"repeat": "daily", "every": 1, "weekdays": [], "per_day": 1,
                "times": ["morning"], "clock": [], "meal": "after"}
    add(db, db.docs["jan"], name="Amlodipine", dose_amount=1, dose_unit="tablet",
        schedule_json=json.dumps(schedule))

    [factor_id] = accept(db, [key("medicine", "Amlodipine")])

    created = factors.get(db.connection, db.alpha, factor_id, today=TODAY)
    assert created["regimen"]["times"] == ["morning"]
    assert created["regimen"]["meal"] == "after"


def test_a_group_the_form_rejects_is_left_new(db):
    too_long = "x" * 201
    candidate = add(db, db.docs["jan"], name=too_long)

    assert accept(db, [key("medicine", too_long)]) == []
    assert state(db, candidate) == ("new", None)


def test_dismiss_marks_only_the_named_groups_for_this_owner(db):
    d = db.docs
    diacor = add(db, d["jan"], name="Diacor")
    add(db, d["jan"], name="Other")
    beta_diacor = add(db, db.beta_doc, name="Diacor", owner=db.beta)

    dismissed = factor_candidates.dismiss(db.connection, db.alpha, [key("medicine", "Diacor"), "bad:key"])

    assert dismissed == 1
    assert state(db, diacor) == ("dismissed", None)
    assert state(db, beta_diacor) == ("new", None)
    assert list(offered(db)) == ["medicine:other"]
    assert factor_candidates.count(db.connection, db.beta) == 1
