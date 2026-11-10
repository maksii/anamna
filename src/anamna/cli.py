from __future__ import annotations

import argparse
import getpass
import json
import shutil
import sqlite3
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import NoReturn

from .config import SECRET_FILE, env, get_settings
from .db import connect, migrate, transaction, utc_now
from .devices import import_device_export
from .export import write_record_archive
from .ingest.pipeline import audit_inventory, ingest_directory
from .security import MINIMUM_PASSWORD_LENGTH, create_user, set_password


def _refuse(message: str) -> NoReturn:
    """Say why nothing was changed on stderr, and exit with status 1."""
    print(message, file=sys.stderr)
    raise SystemExit(1)


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
    if user_by_email(args.email):
        _refuse(
            "An account with this email already exists; nothing was changed. "
            f"To change its password run: anamna set-password --email {args.email}"
        )
    password = args.password or getpass.getpass("Password (10+ characters): ")
    user_id = create_user(settings, args.email, args.name, password)
    patient_id = ensure_patient(user_id, args.patient_name or args.name, args.dob, args.sex)
    print(json.dumps({"user_id": user_id, "patient_id": patient_id}, indent=2))


def command_set_password(args: argparse.Namespace) -> None:
    settings = get_settings()
    user = user_by_email(args.email)
    if not user:
        _refuse("No account with this email.")
    # The environment carries the new password under `docker exec`, where no
    # terminal is attached; a command-line argument would sit in shell history.
    password = env("NEW_PASSWORD")
    if not password:
        password = getpass.getpass("New password: ")
        if password != getpass.getpass("Repeat it: "):
            _refuse("The two entries differ; nothing was changed.")
    if len(password) < MINIMUM_PASSWORD_LENGTH:
        _refuse(f"The password must be at least {MINIMUM_PASSWORD_LENGTH} characters; nothing was changed.")
    # Ends every session of the account, as the profile page's password change does.
    set_password(settings, user["id"], password)
    message = f"Password changed for {user['email']}. All its sessions were ended."
    if args.admin:
        # A sole administrator locked out by a disabled flag or a lost role can
        # come back in through here; the change is one transaction.
        with transaction(settings) as connection:
            connection.execute("UPDATE users SET role = 'admin', disabled_at = NULL WHERE id = ?", (user["id"],))
        message += " The account is now an administrator."
    print(message)


def command_backup(args: argparse.Namespace) -> None:
    settings = get_settings()
    if not settings.database_path.is_file():
        raise SystemExit(f"No database at {settings.database_path}; nothing to back up.")
    target = Path(args.to).resolve()
    sources = settings.source_dir.resolve()
    if target.is_relative_to(sources) or target == settings.database_path.resolve():
        raise SystemExit("The backup directory must not be inside the sources directory or be the database file.")
    if not args.no_sources and target / "sources" == sources:
        raise SystemExit("The backup's sources copy would land on the sources directory itself; choose another directory.")
    target.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    database_copy = target / f"anamna-{stamp}.sqlite3"
    if database_copy.exists():
        raise SystemExit(f"{database_copy} already exists; wait a second and run the backup again.")
    # SQLite's online backup is consistent while the server is writing; a file copy is not.
    source = sqlite3.connect(settings.database_path)
    destination = sqlite3.connect(database_copy)
    try:
        source.backup(destination)
    finally:
        destination.close()
        source.close()
    lines = [f"Database: {database_copy}"]
    key = settings.database_path.parent / SECRET_FILE
    if key.is_file():
        shutil.copy2(key, target / SECRET_FILE)
        lines.append(f"Secret key: {target / SECRET_FILE}")
    if args.no_sources:
        lines.append(f"Original files were not copied: back up {settings.source_dir} separately.")
    else:
        if settings.source_dir.is_dir():
            shutil.copytree(settings.source_dir, target / "sources", dirs_exist_ok=True)
            lines.append(f"Sources: {target / 'sources'}")
    print("\n".join(lines))


def command_export(args: argparse.Namespace) -> None:
    settings = get_settings()
    user = user_by_email(args.email)
    if not user:
        _refuse("No account with this email.")
    path = Path(args.to)
    try:
        handle = path.open("xb")
    except FileExistsError:
        _refuse(f"{path} already exists; nothing was written.")
    with handle:
        try:
            counts = write_record_archive(settings, user["id"], handle)
        except BaseException:
            handle.close()
            path.unlink(missing_ok=True)
            raise
    print(", ".join(f"{name} {count}" for name, count in counts.items()) + f"; written to {path}")


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
    set_password_parser = subparsers.add_parser(
        "set-password",
        help="Set an account's password, ending its sessions (reads ANAMNA_NEW_PASSWORD or prompts)",
    )
    set_password_parser.add_argument("--email", required=True)
    set_password_parser.add_argument(
        "--admin", action="store_true",
        help="Also make the account an administrator and re-enable it, to recover a locked-out installation",
    )
    set_password_parser.set_defaults(func=command_set_password)
    backup = subparsers.add_parser(
        "backup", help="Copy the database, its secret key and the original files into a directory",
    )
    backup.add_argument("--to", required=True, help="Directory to write into (created if missing)")
    backup.add_argument("--no-sources", action="store_true", help="Do not copy the original files")
    backup.set_defaults(func=command_backup)
    export = subparsers.add_parser("export", help="Write one account's whole record as a ZIP archive")
    export.add_argument("--email", required=True)
    export.add_argument("--to", required=True, help="The ZIP file to create; an existing file is not overwritten")
    export.set_defaults(func=command_export)
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


def main(argv: list[str] | None = None) -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    args = build_parser().parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
