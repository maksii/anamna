"""Suite-wide test defaults."""
import sqlite3

import pytest

_connect = sqlite3.connect


def _connect_without_fsync(*args, **kwargs):
    """Nearly every test migrates a fresh database, and on Windows each of the
    migrations' commits waits on a disk flush: 1.8 s per database, against
    0.05 s without.  A test database never has to survive a power cut."""
    connection = _connect(*args, **kwargs)
    connection.execute("PRAGMA synchronous = OFF")
    return connection


sqlite3.connect = _connect_without_fsync


@pytest.fixture(autouse=True)
def english_for_unlabelled_visits(monkeypatch):
    """The app greets a visitor who never chose a language in Ukrainian
    (`i18n.VISITOR_LOCALE`).  The web tests assert English copy, so a client
    that sets no language is English here; the shipped default is asserted by
    `test_a_first_visit_is_in_ukrainian_and_only_a_choice_is_remembered`."""
    from anamna.web import app

    monkeypatch.setattr(app, "VISITOR_LOCALE", "en")
