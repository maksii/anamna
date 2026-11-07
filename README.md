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
  -e ANAMNA_SECRET="$(openssl rand -hex 32)" \
  ghcr.io/maksii/anamna:latest
```

The image keeps the database and uploaded files on the `/data` volume and carries no health data
itself. It stores health information: put it behind TLS and do not expose it without
authentication in front of it (see [SECURITY.md](SECURITY.md)).

## Configure

Settings come from environment variables. Most integrations are configured later in the
Administration pages, where a saved value wins over the environment.

| Variable | Purpose |
|---|---|
| `ANAMNA_DB` | SQLite database path. Default `data/anamna.sqlite3` (`/data/anamna.sqlite3` in the image). |
| `ANAMNA_SOURCES` | Directory for original files. Default `sources/` (`/data/sources` in the image). |
| `ANAMNA_SECRET` | Signing secret for sessions. Set a long random value for any real use; the built-in default is for local development only. |
| `ANAMNA_SECURE_COOKIES` | `1` when TLS terminates at a proxy in front of the app, so the session cookie is always marked `Secure`. |
| `ANAMNA_SETUP_CODE` | Optional first-run setup code. Unset, one is generated and printed to the log. |
| `ANAMNA_AGENT_TOKEN` | Optional operator-pinned `anamna_agent_` credential, recreated on every start. |
| `ANAMNA_PUBLIC_URL` | Public origin used for OAuth redirects and links (Oura, Garmin, Telegram). |
| `ANAMNA_LOG_LEVEL` | Log level, default `INFO`. |
| `ANAMNA_BACKGROUND_WORKERS` | `0` disables all background workers (for an isolated test instance). |
| `ANAMNA_OPENWEARABLES_WORKER` | `0` pauses only the OpenWearables worker. |
| `PORT` | Port for `anamna-web`, default `8000`. |

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
- **Ukrainian lab and clinic accounts**: EskuLab, Synevo, Ekspert (Expert Hospital) and the
  Doctor ELEKS clinics St. Paraskeva and Veselka. Finished orders arrive as their official PDFs,
  and the lab's own values cross-check what was read.
- **Telegram bot**: send documents and photos, look up results, request originals.
- **Vaccination records**: form 063/о scans are read, and doses can be entered by hand.
- **CLI**: `anamna ingest` (a directory of documents), `anamna devices import --vendor
  apple_health|garmin|oura|kardia --path <export>`, `anamna lab-sync --provider eskulab|synevo`.

Other integrations:

- **Paperless-ngx**: mirrors your documents into your own Paperless account and adds its
  full-text search matches. Paperless is never a source of values.
- **AI assist** (OpenRouter by default, Anthropic, OpenAI): optional transcription review of
  documents, suggested titles and metadata, and a plain-language summary of changes. Its output is
  a suggestion and never marks anything verified.

Anamna can merge many overlapping sources, but imported data is still best checked by you: use
your own agent or tools to fix, verify and map what was imported, and verify values against the
source pages in the review queue.

Details: [device imports](docs/device-imports.md), [lab sync](docs/lab-sync.md),
[Oura and Garmin](docs/provider-integrations.md), [OpenWearables](docs/openwearables-webhooks.md),
[Telegram](docs/telegram.md), [architecture](docs/architecture.md),
[extraction and verification](docs/extraction-and-verification.md).

## License and contributing

Anamna is licensed under the [GNU AGPL v3.0 only](LICENSE). See [CONTRIBUTING.md](CONTRIBUTING.md)
to contribute and [SECURITY.md](SECURITY.md) to report a vulnerability.
