"""A settled exclusion rule holds for an export whose kept copy is gone."""
from __future__ import annotations

from anamna import db as database
from anamna.db import connect
from anamna.devices import exclusions
from anamna.devices.importer import import_device_export

from test_linked_metrics import _build

SCALE = "Synthetic scale"


def _export(settings, owner, readings, *, name="apple"):
    """An Apple Health export of (UTC time on 2025-01-01, kilograms) weigh-ins."""
    folder = settings.source_dir / name
    folder.mkdir(exist_ok=True)
    source = folder / "export.xml"
    source.write_text("<HealthData>\n" + "\n".join(
        f'<Record type="HKQuantityTypeIdentifierBodyMass" sourceName="{SCALE}" unit="kg" value="{value}" '
        f'startDate="2025-01-01 {clock} +0000" endDate="2025-01-01 {clock} +0000"/>'
        for clock, value in readings) + "\n</HealthData>", encoding="utf-8")
    with connect(settings) as db:
        db.execute("UPDATE patients SET height_cm=200 WHERE owner_user_id=?", (owner,))
    import_device_export(settings, owner_user_id=owner, patient_id="patient-" + owner,
                         vendor_key="apple_health", source=source, preserve_other_imports=True)
    return source


def _rows(settings, owner):
    """Every stored device row of the person, and the inputs of the calculated ones."""
    with connect(settings) as db:
        return {
            "days": [tuple(row) for row in db.execute(
                "SELECT * FROM device_metric_days WHERE owner_user_id=? ORDER BY id", (owner,))],
            "inputs": [tuple(row) for row in db.execute("SELECT * FROM device_calculation_inputs ORDER BY row_id, input_kind")],
        }


def _keys(settings, owner):
    with connect(settings) as db:
        return sorted(row[0] for row in db.execute(
            "SELECT metric_key FROM device_metric_days WHERE owner_user_id=?", (owner,)))


def _held(settings):
    with connect(settings) as db:
        return db.execute("SELECT COUNT(*) FROM device_exclusion_held").fetchone()[0]


def _revision(settings, owner):
    with connect(settings) as db:
        return db.execute("SELECT revision FROM device_metric_revisions WHERE owner_user_id=?", (owner,)).fetchone()[0]


def test_rule_removes_and_undo_restores_a_reading_whose_export_is_gone(tmp_path):
    settings, owner, _ = _build(tmp_path)
    source = _export(settings, owner, [("08:00:00", 80)])
    before = _rows(settings, owner)
    assert _keys(settings, owner) == ["body_mass_index", "body_weight"]
    rule = exclusions.create(settings, owner, owner, provider="apple_health", source=SCALE, scope="origin")
    source.unlink()  # This synthetic arrival belongs only to this test.
    revision = _revision(settings, owner)
    assert exclusions.run_pending(settings, owner) == 1
    # The weight and the BMI calculated from it are both gone.
    assert _rows(settings, owner) == {"days": [], "inputs": []}
    assert _held(settings) == 2 and _revision(settings, owner) > revision
    # Settled: a second pass has nothing to do and changes nothing.
    revision = _revision(settings, owner)
    assert exclusions.run_pending(settings, owner) == 0
    assert _held(settings) == 2 and _revision(settings, owner) == revision

    assert exclusions.undo(settings, owner, owner, rule)
    assert exclusions.run_pending(settings, owner) == 1
    assert _rows(settings, owner) == before  # ids, values, import_id and created_at included
    assert _held(settings) == 0
    revision = _revision(settings, owner)
    assert exclusions.run_pending(settings, owner) == 0
    assert _rows(settings, owner) == before and _revision(settings, owner) == revision


def test_window_over_part_of_a_day_removes_and_restores_the_whole_day_row(tmp_path):
    settings, owner, _ = _build(tmp_path)
    source = _export(settings, owner, [("08:00:00", 80), ("20:00:00", 82)])
    before = _rows(settings, owner)
    assert len(before["days"]) == 2
    rule = exclusions.create(settings, owner, owner, provider="apple_health", source=SCALE, scope="window",
                             from_text="2025-01-01T07:00:00+00:00", until_text="2025-01-01T09:00:00+00:00")
    source.unlink()
    assert exclusions.run_pending(settings, owner) == 1
    # The evening weigh-in cannot be told from the excluded one without the
    # file: the day's row goes whole rather than keep the excluded reading.
    assert _rows(settings, owner)["days"] == []
    exclusions.undo(settings, owner, owner, rule)
    assert exclusions.run_pending(settings, owner) == 1
    assert _rows(settings, owner) == before and _held(settings) == 0


def test_one_reading_on_another_day_leaves_the_stored_day_alone(tmp_path):
    settings, owner, _ = _build(tmp_path)
    source = _export(settings, owner, [("08:00:00", 80)])
    before = _rows(settings, owner)
    exclusions.create(settings, owner, owner, provider="apple_health", source=SCALE, scope="reading",
                      from_text="2025-01-03T08:00:00+00:00")
    exclusions.create(settings, owner, owner, provider="apple_health", source=SCALE, scope="origin", series=["steps"])
    source.unlink()
    assert exclusions.run_pending(settings, owner) == 2
    assert _rows(settings, owner) == before and _held(settings) == 0


def test_export_with_a_kept_copy_is_re_read_and_nothing_is_held(tmp_path):
    settings, owner, _ = _build(tmp_path)
    _export(settings, owner, [("08:00:00", 80), ("20:00:00", 82)])
    rule = exclusions.create(settings, owner, owner, provider="apple_health", source=SCALE, scope="window",
                             from_text="2025-01-01T19:00:00+00:00", until_text="2025-01-01T21:00:00+00:00")
    assert exclusions.run_pending(settings, owner) == 1
    with connect(settings) as db:
        # Re-read under the rule: the morning weigh-in is what the day holds.
        assert [row[0] for row in db.execute("SELECT value FROM device_metric_days WHERE metric_key='body_weight'")] == [80]
    assert _held(settings) == 0
    exclusions.undo(settings, owner, owner, rule)
    assert exclusions.run_pending(settings, owner) == 1
    with connect(settings) as db:
        assert [row[0] for row in db.execute("SELECT value FROM device_metric_days WHERE metric_key='body_weight'")] == [82]
    assert _held(settings) == 0


def test_undo_keeps_the_live_row_when_the_export_came_back(tmp_path):
    settings, owner, _ = _build(tmp_path)
    source = _export(settings, owner, [("08:00:00", 80)])
    text = source.read_text(encoding="utf-8")
    rule = exclusions.create(settings, owner, owner, provider="apple_health", source=SCALE, scope="origin")
    source.unlink()
    exclusions.run_pending(settings, owner)
    assert _held(settings) == 2
    exclusions.undo(settings, owner, owner, rule)
    # The same export uploaded again before the undo is applied.
    source.write_text(text, encoding="utf-8")
    import_device_export(settings, owner_user_id=owner, patient_id="patient-" + owner,
                         vendor_key="apple_health", source=source, preserve_other_imports=True)
    def live():
        # Without created_at: the undo re-reads the export, which stamps it anew.
        rows = _rows(settings, owner)
        return [row[:-1] for row in rows["days"]], rows["inputs"]

    before = live()
    assert len(before[0]) == 2
    assert exclusions.run_pending(settings, owner) == 1
    assert live() == before and _held(settings) == 0


def test_a_second_rule_keeps_the_reading_out_when_the_first_is_undone(tmp_path):
    settings, owner, _ = _build(tmp_path)
    source = _export(settings, owner, [("08:00:00", 80)])
    before = _rows(settings, owner)
    first = exclusions.create(settings, owner, owner, provider="apple_health", source=SCALE, scope="origin")
    second = exclusions.create(settings, owner, owner, provider="apple_health", source=SCALE, scope="window",
                               from_text="2025-01-01T00:00:00+00:00", until_text="2025-01-01T23:00:00+00:00")
    source.unlink()
    assert exclusions.run_pending(settings, owner) == 2
    exclusions.undo(settings, owner, owner, first)
    exclusions.run_pending(settings, owner)
    assert _rows(settings, owner)["days"] == [] and _held(settings) >= 1
    exclusions.undo(settings, owner, owner, second)
    exclusions.run_pending(settings, owner)
    after = _rows(settings, owner)
    # The weight is the stored row again; its BMI is calculated anew, so only
    # the moment it was written may differ.
    assert [row[:-1] for row in after["days"]] == [row[:-1] for row in before["days"]]
    stored = [row for row in before["days"] if not row[0].startswith("derived-bmi-")]
    assert len(stored) == 1 and stored[0] in after["days"] and after["inputs"] == before["inputs"]
    assert _held(settings) == 0


def test_deleting_the_account_leaves_nothing_held(tmp_path):
    settings, owner, _ = _build(tmp_path)
    source = _export(settings, owner, [("08:00:00", 80)])
    exclusions.create(settings, owner, owner, provider="apple_health", source=SCALE, scope="origin")
    source.unlink()
    exclusions.run_pending(settings, owner)
    assert _held(settings) == 2
    with connect(settings) as db:
        db.execute("DELETE FROM users WHERE id=?", (owner,))
        assert not db.execute("SELECT 1 FROM device_exclusion_held").fetchone()
        assert not db.execute("PRAGMA foreign_key_check").fetchall()


def test_migration_077_runs_inside_the_migration_transaction(tmp_path):
    settings, _, _ = _build(tmp_path)  # applies every migration through migrate()
    script = next(database.MIGRATIONS_DIR.glob("077_*.sql")).read_text(encoding="utf-8")
    assert not database._SELF_MANAGED.search(script)
    with connect(settings) as db:
        assert db.execute("SELECT 1 FROM schema_migrations WHERE version=77").fetchone()
        assert {row[1] for row in db.execute("PRAGMA table_info(device_exclusion_held)")} == {
            "id", "owner_user_id", "exclusion_id", "import_id", "source_table", "row_json"}
