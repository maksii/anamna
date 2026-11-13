"""Keeps the possible diagnoses and the candidate list in step with the record.

A refresh reads the owner's results, documents, findings and diagnoses, so it
runs only when a fingerprint of those inputs has changed.  The Diagnoses page
asks for one before it renders; a background thread asks every minute for
every account, so a result that arrives without a page view still raises its
possible diagnosis.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from datetime import date

from .. import diagnosis_candidates, diagnosis_matrix
from ..db import connect, utc_now

_LOG = logging.getLogger(__name__)
INTERVAL = 60.0

# ponytail: one pass over every account per minute; a per-owner schedule would
# only matter with many accounts.


def _count_and_latest(connection, table: str, owner_id: str) -> tuple:
    return connection.execute(
        f"SELECT COUNT(*), MAX(created_at) FROM {table} WHERE owner_user_id = ?", (owner_id,),
    ).fetchone()


def _diagnosis_counts(connection, owner_id: str) -> tuple:
    return connection.execute(
        "SELECT COUNT(*), MAX(updated_at) FROM diagnoses WHERE owner_user_id = ?", (owner_id,),
    ).fetchone()


def _patient_inputs(connection, owner_id: str) -> tuple:
    row = connection.execute(
        "SELECT date_of_birth, sex_at_birth, pregnancy_due_date, cv_risk_category FROM patients "
        "WHERE owner_user_id = ? ORDER BY created_at LIMIT 1",
        (owner_id,),
    ).fetchone()
    return tuple(row) if row is not None else (None, None, None, None)


def fingerprint(connection, owner_id: str) -> str:
    """One string that changes whenever a refresh could give a different answer."""
    parts: list = [date.today().isoformat(), len(diagnosis_matrix.RULES)]
    for table in ("observations", "device_metric_days", "clinical_findings"):
        parts.extend(_count_and_latest(connection, table, owner_id))
    parts.append(
        connection.execute("SELECT COUNT(*) FROM documents WHERE owner_user_id = ?", (owner_id,)).fetchone()[0]
    )
    parts.extend(_diagnosis_counts(connection, owner_id))
    parts.extend(_patient_inputs(connection, owner_id))
    parts.append(connection.execute("SELECT COUNT(*) FROM curated_reference_rules").fetchone()[0])
    return "|".join(str(part) for part in parts)


def refresh_if_changed(settings, connection, owner_id: str, matrix_cards: Callable, *, force: bool = False) -> bool:
    """Re-collect the candidates and re-match the possible diagnoses when an input changed.

    ``matrix_cards(connection, owner_id)`` gives the English metric cards.  Commits when it runs.
    Returns True when it ran.  ``settings`` is accepted for symmetry with the other jobs.
    """
    current = fingerprint(connection, owner_id)
    row = connection.execute(
        "SELECT fingerprint FROM diagnosis_refresh WHERE owner_user_id = ?", (owner_id,),
    ).fetchone()
    if not force and row is not None and row[0] == current:
        return False
    diagnosis_candidates.collect(connection, owner_id)
    cards = matrix_cards(connection, owner_id)
    diagnosis_matrix.refresh(connection, owner_id, cards, today=date.today())
    connection.execute(
        "INSERT OR REPLACE INTO diagnosis_refresh(owner_user_id, fingerprint, refreshed_at) VALUES (?, ?, ?)",
        (owner_id, fingerprint(connection, owner_id), utc_now()),
    )
    connection.commit()
    return True


def last_refreshed(connection, owner_id: str) -> str | None:
    """When the owner's possible diagnoses were last brought up to date, or None."""
    row = connection.execute(
        "SELECT refreshed_at FROM diagnosis_refresh WHERE owner_user_id = ?", (owner_id,),
    ).fetchone()
    return row[0] if row is not None else None


def _refresh_all(settings, matrix_cards: Callable) -> None:
    """One pass over every account; a failure for one account does not stop the others."""
    try:
        with connect(settings) as connection:
            owners = [row[0] for row in connection.execute("SELECT id FROM users")]
    except Exception as exc:
        _LOG.warning("diagnoses refresh failed: %s", type(exc).__name__)
        return
    for owner_id in owners:
        try:
            with connect(settings) as connection:
                refresh_if_changed(settings, connection, owner_id, matrix_cards)
        except Exception as exc:
            _LOG.warning("diagnoses refresh failed: %s", type(exc).__name__)


def start_scheduler(settings, matrix_cards: Callable, *, interval: float = INTERVAL) -> threading.Event:
    """Refresh every account now and then every ``interval`` seconds, on a daemon thread.

    Set the returned event to stop the thread after its current pass.
    """
    stop = threading.Event()

    def run() -> None:
        while True:
            _refresh_all(settings, matrix_cards)
            if stop.wait(interval):
                return

    threading.Thread(target=run, name="diagnoses-refresh", daemon=True).start()
    return stop
