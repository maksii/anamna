from __future__ import annotations

import argparse
import getpass
import json
import sys
import uuid
from pathlib import Path

from .config import get_settings
from .db import connect, migrate, utc_now
from .devices import import_device_export
from .ingest.pipeline import audit_inventory, ingest_directory
from .security import create_user


def ensure_patient(user_id: str, display_name: str, dob: str | None, sex: str | None) -> str:
    settings = get_settings()
    with connect(settings) as connection:
        existing = connection.execute(
            "SELECT id FROM patients WHERE owner_user_id=? ORDER BY created_at LIMIT 1", (user_id,)
        ).fetchone()
        if existing:
            return existing["id"]
        patient_id = str(uuid.uuid4())
        connection.execute(
            """INSERT INTO patients(id, owner_user_id, display_name, date_of_birth, sex_at_birth, created_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (patient_id, user_id, display_name, dob, sex, utc_now()),
        )
        return patient_id


def user_by_email(email: str):
    with connect(get_settings()) as connection:
        return connection.execute(
            "SELECT * FROM users WHERE email=? COLLATE NOCASE", (email,)
        ).fetchone()


def command_init(args: argparse.Namespace) -> None:
    settings = get_settings()
    migrate(settings)
    password = args.password or getpass.getpass("Password (10+ characters): ")
    existing = user_by_email(args.email)
    user_id = existing["id"] if existing else create_user(settings, args.email, args.name, password)
    patient_id = ensure_patient(user_id, args.patient_name or args.name, args.dob, args.sex)
    print(json.dumps({"user_id": user_id, "patient_id": patient_id}, indent=2))


def command_ingest(args: argparse.Namespace) -> None:
    settings = get_settings()
    migrate(settings)
    user = user_by_email(args.email)
    if not user:
        raise SystemExit(f"No user found for {args.email}; run init first")
    patient_id = ensure_patient(user["id"], user["display_name"], None, None)
    results = ingest_directory(
        settings,
        user["id"],
        patient_id,
        Path(args.source_dir) if args.source_dir else None,
        run_ocr=not args.no_ocr,
    )
    print(json.dumps(results, ensure_ascii=False, indent=2))


def command_audit(args: argparse.Namespace) -> None:
    settings = get_settings()
    user = user_by_email(args.email)
    if not user:
        raise SystemExit(f"No user found for {args.email}")
    payload = json.dumps(audit_inventory(settings, user["id"]), ensure_ascii=False, indent=2)
    if args.output:
        path = Path(args.output)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(payload + "\n", encoding="utf-8")
    else:
        print(payload)


def command_device_import(args: argparse.Namespace) -> None:
    settings = get_settings()
    migrate(settings)
    user = user_by_email(args.email)
    if not user:
        raise SystemExit(f"No user found for {args.email}; run init first")
    patient_id = ensure_patient(user["id"], user["display_name"], None, None)
    result = import_device_export(
        settings,
        owner_user_id=user["id"],
        patient_id=patient_id,
        vendor_key=args.vendor,
        source=Path(args.path),
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


def _environment_credential(key: str) -> tuple[str | None, str | None]:
    """The credential given through the environment, or ``(None, None)``."""
    import os

    from . import labsync

    # Esculab signs in with a texted code on the profile; it has no
    # credential that could be pasted into the environment.
    form = {"token": os.getenv("SYNEVO_SESSION", "") if key == "synevo" else ""}
    if not form["token"]:
        return None, None
    try:
        parsed = labsync.provider(key).parse_credentials(form)
    except labsync.LabSyncError as exc:
        raise SystemExit(f"{exc.key}: the credential in the environment is not usable") from None
    return parsed["secret"], parsed["phone"]


def _chosen_person(settings, user_id: str, key: str, secret, phone, args: argparse.Namespace) -> dict:
    """The lab person ``--patient-id`` names, refused when it disagrees with the profile."""
    from . import labsync

    stored = labsync.account(settings, user_id, key)
    client = labsync.provider(key).Client(
        labsync.provider_settings(settings, key)["url"], secret or (stored["secret"] if stored else ""),
        phone or (stored["phone"] if stored else ""))
    try:
        people, _ = client.check()
    except labsync.LabSyncError as exc:
        raise SystemExit(exc.key) from None
    person = next((entry for entry in people if entry["id"] == args.patient_id), None)
    if person is None:
        raise SystemExit("labsync.error_patient_unknown")
    with connect(settings) as connection:
        patient = labsync._patient(connection, user_id)
    if not labsync.demographics(person, patient)["ok"] and not args.confirm_person_mismatch:
        raise SystemExit("labsync.error_confirm: date of birth or sex differs from the profile; "
                         "pass --confirm-person-mismatch if these really are this person's results")
    return person


def command_lab_sync(args: argparse.Namespace) -> None:
    """Sync one person's orders from a lab connection, as the profile's
    "Sync now" does, on this thread.  The credential comes from the stored
    connection (Esculab signs in on the profile with phone and a texted code)
    or, for Synevo, from SYNEVO_SESSION in the environment; it is never
    printed."""
    from . import labsync

    settings = get_settings()
    migrate(settings)
    user = user_by_email(args.email)
    if not user:
        raise SystemExit(f"No user found for {args.email}")
    key = args.provider
    secret, phone = _environment_credential(key)
    person = None
    if args.patient_id:
        person = _chosen_person(settings, user["id"], key, secret, phone, args)
    try:
        summary = labsync.sync(settings, user["id"], key, secret=secret, phone=phone, person=person, inline=True)
    except labsync.LabSyncError as exc:
        raise SystemExit(exc.key) from None
    print(json.dumps(summary, ensure_ascii=False, indent=2))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="anamna")
    subparsers = parser.add_subparsers(required=True)
    init = subparsers.add_parser("init", help="Create the database, owner account and patient profile")
    init.add_argument("--email", required=True)
    init.add_argument("--name", required=True)
    init.add_argument("--patient-name")
    init.add_argument("--dob")
    init.add_argument("--sex", choices=["female", "male", "intersex", "unknown"])
    init.add_argument("--password")
    init.set_defaults(func=command_init)
    ingest = subparsers.add_parser("ingest", help="Classify and ingest supported source documents")
    ingest.add_argument("--email", required=True)
    ingest.add_argument("--source-dir")
    ingest.add_argument("--no-ocr", action="store_true")
    ingest.set_defaults(func=command_ingest)
    audit = subparsers.add_parser("audit", help="Export document classification and extraction inventory")
    audit.add_argument("--email", required=True)
    audit.add_argument("--output")
    audit.set_defaults(func=command_audit)
    devices = subparsers.add_parser("devices", help="Import Apple Health, Oura, Garmin or Kardia exports")
    device_commands = devices.add_subparsers(required=True)
    device_import = device_commands.add_parser("import", help="Import a device export")
    device_import.add_argument("--email", required=True)
    device_import.add_argument("--vendor", required=True, choices=["apple_health", "oura", "garmin", "kardia"])
    device_import.add_argument("--path", required=True)
    device_import.set_defaults(func=command_device_import)
    lab = subparsers.add_parser("lab-sync", help="Sync results from a lab connection (Esculab, Synevo)")
    lab.add_argument("--provider", required=True, choices=["esculab", "synevo"])
    lab.add_argument("--email", required=True)
    lab.add_argument("--patient-id", help="The lab's person id; defaults to the one chosen on the profile")
    lab.add_argument("--confirm-person-mismatch", action="store_true")
    lab.set_defaults(func=command_lab_sync)
    return parser


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    args = build_parser().parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
