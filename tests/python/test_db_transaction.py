"""A unit of work waits for the write lock instead of failing when another
connection commits between its read and its write (sandbox, 2026-11-06:
the lab re-check answered 500 "database is locked" when an Oura sync
committed in the middle of it)."""

import threading
from pathlib import Path

from anamna.config import Settings
from anamna.db import connect, transaction


def test_read_then_write_survives_a_commit_in_between(tmp_path: Path):
    settings = Settings(database_path=tmp_path / "t.sqlite3", source_dir=tmp_path, secret_key="x")
    with connect(settings) as db:
        db.execute("CREATE TABLE t(n INTEGER)")
        db.execute("INSERT INTO t VALUES (0)")
    read_done, other_done = threading.Event(), threading.Event()

    def other_writer():
        read_done.wait(5)
        try:
            # Under IMMEDIATE this waits until the unit below commits; with a
            # deferred BEGIN it commits in the middle of that unit.
            with transaction(settings) as db:
                db.execute("UPDATE t SET n=n+1")
        finally:
            other_done.set()

    thread = threading.Thread(target=other_writer)
    thread.start()
    with transaction(settings) as db:
        value = db.execute("SELECT n FROM t").fetchone()[0]
        read_done.set()
        other_done.wait(1.0)  # give the other writer its chance to commit first
        db.execute("UPDATE t SET n=?", (value + 10,))
    thread.join()
    with connect(settings) as db:
        assert db.execute("SELECT n FROM t").fetchone()[0] == 11
