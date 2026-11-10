"""The integration secrets read from a .env file at the executable entry point."""

from __future__ import annotations

import os

from anamna import config


def test_the_tabletki_alias_in_the_env_file_sets_the_application_variable(tmp_path, monkeypatch):
    monkeypatch.delenv("ANAMNA_TABLETKI_TOKEN", raising=False)
    env_file = tmp_path / ".env"
    env_file.write_text("TABLETKI_TOKEN=abc\n", encoding="utf-8")
    config.load_integration_environment(env_file)
    assert os.environ["ANAMNA_TABLETKI_TOKEN"] == "abc"
