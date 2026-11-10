from __future__ import annotations

import re
import sqlite3
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Iterator

from .config import Settings, get_settings, resource_path


MIGRATIONS_DIR = resource_path("migrations")
#: A migration that opens its own transaction or sets a PRAGMA (which a
#: wrapping transaction silently ignores) runs as written.  A trigger body's
#: BEGIN on its own line also matches, so such a file is simply not wrapped.
_SELF_MANAGED = re.compile(r"^\s*(BEGIN|COMMIT|PRAGMA)\b", re.IGNORECASE | re.MULTILINE)


def utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def connect(settings: Settings | None = None) -> sqlite3.Connection:
    settings = settings or get_settings()
    settings.database_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(settings.database_path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA journal_mode = WAL")
    connection.execute("PRAGMA busy_timeout = 5000")
    return connection


@contextmanager
def transaction(
    settings: Settings | None = None, immediate: bool = True
) -> Iterator[sqlite3.Connection]:
    """A committed-or-rolled-back unit of work.

    ``BEGIN IMMEDIATE`` by default.  A plain ``BEGIN`` is deferred: it takes
    its read lock first and asks for the write lock later, and if another
    connection wrote in between, SQLite cannot safely retry and returns
    "database is locked" at once, ignoring ``busy_timeout``.  With several
    background writers (archive compaction, wearable syncs, re-reads) that was
    an admin action failing with a 500 the moment a sync committed.  IMMEDIATE
    takes the write lock up front, which is what the timeout can wait on; under
    WAL it never blocks readers.  Pass ``immediate=False`` only for a block
    that is known never to write.
    """
    connection = connect(settings)
    try:
        connection.execute("BEGIN IMMEDIATE" if immediate else "BEGIN")
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def migrate(settings: Settings | None = None) -> None:
    settings = settings or get_settings()
    connection = connect(settings)
    try:
        connection.execute(
            "CREATE TABLE IF NOT EXISTS schema_migrations (version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)"
        )
        applied = {row[0] for row in connection.execute("SELECT version FROM schema_migrations")}
        for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
            version = int(path.name.split("_", 1)[0])
            if version in applied:
                continue
            script = path.read_text(encoding="utf-8")
            record = (
                "INSERT INTO schema_migrations(version, applied_at) "
                f"VALUES ({version}, '{utc_now()}');"
            )
            if _SELF_MANAGED.search(script):
                # Opens its own transaction or sets a PRAGMA that a wrapping
                # transaction would silence: runs as written.
                connection.executescript(script)
                connection.executescript(record)
                continue
            try:
                # One transaction per migration, version row included: a
                # failure half-way leaves nothing behind, so the next start
                # runs the same file again from a clean schema.
                connection.executescript(f"BEGIN IMMEDIATE;\n{script}\n{record}\nCOMMIT;")
            except BaseException:
                if connection.in_transaction:
                    connection.rollback()
                raise
        connection.execute("PRAGMA optimize")
        connection.commit()
    finally:
        connection.close()
