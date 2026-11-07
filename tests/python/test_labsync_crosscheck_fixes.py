"""Lab connections after the 2026-11-06 sandbox audit: the lab&#39;s own flag in
the verdict, units adopted only when they are units, the reference interval
and lab-flag buckets, review tasks for what the reading lacks, the order
linked to the document holding its results, long part-done orders, and the
profile card updating itself in place.

Same synthetic fixtures and HTTP stub as ``test_labsync`` — no real lab is
ever called.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from anamna import labsync
from anamna.db import connect, utc_now
from anamna.ingest.pipeline import repair_observation_semantics
from anamna.labsync import common
from anamna.reference import evaluate
from anamna.security import create_access_token

from test_labsync import (
    PHONE, TOKEN, connect_eskulab, csrf, es_row, eskulab_routes, family_member, make, obs, order, router, row,
    seed_doc, stub_intake,
)


def lab_row(test, result, units="", state="normal", norm="{NULL}", resulttype="digital"):
    return {**es_row(test, result, units, resulttype=resulttype), "state": state, "norm": norm}


def set_reference(settings, observation_id, text, low, high, reading="within_vendor_range"):
    with connect(settings) as connection:
        connection.execute(
            """UPDATE observations SET vendor_reference_text=?, vendor_reference_low=?, vendor_reference_high=?,
                   vendor_interpretation=? WHERE id=?""", (text, low, high, reading, observation_id))


def observation(settings, observation_id):
    with connect(settings) as connection:
        return dict(connection.execute("SELECT * FROM observations WHERE id=?", (observation_id,)).fetchone())


def audit_count(settings, action):
    with connect(settings) as connection:
        return connection.execute("SELECT COUNT(*) FROM audit_events WHERE action=?", (action,)).fetchone()[0]


# --- DOCA-10 / DOCC-21: the lab&#39;s flag reaches the verdict -------------------------


def test_a_lab_flag_reaches_the_verdict_survives_a_restart_and_follows_an_amendment(tmp_path: Path, monkeypatch):
    settings, user_id, client = make(tmp_path)
    document_id = seed_doc(settings, user_id, vendor="EskuLab", order="9700", day="2026-01-10", values=[
        ("рН (C-PH)", 5.5, None, "within_vendor_range"), ("Еозинофіли", 1.0, "%", "within_vendor_range"),
        ("Гемоглобін (HGB)", 151.0, "г/л", "within_vendor_range")])
    ph, eos, hgb = (f"{document_id}-{index}" for index in range(3))
    set_reference(settings, ph, "5.5 - 7.0", 5.5, 7.0)
    set_reference(settings, eos, "1-5", 1.0, 5.0)
    set_reference(settings, hgb, "130-170", 130.0, 170.0)
    rows = {"9700": [lab_row("рН (C-PH)", "5.5", state="critical", norm="{5.5-7.0#%}"),
                     lab_row("Еозинофіли", "1", "%", state="critical"),
                     lab_row("Гемоглобін (HGB)", "151", "г/л", norm="{130-170#%}")]}
    routes = eskulab_routes([order(9700, ready=3, total=3)], rows)
    connect_eskulab(settings, user_id, monkeypatch, routes)
    stub_intake(monkeypatch, settings, user_id, {})
    labsync.sync(settings, user_id, "eskulab", inline=True)

    # At the lower edge of both intervals: below range, from the lab&#39;s record.
    assert (observation(settings, ph)["vendor_interpretation"], observation(settings, ph)["vendor_interpretation_source"]) \
        == ("low", "lab_record")
    assert observation(settings, eos)["vendor_interpretation"] == "low"
    assert observation(settings, hgb)["vendor_interpretation_source"] is None  # the lab agrees: untouched
    assert audit_count(settings, "observation_flag_from_lab") == 2
    with connect(settings) as connection:
        stored = observation(settings, ph)
        verdict = evaluate(connection, stored["concept_id"], 5.5, None, None, vendor_low=5.5, vendor_high=7.0,
                           vendor_interpretation=stored["vendor_interpretation"])
        assert verdict["interpretation"] != "normal" and verdict["authority"] == "vendor"
        # The start-up repair re-derives readings from the printed bounds; it
        # must not paint the lab&#39;s flag green again.
        repair_observation_semantics(connection)
    assert observation(settings, ph)["vendor_interpretation"] == "low"

    page = client.get(f"/documents/{document_id}").text
    assert "The verdict now follows the lab&#39;s flag" in page and "Values the lab flags differently (2)" in page

    labsync.sync(settings, user_id, "eskulab", inline=True)
    assert audit_count(settings, "observation_flag_from_lab") == 2  # idempotent

    # The lab amends pH to normal: our reading goes back to the printed range.
    rows["9700"][0]["state"] = "normal"
    monkeypatch.setattr(common, "_http", router(eskulab_routes([order(9700, ready=3, total=3)], rows)))
    labsync.sync(settings, user_id, "eskulab", inline=True)
    assert (observation(settings, ph)["vendor_interpretation"], observation(settings, ph)["vendor_interpretation_source"]) \
        == ("within_vendor_range", None)
    assert audit_count(settings, "observation_flag_from_lab_undone") == 1


def test_the_flag_direction_comes_from_the_band_that_fits_the_person(tmp_path: Path, monkeypatch):
    settings, user_id, _ = make(tmp_path)  # born 1990: an adult
    document_id = seed_doc(settings, user_id, vendor="EskuLab", order="9701", day="2026-01-10", values=[
        ("Лімфоцити (Lymph)", 43.0, "%", None)])
    set_reference(settings, f"{document_id}-0",
                  "До 1р.: 38-74 1-6р.: 26-60 6-12р.: 24-54 12-16р.: 22-50 Дорослі: 20-40", None, None, None)
    rows = {"9701": [lab_row("Лімфоцити (Lymph)", "43", "%", state="critical")]}
    connect_eskulab(settings, user_id, monkeypatch, eskulab_routes([order(9701, ready=1, total=1)], rows))
    stub_intake(monkeypatch, settings, user_id, {})
    labsync.sync(settings, user_id, "eskulab", inline=True)
    assert observation(settings, f"{document_id}-0")["vendor_interpretation"] == "high"


def test_a_flag_whose_direction_no_interval_shows_is_indeterminate_not_green():
    result = labsync.cross_check([row("Слиз", "+", state="critical", resulttype="string")],
                                 [{**obs("Слиз", "+", interp=None)}])
    item = result["items"][0]
    assert item["cls"] == "match" and item["flag"] == "lab_out_ours_in" and item["lab_reading"] == "borderline"


# --- OPS-37: a lab&#39;s unit only where it is a unit of that measurement ---------------


def test_units_are_adopted_only_when_real_and_the_repair_takes_wrong_ones_back(tmp_path: Path, monkeypatch):
    settings, user_id, _ = make(tmp_path)
    document_id = seed_doc(settings, user_id, vendor="EskuLab", order="9710", day="2026-01-10", values=[
        ("АЛАТ(АЛТ)", 37.0, None, None), ("Питома вага", 1.035, None, None)])
    alt, gravity = f"{document_id}-0", f"{document_id}-1"
    with connect(settings) as connection:
        preferred = dict(connection.execute(
            "SELECT o.id, c.preferred_unit FROM observations o JOIN concepts c ON c.id=o.concept_id "
            "WHERE o.document_id=?", (document_id,)).fetchall())
    assert preferred[alt] == "U/L" and not preferred[gravity]  # specific gravity is dimensionless
    rows = {"9710": [lab_row("АЛАТ(АЛТ)", "37", "од/л"), lab_row("Питома вага", "1.035", "г/мл")]}
    connect_eskulab(settings, user_id, monkeypatch, eskulab_routes([order(9710, ready=2, total=2)], rows))
    stub_intake(monkeypatch, settings, user_id, {})
    labsync.sync(settings, user_id, "eskulab", inline=True)
    assert observation(settings, alt)["unit_raw"] == "од/л"
    assert observation(settings, gravity)["unit_raw"] is None
    assert audit_count(settings, "observation_unit_from_lab") == 1

    # What the sync wrote before this fix: «г/мл» on the specific gravity.
    with connect(settings) as connection:
        connection.execute("UPDATE observations SET unit_raw='г/мл', unit_canonical='г/мл' WHERE id=?", (gravity,))
        connection.execute(
            """INSERT INTO audit_events(owner_user_id, actor_user_id, action, entity_type, entity_id, details_json,
                   created_at) VALUES (?, ?, 'observation_unit_from_lab', 'observation', ?, ?, ?)""",
            (user_id, user_id, gravity, json.dumps({"unit": "г/мл"}), utc_now()))
    first = labsync.recheck(settings)
    assert first["units_undone"] == 1
    assert (observation(settings, gravity)["unit_raw"], observation(settings, alt)["unit_raw"]) == (None, "од/л")
    assert labsync.recheck(settings)["units_undone"] == 0  # idempotent
    assert audit_count(settings, "observation_unit_from_lab_undone") == 1


# --- DOCB-20 / OPS-18: reference intervals and the "differ" count -------------------


def test_the_cross_check_compares_reference_intervals():
    iron = {**obs("Залізо", 20.1, "мкмоль/л"), "vendor_reference_low": 9.0, "vendor_reference_high": 30.4,
            "vendor_reference_text": "9 - 30.4"}
    same = {**obs("Глюкоза", 5.1, "ммоль/л"), "vendor_reference_low": 3.9, "vendor_reference_high": 6.1}
    open_low = {**obs("Тригліцериди", 2.26, "ммоль/л"), "vendor_reference_low": None, "vendor_reference_high": 1.7}
    lab = [{**row("Залізо", "20.1", "мкмоль/л"), "norm": ["Від 11.6 до 31.3"]},
           {**row("Глюкоза", "5.1", "ммоль/л"), "norm": ["3.9-6.1"]},
           {**row("Тригліцериди", "2.26", "ммоль/л"), "norm": ["Від 0 до 1.7"]}]
    result = labsync.cross_check(lab, [iron, same, open_low])
    by_name = {item["lab"]["test"]: item for item in result["items"]}
    assert by_name["Залізо"]["cls"] == "match" and by_name["Залізо"]["reference_differs"]
    assert not by_name["Глюкоза"]["reference_differs"]
    assert not by_name["Тригліцериди"]["reference_differs"]  # «від 0 до 1.7» is «до 1,7»
    assert result["counts"]["reference_differs"] == 1


def test_the_profile_counts_only_values_and_units_as_differing(tmp_path: Path, monkeypatch):
    settings, user_id, client = make(tmp_path)
    seed_doc(settings, user_id, vendor="EskuLab", order="9720", day="2026-01-10", values=[
        ("Ліпопротеїди високої щільності (ЛПВЩ", 1.33, "ммоль/л", None), ("Глюкоза", 5.1, "ммоль/л", None)])
    rows = {"9720": [lab_row("Ліпопротеїди високої щільності (ЛПВЩ, HDL)", "1.33", "ммоль/л"),
                     lab_row("Глюкоза", "5.1", "ммоль/л")], "9721": []}
    orders = [order(9720, ready=2, total=2), order(9721, ready=0, total=0, status="DONE"),
              {**order(9722, ready=0, total=0), "dt": None}]
    connect_eskulab(settings, user_id, monkeypatch, eskulab_routes(orders, rows))
    stub_intake(monkeypatch, settings, user_id, {})
    labsync.sync(settings, user_id, "eskulab", inline=True)
    card = labsync.profile_cards(settings, {"id": user_id})[0]
    assert card["orders"][0]["ordered_at"] is None  # an undated order is not buried at the end
    page = client.get("/profile?tab=connections").text
    assert "1 match · 0 differ · 0 missing · 0 extra" in page and "names cut short: 1" in page


# --- OPS-19: a review task for what the reading lacks -------------------------------


def _with_reason_columns(settings):
    """What F2's migration 037 adds; this branch creates the task either way."""
    with connect(settings) as connection:
        columns = {r[1] for r in connection.execute("PRAGMA table_info(review_tasks)")}
        for name in ("reason_key", "reason_params_json"):
            if name not in columns:
                connection.execute(f"ALTER TABLE review_tasks ADD COLUMN {name} TEXT")


def _tasks(settings, document_id):
    with connect(settings) as connection:
        return [dict(r) for r in connection.execute(
            "SELECT * FROM review_tasks WHERE entity_type='document' AND entity_id=? ORDER BY created_at",
            (document_id,))]


def test_rows_the_reading_lacks_open_one_review_task_that_follows_the_check(tmp_path: Path, monkeypatch):
    settings, user_id, _ = make(tmp_path)
    _with_reason_columns(settings)
    document_id = seed_doc(settings, user_id, vendor="EskuLab", order="9730", day="2026-01-10", values=[
        ("Креатинін", 68.3, "мкмоль/л", None)])
    rows = {"9730": [lab_row("Креатинін", "68.3", "мкмоль/л"), lab_row("Сечова кислота", "361", "мкмоль/л"),
                     lab_row("Сечовина", "5.5", "ммоль/л")]}
    connect_eskulab(settings, user_id, monkeypatch, eskulab_routes([order(9730, ready=3, total=3)], rows))
    stub_intake(monkeypatch, settings, user_id, {})
    labsync.sync(settings, user_id, "eskulab", inline=True)
    tasks = _tasks(settings, document_id)
    assert len(tasks) == 1 and tasks[0]["state"] == "open" and tasks[0]["reason_key"] == "labsync.review_missing"
    params = json.loads(tasks[0]["reason_params_json"])
    assert params == {"count": 2, "lab": "EskuLab", "order": "9730", "names": "Сечова кислота; Сечовина"}
    assert "2 result(s)" in tasks[0]["reason"]
    labsync.sync(settings, user_id, "eskulab", inline=True)
    assert len(_tasks(settings, document_id)) == 1  # the same task, not a second one

    # Both added by hand (as the cross-check offers): the task closes itself.
    with connect(settings) as connection:
        for index, (name, value, unit) in enumerate((("Сечова кислота", 361.0, "мкмоль/л"),
                                                     ("Сечовина", 5.5, "ммоль/л")), start=5):
            connection.execute(
                """INSERT INTO observations(id, owner_user_id, patient_id, document_id, page_number, concept_id,
                       raw_name, value_type, value_numeric, unit_raw, verification_status, extraction_method,
                       confidence, evidence_text, parser_version, created_at)
                   SELECT ?, owner_user_id, patient_id, document_id, 1, concept_id, ?, 'numeric', ?, ?, 'extracted',
                          'human_entered', 1, '', 'test', ? FROM observations WHERE id=?""",
                (f"{document_id}-{index}", name, value, unit, utc_now(), f"{document_id}-0"))
    assert labsync.recheck(settings)["tasks"] == 1
    assert [t["state"] for t in _tasks(settings, document_id)] == ["resolved"]
    assert labsync.recheck(settings)["tasks"] == 0


def test_the_review_task_works_before_the_reason_columns_exist(tmp_path: Path, monkeypatch):
    settings, user_id, _ = make(tmp_path)
    with connect(settings) as connection:
        if "reason_key" in {r[1] for r in connection.execute("PRAGMA table_info(review_tasks)")}:
            return  # merged with F2: covered above
    document_id = seed_doc(settings, user_id, vendor="EskuLab", order="9731", day="2026-01-10", values=[])
    rows = {"9731": [lab_row("Сечовина", "5.5", "ммоль/л")]}
    connect_eskulab(settings, user_id, monkeypatch, eskulab_routes([order(9731, ready=1, total=1)], rows))
    stub_intake(monkeypatch, settings, user_id, {})
    labsync.sync(settings, user_id, "eskulab", inline=True)
    labsync.sync(settings, user_id, "eskulab", inline=True)
    tasks = _tasks(settings, document_id)
    assert len(tasks) == 1 and tasks[0]["reason"].startswith("The EskuLab record of order 9731 has 1 result(s)")


# --- DOCC-15: the order links to the document that holds its results ---------------


def test_an_order_printed_on_a_cover_sheet_links_to_the_document_with_its_results(tmp_path: Path, monkeypatch):
    settings, user_id, _ = make(tmp_path)
    cover = seed_doc(settings, user_id, vendor="EskuLab", order="9000123", day="2025-08-28", values=[])
    panel = seed_doc(settings, user_id, vendor="EskuLab", order=None, day="2025-08-31", values=[
        ("Bet v 1", 0.1, "kUA/L", None), ("Phl p 1", 0.1, "kUA/L", None)])
    with connect(settings) as connection:
        connection.execute("UPDATE documents SET original_filename=? WHERE id=?",
                           ("2025-08-31__eskulab__alex2-allergy-panel__9000123.pdf", panel))
    rows = {"9000123": [lab_row("ALEX2-тест", "Ваш результат готовий і знаходиться в додатковому pdf файлі.",
                                resulttype="info")]}
    connect_eskulab(settings, user_id, monkeypatch,
                    eskulab_routes([order(9000123, ready=1, total=1, dt="2025-08-28 08:38")], rows))
    stub_intake(monkeypatch, settings, user_id, {})
    labsync.sync(settings, user_id, "eskulab", inline=True)
    with connect(settings) as connection:
        tracked = connection.execute("SELECT document_id, crosscheck_json FROM lab_orders").fetchone()
    assert tracked["document_id"] == panel
    counts = json.loads(tracked["crosscheck_json"])["counts"]
    assert counts["extra"] == 0 and counts["info"] == 3  # the placeholder row and the two values it points to

    # An order linked to the cover before this fix is re-pointed by the repair.
    with connect(settings) as connection:
        connection.execute("UPDATE lab_orders SET document_id=?", (cover,))
    assert labsync.recheck(settings)["relinked"] == 1
    assert labsync.recheck(settings)["relinked"] == 0
    with connect(settings) as connection:
        assert connection.execute("SELECT document_id FROM lab_orders").fetchone()[0] == panel
        assert connection.execute(
            "SELECT COUNT(*) FROM audit_events WHERE action='labsync_order_relinked'").fetchone()[0] == 1


# --- OPS-21: an order the lab never finishes ----------------------------------------


def test_a_long_unfinished_order_imports_what_is_ready_and_says_so(tmp_path: Path, monkeypatch):
    settings, user_id, client = make(tmp_path)
    orders = [order(9750, ready=9, total=40, status="PARTLY_DONE", dt="2022-03-01 08:00"),
              order(9751, ready=1, total=2, status="PARTLY_DONE", dt="2022-03-02 08:00")]
    rows = {"9750": [lab_row("Глюкоза", "5.1", "ммоль/л")], "9751": [lab_row("Сечовина", "5.5", "ммоль/л")]}
    routes = eskulab_routes(orders, rows)
    routes[("GET", "/api/results/getResults/111/9751")] = 500  # no report for the ready part
    connect_eskulab(settings, user_id, monkeypatch, routes)
    calls = stub_intake(monkeypatch, settings, user_id, {
        "eskulab-9750.pdf": {"vendor": "EskuLab", "order": "9750", "day": "2022-03-01",
                             "values": [("Глюкоза", 5.1, "ммоль/л", None)]}})
    summary = labsync.sync(settings, user_id, "eskulab", inline=True)
    assert calls == ["eskulab-9750.pdf"] and summary["imported"] == 1 and summary["pending"] == 1
    with connect(settings) as connection:
        states = {r[0]: (r[1], r[2]) for r in connection.execute("SELECT order_id, state, error_key FROM lab_orders")}
    assert states == {"9750": ("imported", "labsync.partial_imported"), "9751": ("pending", "labsync.partial_no_pdf")}
    page = client.get("/profile?tab=connections").text
    assert "so the results that are ready were imported" in page
    assert "offers no report file for the finished part yet" in page


# --- OPS-20: a profile without date of birth or sex ---------------------------------


def test_a_family_profile_without_birthday_says_it_cannot_be_compared(tmp_path: Path, monkeypatch):
    settings, holder, client = make(tmp_path)
    member = family_member(settings, holder, "member@example.test")
    with connect(settings) as connection:
        connection.execute("UPDATE patients SET date_of_birth=NULL, sex_at_birth=NULL WHERE owner_user_id=?",
                           (member,))
    monkeypatch.setattr(common, "_http", router(eskulab_routes([], {})))
    labsync.save_credentials(settings, holder, "eskulab", {"token": TOKEN, "phone": PHONE})
    labsync.check_account(settings, holder, "eskulab")
    page = client.get("/profile?tab=connections").text
    assert re.search(r"member\s+-\s+cannot be compared \(date of birth or sex missing", page)
    client.cookies.set("anamna_lang", "uk")
    assert "неможливо порівняти" in client.get("/profile?tab=connections").text


# --- PERF-06 / UX-21: the card updates itself in place ------------------------------


def test_a_running_sync_updates_the_card_in_place_from_a_status_endpoint(tmp_path: Path, monkeypatch):
    settings, user_id, client = make(tmp_path)
    monkeypatch.setattr(common, "_http", router(eskulab_routes([], {})))
    labsync.save_credentials(settings, user_id, "eskulab", {"token": TOKEN, "phone": PHONE})
    labsync.check_account(settings, user_id, "eskulab")
    labsync.link_person(settings, user_id, "eskulab", "111", "self", confirmed=False)
    with connect(settings) as connection:
        connection.execute("UPDATE lab_accounts SET sync_state='running', sync_started_at=? WHERE user_id=?",
                           (utc_now(), user_id))
    page = client.get("/profile?tab=connections").text
    card = page[page.index('id="lab-eskulab"'):]
    assert "location.replace" not in card and "/api/lab-sync/eskulab/status" in card
    assert "visibilityState" in card and 'data-lab-live="status"' in card
    assert ">\n      Connected\n" in card or "Connected" in card[:1500]  # the one word for connected
    running = client.get("/api/lab-sync/eskulab/status").json()
    # The card comes back on every poll, so documents appear as they arrive.
    assert (running["state"], running["finished_at"]) == ("running", None)
    assert 'data-lab-live="status"' in running["html"] and "Syncing" in running["html"]
    with connect(settings) as connection:
        connection.execute("UPDATE lab_accounts SET sync_summary_json=? WHERE user_id=?",
                           (json.dumps({"orders": 3, "total": 7, "current": "Загальний аналіз крові"}), user_id))
    progress = client.get("/api/lab-sync/eskulab/status").json()["html"]
    assert "Fetching 3 of 7" in progress and "Загальний аналіз крові" in progress
    with connect(settings) as connection:
        connection.execute("UPDATE lab_accounts SET sync_state='done', sync_finished_at=?, sync_summary_json=? "
                           "WHERE user_id=?", (utc_now(), json.dumps({
                               "imported": 1, "linked": 0, "already": 0, "pending": 0, "unavailable": 0,
                               "failed": 0, "awaiting": 0}), user_id))
    done = client.get("/api/lab-sync/eskulab/status").json()
    assert done["state"] == "done" and 'data-lab-live="status"' in done["html"] and "Imported: 1" in done["html"]
    assert client.get("/api/lab-sync/nolab/status").status_code == 404
    _, secret = create_access_token(settings, user_id, "api", "Integration")
    assert client.get("/api/lab-sync/eskulab/status",
                      headers={"Authorization": f"Bearer {secret}"}).status_code == 404


def test_the_admin_recheck_needs_an_administrator_and_reports_what_changed(tmp_path: Path):
    settings, user_id, client = make(tmp_path)
    assert client.post("/admin/lab-connections/recheck", data={}).status_code == 403
    done = client.post("/admin/lab-connections/recheck", data={"csrf_token": csrf(settings, user_id)},
                       follow_redirects=False)
    assert done.status_code == 303 and "done=rechecked" in done.headers["location"]
    page = client.get(done.headers["location"]).text
    assert "Re-checked 0 orders" in page
    client.cookies.set("anamna_lang", "uk")
    assert "Перевірено замовлень: 0" in client.get(done.headers["location"]).text


def test_an_adopted_flag_is_read_again_once_the_profile_says_who_the_person_is(tmp_path: Path, monkeypatch):
    """Adopted while the profile had no sex: between a woman's and a man's band
    the direction is unknown.  Filling in the profile must not leave it so."""
    settings, user_id, _ = make(tmp_path)
    document_id = seed_doc(settings, user_id, vendor="EskuLab", order="9702", day="2026-01-10", values=[
        ("Гемоглобін (HGB)", 118.0, "г/л", None)])
    obs_id = f"{document_id}-0"
    set_reference(settings, obs_id, "Жінки: 120-140 Чоловіки: 130-160", None, None, None)
    rows = {"9702": [lab_row("Гемоглобін (HGB)", "118", "г/л", state="critical")]}
    connect_eskulab(settings, user_id, monkeypatch, eskulab_routes([order(9702, ready=1, total=1)], rows))
    stub_intake(monkeypatch, settings, user_id, {})
    with connect(settings) as connection:
        connection.execute("UPDATE patients SET sex_at_birth=NULL WHERE owner_user_id=?", (user_id,))
    labsync.sync(settings, user_id, "eskulab", inline=True)
    before = observation(settings, obs_id)["vendor_interpretation"]
    with connect(settings) as connection:
        connection.execute("UPDATE patients SET sex_at_birth='female' WHERE owner_user_id=?", (user_id,))
    labsync.recheck(settings)
    after = observation(settings, obs_id)
    assert before != "low" and (after["vendor_interpretation"], after["vendor_interpretation_source"]) == ("low", "lab_record")
