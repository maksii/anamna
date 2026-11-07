"""CLI for the curated reference library loader.

The loader itself lives in :mod:`anamna.reference` because the ingest
pipeline seeds the library on start-up; this script is the operator entry
point for re-seeding after editing ``data/reference_library.json``.

    uv run python scripts/seed_reference_library.py [--library PATH]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from anamna.config import get_settings  # noqa: E402
from anamna.db import connect, migrate  # noqa: E402
from anamna.reference import (  # noqa: E402
    LIBRARY_PATH,
    load_library,
    seed_reference_library,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Seed the curated reference library")
    parser.add_argument("--library", type=Path, default=LIBRARY_PATH)
    args = parser.parse_args(argv)
    settings = get_settings()
    migrate(settings)
    with connect(settings) as connection:
        with connection:
            counts = seed_reference_library(connection, load_library(args.library))
    print(json.dumps(counts, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
