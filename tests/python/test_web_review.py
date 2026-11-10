"""`/review` - the queue, and the writes a reviewer makes from it.

A reviewer's decision is the one thing no parser can reproduce, so each test
here pins a way one used to be lost: a bulk verification overwriting a
correction, a value set aside that went on driving a chart and a metric card,
a queue that rendered only its open state, and a correction that had to be
made again on the next import of the same report.
"""

from __future__ import annotations

import re
from pathlib import Path

from anamna.db import connect, utc_now
from anamna.ingest.pipeline import ensure_concept
from anamna.ingest.text import normalized_key
from anamna.security import create_user

from test_web_panels import build, catalog_for


# The label a laboratory printed and no parser knows. Remapping it by hand is
# the only way this value reaches the right metric.
UNKNOWN_LABEL = "Показник 42"


def csrf_for(settings, user_id: str) -> str:
    with connect(settings) as connection:
        return connection.execute(
            "SELECT csrf_token FROM sessions WHERE user_id=?", (user_id,)
        ).fetchone()[0]


def statuses(settings) -> dict[str, str]:
    with connect(settings) as connection:
        return {
            str(row["id"]): str(row["verification_status"])
            for row in connection.execute(
                "SELECT id, verification_status FROM observations WHERE document_id='doc-1'"
            )
        }


def audit_actions(settings, entity_id: str | None = None) -> list[str]:
    where = "WHERE entity_id=?" if entity_id else ""
    with connect(settings) as connection:
        return [
            str(row[0])
            for row in connection.execute(
                f"SELECT action FROM audit_events {where} ORDER BY id",
                (entity_id,) if entity_id else (),
            )
        ]


def concept_id_for(settings, canonical_name: str) -> str:
    with connect(settings) as connection:
        return str(
            connection.execute(
                "SELECT id FROM concepts WHERE canonical_name=? COLLATE NOCASE", (canonical_name,)
            ).fetchone()[0]
        )


def results_count(client) -> int:
    """The `results` figure the documents list prints for the fixture document."""
    body = client.get("/documents").text
    matches = re.findall(r"<dt>results</dt>\s*<dd>(\d+)</dd>", body)
    assert len(matches) == 1, matches
    return int(matches[0])


def test_open_review_count_matches_documents_filter(tmp_path: Path):
    settings, user_id, client = build(tmp_path)
    with connect(settings) as connection:
        connection.execute(
            """INSERT INTO review_tasks(id, owner_user_id, entity_type, entity_id, reason, state, created_at)
               VALUES ('orphan-task', ?, 'document', 'missing-doc', 'Orphan', 'open', ?)""",
            (user_id, utc_now()),
        )
    open_docs = client.get("/documents?review_state=open").text
    assert open_docs.count('class="document-card"') == 1
    # The home tile that links to that filter names the same number (the
    # retired /insights page used to carry this count).
    home = client.get("/").text
    match = re.search(
        r'<a class="an-stat-tile" href="/documents\?review_state=open"[\s\S]*?'
        r'<span class="an-stat-tile__note">([^<]+)</span>',
        home,
    )
    assert match, home
    assert match.group(1).strip().startswith("1 ")


def add_task(settings, user_id: str, task_id: str, document_id: str, state: str, created_at: str) -> None:
    with connect(settings) as connection:
        connection.execute(
            """INSERT INTO review_tasks(id, owner_user_id, entity_type, entity_id, reason, state, created_at)
               VALUES (?, ?, 'document', ?, 'Verify extracted observation(s) against page evidence', ?, ?)""",
            (task_id, user_id, document_id, state, created_at),
        )


def add_document(settings, user_id: str, document_id: str) -> None:
    """A second file, so the queue has a *next* one to land on."""
    with connect(settings) as connection:
        vendor_id = connection.execute(
            "SELECT vendor_id FROM documents WHERE id='doc-1'"
        ).fetchone()[0]
        connection.execute(
            """INSERT INTO documents(
                   id, owner_user_id, patient_id, vendor_id, original_filename, source_path,
                   mime_type, byte_size, sha256, page_count, title, clinical_type,
                   extraction_strategy, classification_confidence, report_date, imported_at, status
               ) VALUES (?, ?, ?, ?, 'second.pdf', ?, 'application/pdf', 10, ?, 2,
                         '2025-03-01__test-lab__laboratory__result-2', 'laboratory', 'native_text', 1,
                         '2025-03-01', ?, 'final')""",
            (
                document_id, user_id, f"patient-{user_id}", vendor_id,
                str(settings.source_dir / "report.pdf"), f"sha-{document_id}", utc_now(),
            ),
        )
        connection.execute(
            "INSERT INTO search_index(document_id, owner_user_id, content) VALUES (?, ?, 'second')",
            (document_id, user_id),
        )


def add_report(settings, user_id: str, start_page: int, end_page: int) -> str:
    with connect(settings) as connection:
        vendor_id = connection.execute(
            "SELECT vendor_id FROM documents WHERE id='doc-1'"
        ).fetchone()[0]
        connection.execute(
            """INSERT INTO reports(
                   id, owner_user_id, patient_id, document_id, vendor_id, title, clinical_type,
                   report_date, start_page, end_page, created_at
               ) VALUES ('report-1', ?, ?, 'doc-1', ?, 'Lipid panel', 'laboratory', '2025-02-13', ?, ?, ?)""",
            (user_id, f"patient-{user_id}", vendor_id, start_page, end_page, utc_now()),
        )
    return "report-1"


def foreign_observation(settings) -> str:
    """One value in a second account's record, which this session must not touch."""
    other = create_user(settings, "other@example.test", "Other", "another-long-password")
    with connect(settings) as connection:
        vendor_id = connection.execute(
            "SELECT vendor_id FROM documents WHERE id='doc-1'"
        ).fetchone()[0]
        connection.execute(
            """INSERT INTO patients(id, owner_user_id, display_name, date_of_birth, sex_at_birth, created_at)
               VALUES ('patient-other', ?, 'Other', '1990-01-01', 'female', ?)""",
            (other, utc_now()),
        )
        connection.execute(
            """INSERT INTO documents(
                   id, owner_user_id, patient_id, vendor_id, original_filename, source_path,
                   mime_type, byte_size, sha256, page_count, title, clinical_type,
                   extraction_strategy, classification_confidence, report_date, imported_at, status
               ) VALUES ('doc-other', ?, 'patient-other', ?, 'other.pdf', 'other.pdf',
                         'application/pdf', 10, 'sha-other', 1, 'Other report', 'laboratory',
                         'native_text', 1, '2025-01-01', ?, 'final')""",
            (other, vendor_id, utc_now()),
        )
        connection.execute(
            """INSERT INTO observations(
                   id, owner_user_id, patient_id, document_id, page_number, concept_id, raw_name,
                   value_type, value_numeric, unit_raw, observed_at, verification_status,
                   extraction_method, confidence, evidence_text, parser_version, created_at
               ) VALUES ('obs-other', ?, 'patient-other', 'doc-other', 1, ?, 'Creatinine',
                         'numeric', 90.0, 'µmol/L', '2025-01-01', 'extracted', 'test', 0.9,
                         'evidence', 'test', ?)""",
            (other, concept_id_for(settings, "Creatinine"), utc_now()),
        )
    return "obs-other"


# --- the page ---------------------------------------------------------------


def test_documents_filter_by_review_state_and_details_hold_the_workspace(tmp_path: Path):
    settings, user_id, client = build(tmp_path)
    add_task(settings, user_id, "task-done", "doc-1", "resolved", "2024-01-01T00:00:00+00:00")
    add_task(settings, user_id, "task-fix", "doc-1", "needs_correction", "2024-01-02T00:00:00+00:00")
    open_body = client.get("/documents?review_state=open").text
    assert 'class="document-card"' in open_body
    assert 'value="open" selected' in open_body
    # Historical task rows do not make one document appear under several
    # statuses; the latest review decision is the file's current state.
    for state in ("resolved", "needs_correction"):
        assert 'class="document-card"' not in client.get(f"/documents?review_state={state}").text
    detail = client.get("/documents/doc-1").text
    assert 'id="observation-obs-0"' in detail
    assert 'id="an-concept-list"' in detail
    assert 'action="/documents/doc-1/review"' in detail
    assert 'value="verify"' in detail
    client.post(
        "/documents/doc-1/review",
        data={"csrf_token": csrf_for(settings, user_id), "action": "verify"},
        follow_redirects=False,
    )
    assert 'class="document-card"' in client.get("/documents?review_state=resolved").text
    assert 'value="reopen"' in client.get("/documents/doc-1").text
    assert client.get("/documents?review_state=archived").status_code == 404


def test_old_review_links_redirect_to_documents(tmp_path: Path):
    settings, user_id, client = build(tmp_path)
    add_document(settings, user_id, "doc-2")
    add_task(settings, user_id, "task-2", "doc-2", "open", "2020-01-01T00:00:00+00:00")

    first = client.get("/review", follow_redirects=False)
    assert first.status_code == 302
    assert first.headers["location"] == "/documents?review_state=open"
    second = client.get("/review?state=open&document=doc-2", follow_redirects=False)
    assert second.status_code == 302
    assert second.headers["location"] == "/documents/doc-2"


def test_finishing_a_file_from_details_returns_to_that_file(tmp_path: Path):
    settings, user_id, client = build(tmp_path)
    add_document(settings, user_id, "doc-2")
    add_task(settings, user_id, "task-2", "doc-2", "open", "2020-01-01T00:00:00+00:00")

    moved = client.post(
        "/documents/doc-1/review",
        data={
            "action": "verify",
            "csrf_token": csrf_for(settings, user_id),
        },
        follow_redirects=False,
    )
    assert moved.status_code == 303
    assert moved.headers["location"] == "/documents/doc-1"


def test_progress_is_counted_per_value_not_per_file(tmp_path: Path):
    settings, user_id, client = build(tmp_path)
    token = csrf_for(settings, user_id)
    body = client.get("/documents/doc-1").text
    assert "0 of 8 checked" in body

    client.post("/observations/obs-0/state", data={"action": "verify", "csrf_token": token})
    assert "1 of 8 checked" in client.get("/documents/doc-1").text

    # A value set aside is neither work done nor work left: it leaves the total.
    client.post("/observations/obs-1/state", data={"action": "reject", "csrf_token": token})
    body = client.get("/documents/doc-1").text
    assert "1 of 7 checked" in body
    assert "1 set aside" in body


def test_one_concept_list_serves_every_form_on_the_page(tmp_path: Path):
    settings, _, client = build(tmp_path)
    body = client.get("/documents/doc-1").text
    assert body.count('id="an-concept-list"') == 1
    # One correction form per value, plus the add form, all pointing at it -
    # inlining the catalogue per row is megabytes of repeated options.
    assert body.count('list="an-concept-list"') == 9
    assert body.count("<datalist") == 1
    assert 'name="vendor"' in body
    assert 'value="__clear__"' in body
    assert 'value="__custom__"' in body
    assert "Add a report type or provider" in body
    # The placeholder is what makes the browser refuse an unchosen category.
    assert '<option value="" selected disabled>' in body


# --- one value at a time ----------------------------------------------------


def test_one_value_can_be_accepted_set_aside_and_restored(tmp_path: Path):
    settings, user_id, client = build(tmp_path)
    token = csrf_for(settings, user_id)
    for action, expected in (("verify", "verified"), ("reject", "rejected"), ("restore", "extracted")):
        response = client.post(
            "/observations/obs-0/state",
            data={
                "action": action,
                "csrf_token": token,
                "next": "/review?state=open&document=doc-1",
            },
            follow_redirects=False,
        )
        assert response.status_code == 303, action
        # Back where the reviewer was, at the row they just ruled on.
        assert response.headers["location"] == (
            "/review?state=open&document=doc-1#observation-obs-0"
        ), action
        assert statuses(settings)["obs-0"] == expected, action
    assert audit_actions(settings, "obs-0") == [
        "observation_verify", "observation_reject", "observation_restore"
    ]


def test_an_unknown_value_action_is_refused(tmp_path: Path):
    settings, user_id, client = build(tmp_path)
    response = client.post(
        "/observations/obs-0/state",
        data={"action": "delete", "csrf_token": csrf_for(settings, user_id)},
    )
    assert response.status_code == 400
    assert statuses(settings)["obs-0"] == "extracted"
    assert audit_actions(settings, "obs-0") == []


def test_a_value_state_change_needs_the_session_token(tmp_path: Path):
    settings, _, client = build(tmp_path)
    assert client.post("/observations/obs-0/state", data={"action": "verify"}).status_code == 403
    assert client.post(
        "/observations/obs-0/state", data={"action": "verify", "csrf_token": "not-the-token"}
    ).status_code == 403
    assert statuses(settings)["obs-0"] == "extracted"


def test_another_owners_value_is_not_found(tmp_path: Path):
    settings, user_id, client = build(tmp_path)
    foreign = foreign_observation(settings)
    token = csrf_for(settings, user_id)
    assert client.post(
        f"/observations/{foreign}/state", data={"action": "verify", "csrf_token": token}
    ).status_code == 404
    assert client.post(
        f"/observations/{foreign}",
        data={"raw_name": "Creatinine", "value_numeric": "1", "csrf_token": token},
    ).status_code == 404
    with connect(settings) as connection:
        row = connection.execute(
            "SELECT verification_status, value_numeric FROM observations WHERE id=?", (foreign,)
        ).fetchone()
    assert (row["verification_status"], row["value_numeric"]) == ("extracted", 90.0)


def test_an_off_site_next_falls_back_to_the_document(tmp_path: Path):
    settings, user_id, client = build(tmp_path)
    response = client.post(
        "/observations/obs-0/state",
        data={
            "action": "verify",
            "csrf_token": csrf_for(settings, user_id),
            "next": "https://evil.test/steal",
        },
        follow_redirects=False,
    )
    assert response.headers["location"] == "/documents/doc-1#observation-obs-0"


# --- corrections ------------------------------------------------------------


def test_naming_a_metric_moves_the_value_and_learns_the_printed_label(tmp_path: Path):
    settings, user_id, client = build(tmp_path)
    ldl = concept_id_for(settings, "LDL cholesterol")
    response = client.post(
        "/observations/obs-3",
        data={
            "raw_name": UNKNOWN_LABEL,
            "canonical_name": "ldl cholesterol",
            "value_numeric": "3.9",
            "unit_raw": "mmol/L",
            "csrf_token": csrf_for(settings, user_id),
            "next": "/review?state=open&document=doc-1",
        },
        follow_redirects=False,
    )
    assert response.headers["location"] == "/review?state=open&document=doc-1#observation-obs-3"
    with connect(settings) as connection:
        row = connection.execute(
            "SELECT concept_id, raw_name, verification_status FROM observations WHERE id='obs-3'"
        ).fetchone()
        assert row["concept_id"] == ldl
        assert row["verification_status"] == "corrected"
        # The label stays as printed. Renaming it to force a mapping is what
        # destroyed the provenance this row is for.
        assert row["raw_name"] == UNKNOWN_LABEL
        alias = connection.execute(
            "SELECT concept_id FROM concept_aliases WHERE normalized_alias=?",
            (normalized_key(UNKNOWN_LABEL),),
        ).fetchone()
        assert alias is not None and alias["concept_id"] == ldl
        # And that is the point of the alias: a re-import of the same report
        # resolves it without a second correction.
        vendor_id = connection.execute(
            "SELECT vendor_id FROM documents WHERE id='doc-1'"
        ).fetchone()[0]
        assert ensure_concept(connection, UNKNOWN_LABEL, vendor_id)[0] == ldl


def test_a_remap_never_rewrites_an_alias_another_account_resolves_through(tmp_path: Path):
    """`concept_aliases` is shared: no owner column, and vendors are global.

    So a correction may teach the table a label nothing has claimed, but it
    must never overwrite an existing row - that row is what somebody else's
    next import resolves through, and one person's remap would silently refile
    another person's results under a different analyte. The correction still
    lands on this observation; only the shared rule is left alone.
    """
    settings, user_id, client = build(tmp_path)
    creatinine = concept_id_for(settings, "Creatinine")
    ldl = concept_id_for(settings, "LDL cholesterol")
    with connect(settings) as connection:
        claimed = connection.execute(
            "SELECT concept_id FROM concept_aliases WHERE normalized_alias=?",
            (normalized_key("Creatinine"),),
        ).fetchone()
        assert claimed is not None and claimed["concept_id"] == creatinine

    response = client.post(
        "/observations/obs-2",
        data={
            "raw_name": "Creatinine",
            "canonical_name": "LDL cholesterol",
            "value_numeric": "91",
            "unit_raw": "µmol/L",
            "csrf_token": csrf_for(settings, user_id),
        },
    )
    assert response.status_code == 200
    with connect(settings) as connection:
        # The reviewer's own value went where they said.
        assert connection.execute(
            "SELECT concept_id FROM observations WHERE id='obs-2'"
        ).fetchone()["concept_id"] == ldl
        # The shared rule did not move: nothing claiming this printed label
        # points anywhere other than where it pointed before.
        rows = connection.execute(
            "SELECT concept_id FROM concept_aliases WHERE normalized_alias=?",
            (normalized_key("Creatinine"),),
        ).fetchall()
        assert {row["concept_id"] for row in rows} == {creatinine}


def test_correcting_a_set_aside_value_does_not_quietly_restore_it(tmp_path: Path):
    """Tidying the wording of something you rejected is not un-rejecting it.

    The correction form renders on set-aside rows too, and it used to write
    `verification_status='corrected'` unconditionally - so fixing a stray unit
    on parser debris put it back into every chart, panel and verdict with no
    signal that it had returned.
    """
    settings, user_id, client = build(tmp_path)
    token = csrf_for(settings, user_id)
    client.post("/observations/obs-2/state", data={"action": "reject", "csrf_token": token})
    client.post(
        "/observations/obs-2",
        data={
            "raw_name": "Creatinine",
            "value_numeric": "91",
            "unit_raw": "µmol/L",
            "csrf_token": token,
        },
    )
    with connect(settings) as connection:
        row = connection.execute(
            "SELECT verification_status, unit_raw FROM observations WHERE id='obs-2'"
        ).fetchone()
    assert row["unit_raw"] == "µmol/L", "the edit itself must still be saved"
    assert row["verification_status"] == "rejected"


def test_a_blank_or_unknown_metric_name_leaves_the_parser_in_charge(tmp_path: Path):
    settings, user_id, client = build(tmp_path)
    creatinine = concept_id_for(settings, "Creatinine")
    token = csrf_for(settings, user_id)
    for named in ("", "   ", "No Such Metric In The Catalogue"):
        client.post(
            "/observations/obs-2",
            data={
                "raw_name": "Creatinine",
                "canonical_name": named,
                "value_numeric": "91",
                "unit_raw": "µmol/L",
                "csrf_token": token,
            },
        )
        with connect(settings) as connection:
            assert connection.execute(
                "SELECT concept_id FROM observations WHERE id='obs-2'"
            ).fetchone()[0] == creatinine, named
            # A name nobody knows invents nothing: no concept is created for it.
            assert connection.execute(
                "SELECT COUNT(*) FROM concepts WHERE canonical_name=? COLLATE NOCASE",
                ("No Such Metric In The Catalogue",),
            ).fetchone()[0] == 0


# --- values the parser missed -----------------------------------------------


def test_a_value_the_parser_missed_is_entered_by_hand(tmp_path: Path):
    settings, user_id, client = build(tmp_path)
    add_report(settings, user_id, 1, 3)
    response = client.post(
        "/documents/doc-1/observations",
        data={
            "raw_name": "Тригліцериди",
            "canonical_name": "Triglycerides",
            "value_numeric": "1,84",
            "unit_raw": "mmol/L",
            "page_number": "2",
            "vendor_reference_text": "0 - 1.7",
            "observed_at": "2025-02-12",
            "evidence_text": "Тригліцериди 1,84 mmol/L",
            "csrf_token": csrf_for(settings, user_id),
            "next": "/review?state=open&document=doc-1",
        },
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert response.headers["location"].startswith(
        "/review?state=open&document=doc-1#observation-"
    )
    # A second value, printed on a page no report covers.
    client.post(
        "/documents/doc-1/observations",
        data={
            "raw_name": "Ferritin",
            "value_numeric": "44",
            "page_number": "5",
            "csrf_token": csrf_for(settings, user_id),
        },
    )
    with connect(settings) as connection:
        entered = {
            str(item["raw_name"]): item
            for item in connection.execute(
                "SELECT * FROM observations WHERE document_id='doc-1' AND extraction_method='human_entered'"
            )
        }
        row = entered["Тригліцериди"]
        assert row["verification_status"] == "corrected"
        assert row["value_numeric"] == 1.84
        assert row["page_number"] == 2
        assert row["observed_at"] == "2025-02-12"
        assert row["evidence_text"] == "Тригліцериди 1,84 mmol/L"
        # The page it was printed on decides which report it belongs to.
        assert row["report_id"] == "report-1"
        assert entered["Ferritin"]["report_id"] is None
        assert row["concept_id"] == concept_id_for(settings, "Triglycerides")
        assert audit_actions(settings, str(row["id"])) == ["observation_entered"]
    # From here it is a value like any other, and appears where it is reviewed.
    page = client.get("/documents/doc-1").text
    assert f'id="observation-{row["id"]}"' in page
    assert 'name="observed_at" type="date"' in page
    assert 'name="evidence_text"' in page


def test_an_entered_value_needs_a_name_and_a_value(tmp_path: Path):
    settings, user_id, client = build(tmp_path)
    token = csrf_for(settings, user_id)
    assert client.post(
        "/documents/doc-1/observations",
        data={"raw_name": "   ", "value_numeric": "5", "csrf_token": token},
    ).status_code == 400
    assert client.post(
        "/documents/doc-1/observations", data={"raw_name": "Ferritin", "csrf_token": token}
    ).status_code == 400
    not_a_number = client.post(
        "/documents/doc-1/observations",
        data={
            "raw_name": "Ferritin",
            "value_numeric": "about ten",
            "value_text": "low",
            "csrf_token": token,
        },
    )
    assert not_a_number.status_code == 400
    assert not_a_number.json()["detail"] == "Numeric value is not valid"
    with connect(settings) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM observations WHERE document_id='doc-1'"
        ).fetchone()[0] == 8


def test_the_page_number_is_clamped_to_the_document(tmp_path: Path):
    settings, user_id, client = build(tmp_path)
    token = csrf_for(settings, user_id)
    for sent in ("99", "0", "-3", "4"):
        client.post(
            "/documents/doc-1/observations",
            data={
                "raw_name": f"Missed {sent}",
                "value_text": "present",
                "page_number": sent,
                "csrf_token": token,
            },
        )
    with connect(settings) as connection:
        pages = {
            str(row["raw_name"]): int(row["page_number"])
            for row in connection.execute(
                "SELECT raw_name, page_number FROM observations WHERE extraction_method='human_entered'"
            )
        }
    # The fixture document has 5 pages; nothing may point outside it.
    assert pages == {"Missed 99": 5, "Missed 0": 1, "Missed -3": 1, "Missed 4": 4}


# --- closing and reopening a file -------------------------------------------


def decide_two_values(settings, user_id: str, client) -> None:
    """One corrected value and one set aside, both before the file is closed."""
    token = csrf_for(settings, user_id)
    client.post(
        "/observations/obs-0",
        data={
            "raw_name": "LDL cholesterol",
            "value_numeric": "4.5",
            "unit_raw": "mmol/L",
            "csrf_token": token,
        },
    )
    client.post("/observations/obs-1/state", data={"action": "reject", "csrf_token": token})
    assert statuses(settings)["obs-0"] == "corrected"
    assert statuses(settings)["obs-1"] == "rejected"


def test_verifying_a_file_never_overwrites_a_decision_already_made(tmp_path: Path):
    settings, user_id, client = build(tmp_path)
    decide_two_values(settings, user_id, client)

    response = client.post(
        "/review/task-1",
        data={"action": "verify", "csrf_token": csrf_for(settings, user_id)},
        follow_redirects=False,
    )
    assert response.status_code == 303

    state = statuses(settings)
    # Only the values nobody had ruled on move. A blanket update here silently
    # relabelled a reviewer's correction and un-set-aside their parser debris.
    assert state["obs-0"] == "corrected"
    assert state["obs-1"] == "rejected"
    assert [state[f"obs-{n}"] for n in range(2, 8)] == ["verified"] * 6

    with connect(settings) as connection:
        task = connection.execute(
            "SELECT state, resolution, resolved_at FROM review_tasks WHERE id='task-1'"
        ).fetchone()
    assert (task["state"], task["resolution"]) == ("resolved", "verify")
    assert task["resolved_at"]
    assert "review_verify" in audit_actions(settings, "doc-1")


def test_reopening_returns_only_what_verification_touched(tmp_path: Path):
    settings, user_id, client = build(tmp_path)
    token = csrf_for(settings, user_id)
    decide_two_values(settings, user_id, client)
    client.post("/review/task-1", data={"action": "verify", "csrf_token": token})

    client.post("/review/task-1", data={"action": "reopen", "csrf_token": token})
    state = statuses(settings)
    assert state["obs-0"] == "corrected"
    assert state["obs-1"] == "rejected"
    assert [state[f"obs-{n}"] for n in range(2, 8)] == ["extracted"] * 6

    with connect(settings) as connection:
        task = connection.execute(
            "SELECT state, resolution, resolved_at FROM review_tasks WHERE id='task-1'"
        ).fetchone()
    assert task["state"] == "open"
    assert task["resolution"] is None
    assert task["resolved_at"] is None
    assert 'action="/documents/doc-1/review"' in client.get("/documents/doc-1").text


def test_an_unknown_review_action_is_refused(tmp_path: Path):
    settings, user_id, client = build(tmp_path)
    response = client.post(
        "/review/task-1",
        data={"action": "archive", "csrf_token": csrf_for(settings, user_id)},
    )
    assert response.status_code == 400
    with connect(settings) as connection:
        assert connection.execute(
            "SELECT state FROM review_tasks WHERE id='task-1'"
        ).fetchone()[0] == "open"
    assert statuses(settings)["obs-0"] == "extracted"


# --- the consequence of setting a value aside -------------------------------


def test_a_value_set_aside_leaves_the_rest_of_the_application(tmp_path: Path):
    settings, user_id, client = build(tmp_path)
    creatinine = concept_id_for(settings, "Creatinine")

    assert len(client.get(f"/api/metrics/{creatinine}").json()) == 1
    assert "creatinine" in catalog_for(settings, user_id)
    assert results_count(client) == 8

    client.post(
        "/observations/obs-2/state",
        data={"action": "reject", "csrf_token": csrf_for(settings, user_id)},
    )

    # Not a measurement any more: no point on the series, no card, not counted
    # among the document's results.
    assert client.get(f"/api/metrics/{creatinine}").json() == []
    assert "creatinine" not in catalog_for(settings, user_id)
    assert results_count(client) == 7

    # But not deleted either: the row keeps its evidence, stays on the review
    # pane, and offers the way back.
    body = client.get("/documents/doc-1").text
    assert 'id="observation-obs-2"' in body
    assert 'data-verification="rejected"' in body
    assert 'value="restore"' in body
    with connect(settings) as connection:
        row = connection.execute(
            "SELECT verification_status, evidence_text FROM observations WHERE id='obs-2'"
        ).fetchone()
    assert row["verification_status"] == "rejected"
    assert row["evidence_text"] == "Creatinine evidence"
