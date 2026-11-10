"""Second audit round, three small gaps: an account's device-export files go
with the account, the record search does its per-query work once per query,
and a chat message sent without script while an answer is still being written
says why it was not sent.
"""

from __future__ import annotations

import html
import json
from pathlib import Path

import pytest

from anamna.config import Settings
from anamna.db import connect, migrate, utc_now
from anamna.ingest.pipeline import ensure_vendor, seed_concepts
from anamna.reference import LIBRARY_PATH, evaluate, seed_reference_library
from anamna.security import create_user
from anamna.web import app as web
from anamna.web import chat_routes, search
from test_web_panels import build
from test_web_profile import csrf_for
from test_web_security import PASSWORD, seed_patient, settings_for


# --- Task 1: account deletion removes device-export files ----------------------------


def _account_with_device_import(settings, email: str, source_path: str, fingerprint: str) -> str:
    user_id = create_user(settings, email, email.split("@")[0].title(), PASSWORD)
    patient_id = seed_patient(settings, user_id, email)
    with connect(settings) as connection:
        vendor_id = ensure_vendor(connection, "Test Device", None)
        connection.execute(
            """INSERT INTO device_imports(
                   id, owner_user_id, patient_id, vendor_id, adapter_key, source_path,
                   source_fingerprint, source_bytes, raw_record_count, status, metadata_json, imported_at)
               VALUES (?, ?, ?, ?, 'test_export', ?, ?, 0, 0, 'complete', '{}', ?)""",
            (f"import-{fingerprint}", user_id, patient_id, vendor_id, source_path, fingerprint, utc_now()),
        )
    return user_id


def _delete(settings, user_id: str) -> None:
    with connect(settings) as connection:
        web._delete_account(settings, connection, user_id)


def _exists_user(settings, user_id: str) -> bool:
    with connect(settings) as connection:
        return connection.execute("SELECT 1 FROM users WHERE id=?", (user_id,)).fetchone() is not None


def _export_folder(settings) -> Path:
    folder = settings.source_dir / "uploads" / "2026-01" / "export-x"
    folder.mkdir(parents=True)
    (folder / "export.xml").write_text("<HealthData/>", encoding="utf-8")
    return folder


def test_deleting_an_account_removes_the_device_export_folder_it_unpacked(tmp_path: Path):
    settings = settings_for(tmp_path)
    migrate(settings)
    folder = _export_folder(settings)
    alpha = _account_with_device_import(settings, "alpha@example.test", str(folder), "fp-a")
    _delete(settings, alpha)
    assert not _exists_user(settings, alpha)
    assert not folder.exists()


def test_a_device_export_folder_another_account_still_uses_stays(tmp_path: Path):
    settings = settings_for(tmp_path)
    migrate(settings)
    folder = _export_folder(settings)
    alpha = _account_with_device_import(settings, "alpha@example.test", str(folder), "fp-a")
    _account_with_device_import(settings, "beta@example.test", str(folder), "fp-b")
    _delete(settings, alpha)
    assert not _exists_user(settings, alpha)
    assert (folder / "export.xml").is_file()


def test_a_folder_an_operator_placed_in_sources_by_hand_stays(tmp_path: Path):
    settings = settings_for(tmp_path)
    migrate(settings)
    folder = settings.source_dir / "manual-export" / "folder"
    folder.mkdir(parents=True)
    (folder / "export.xml").write_text("<HealthData/>", encoding="utf-8")
    alpha = _account_with_device_import(settings, "alpha@example.test", str(folder), "fp-a")
    _delete(settings, alpha)
    assert not _exists_user(settings, alpha)
    assert (folder / "export.xml").is_file()


def test_a_single_device_export_file_under_sources_is_removed(tmp_path: Path):
    settings = settings_for(tmp_path)
    migrate(settings)
    export = settings.source_dir / "watch-export.xml"
    export.write_text("<HealthData/>", encoding="utf-8")
    alpha = _account_with_device_import(settings, "alpha@example.test", str(export), "fp-a")
    _delete(settings, alpha)
    assert not _exists_user(settings, alpha)
    assert not export.exists()


def test_an_api_feed_import_has_no_file_and_deletes_cleanly(tmp_path: Path):
    settings = settings_for(tmp_path)
    migrate(settings)
    alpha = _account_with_device_import(settings, "alpha@example.test", "openwearables://api", "fp-a")
    _delete(settings, alpha)
    assert not _exists_user(settings, alpha)


# --- Task 2: the search scores each phrase once per query -----------------------------


def old_score(query, searchable):
    matcher = search._Matcher([searchable])
    out = []
    for term, weight in searchable:
        for phrase in query.phrases:
            spelled, mode, floor = phrase
            found = [matcher.tiers(w, mode) for w in spelled]
            if any(t.keys().isdisjoint(term) for t in found):
                continue
            if len(spelled) == len(term) and all(w in have for w, have in zip(spelled, term)):
                out.append(floor + weight)
                continue
            out.append(max(floor, *(min(t[have] for have in term if have in t) for t in found)) + weight)
    return min(out, default=None)


SEARCHABLES = [
    search.terms(["Холестерин загальний", "Cholesterol, total"]),
    search.terms(["Холестерин ЛПНЩ", "LDL cholesterol"]),
    search.terms(["Total cholesterol"]),
    search.terms(["Vitamin D", "25-OH vitamin D"]),
    search.terms(["Гемоглобін"]),
]
QUERIES = ["холест", "холестерин загальний", "vitamin d", "хо", "zzz", "Total cholesterol", "гемоглобін"]


@pytest.mark.parametrize("text", QUERIES)
def test_score_matches_the_per_term_reference_for_every_searchable(text: str):
    query = search.parse(text)
    for searchable in SEARCHABLES:
        assert search.score(query, searchable) == old_score(query, searchable)
    if text == "zzz":
        assert all(search.score(query, searchable) is None for searchable in SEARCHABLES)


# --- Task 3: a message sent without script while an answer is being written ----------


def test_a_plain_form_post_during_a_running_turn_says_why_nothing_was_sent(tmp_path: Path):
    settings, owner, client = build(tmp_path)
    client.cookies.set("anamna_lang", "en")
    key = (str(settings.database_path), str(owner))
    with chat_routes._TURNS_LOCK:
        chat_routes._TURNS.add(key)
    try:
        response = client.post(
            "/chat/send",
            data={"csrf_token": csrf_for(settings, client), "message": "Again?"},
            follow_redirects=False,
        )
        assert response.status_code == 303
        assert "busy=1" in response.headers["location"]
        page = client.get(response.headers["location"])
    finally:
        with chat_routes._TURNS_LOCK:
            chat_routes._TURNS.discard(key)
    assert page.status_code == 200
    assert html.escape(chat_routes.error_text("in_progress", admin=False)) in page.text


# --- a band's lower edge can belong to another body: ferritin 30 is NIH ODS's ---------

_FERRITIN_UNIT = next(
    entry["unit"] for entry in json.loads(Path(LIBRARY_PATH).read_text(encoding="utf-8"))["analytes"]
    if entry["concept_id"] == "ferritin"
)


@pytest.fixture
def ferritin_connection(tmp_path: Path):
    settings = Settings(tmp_path / "health.sqlite3", tmp_path / "sources", "test-secret")
    migrate(settings)
    with connect(settings) as conn:
        seed_concepts(conn)
        seed_reference_library(conn)
        yield conn


def _ferritin(connection, value: float, sex: str = "male") -> dict:
    return evaluate(connection, "ferritin", value_numeric=value, unit=_FERRITIN_UNIT, age_years=40, sex=sex)


def test_ferritin_below_the_healthy_edge_cites_nih_ods_for_the_30_target(ferritin_connection):
    verdict = _ferritin(ferritin_connection, 9.0)
    assert verdict["interpretation"] == "low"
    assert verdict["source_id"] == "who-ferritin-2020"
    assert verdict["target_low"] == 30
    assert verdict["target_source_id"] == "nih-ods-iron"


def test_ferritin_in_the_borderline_band_cites_nih_ods_for_the_30_target(ferritin_connection):
    verdict = _ferritin(ferritin_connection, 20.0)
    assert verdict["interpretation"] == "borderline_low"
    assert verdict["target_source_id"] == "nih-ods-iron"


def test_ferritin_above_the_healthy_band_keeps_whos_200_target(ferritin_connection):
    verdict = _ferritin(ferritin_connection, 250.0)
    assert verdict["interpretation"] == "high"
    assert verdict["target_high"] == 200
    assert verdict["target_source_id"] == "who-ferritin-2020"


def test_ferritin_inside_the_healthy_band_cites_whos_band(ferritin_connection):
    verdict = _ferritin(ferritin_connection, 80.0)
    assert verdict["interpretation"] == "normal"
    assert verdict["target_source_id"] == "who-ferritin-2020"
