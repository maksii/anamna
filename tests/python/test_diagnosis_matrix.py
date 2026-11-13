import sqlite3
from datetime import date, timedelta

import pytest

from anamna.config import Settings
from anamna.db import connect, migrate
from anamna.diagnosis_matrix import (
    RECENT_DAYS,
    RULES,
    WATCH,
    band_text,
    confirm,
    listing,
    matches,
    mute,
    refresh,
    restore,
    watch_metrics,
)
from anamna.ingest.pipeline import seed_concepts
from anamna.locales.messages_diagnosis_rules import MESSAGES_DIAGNOSIS_RULES
from anamna.reference import seed_reference_library

TODAY = date(2026, 11, 13)
LDL_HIGH = "Above the European laboratory flagging cut-point"
TG_HIGH = "High"
TG_NORMAL = "Normal (fasting)"

# --- the curated library -----------------------------------------------------


@pytest.fixture(scope="module")
def library(tmp_path_factory):
    base = tmp_path_factory.mktemp("diagnosis-matrix-library")
    settings = Settings(base / "health.sqlite3", base / "sources", "test-secret")
    migrate(settings)
    with connect(settings) as conn:
        seed_concepts(conn)
        seed_reference_library(conn)
        yield conn


def _library_bands(conn) -> set[tuple[str, str]]:
    rows = conn.execute(
        "SELECT k.canonical_name, r.label FROM curated_reference_rules r"
        " JOIN concepts k ON k.id = r.concept_id"
    )
    return {(row[0], row[1]) for row in rows}


def _band_pairs() -> list[tuple[str, str]]:
    pairs = set()
    for rule in RULES:
        for group in (*rule.all, *rule.none):
            for metric, labels in group:
                pairs.update((metric, label) for label in labels)
    return sorted(pairs)


def _metric_names() -> list[str]:
    names = {name for rule in RULES for metrics in rule.needs for name in metrics}
    names.update(name for _, metrics in WATCH for name in metrics)
    return sorted(names)


@pytest.mark.parametrize("metric,label", _band_pairs())
def test_every_band_label_the_matrix_names_exists(library, metric, label):
    assert (metric, label) in _library_bands(library)


@pytest.mark.parametrize("name", _metric_names())
def test_every_metric_the_matrix_names_is_a_concept(library, name):
    row = library.execute("SELECT 1 FROM concepts WHERE canonical_name=?", (name,)).fetchone()
    assert row is not None


# --- texts -------------------------------------------------------------------


def test_rule_ids_are_unique():
    ids = [rule.id for rule in RULES]
    assert len(ids) == len(set(ids))


@pytest.mark.parametrize("rule_id", [rule.id for rule in RULES])
def test_every_rule_has_a_note_in_both_locales(rule_id):
    entry = MESSAGES_DIAGNOSIS_RULES[f"dx.rule.{rule_id}.note"]
    assert entry["en"].strip()
    assert entry["uk"].strip()


@pytest.mark.parametrize(
    "doctor",
    ["family", "cardiologist", "endocrinologist", "haematologist", "nephrologist", "gastroenterologist"],
)
def test_every_doctor_has_a_line_in_both_locales(doctor):
    entry = MESSAGES_DIAGNOSIS_RULES[f"dx.doctor.{doctor}"]
    assert entry["en"].strip()
    assert entry["uk"].strip()


def test_every_rule_names_a_known_doctor():
    doctors = {"family", "cardiologist", "endocrinologist", "haematologist", "nephrologist", "gastroenterologist"}
    assert {rule.doctor for rule in RULES} <= doctors


def test_watch_metrics_takes_the_first_matching_entry():
    assert watch_metrics("E78.2") == WATCH[0][1]
    assert watch_metrics("E11.9") == ("Blood glucose", "Hemoglobin A1c")
    assert watch_metrics("Z00.0") == ()


# --- matching ----------------------------------------------------------------


def _verdict_position(label: str, source_id: str = "ps") -> dict:
    return {
        "band_label": label,
        "source_id": source_id,
        "source_name": "Position source",
        "source_url": "https://example.test/position",
    }


def _card(name: str, label: str, *, day: date = TODAY, positions: tuple = ()) -> dict:
    return {
        "name": name,
        "id": name.casefold().replace(" ", "-"),
        "url": f"/metrics/{name.casefold().replace(' ', '-')}",
        "value_text": "5.5",
        "unit": "mmol/L",
        "latest_date": day.isoformat(),
        "verdict": {
            "band_label": label,
            "source_id": "s",
            "source_name": "S",
            "source_url": "u",
            "authority_positions": list(positions),
        },
    }


def test_raised_ldl_with_high_triglycerides_is_mixed_only():
    cards = [_card("LDL cholesterol", LDL_HIGH), _card("Triglycerides", TG_HIGH)]
    assert set(matches(cards, today=TODAY)) == {"lipid_mixed"}


def test_raised_ldl_with_normal_triglycerides_is_cholesterol_only():
    cards = [_card("LDL cholesterol", LDL_HIGH), _card("Triglycerides", TG_NORMAL)]
    assert set(matches(cards, today=TODAY)) == {"lipid_cholesterol"}


def test_raised_ldl_without_a_triglycerides_card_is_neither_cholesterol_nor_mixed():
    held = matches([_card("LDL cholesterol", LDL_HIGH)], today=TODAY)
    assert "lipid_cholesterol" not in held
    assert "lipid_mixed" not in held


def test_a_label_found_only_in_an_authority_position_counts():
    ldl = _card(
        "LDL cholesterol",
        "Below the European laboratory flagging cut-point",
        positions=(_verdict_position(LDL_HIGH),),
    )
    held = matches([ldl, _card("Triglycerides", TG_NORMAL)], today=TODAY)
    assert set(held) == {"lipid_cholesterol"}
    evidence = held["lipid_cholesterol"][0]
    assert evidence["band"] == LDL_HIGH
    assert evidence["source_id"] == "ps"
    assert evidence["metric"] == "LDL cholesterol"
    assert evidence["date"] == TODAY.isoformat()


def test_a_card_older_than_recent_days_raises_nothing():
    old = TODAY - timedelta(days=RECENT_DAYS + 1)
    cards = [_card("LDL cholesterol", LDL_HIGH, day=old), _card("Triglycerides", TG_HIGH, day=old)]
    assert matches(cards, today=TODAY) == {}


def test_a_card_exactly_recent_days_old_still_counts():
    edge = TODAY - timedelta(days=RECENT_DAYS)
    cards = [_card("LDL cholesterol", LDL_HIGH, day=edge), _card("Triglycerides", TG_NORMAL, day=edge)]
    assert set(matches(cards, today=TODAY)) == {"lipid_cholesterol"}


def test_anaemia_with_low_ferritin_is_iron_anaemia_and_not_the_other_two():
    cards = [
        _card("Hemoglobin", "Moderate anaemia (WHO)"),
        _card("Ferritin", "Iron deficiency (apparently healthy adults)"),
    ]
    assert set(matches(cards, today=TODAY)) == {"anaemia_iron"}


# --- refresh -----------------------------------------------------------------

SCHEMA = """
CREATE TABLE users (id TEXT PRIMARY KEY);
CREATE TABLE patients (id TEXT PRIMARY KEY);
CREATE TABLE documents (id TEXT PRIMARY KEY);
CREATE TABLE diagnoses (
    id TEXT PRIMARY KEY,
    owner_user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    patient_id TEXT NOT NULL REFERENCES patients(id) ON DELETE CASCADE,
    code TEXT NOT NULL DEFAULT '',
    name TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active','resolved','outdated')),
    certainty TEXT NOT NULL DEFAULT 'confirmed' CHECK (certainty IN ('confirmed','provisional')),
    diagnosed_on TEXT,
    resolved_on TEXT,
    dates_approximate INTEGER NOT NULL DEFAULT 0,
    clinician TEXT NOT NULL DEFAULT '',
    document_id TEXT REFERENCES documents(id) ON DELETE SET NULL,
    notes TEXT NOT NULL DEFAULT '',
    origin TEXT NOT NULL DEFAULT 'person' CHECK (origin IN ('person','document','suspicion')),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    CHECK (code <> '' OR name <> ''),
    CHECK (resolved_on IS NULL OR diagnosed_on IS NULL OR diagnosed_on <= resolved_on)
);
CREATE TABLE diagnosis_suspicions (
    id TEXT PRIMARY KEY,
    owner_user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    rule_id TEXT NOT NULL,
    code TEXT NOT NULL,
    state TEXT NOT NULL DEFAULT 'open' CHECK (state IN ('open','muted','confirmed','cleared')),
    evidence_json TEXT NOT NULL DEFAULT '[]',
    first_seen_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    state_changed_at TEXT NOT NULL,
    diagnosis_id TEXT REFERENCES diagnoses(id) ON DELETE SET NULL,
    UNIQUE (owner_user_id, rule_id)
);
"""


@pytest.fixture
def db():
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.executescript(SCHEMA)
    connection.execute("INSERT INTO users(id) VALUES ('u1')")
    connection.execute("INSERT INTO patients(id) VALUES ('p1')")
    yield connection
    connection.close()


def _lipid_mixed_cards() -> list[dict]:
    return [_card("LDL cholesterol", LDL_HIGH), _card("Triglycerides", TG_HIGH)]


def _state(connection, rule_id: str) -> str | None:
    row = connection.execute(
        "SELECT state FROM diagnosis_suspicions WHERE owner_user_id='u1' AND rule_id=?", (rule_id,)
    ).fetchone()
    return None if row is None else row[0]


def _suspicion_id(connection, rule_id: str) -> str:
    return connection.execute(
        "SELECT id FROM diagnosis_suspicions WHERE owner_user_id='u1' AND rule_id=?", (rule_id,)
    ).fetchone()[0]


def _diagnosis(connection, code: str) -> str:
    diagnosis_id = f"dx-{code}"
    connection.execute(
        """INSERT INTO diagnoses(id, owner_user_id, patient_id, code, status, created_at, updated_at)
           VALUES (?, 'u1', 'p1', ?, 'active', '2026-01-01', '2026-01-01')""",
        (diagnosis_id, code),
    )
    return diagnosis_id


def test_first_refresh_opens_and_a_second_keeps_one_row(db):
    assert refresh(db, "u1", _lipid_mixed_cards(), today=TODAY) == {"opened": 1, "cleared": 0}
    assert refresh(db, "u1", _lipid_mixed_cards(), today=TODAY) == {"opened": 0, "cleared": 0}
    assert db.execute("SELECT COUNT(*) FROM diagnosis_suspicions").fetchone()[0] == 1
    assert _state(db, "lipid_mixed") == "open"


def test_mute_survives_a_refresh(db):
    refresh(db, "u1", _lipid_mixed_cards(), today=TODAY)
    assert mute(db, "u1", _suspicion_id(db, "lipid_mixed"))
    assert refresh(db, "u1", _lipid_mixed_cards(), today=TODAY) == {"opened": 0, "cleared": 0}
    assert _state(db, "lipid_mixed") == "muted"


def test_refresh_without_matching_cards_clears_open_and_keeps_muted(db):
    refresh(db, "u1", _lipid_mixed_cards(), today=TODAY)
    assert refresh(db, "u1", [], today=TODAY) == {"opened": 0, "cleared": 1}
    assert _state(db, "lipid_mixed") == "cleared"


def test_refresh_without_matching_cards_leaves_muted_muted(db):
    refresh(db, "u1", _lipid_mixed_cards(), today=TODAY)
    mute(db, "u1", _suspicion_id(db, "lipid_mixed"))
    assert refresh(db, "u1", [], today=TODAY) == {"opened": 0, "cleared": 0}
    assert _state(db, "lipid_mixed") == "muted"


def test_a_cleared_row_reopens_when_it_matches_again(db):
    refresh(db, "u1", _lipid_mixed_cards(), today=TODAY)
    refresh(db, "u1", [], today=TODAY)
    assert refresh(db, "u1", _lipid_mixed_cards(), today=TODAY) == {"opened": 1, "cleared": 0}
    assert _state(db, "lipid_mixed") == "open"


def test_an_active_diagnosis_clears_the_pattern_and_stops_it_reopening(db):
    refresh(db, "u1", _lipid_mixed_cards(), today=TODAY)
    _diagnosis(db, "E78.2")
    assert refresh(db, "u1", _lipid_mixed_cards(), today=TODAY) == {"opened": 0, "cleared": 1}
    assert _state(db, "lipid_mixed") == "cleared"
    assert refresh(db, "u1", _lipid_mixed_cards(), today=TODAY) == {"opened": 0, "cleared": 0}
    assert _state(db, "lipid_mixed") == "cleared"
    assert "lipid_mixed" not in {row["rule_id"] for row in listing(db, "u1")}


def test_restore_turns_muted_into_open(db):
    refresh(db, "u1", _lipid_mixed_cards(), today=TODAY)
    sid = _suspicion_id(db, "lipid_mixed")
    mute(db, "u1", sid)
    assert restore(db, "u1", sid)
    assert _state(db, "lipid_mixed") == "open"


def test_confirm_sets_confirmed_and_the_diagnosis(db):
    refresh(db, "u1", _lipid_mixed_cards(), today=TODAY)
    sid = _suspicion_id(db, "lipid_mixed")
    did = _diagnosis(db, "E78.1")
    assert confirm(db, "u1", sid, did)
    row = db.execute("SELECT state, diagnosis_id FROM diagnosis_suspicions WHERE id=?", (sid,)).fetchone()
    assert (row["state"], row["diagnosis_id"]) == ("confirmed", did)


def _link(connection) -> tuple[str, str | None]:
    """The lipid_mixed row's state and the diagnosis that confirmed it."""
    row = connection.execute(
        "SELECT state, diagnosis_id FROM diagnosis_suspicions WHERE owner_user_id='u1' AND rule_id='lipid_mixed'"
    ).fetchone()
    return row["state"], row["diagnosis_id"]


def _confirmed(connection) -> str:
    """A possible diagnosis confirmed by an active E78.1 diagnosis; returns that diagnosis's id."""
    refresh(connection, "u1", _lipid_mixed_cards(), today=TODAY)
    diagnosis_id = _diagnosis(connection, "E78.1")
    assert confirm(connection, "u1", _suspicion_id(connection, "lipid_mixed"), diagnosis_id)
    return diagnosis_id


def test_a_confirmed_row_reopens_when_its_diagnosis_is_deleted_and_the_rule_still_holds(db):
    diagnosis_id = _confirmed(db)
    db.execute("DELETE FROM diagnoses WHERE id=?", (diagnosis_id,))
    assert refresh(db, "u1", _lipid_mixed_cards(), today=TODAY) == {"opened": 1, "cleared": 0}
    assert _link(db) == ("open", None)


def test_a_confirmed_row_clears_when_its_diagnosis_is_resolved_and_the_rule_no_longer_holds(db):
    diagnosis_id = _confirmed(db)
    db.execute("UPDATE diagnoses SET status='resolved' WHERE id=?", (diagnosis_id,))
    assert refresh(db, "u1", [], today=TODAY) == {"opened": 0, "cleared": 1}
    assert _link(db) == ("cleared", None)


def test_a_confirmed_row_with_an_active_diagnosis_stays_confirmed(db):
    diagnosis_id = _confirmed(db)
    assert refresh(db, "u1", _lipid_mixed_cards(), today=TODAY) == {"opened": 0, "cleared": 0}
    assert _link(db) == ("confirmed", diagnosis_id)


# --- band labels ---------------------------------------------------------------


def test_band_text_gives_the_ukrainian_label_of_the_curated_band(library):
    english = "Obesity class I"
    label = band_text(library, "Body mass index", english, "uk")
    assert label != english
    assert any("Ѐ" <= char <= "ӿ" for char in label)
    assert band_text(library, "Body mass index", english, "en") == english


def test_band_text_gives_back_a_band_the_library_no_longer_has(library):
    assert band_text(library, "Body mass index", "No such band", "uk") == "No such band"
    assert band_text(library, "Body mass index", "No such band", "en") == "No such band"


def test_listing_decodes_evidence_and_leaves_out_unknown_rules(db):
    refresh(db, "u1", _lipid_mixed_cards(), today=TODAY)
    db.execute(
        """INSERT INTO diagnosis_suspicions(id, owner_user_id, rule_id, code, state, evidence_json,
               first_seen_at, last_seen_at, state_changed_at)
           VALUES ('gone', 'u1', 'retired_rule', 'X00', 'open', '[]', 't', 't', 't')"""
    )
    rows = listing(db, "u1")
    assert [row["rule_id"] for row in rows] == ["lipid_mixed"]
    item = rows[0]
    assert item["doctor"] == "cardiologist"
    assert item["code"] == "E78.2"
    assert [entry["value"] for entry in item["evidence"]] == ["5.5", "5.5"]
    assert {entry["metric"] for entry in item["evidence"]} == {"LDL cholesterol", "Triglycerides"}
