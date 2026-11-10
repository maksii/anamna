from __future__ import annotations

import sqlite3

import pytest

from anamna import db
from anamna.config import Settings


def _settings(tmp_path):
    return Settings(database_path=tmp_path / "t.sqlite3", source_dir=tmp_path / "s", secret_key="x")


def _tables_and_triggers(path):
    connection = sqlite3.connect(path)
    try:
        return {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type IN ('table', 'trigger')"
            )
        }
    finally:
        connection.close()


def _versions(path):
    connection = sqlite3.connect(path)
    try:
        return [row[0] for row in connection.execute("SELECT version FROM schema_migrations ORDER BY version")]
    finally:
        connection.close()


def test_failed_migration_leaves_nothing_behind(tmp_path, monkeypatch):
    migrations = tmp_path / "migrations"
    migrations.mkdir()
    monkeypatch.setattr(db, "MIGRATIONS_DIR", migrations)
    (migrations / "001_ok.sql").write_text("CREATE TABLE a(x);\n", encoding="utf-8")
    bad = migrations / "002_bad.sql"
    bad.write_text(
        "CREATE TABLE b(x); ALTER TABLE b ADD COLUMN y; ALTER TABLE missing ADD COLUMN z;\n",
        encoding="utf-8",
    )
    settings = _settings(tmp_path)

    with pytest.raises(sqlite3.OperationalError):
        db.migrate(settings)

    tables = _tables_and_triggers(settings.database_path)
    assert "a" in tables
    assert "b" not in tables
    assert _versions(settings.database_path) == [1]

    bad.write_text("CREATE TABLE b(x);\nALTER TABLE b ADD COLUMN y;\n", encoding="utf-8")
    db.migrate(settings)

    assert "b" in _tables_and_triggers(settings.database_path)
    assert _versions(settings.database_path) == [1, 2]


def test_self_managed_migration_runs_as_written(tmp_path, monkeypatch):
    migrations = tmp_path / "migrations"
    migrations.mkdir()
    monkeypatch.setattr(db, "MIGRATIONS_DIR", migrations)
    (migrations / "001_pragma.sql").write_text(
        "PRAGMA foreign_keys=OFF;\nCREATE TABLE c(x);\n", encoding="utf-8"
    )
    settings = _settings(tmp_path)

    db.migrate(settings)

    assert "c" in _tables_and_triggers(settings.database_path)
    assert _versions(settings.database_path) == [1]


def test_migration_with_trigger_applies(tmp_path, monkeypatch):
    migrations = tmp_path / "migrations"
    migrations.mkdir()
    monkeypatch.setattr(db, "MIGRATIONS_DIR", migrations)
    (migrations / "001_trigger.sql").write_text(
        "CREATE TABLE t(x);\n"
        "CREATE TABLE log(y);\n"
        "CREATE TRIGGER t_ins AFTER INSERT ON t\n"
        "BEGIN\n"
        "  INSERT INTO log(y) VALUES (new.x);\n"
        "END;\n",
        encoding="utf-8",
    )
    settings = _settings(tmp_path)

    db.migrate(settings)

    assert "t_ins" in _tables_and_triggers(settings.database_path)
    assert _versions(settings.database_path) == [1]


def test_database_from_a_newer_version_is_refused(tmp_path):
    settings = _settings(tmp_path)
    db.migrate(settings)
    connection = sqlite3.connect(settings.database_path)
    connection.execute(
        "INSERT INTO schema_migrations(version, applied_at) VALUES (9999, '2026-01-01T00:00:00+00:00')"
    )
    connection.commit()
    connection.close()

    with pytest.raises(RuntimeError, match="newer Anamna"):
        db.migrate(settings)

    assert 9999 in _versions(settings.database_path)


def test_real_migrations_apply_on_a_fresh_database(tmp_path):
    settings = _settings(tmp_path)
    expected = len(list(db.MIGRATIONS_DIR.glob("*.sql")))

    db.migrate(settings)

    assert len(_versions(settings.database_path)) == expected

    connection = sqlite3.connect(settings.database_path)
    before = connection.execute("SELECT version, applied_at FROM schema_migrations").fetchall()
    connection.close()

    db.migrate(settings)

    connection = sqlite3.connect(settings.database_path)
    after = connection.execute("SELECT version, applied_at FROM schema_migrations").fetchall()
    connection.close()
    assert after == before
