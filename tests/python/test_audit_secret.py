from __future__ import annotations

import re

from anamna import config

OLD_DEFAULT = "local-development-only-change-me"
HEX_SECRET = re.compile(r"[0-9a-f]{64}")


def _installation(monkeypatch, directory):
    """Point the app at one installation's database, with no environment secret."""
    monkeypatch.setenv("ANAMNA_DB", str(directory / "db" / "anamna.sqlite3"))
    monkeypatch.delenv("ANAMNA_SECRET", raising=False)
    config._stored_secret.cache_clear()


def test_secret_is_generated_once_and_persisted(tmp_path, monkeypatch):
    _installation(monkeypatch, tmp_path)

    secret = config.get_settings().secret_key
    key_file = tmp_path / "db" / "secret.key"

    assert HEX_SECRET.fullmatch(secret)
    assert secret != OLD_DEFAULT
    assert key_file.read_text(encoding="utf-8") == secret

    config._stored_secret.cache_clear()
    assert config.get_settings().secret_key == secret


def test_environment_secret_wins(tmp_path, monkeypatch):
    _installation(monkeypatch, tmp_path)
    monkeypatch.setenv("ANAMNA_SECRET", "from-the-environment")

    assert config.get_settings().secret_key == "from-the-environment"
    assert not (tmp_path / "db" / "secret.key").exists()


def test_two_installations_get_different_secrets(tmp_path, monkeypatch):
    _installation(monkeypatch, tmp_path / "first")
    first = config.get_settings().secret_key

    _installation(monkeypatch, tmp_path / "second")
    second = config.get_settings().secret_key

    assert first != second


def test_blank_environment_secret_is_not_used(tmp_path, monkeypatch):
    _installation(monkeypatch, tmp_path)
    monkeypatch.setenv("ANAMNA_SECRET", "   ")

    secret = config.get_settings().secret_key

    assert HEX_SECRET.fullmatch(secret)
    assert secret != OLD_DEFAULT
