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
    from anamna import i18n
    from anamna.web import app

    monkeypatch.setattr(app, "VISITOR_LOCALE", "en")
    # A test that activates a language and fails before switching back left
    # it set for every later test on that worker: English assertions then met
    # Ukrainian labels, but only in a full parallel run.
    token = i18n._locale.set(i18n.DEFAULT_LOCALE)
    yield
    i18n._locale.reset(token)


@pytest.fixture(autouse=True)
def empty_sign_in_meters():
    """Sign-in throttling counts failures per address in a module-level dict.
    Every test client shares one address, and a working sign-in no longer
    resets that address's count, so one test's wrong passwords would lock the
    next test out."""
    from anamna import security

    security._attempts.clear()
    yield
    security._attempts.clear()


@pytest.fixture(autouse=True)
def reference_site_is_never_called(monkeypatch):
    """Saving a linked medicine reads its instruction on a background job.  No
    test may reach the reference site: one that needs a reply fakes the network
    under `drugref._open` (`urllib.request.build_opener`), `drugref._open`
    itself or `drugref.cached_instruction`.  The jobs a test started are waited
    for before the guard is lifted, so none of them calls the real site after
    the test."""
    import urllib.request

    from anamna import drugref, factor_jobs

    real_open, real_opener = drugref._open, urllib.request.build_opener

    def guarded(*args, **kwargs):
        if urllib.request.build_opener is real_opener:
            raise drugref.DrugRefError("the reference site is not called from tests")
        return real_open(*args, **kwargs)

    monkeypatch.setattr(drugref, "_open", guarded)
    yield
    for job_id in list(factor_jobs._JOBS):
        factor_jobs.join(job_id, timeout=10)
