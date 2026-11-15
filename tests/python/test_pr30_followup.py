"""What the review of the metric-connections change left open, each held by a test.

Two results of one analyte on one day stay two results, and the change
sentence names the one it did not compare with.  The edit form of a calculated
row offers the formula, never the machine record.  A write recalculates the
record of the account that made it, and an administrator's write every record.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from anamna import derived
from anamna.i18n import MESSAGES, activate_locale, reset_locale
from anamna.web import app as web
from anamna.web.app import templates

from test_linked_metrics import _build, _document, _observation
from test_pr30_review_app import _card, _unit
from test_pr30_review_ui import LAB_EVIDENCE, UUID


@pytest.fixture(params=["en", "uk"])
def lang(request):
    token = activate_locale(request.param)
    yield request.param
    reset_locale(token)


def test_two_documents_on_one_day_are_two_results_and_the_change_names_the_other(tmp_path: Path, lang):
    settings, user_id, _client = _build(tmp_path)
    unit = _unit(settings, "hemoglobin")
    for index, (day, value) in enumerate([("2026-08-04", 152.0), ("2025-08-28", 146.0), ("2025-08-28", 141.0)]):
        _document(settings, user_id, f"doc-{index}", "Synevo", "laboratory", day)
        _observation(settings, user_id, f"hgb-{index}", f"doc-{index}", "hemoglobin", value, unit, day)
    card = _card(settings, user_id, "hemoglobin")
    assert sorted(point["value"] for point in card["series"]) == [141.0, 146.0, 152.0]
    since = card["trend"]["since_text"]
    stem = MESSAGES["panel.delta_since_also"][lang].split("{date}")[0]
    assert since.startswith(stem)
    # The delta is against one of the two; the sentence carries the other.
    compared = 152.0 - float(card["trend"]["delta_text"].split()[0].replace(",", "."))
    other = ({141.0, 146.0} - {compared}).pop()
    assert f"{other:.0f}" in since


def test_one_result_on_the_previous_day_keeps_the_plain_sentence(tmp_path: Path, lang):
    settings, user_id, _client = _build(tmp_path)
    unit = _unit(settings, "hemoglobin")
    for index, (day, value) in enumerate([("2026-08-04", 152.0), ("2025-08-28", 146.0)]):
        _document(settings, user_id, f"doc-{index}", "Synevo", "laboratory", day)
        _observation(settings, user_id, f"hgb-{index}", f"doc-{index}", "hemoglobin", value, unit, day)
    since = _card(settings, user_id, "hemoglobin")["trend"]["since_text"]
    assert "(" not in since


def test_the_edit_form_of_a_calculated_row_offers_the_formula_only(lang):
    macro = getattr(templates.env.get_template("_components.html").module, "observation_row")
    html = str(macro({
        "id": "row", "concept_id": "c", "canonical_name": "Hemoglobin", "raw_name": "Hemoglobin",
        "verification_status": "extracted", "extraction_method": "derived_mch", "evidence_text": LAB_EVIDENCE,
        "page_number": 1, "display_value": "30", "unit_text": "pg", "value_numeric": 30,
    }))
    assert UUID not in html and "input_id" not in html and "unit_canonical" not in html


@pytest.mark.parametrize(("path", "scoped"), [("/profile", True), ("/admin/throttles/release", False)])
def test_a_write_recalculates_the_writer_s_record_and_an_admin_write_every_record(tmp_path: Path, monkeypatch, path, scoped):
    settings, user_id, client = _build(tmp_path)
    seen = []

    def refresh(connection, *, owner_user_id=None):
        seen.append(owner_user_id)
        return {"added": 0, "updated": 0, "removed": 0}

    monkeypatch.setattr(web, "refresh_derived_observations", refresh)
    response = client.post(path, data={"csrf_token": web_csrf(settings, client)}, follow_redirects=False)
    assert response.status_code == 303
    assert seen == [user_id if scoped else None]


def web_csrf(settings, client) -> str:
    from test_round3_mutation_paths import csrf_for

    return csrf_for(settings, client)


def test_an_owner_scope_leaves_another_account_s_calculations_alone(tmp_path: Path):
    settings, user_id, _client = _build(tmp_path)
    from anamna.db import connect

    with connect(settings) as connection:
        whole = derived.refresh_derived_observations(connection)
        scoped = derived.refresh_derived_observations(connection, owner_user_id="nobody")
    assert set(whole) == set(scoped) == {"added", "updated", "removed"}
    assert not any(scoped.values())


def test_an_export_that_holds_only_an_event_is_not_treated_as_superseded(tmp_path: Path):
    """Re-reading under a rule skips an export that owns no rows; one that
    owns only a recording (an ECG event) owns something and must be re-read."""
    from anamna.db import connect, utc_now
    from anamna.devices.reaggregate import reimport_files

    settings, user_id, _client = _build(tmp_path)
    with connect(settings) as connection:
        patient = connection.execute("SELECT id FROM patients WHERE owner_user_id=?", (user_id,)).fetchone()[0]
        vendor = connection.execute("SELECT id FROM vendors LIMIT 1").fetchone()
        vendor_id = vendor[0] if vendor else connection.execute(
            "INSERT INTO vendors(id, name, created_at) VALUES ('v-ecg', 'Synthetic ECG', ?) RETURNING id", (utc_now(),)
        ).fetchone()[0]
        connection.execute(
            """INSERT INTO device_imports(id, owner_user_id, patient_id, vendor_id, adapter_key, source_path,
                   source_fingerprint, source_bytes, raw_record_count, status, metadata_json, imported_at)
               VALUES ('imp-ecg', ?, ?, ?, 'kardia', 'uploads/gone.pdf', 'fp', 1, 1, 'imported', '{}', ?)""",
            (user_id, patient, vendor_id, utc_now()),
        )
        connection.execute(
            """INSERT INTO device_events(id, owner_user_id, patient_id, import_id, source_name, source_vendor,
                   event_type, started_at, created_at)
               VALUES ('ev-1', ?, ?, 'imp-ecg', 'Synthetic ECG', 'Kardia', 'ecg', '2025-01-01T08:00:00Z', ?)""",
            (user_id, patient, utc_now()),
        )
    statuses = [item["status"] for item in reimport_files(settings, user_id, adapters={"kardia"})]
    assert statuses == ["skipped_source_missing"]
