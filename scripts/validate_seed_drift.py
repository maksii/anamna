"""Does the database still match the files that are meant to define it?

Three kinds of curated content ship in the image and are pushed into the
database at startup: the schema from ``migrations/``, the concept catalogue from
``ingest/concepts.py``, and the clinical guidance from
``data/reference_library.json``.  Nothing stops a row being written directly to
the database instead, and nothing notices afterwards -- the seeding is
idempotent, so it overwrites what it owns and leaves everything else alone.

This reports the everything else:

  1. schema objects that no migration creates, or that a migration creates and
     the database lacks;
  2. concepts with a curated-looking id that no definition describes, which is
     what a concept rename leaves behind -- `stable_concept_id` slugs the
     English name, so renaming mints a new id and abandons the old one;
  3. seeded aliases (``vendor_id IS NULL``) no definition lists;
  4. reference-library entries keyed to a concept id that only ever existed
     because the parser produced a wrong name.  Unmapped ids are uuid5 of the
     printed label, so guidance written against a truncated name is keyed to
     that truncation and can never reach the corrected concept.

Exit code is the number of findings, so CI can gate on it.

    uv run python scripts/validate_seed_drift.py
"""
from __future__ import annotations

import json
import re
import sqlite3
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from anamna.config import ROOT as APP_ROOT, get_settings  # noqa: E402
from anamna.ingest.concepts import CONCEPT_DEFINITIONS, stable_concept_id  # noqa: E402
from anamna.ingest.text import normalized_key  # noqa: E402

UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")


def schema_objects(path: Path) -> dict[tuple[str, str], str]:
    connection = sqlite3.connect(path)
    try:
        return {
            (kind, name): " ".join((sql or "").split())
            for kind, name, sql in connection.execute(
                "SELECT type, name, sql FROM sqlite_master "
                "WHERE name NOT LIKE 'sqlite_%' ORDER BY type, name"
            )
        }
    finally:
        connection.close()


def main() -> int:
    settings = get_settings()
    live = settings.database_path
    if not live.exists():
        print(f"no database at {live}")
        return 0
    findings: list[str] = []
    report: dict[str, object] = {}

    # 1. Schema, against a database built from the migrations alone.
    import os

    # `ignore_cleanup_errors` because SQLite's WAL sidecar is still mapped when
    # the block exits on Windows, and the resulting WinError 32 has nothing to
    # do with what is being measured.
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        fresh = Path(tmp) / "fresh.sqlite3"
        previous = os.environ.get("ANAMNA_DB")
        os.environ["ANAMNA_DB"] = str(fresh)
        try:
            from anamna.db import migrate

            migrate(get_settings())
            live_objects, fresh_objects = schema_objects(live), schema_objects(fresh)
        finally:
            if previous is None:
                os.environ.pop("ANAMNA_DB", None)
            else:
                os.environ["ANAMNA_DB"] = previous

    unmigrated = sorted(f"{k} {n}" for k, n in set(live_objects) - set(fresh_objects))
    unapplied = sorted(f"{k} {n}" for k, n in set(fresh_objects) - set(live_objects))
    redefined = sorted(
        f"{k} {n}"
        for k, n in set(live_objects) & set(fresh_objects)
        if live_objects[(k, n)] != fresh_objects[(k, n)]
    )
    report["schema"] = {
        "in_database_only": unmigrated,
        "in_migrations_only": unapplied,
        "definition_differs": redefined,
    }
    findings += unmigrated + unapplied + redefined

    connection = sqlite3.connect(live)
    connection.row_factory = sqlite3.Row

    # 2. Concepts with a curated-looking id that no definition describes.
    defined = {stable_concept_id(str(d["name"])) for d in CONCEPT_DEFINITIONS}
    undescribed = [
        row["id"]
        for row in connection.execute("SELECT id FROM concepts")
        if not UUID.match(row["id"]) and row["id"] not in defined
    ]
    report["concepts_no_definition_describes"] = undescribed
    findings += undescribed

    # 3. Seeded aliases no definition lists.
    described = {
        (stable_concept_id(str(d["name"])), normalized_key(str(a)))
        for d in CONCEPT_DEFINITIONS
        for a in d["aliases"]
    }
    stray = [
        f"{row['concept_id']} :: {row['alias']}"
        for row in connection.execute(
            "SELECT concept_id, alias, normalized_alias FROM concept_aliases "
            "WHERE vendor_id IS NULL"
        )
        if (row["concept_id"], row["normalized_alias"]) not in described
    ]
    report["seeded_aliases_no_definition_lists"] = stray
    findings += stray

    # 4. Library entries keyed to a name the parser no longer produces.
    library = json.loads(
        (APP_ROOT / "data" / "reference_library.json").read_text(encoding="utf-8")
    )
    used = {row[0] for row in connection.execute("SELECT DISTINCT concept_id FROM observations")}
    known = {row["id"]: row["canonical_name"] for row in connection.execute(
        "SELECT id, canonical_name FROM concepts")}
    artefacts = [
        f"{a['concept_id']} :: {known.get(a['concept_id'], '(no concept row)')}"
        for a in library["analytes"]
        if UUID.match(a["concept_id"]) and a["concept_id"] not in used
    ]
    report["library_entries_keyed_to_a_parser_artefact"] = artefacts
    findings += artefacts
    connection.close()

    report["errors"] = len(findings)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return len(findings)


if __name__ == "__main__":
    raise SystemExit(main())
