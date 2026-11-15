"""Aggregate-only connection audit; never prints patient values or labels.

Use a copied database. --refresh takes an online backup, applies the normal
startup repair and derived refresh, and verifies original measurements stay
unchanged. The immutable source snapshot is not modified.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
from collections import Counter
from pathlib import Path

from anamna.config import Settings
from anamna.db import connect, migrate
from anamna.ingest.concepts import CONCEPT_DEFINITIONS, stable_concept_id
from anamna.ingest.pipeline import repair_observation_semantics
from anamna.panels import PANELS, SAME_DEVICE_KEYS


def _content(db, device=False):
    if device:
        query = "SELECT id,owner_user_id,patient_id,metric_key,day,unit,value FROM device_metric_days WHERE substr(id,1,12)<>'derived-bmi-' ORDER BY id"
    else:
        query = "SELECT id,owner_user_id,patient_id,value_numeric,value_text,unit_raw,observed_at,verification_status FROM observations WHERE substr(extraction_method,1,8)<>'derived_' ORDER BY id"
    return hashlib.sha256(json.dumps([tuple(row) for row in db.execute(query)], ensure_ascii=True).encode()).hexdigest()


def audit(db):
    seeded = {stable_concept_id(str(item["name"])) for item in CONCEPT_DEFINITIONS}
    keys = {str(row[0]) for row in db.execute("SELECT DISTINCT metric_key FROM device_metric_days")}
    panel_keys = {key for panel in PANELS for key in panel.device_members} | set(SAME_DEVICE_KEYS)
    active = db.execute("SELECT concept_id,category FROM observations o LEFT JOIN concepts c ON c.id=o.concept_id WHERE verification_status<>'rejected'").fetchall()
    return {
        "documents": db.execute("SELECT COUNT(*) FROM documents").fetchone()[0],
        "observations": db.execute("SELECT COUNT(*) FROM observations").fetchone()[0],
        "device_days": db.execute("SELECT COUNT(*) FROM device_metric_days").fetchone()[0],
        "device_metrics": len(keys), "device_metrics_without_panel": sorted(keys - panel_keys),
        "active_seeded_observations": sum(row[0] in seeded for row in active),
        "active_unmapped_observations": sum(row[1] == "unmapped" for row in active),
        "active_dynamic_observations": sum(row[0] not in seeded for row in active),
        "derived_by_method": dict(db.execute("SELECT extraction_method,COUNT(*) FROM observations WHERE substr(extraction_method,1,8)='derived_' GROUP BY extraction_method")),
        "calculated_device_bmi": db.execute("SELECT COUNT(*) FROM device_metric_days WHERE substr(id,1,12)='derived-bmi-'").fetchone()[0],
        "foreign_key_errors": len(db.execute("PRAGMA foreign_key_check").fetchall()),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--refresh", action="store_true")
    parser.add_argument("--backup-dir", type=Path, default=Path("work/db-archive"))
    args = parser.parse_args()
    path = args.db.resolve()
    if not path.is_file():
        raise SystemExit("Database must already exist")
    with sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True) as db:
        db.row_factory = sqlite3.Row
        before = audit(db)
        source_content = _content(db), _content(db, True)
        if args.refresh:
            # Private records are restricted to ignored scratch paths.
            root = Path(__file__).resolve().parents[1]
            if not path.is_relative_to(root / "work") or path.is_relative_to(root / "work/db-archive"):
                raise SystemExit("--refresh requires a working copy under work/, outside db-archive")
            args.backup_dir.mkdir(parents=True, exist_ok=True)
            backup = args.backup_dir / "device-audit-before-refresh.sqlite3"
            if backup.exists():
                with sqlite3.connect(backup) as target:
                    if (_content(target), _content(target, True)) != source_content:
                        raise SystemExit("Backup differs; refusing overwrite")
            else:
                with sqlite3.connect(backup) as target:
                    db.backup(target)
            with (args.backup_dir / "README.md").open("a", encoding="utf-8") as f:
                f.write("\n- 2026-11-15: device-audit-before-refresh.sqlite3 backs up the hosted-sandbox working copy before metric repair/backfill; removable after audit acceptance. Private health data.\n")
    result = {"before": before}
    if args.refresh:
        settings = Settings(database_path=path, source_dir=path.parent / "sources", secret_key="isolated-audit-copy")
        migrate(settings)
        with connect(settings) as db:
            methods_before = Counter(row[0] for row in db.execute("SELECT extraction_method FROM observations"))
            result["remapped_or_folded"] = repair_observation_semantics(db)
            result["after"] = audit(db)
            result["original_observations_unchanged"] = _content(db) == source_content[0]
            result["original_device_values_unchanged"] = _content(db, True) == source_content[1]
            methods_after = Counter(row[0] for row in db.execute("SELECT extraction_method FROM observations"))
            result["method_count_changes"] = {key: methods_after[key] - methods_before[key] for key in methods_after.keys() | methods_before.keys() if methods_after[key] != methods_before[key]}
            if not all(result[key] for key in ("original_observations_unchanged", "original_device_values_unchanged")):
                raise RuntimeError("Original measurement content changed; inspect private backup before accepting")
    print(json.dumps(result, ensure_ascii=True, indent=2))


if __name__ == "__main__":
    main()
