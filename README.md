# Anamna

Anamna is a local-first personal medical record. It keeps your original lab reports, scans and
device exports, reads the values out of them, and shows each result with its history, its source
page and a cited reference interval. The interface is fully bilingual, Ukrainian and English.

Every extracted value stays provisional until a person checks it against the source page. Anamna
organizes evidence; it does not diagnose or replace a clinician.

## Set up

With [uv](https://docs.astral.sh/uv/) and Python 3.12:

```bash
uv sync --locked
uv run anamna-web
```

The server listens on http://127.0.0.1:8000. For OCR of scans and photos, install
[Tesseract](https://tesseract-ocr.github.io/) with the `ukr` and `eng` language data on `PATH`
(on Windows a Tesseract inside WSL is also found).

With Docker (OCR included):

```bash
docker run -d --name anamna -p 127.0.0.1:8000:8000 \
  -v anamna-data:/data \
  ghcr.io/maksii/anamna:latest
```

The image keeps the database and uploaded files on the `/data` volume and carries no health data
itself. It stores health information: put it behind TLS and do not expose it without
authentication in front of it (see [SECURITY.md](SECURITY.md)).

The server runs as an unprivileged user inside the container. On first start it takes ownership of
the `/data` volume, so a volume created by an earlier image keeps working. A ready-made
[compose.yaml](compose.yaml) is in this repository: `docker compose up -d`, then
`docker compose logs anamna` for the first-run setup code.

The compose file runs the container with a read-only root filesystem and without Linux capabilities beyond the four the start-up needs. The server writes only to `/data` and to temporary memory-backed directories. The server prints no access log, because request lines would carry guest-link secrets and search text.

## Configure

Settings come from environment variables. Most integrations are configured later in the
Administration pages, where a saved value wins over the environment.

| Variable | Purpose |
|---|---|
| `ANAMNA_DB` | SQLite database path. Default `data/anamna.sqlite3` (`/data/anamna.sqlite3` in the image). |
| `ANAMNA_SOURCES` | Directory for original files. Default `sources/` (`/data/sources` in the image). |
| `ANAMNA_SECRET` | Optional. Secret that keys the stored hashes of one-time doctor codes. Unset, a random one is generated on first start and kept in `secret.key` beside the database; back that file up together with the database. |
| `ANAMNA_SECURE_COOKIES` | `1` when TLS terminates at a proxy in front of the app, so the session cookie is always marked `Secure`. It also turns on the `Strict-Transport-Security` header. |
| `ANAMNA_SETUP_CODE` | Optional first-run setup code. Unset, one is generated and printed to the log. |
| `ANAMNA_AGENT_TOKEN` | Optional operator-pinned `anamna_agent_` credential, recreated on every start. |
| `ANAMNA_PUBLIC_URL` | Public origin used for OAuth redirects and links (Oura, Garmin, Telegram). |
| `ANAMNA_LOG_LEVEL` | Log level, default `INFO`. |
| `ANAMNA_BACKGROUND_WORKERS` | `0` disables all background workers (for an isolated test instance). |
| `ANAMNA_OPENWEARABLES_WORKER` | `0` pauses only the OpenWearables worker. |
| `PORT` | Port for `anamna-web`, default `8000`. |
| `ANAMNA_ALLOW_ROOT` | `1` lets the container keep running as root when it cannot take ownership of the data volume (some network shares). Without it the container stops instead. |
| `FORWARDED_ALLOW_IPS` | Address of your reverse proxy, so the server trusts its `X-Forwarded-*` headers (read by uvicorn). |

A sign-in session lasts 14 days. `anamna-web` listens on 127.0.0.1 only; the container image listens on all interfaces of the container.

Integration credentials (all optional): `ANAMNA_OURA_CLIENT_ID`, `ANAMNA_OURA_CLIENT_SECRET`,
`ANAMNA_GARMIN_CLIENT_ID`, `ANAMNA_GARMIN_CLIENT_SECRET`, `ANAMNA_GARMIN_PERSONAL` (`1` offers
Garmin Personal API keys), `ANAMNA_OPENWEARABLES_URL`, `ANAMNA_OPENWEARABLES_API_KEY`,
`ANAMNA_OPENWEARABLES_WEBHOOK_TOKEN`, `ANAMNA_TELEGRAM_BOT_TOKEN`,
`ANAMNA_TELEGRAM_BOT_USERNAME`, `ANAMNA_TELEGRAM_WEBHOOK_SECRET`, `PAPERLESS_URL`, and the AI keys
`OPENROUTER_API_KEY`, `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`.

## First run

On an empty database every page leads to `/setup`, which creates the administrator account and
that person's record. It asks for a one-time setup code, so whoever reaches a fresh server first
cannot claim it. Find the code in the server log:

```text
First-run setup code: 1a2b-3c4d-5e6f-7a8b
```

In a container, read it with `docker logs anamna`. If `ANAMNA_SETUP_CODE` is set, that value is
the code and it is never printed. Once the first account exists, `/setup` sends visitors to the
sign-in page, and sign-up stays closed until the administrator opens it or adds people.

On the server itself, the CLI does the same without a code:

```bash
uv run anamna init --email you@example.com --name "Your name"
```

In a container the same command is `docker exec -it anamna /app/.venv/bin/anamna init --email you@example.com --name "Your name"`. It asks for the password, so it needs `-it`. With `docker compose` the container name comes from compose, so run `docker compose exec anamna /app/.venv/bin/anamna init --email you@example.com --name "Your name"` instead. `init` refuses an email that already has an account.

## Lost access

- **Lost the first-run setup code.** Restart the server while the database has no accounts: a new code is printed to the log on start (`docker logs anamna` in a container). Or set `ANAMNA_SETUP_CODE` before the first start. Or create the first account with `anamna init`, as above.
- **A person forgot their password.** An administrator sets a new one on the Users page, `/admin/users`.
- **The only administrator forgot theirs.** On the server, run `anamna set-password --email you@example.com --admin` (with uv: `uv run anamna set-password ...`). It asks for the new password twice and ends every session of that account. With `--admin` it also makes the account an administrator and re-enables it. In a container: `docker exec -it anamna /app/.venv/bin/anamna set-password --email you@example.com --admin`. Without a terminal, pass the password in the environment variable `ANAMNA_NEW_PASSWORD`: `docker exec -e ANAMNA_NEW_PASSWORD=... anamna /app/.venv/bin/anamna set-password --email you@example.com`.

## Backup, restore and upgrade

- **What to back up.** The database, the `sources/` directory with the original files, and `secret.key`. In the image all three are under `/data`: `/data/anamna.sqlite3`, `/data/sources` and `/data/secret.key`.
- **Take the backup with `anamna backup`.** Do not copy the database file of a running server. It uses SQLite's WAL mode, and a plain copy can be torn. `anamna backup --to DIR` writes a consistent copy of the database as `anamna-YYYYMMDD-HHMMSS.sqlite3`, copies `secret.key`, and copies `sources/` unless `--no-sources` is given. In a container: `docker exec anamna /app/.venv/bin/anamna backup --to /data/backup --no-sources`, then copy `/data/backup` and `/data/sources` off the host with your usual file backup.
- A backup holds health data and the stored credentials of connected services. Keep it encrypted; see [SECURITY.md](SECURITY.md).
- **Restore.** Stop the server. Put the database copy back as the database file (`/data/anamna.sqlite3` in the image), put back `sources/` and `secret.key`, and start the server.
- **Upgrade.** Take a backup, then pull the new image and start it: `docker compose pull`, then `docker compose up -d`. Database migrations run on start, each in one transaction. A database last opened by a newer version is refused with a message that says so. There is no downgrade: to go back, restore the backup and run the previous image tag. CI tags each image with its commit, as `ghcr.io/maksii/anamna:<sha>`.

## Your data

On the Profile page, under the security tab, a person can:

- change the address they sign in with, using the current password;
- download a ZIP of their own record: the original files they uploaded, device exports included, and CSV copies of their results, documents, vaccinations and device data, with a `manifest.json`;
- delete their account. Deleting needs the password and the address typed in full. An administrator can delete their own account only while another enabled administrator exists. Before the account is removed, its Oura, Garmin and OpenWearables links are disconnected, best effort. The account's rows and the original document files that no other account uses are removed. Device exports uploaded through the application are removed with the account. A folder an operator placed in `sources/` by hand and imported from the command line stays there for the operator to remove.

These panels are not offered to a guest link or while someone views a shared record. The download always covers the signed-in account, never the record being viewed.

An operator exports one account's whole record with `anamna export --email you@example.com --to record.zip`. An existing file is not overwritten. The ZIP holds CSV files of the observations, documents, vaccinations and device data, a `manifest.json`, and the original uploaded files in its `files/` folder. To move a record to another installation, upload those original files there.

## Sharing a record

A record can be shared with another account on the same server, read only or with full access. Read only shows everything the owner sees. Full access also lets that person ask the AI assistant about the record and order laboratory tests through the owner's laboratory account. Nobody a record is shared with can change it. A read-only viewer can save a selection of tests as a suggestion for the owner, the same way a doctor with a one-time code can. Shares that existed before the read-only level was added keep full access. A new share is read only unless its owner chooses full access.

## Ways to get data in

- **File upload** (web, and Telegram): PDF, JPEG, PNG and TIFF, read from native text with OCR for
  scans and photos; ZIP archives are unpacked, and device exports inside are recognized.
- **Apple Health export** (`export.zip` / `export.xml`, ECG CSVs, workout routes).
- **Garmin account export** (JSON, CSV and FIT archives).
- **Oura export** (API-shaped JSON/CSV or the Takeout `data.zip`).
- **Kardia** ECG PDF reports.
- **Oura API**: OAuth connection with webhook updates.
- **Garmin API**: Personal API keys (pull, per person) and the Connect Developer Program
  (OAuth with push webhooks).
- **OpenWearables**: a self-hosted aggregation server; linked accounts are pulled and receive
  signed webhooks.
- **Ukrainian lab and clinic accounts**: Esculab, Synevo, Expert Hospital and the
  Doctor Eleks clinics St. Paraskeva and Veselka. Finished orders arrive as their official PDFs,
  and the lab's own values cross-check what was read.
- **Telegram bot**: send documents and photos, look up results, request originals.
- **Vaccination records**: form 063/о scans are read, and doses can be entered by hand.
- **CLI**: `anamna ingest` (a directory of documents), `anamna devices import --vendor
  apple_health|garmin|oura|kardia --path <export>`, `anamna lab-sync --provider esculab|synevo`.

Other integrations:

- **Paperless-ngx**: mirrors your documents into your own Paperless account and adds its
  full-text search matches. Paperless is never a source of values.
- **AI assist** (OpenRouter by default, Anthropic, OpenAI): optional transcription review of
  documents, suggested titles and metadata, and a plain-language summary of changes. Its output is
  a suggestion and never marks anything verified. Requests to OpenRouter go only to providers that
  do not store prompts or train on them, unless an administrator allows otherwise on the AI page.

Anamna can merge many overlapping sources, but imported data is still best checked by you: use
your own agent or tools to fix, verify and map what was imported, and verify values against the
source pages in the review queue.

**Fasting and pregnancy.** A blood glucose result is judged against fasting ranges unless you mark its sample as not fasting. On a test's page that has fasting ranges, each result has a choice: Fasting, Not fasting or Not sure. A date in the Expected due date field of the Profile page makes Anamna treat results dated within the 280 days before it as taken during pregnancy. Ranges written for people who are not pregnant do not judge those results.

Details: [device imports](docs/device-imports.md), [lab sync](docs/lab-sync.md),
[Oura and Garmin](docs/provider-integrations.md), [OpenWearables](docs/openwearables-webhooks.md),
[Telegram](docs/telegram.md), [architecture](docs/architecture.md),
[extraction and verification](docs/extraction-and-verification.md).

## License and contributing

Anamna is licensed under the [GNU AGPL v3.0 only](LICENSE). See [CONTRIBUTING.md](CONTRIBUTING.md)
to contribute and [SECURITY.md](SECURITY.md) to report a vulnerability.
