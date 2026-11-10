from __future__ import annotations

import getpass
import sqlite3
from datetime import UTC, datetime, timedelta

import pytest

from anamna import cli
from anamna.security import MINIMUM_PASSWORD_LENGTH

EMAIL = "owner@example.com"
FIRST = "first-password-1"


@pytest.fixture
def installation(tmp_path, monkeypatch):
    """One installation on a temp database; the secret is pinned so no key file is written."""
    monkeypatch.setenv("ANAMNA_DB", str(tmp_path / "data" / "anamna.sqlite3"))
    monkeypatch.setenv("ANAMNA_SOURCES", str(tmp_path / "sources"))
    monkeypatch.setenv("ANAMNA_SECRET", "test-secret-for-cli")
    monkeypatch.delenv("ANAMNA_NEW_PASSWORD", raising=False)
    return tmp_path


def _database(tmp_path):
    return tmp_path / "data" / "anamna.sqlite3"


def _init(email=EMAIL, password=FIRST):
    cli.main(["init", "--email", email, "--name", "Owner", "--password", password])


def _account(tmp_path, email=EMAIL):
    connection = sqlite3.connect(_database(tmp_path))
    try:
        return connection.execute(
            "SELECT id, password_hash, password_salt, role, disabled_at FROM users WHERE email = ?", (email,)
        ).fetchone()
    finally:
        connection.close()


def _execute(tmp_path, sql, params=()):
    connection = sqlite3.connect(_database(tmp_path))
    try:
        connection.execute(sql, params)
        connection.commit()
    finally:
        connection.close()


def _count(tmp_path, sql, params=()):
    connection = sqlite3.connect(_database(tmp_path))
    try:
        return connection.execute(sql, params).fetchone()[0]
    finally:
        connection.close()


def test_init_on_an_existing_email_exits_1_and_changes_nothing(installation, capsys):
    _init()
    before = _account(installation)

    with pytest.raises(SystemExit) as refused:
        _init(password="second-password-2")

    assert refused.value.code == 1
    assert "already exists; nothing was changed" in capsys.readouterr().err
    assert _account(installation) == before


def test_set_password_changes_the_hash_and_ends_sessions(installation, monkeypatch):
    _init()
    user_id, old_hash, _, _, _ = _account(installation)
    _execute(
        installation,
        "INSERT INTO sessions(token_hash, user_id, csrf_token, created_at, expires_at) VALUES (?, ?, ?, ?, ?)",
        ("a" * 64, user_id, "csrf", datetime.now(UTC).isoformat(), (datetime.now(UTC) + timedelta(days=1)).isoformat()),
    )
    monkeypatch.setenv("ANAMNA_NEW_PASSWORD", "second-password-2")

    cli.main(["set-password", "--email", EMAIL.upper()])

    assert _account(installation)[1] != old_hash
    assert _count(installation, "SELECT COUNT(*) FROM sessions WHERE user_id = ?", (user_id,)) == 0


def test_set_password_refuses_a_short_password(installation, monkeypatch, capsys):
    _init()
    before = _account(installation)
    monkeypatch.setenv("ANAMNA_NEW_PASSWORD", "x" * (MINIMUM_PASSWORD_LENGTH - 1))

    with pytest.raises(SystemExit) as refused:
        cli.main(["set-password", "--email", EMAIL])

    assert refused.value.code == 1
    assert f"at least {MINIMUM_PASSWORD_LENGTH} characters; nothing was changed" in capsys.readouterr().err
    assert _account(installation) == before


def test_set_password_prompt_refuses_differing_entries(installation, monkeypatch, capsys):
    _init()
    before = _account(installation)
    entries = iter(["second-password-2", "second-password-3"])
    monkeypatch.setattr(getpass, "getpass", lambda prompt="": next(entries))

    with pytest.raises(SystemExit) as refused:
        cli.main(["set-password", "--email", EMAIL])

    assert refused.value.code == 1
    assert "The two entries differ; nothing was changed." in capsys.readouterr().err
    assert _account(installation) == before


def test_set_password_prompt_accepts_matching_entries(installation, monkeypatch):
    _init()
    before = _account(installation)
    entries = iter(["second-password-2", "second-password-2"])
    monkeypatch.setattr(getpass, "getpass", lambda prompt="": next(entries))

    cli.main(["set-password", "--email", EMAIL])

    assert _account(installation)[1] != before[1]


def test_set_password_admin_promotes_and_re_enables(installation, monkeypatch, capsys):
    _init()
    _execute(installation, "UPDATE users SET role = 'user', disabled_at = '2026-01-01T00:00:00+00:00' WHERE email = ?", (EMAIL,))
    monkeypatch.setenv("ANAMNA_NEW_PASSWORD", "second-password-2")

    cli.main(["set-password", "--email", EMAIL, "--admin"])

    _, _, _, role, disabled_at = _account(installation)
    assert role == "admin"
    assert disabled_at is None
    assert "The account is now an administrator." in capsys.readouterr().out


def test_set_password_unknown_email_exits_1(installation, monkeypatch, capsys):
    _init()
    monkeypatch.setenv("ANAMNA_NEW_PASSWORD", "second-password-2")

    with pytest.raises(SystemExit) as refused:
        cli.main(["set-password", "--email", "nobody@example.com"])

    assert refused.value.code == 1
    assert "No account with this email." in capsys.readouterr().err


def test_backup_copies_database_key_and_sources(installation, capsys):
    _init()
    (_database(installation).parent / "secret.key").write_text("stored-key", encoding="utf-8")
    uploads = installation / "sources" / "uploads" / "2026-11"
    uploads.mkdir(parents=True)
    (uploads / "report.pdf").write_bytes(b"%PDF-1.4 test")
    target = installation / "backup"

    cli.main(["backup", "--to", str(target)])

    copies = list(target.glob("anamna-*.sqlite3"))
    assert len(copies) == 1
    connection = sqlite3.connect(copies[0])
    try:
        assert connection.execute("SELECT email FROM users").fetchall() == [(EMAIL,)]
    finally:
        connection.close()
    assert (target / "secret.key").read_text(encoding="utf-8") == "stored-key"
    assert (target / "sources" / "uploads" / "2026-11" / "report.pdf").read_bytes() == b"%PDF-1.4 test"
    assert "Original files were not copied" not in capsys.readouterr().out


def test_backup_no_sources_skips_the_tree_and_says_so(installation, capsys):
    _init()
    (installation / "sources").mkdir()
    (installation / "sources" / "a.pdf").write_bytes(b"x")
    target = installation / "backup"

    cli.main(["backup", "--to", str(target), "--no-sources"])

    assert not (target / "sources").exists()
    assert list(target.glob("anamna-*.sqlite3"))
    assert f"Original files were not copied: back up {installation / 'sources'} separately." in capsys.readouterr().out


def test_backup_refuses_a_directory_inside_the_sources(installation):
    _init()
    sources = installation / "sources"
    sources.mkdir()

    with pytest.raises(SystemExit) as refused:
        cli.main(["backup", "--to", str(sources / "inside")])

    assert refused.value.code != 0
    assert not (sources / "inside").exists()


def test_export_refuses_to_overwrite(installation, capsys):
    _init()
    target = installation / "record.zip"
    target.write_bytes(b"keep me")

    with pytest.raises(SystemExit) as refused:
        cli.main(["export", "--email", EMAIL, "--to", str(target)])

    assert refused.value.code == 1
    assert "already exists; nothing was written" in capsys.readouterr().err
    assert target.read_bytes() == b"keep me"


def test_export_writes_an_archive(installation, capsys):
    _init()
    target = installation / "record.zip"

    cli.main(["export", "--email", EMAIL, "--to", str(target)])

    assert target.read_bytes()[:2] == b"PK"
    assert "documents 0" in capsys.readouterr().out


def test_export_unknown_email_exits_1(installation, capsys):
    _init()

    with pytest.raises(SystemExit) as refused:
        cli.main(["export", "--email", "nobody@example.com", "--to", str(installation / "x.zip")])

    assert refused.value.code == 1
    assert "No account with this email." in capsys.readouterr().err
    assert not (installation / "x.zip").exists()
