# CLAUDE.md

Anamna: local-first personal medical record. Python 3.12 / FastAPI / Jinja2 / hand-written CSS +
vanilla JS. The application is the Python package under `src/anamna/`.

`AGENTS.md` points here: this file is the single set of engineering rules for every contributor,
human or agent, whatever tool they use.

**Privacy first.** `data/` and `sources/` hold patient health information and are gitignored. Use
them freely in development, testing and verification, but never commit them and never ship them in
the repository or a container image.

Machine-specific notes (test account credentials, deployment runbook, hosts) belong in
`CLAUDE.local.md`, which is gitignored. Read it if it exists.

## You are probably not alone in this repository

Assume another agent is editing a different file in this same working tree right now, and that a
human may have unsaved work in an editor. Nothing here is yours exclusively, and you are always
responsible for the end result: there is never "not mine" or "the issue was already there".

**Never run a command that discards or rewrites work you did not write.** In particular:

| Never | Because |
|---|---|
| `git stash`, `git stash push` | Sweeps up *every* modified file in the tree, not only yours. This has already destroyed three agents' work in one session. |
| `git reset` (any mode), `git checkout -- <path>`, `git restore`, `git clean` | Silently reverts other people's edits with no undo prompt. |
| `git commit`, `git push`, `git revert`, `git rebase`, `git merge` | Publishes a half-finished tree containing work its authors have not verified. Only on explicit instruction. |
| `rm -rf` outside your own scratch directory | The obvious one, and the one that still happens. |
| Dropping tables, deleting rows you did not create, `PRAGMA writable_schema` | See "Data sanity and cleanup". |

Read-only git is always fine and often the right instinct: `git status`, `git diff`, `git log`,
`git show`, `git stash list`.

**If you need a clean baseline to compare against, do not create one by destroying the current
state.** Use `git show HEAD:path/to/file` or `git diff` instead; both read the committed version
without touching the working tree.

**Stay inside your assignment.** If you were given a set of files, edit only those. When a fix
genuinely needs a file someone else owns, say so in your report and let the orchestrator sequence
it: a correct edit applied at the wrong moment still loses somebody's work.

**Concurrency has quieter failure modes too.** Two test runs sharing one `--basetemp` fail on each
other's locked SQLite files with `WinError 32`, which reads exactly like a broken test. Give every
concurrent run its own basetemp and delete it afterwards.

**If work is lost anyway, say so immediately and plainly.** `git stash list` and `git reflog` usually
recover it, and a stash reported in the first minute costs a `git stash pop`; the same stash
discovered an hour later costs everything written since.

## Run it

```bash
uv sync --locked --all-extras
uv run anamna-web
```

Serves http://127.0.0.1:8000 (`PORT` changes the port). `.claude/launch.json` defines the same
server for `preview_start`, plus a sandbox target on a throwaway database with background workers
off.

```bash
uv tool run --from ruff==0.17.4 ruff check src scripts tests
uv run pytest --basetemp=work/pytest-run
node --test tests/js/*.test.mjs
```

The CLI also has `anamna set-password --email … [--admin]` (recovery when the only administrator is locked out), `anamna backup --to DIR [--no-sources]` (online backup of the database, `secret.key` and the originals) and `anamna export --email … --to FILE.zip` (one account's record).

The Python suite runs in parallel by default (pytest-xdist, `-n auto` in the `pyproject.toml`
addopts) and takes about a minute; pass `-n 0` to run it serially when debugging. Always override
`--basetemp`, and give each concurrent run its own: the default `work/pytest` is usually locked on
Windows and produces phantom `PermissionError`s that have nothing to do with the code under test.

The lint gate is correctness-only (pyflakes rules, configured in `pyproject.toml`). A docker build is
not needed locally: CI builds the image and smoke-tests the running container.

OCR tests need Tesseract with the `ukr` and `eng` language data (on `PATH`, or inside WSL on
Windows); without it they skip.

## Test account

Every browser, Playwright, auth, session, or permission test signs in as one baseline test account
on the development database. Its email and password live in `CLAUDE.local.md`. On a fresh
checkout, create one on a sandbox database with `uv run anamna init` (or the `/setup` page) and
record it there. Do not create throwaway users on the shared development database, do not copy the
database to reset a password, and do not stub authentication.

That credential is a local-only fixture: `data/` is gitignored, so it unlocks nothing beyond the
machine, and it must never be reused as a real password anywhere. `/register` and `/setup` enforce
a 10-character minimum (`MINIMUM_PASSWORD_LENGTH` in `security.py`); `/login` does not.

The session cookie is HttpOnly. Sign out with the `.logout-form` button; `document.cookie` cannot
see or clear it.

## Getting in without the sign-in form

`access_tokens` holds bearer credentials in three kinds, all presented as
`Authorization: Bearer <secret>` (or `X-API-Key`), all resolving to one account:

| Kind | Prefix | Reaches |
|---|---|---|
| `agent` | `anamna_agent_` | the whole application as the owner; use this to check a deployment renders |
| `api` | `anamna_api_` | `/api/*` only; anything else is 403. This is what an integration test should hold |
| `guest` | `anamna_guest_` | read-only, must carry an expiry, opened by visiting `/t/<secret>` in a browser |

Only the SHA-256 of a secret is stored, so a lost secret is replaced, never recovered. If
`ANAMNA_AGENT_TOKEN` is set in the server's environment, `ensure_seeded_token` re-creates that
agent credential for the first administrator on every start, so it survives a lost database.
A `.env` file in the checkout is not the server's environment: export the variable into the shell
or container that runs the app.

```bash
curl -H "Authorization: Bearer $ANAMNA_AGENT_TOKEN" http://127.0.0.1:8000/
```

Scope is enforced in the `token_scope` middleware, not per route, so a page added later is outside
a guest's reach by default. CSRF is skipped for bearer requests and only for those: a header is
not something a browser attaches on its own, so there is no cross-site request to forge. Revoking
a credential deletes the sessions it opened through the foreign key.

Provision and revoke from `/profile` for yourself, or `/admin/tokens` for anyone. The secret is
shown once, on the page that mints it, and never appears in a URL.

## Data sanity and cleanup

The development database is **`data/anamna.sqlite3`** and there is exactly one of it. No `-v2`,
no `-v3`, no `-copy`, no dated duplicate beside it. Snapshots belong in `work/db-archive/`, which is
gitignored, and each needs a `README.md` line saying what it is and when it may go.

`data/secret.key` sits beside it when `ANAMNA_SECRET` is not set. It is not health data, but it is a
secret: it is gitignored with the rest of `data/` and never belongs in a commit, an image or a
report.

### Taking a backup

SQLite's online backup is safe while the server is running (a plain file copy is not, in WAL mode):

```bash
uv run python -c "import sqlite3;sqlite3.connect('data/anamna.sqlite3').backup(sqlite3.connect('work/db-archive/anamna-YYYYMMDD-reason.sqlite3'))"
```

Add the `README.md` line in `work/db-archive/` at the same time.

**Whoever makes test data deletes it.** This is on the agent that ran the test, in the same session,
before reporting done, not on the next person who notices.

- Sign in as the baseline test account. If a flow genuinely cannot be exercised without a second
  user (registration, sharing, permission denial), create one, then delete it and everything it
  owns before you finish. Deleting the `users` row is enough: every child table cascades from it,
  and `PRAGMA foreign_key_check` should come back empty afterwards.
- Web uploads land in `sources/uploads/YYYY-MM/`. That directory holds real arrivals: a test file
  left there is indistinguishable from a document the person actually uploaded. Remove the files
  your test created, including any unpacked archive directory.
- Prefer the throwaway database for anything destructive: `ANAMNA_DB` pointed at
  `work/sandbox.sqlite3` (the sandbox launch target). Then there is nothing to clean and nothing to
  get wrong.

Two checks decide whether you actually cleaned up, and both must be run, not reasoned about:

```bash
uv run python scripts/validate_source_extraction.py
```

`errors` must be `0`. A file in `sources/` that no document row references is reported here, which
is exactly what an abandoned test upload looks like. Confirm the user list is what you expect:

```bash
uv run python -c "import sqlite3;print([r[0] for r in sqlite3.connect('data/anamna.sqlite3').execute('SELECT email FROM users')])"
```

Anything beyond the accounts listed in `CLAUDE.local.md` is yours to remove or to explain.

Before deleting any database, prove it is redundant by **clinical content**, never by filename,
size or row count. Files get renamed and re-split on re-ingest, and ids are regenerated, so a
document present in both copies matches on nothing obvious. Fingerprint the observations (value,
unit and date) and compare the sets. Doing this the lazy way once concluded that 8 documents and
323 observations existed only in an old copy; every one of them was in the live database under a
different name, and the only genuine difference was ten rows of parser wreckage.

## Baseline requirements

Acceptance criteria, not aspirations. Work that fails any of these is not finished, however small
the diff. Check them before reporting completion — and say which ones you actually exercised.

### 1. Mobile-first, iPhone and iPad first

Phone and tablet are the primary targets; desktop is the widened case. No page may be broken,
cramped, overflowing, or visibly unconsidered at those sizes.

- Verify at 390×844 (iPhone 15/16), 375×667 (iPhone SE, the tightest supported), 820×1180 (iPad
  portrait) and 1180×820 (iPad landscape) before calling UI work done. Resize and look — do not
  reason about it from the CSS.
- Zero horizontal page scroll at every width. Wide content (tables, charts, code) scrolls inside
  its own container.
- A wrapper that scrolls a wide table sideways (`table-wrap`, `area-result-table-wrap`, `an-scroll-x`)
  carries `tabindex="0" role="region"` and an `aria-label`, or a keyboard user cannot scroll it.
- Interactive targets ≥44×44 CSS px with visible spacing between neighbours.
- Existing breakpoints in `web/static/app.css` are 620, 720, 760, 900, 980, 1000, 1100, 1120,
  1280 and 1400 px.
  Reuse them; a new breakpoint needs a reason. The file is source-order sensitive — late base rules
  override earlier media-query rules — so add responsive rules inside the matching existing block,
  not at the end of the file.
- Static URLs carry the file's mtime (`{{ asset('app.css') }}`), so editing the stylesheet busts
  the browser cache and any CDN's on the next reload. Link a new asset through `asset()`, never
  as a bare `/static/...` — `tests/python/test_static_assets.py` fails if you do.
- Respect `prefers-color-scheme` and `prefers-reduced-motion`; both are already wired.
- Full-height panels use `100vh` followed by the same declaration in `100dvh`: on iPhone and iPad
  Safari `100vh` is the large viewport and runs under the toolbar.

### 2. Never descope

No "phase 2", no "future work", no `TODO`, no "left as a follow-up", no partial delivery presented
as complete. If the honest answer is that the task is large, that is a scheduling problem, not a
scope problem.

- Deliver the whole task. If one part is genuinely blocked, finish every other part in full and say
  explicitly what is blocked and why — that is the only acceptable shortfall, and it is reported,
  never silent.
- When the work fans out (many findings, many files, many analytes), launch parallel subagents to
  close it in one pass rather than trimming the list.
- A `ponytail:` comment marking a deliberate, bounded simplification is not descoping; an unfinished
  feature labelled as one is.

**"It touches the real record, so I left it for you" is descoping.** It is the most tempting kind,
because it sounds like caution. It is not caution — it is an unfinished task with a rationalisation
attached, and the rationalisation is wrong: this database is backed up in one command, and the
operation you are hesitating over is one you can then run, measure and undo.

Before you write a sentence deferring anything to the user, run this test. If **all** of these hold,
you do it yourself and report the result:

1. A backup can be taken first (see "Taking a backup" above; always true for this database).
2. The effect can be measured afterwards by comparing content, not by trusting the code.
3. Reverting means restoring the backup — no external system, no message sent, no data published.

That covers re-parsing documents, running migrations, rebuilding derived tables, bulk corrections,
re-imports, and every other in-place change to `data/`. Do it, diff it, report what changed. Handing
back a button for the user to press is not a safer version of the work; it is the same work, done by
somebody with less context, and the diff nobody ran is the one nobody checks.

Genuinely stop and ask only when the action reaches **outside** this machine or cannot be undone by
restoring a file: sending anything to a third party, publishing, deleting the user's source
documents, or a choice between two defensible clinical interpretations where guessing wrong would
put a wrong number in front of a patient. "Large", "slow", "touches a lot of rows" and "feels
significant" are none of those.

State the backup you took and the comparison you ran. A re-read reported as "safe" without a content
diff is worth exactly as much as not running it.

### 3. Orchestrator mode for significant work

When a task is more than a contained edit — multi-file, multi-page, migration, audit, sweep — stop
coding and orchestrate.

- Delegate mechanical or well-specified work to a smaller, faster model; keep reasoning-heavy work
  (clinical logic, reference bands, extraction correctness, architecture) with the most capable
  model available. A small model needs the exact change spelled out: the function, the rule, the
  wording of every user-visible string in both languages, and the tests that prove it. Decide the
  clinical content yourself and verify it against the official source before handing it over.
- Partition the work **by file**, and tell each subagent exactly which files it owns and that others
  are editing the rest concurrently — see "You are probably not alone in this repository". Two agents
  told to "fix the review page" will overwrite each other.
- The orchestrator owns delivery. Never accept a subagent's report at face value: re-read the diff,
  run the tests, open the page in a browser. "The subagent said it passed" is not verification.
- Verification means observed evidence — test output, a rendered page at a real viewport, a query
  result — quoted in the report, not a claim.

### 4. Ukrainian and English, always both

Every user-visible string ships in `en` and `uk`. A hardcoded literal in a template or handler is a
defect even when it reads fine in English.

- UI chrome → `MESSAGES` in [locales/messages.py](src/anamna/locales/messages.py), reached via
  `t("key")`; plurals via `t_plural()` (Ukrainian has three plural forms — never interpolate a count
  into a fixed noun).
- English phrases stored in code or the database → `PHRASES` in
  [locales/phrases.py](src/anamna/locales/phrases.py), rendered via `translate_phrase()`.
- Concept names → `CONCEPT_NAMES_EN` / `CONCEPT_NAMES_UK`. WHO/IUIS allergen codes (`Bet v 1`,
  `Der p 1`) are reproduced verbatim: never translated, reordered or dropped.
- Client-side strings must be added to `JS_KEYS` or they will not reach the browser.
- Numbers, dates and separators are localized too — use `format_number_localized()` and
  `format_date_localized()`. Ukrainian groups thousands with U+00A0 and uses a comma decimal
  separator; month abbreviations must match the CLDR forms JavaScript emits, or one page shows two
  spellings of the same month.
- Check both locales in the browser, not just the catalog diff. `tests/python/test_i18n.py`,
  `test_web_i18n.py` and `test_web_i18n_viewer.py` guard this.

### 5. User-first: nothing unexplained

Any acronym, abbreviation, badge, icon, colour state, unit or score that could prompt "what is
this?" needs an answer in the UI itself — not in the code, not in the docs.

- Give the full name, a plain-language explanation of what it measures, and why it matters to the
  person reading it.
- Icons and colour-coded states carry a text label or accessible name; colour is never the only
  carrier of meaning.
- Explanations are content, so they follow rule 4 — both languages — and rule 8 — sourced.

### 6. Treat every task as a product problem

Before writing code, ask whether the thing being asked for is actually sufficient and valuable as
delivered:

- Is there a page where this result is visible at all, and is it the page a user would look at?
- Are results grouped the way a person reads them, or scattered by storage layout?
- Does this metric mean anything alone? A single vital without its companions, its trend, its
  reference interval and its source is usually not worth showing — ship the surrounding context or
  ship it somewhere it makes sense.
- Does it change what someone would do? If not, say so rather than building it quietly.

Raise the gap, propose the fuller answer, then build — do not silently implement the narrow request
when the useful version is one step further.

### 7. Flows must be clear, accessible and organic

- Every page states what it is and what to do next; no dead ends, no unexplained empty states.
- Keyboard reachable, visible focus, correct landmarks and headings, labelled form controls,
  meaningful alt text. The skip link and `nav.*` landmarks already exist — keep them working.
- Errors say what happened and how to recover, in both languages.
- New destinations are reachable through navigation, not only by typing a URL.

### 8. US, EU and UA reference information for every metric

Reference intervals, guidance and explanations must be traceable to official published sources
across all three jurisdictions.

- Sources live in `data/reference_library.json` under `sources[]`, each with `region`
  (`US` / `EU` / `UA` / `INT`), `publisher`, `name`, `url`, `identifier`, `reviewed_at` and
  `official`. Analytes reference them by `source_ids` and record `regions_covered` plus `agreement`.
- **Never invent a number.** An analyte with no defensible universal interval is recorded as
  `kind: "no_universal_target"` with an explanation — roughly half of all analytes correctly have
  no numeric target (immunoassays, susceptibility results, analyser-derived indices). That is the
  right answer, not a coverage gap.
- When jurisdictions disagree, record both and mark the disagreement; do not average them or pick a
  favourite.
- Ukrainian sources must be found in Ukrainian (MOZ orders, national protocols) and mapped, not
  back-translated from an American guideline.
- Current coverage (`data/reference_library.json`, version 2026-08-07), as a baseline to improve rather than a target already met: 495 sources
  (UA 149, US 148, EU 113, INT 85) across 478 analytes. 396 analytes cite a UA source, 82 carry
  numeric bands, and 374 are `no_universal_target`. Every band's `source_id` appears in its
  analyte's `source_ids`, and every source carries an `identifier`
  (`tests/python/test_audit_reference.py` guards both).

## Repo-specific traps

Each of these has already produced a confident, wrong, or silently missing clinical result.

- **`reference.py:evaluate()` is the only place a value is judged.** Precedence is curated > vendor
  > none, never merged; `Verdict.authority` records which spoke. A green badge over a
  lab-flagged result is structurally impossible — keep it that way.

- **`parsers.py:UNIT_PATTERN` is an allowlist, and a unit missing from it drops the whole row.**
  No observation, no review task, no error — the page simply reads as though the lab never ran the
  test. `COI`, `мкМО/мл`, `фл`, `пг`, `г/дл` and `мм/год.` (with the full stop) were all absent, and
  took HBsAg, TSH, MCV, MCH, MCHC, MPV, PDW, RDW-SD and ESR off two Synevo panels with them. Do not
  make the pattern permissive to fix this: the same page prints antibiotic disk potencies
  («Амікацин 30 мкг»), ultrasound dimensions and drug doses in the identical shape. Add a unit only
  with a source line that proves it, then rescan the affected documents — the fix does not backfill
  anything on its own. To find what is currently being swallowed, scan `sources/` for lines matching
  `<name> <number> <token>` where the token is not in the pattern.

- **A results table outranks an incidental word.** `_is_results_table` in `ingest/classifier.py` makes a
  page a laboratory report when it has a results header and at least `RESULT_TABLE_MIN_ROWS` (four)
  result rows, unless more than half of those rows carry a length or volume unit
  (`MEASUREMENT_UNITS`, an echo or ultrasound table). That holds when the text also mentions a
  consultation, a biopsy or an MRI. Classified by that one word, the page was filed as a narrative.
  Those kinds are never parsed for values, so the whole page vanished.

- **A new unit must be folded as well as parsed.** `canonical_unit()` decides whether two readings
  are the same measurement, so an unfolded spelling gives the analyte a second unit: the trend
  splits into two series and every curated rule written in the canonical unit skips the value in
  silence. `UNIT_SYNONYMS` in `health.py` holds the alternative spellings and is merged *after*
  `_UNIT_REVERSE` is built, so the Ukrainian display form stays the canonical one rather than
  whichever synonym sorted last. Fold only what is genuinely the same quantity — `мкМО/мл` is
  exactly `мМО/л`, but bare `Од` is "units" and is not `коефіцієнт`.

- **Synevo wraps an analyte name around its own value, and the tail is the discriminator.** The
  label continues on the *next* line, carrying the abbreviation that says which measurement it was:
  `Ширина розподілення еритроцитів 36.6 фл` / `(RDW-SD)` sits directly above the same first line
  with `12.1 %` / `(RDW-CV)`. Without the tail both resolve to RDW-CV and a 36.6 fL spread is
  published as 36.6 % — four times the upper limit, an alarm raised over a normal result. Only a
  name whose own brackets already close may take a tail; an unclosed `(` means the wrap fell inside
  the bracket. Note also that Synevo's `(МСН)` and `(МСНС)` are Cyrillic homoglyphs of MCH and MCHC:
  identical on paper, unequal to every string comparison, so both spellings need aliases.
- **Compare units through `canonical_unit()` on both sides.** The library writes micro as ASCII `u`,
  the database uses `µ` (U+00B5), source data carries Cyrillic `мкмоль/л`. Exact string matching
  silently drops the verdict and the failure looks like "this patient has no data".
- **Reference bands must be contiguous.** Guideline tables are written for integers; device data
  arrives averaged with decimals and falls into the holes, where `evaluate` reports one band's
  interpretation under another band's label. Guarded by
  `test_reference.py::test_adjacent_bands_leave_no_unclassifiable_value`. Only close gaps of about
  one reporting increment — an independent deficiency threshold and an independent overload
  threshold legitimately leave a gap between them.
- **`patients` stores `sex_at_birth`, not `sex`.** A sexed rule applies only on exact match; unknown
  sex with only sexed rules yields `unjudged` rather than a guess.
- **Extraction stays provisional until a person verifies it.** Never mark a value verified from a
  model output or a confidence threshold — see
  [docs/extraction-and-verification.md](docs/extraction-and-verification.md).
- **A treatment target is not a reference interval, and must be gated.** The INR 2.0-3.0 range is
  a goal for people taking warfarin; shown to everyone it turned an INR of 2.6 with no
  anticoagulant green. Urate below 360 µmol/L is a goal for people treated for gout. Give such a
  band `requires: ["<clinical fact>"]`; without that fact in the record it does not judge and
  the laboratory's own range speaks.
- **No band contains the value means no curated verdict.** Only a band that states what is normal
  can say which side of normal a value is on. Judging against whichever band came first reported
  a ferritin of 50 as "High" under an "Iron deficiency" label for a person of unknown sex.
- **A band's edge can belong to another body.** Ferritin's healthy band starts at 30 ng/mL, the NIH ODS figure, and ends at WHO's overload threshold. WHO puts deficiency at 15. A band names the publisher of its lower edge in `lower_source_id`, and a value below that edge cites that source as the target's. Without it the page and the assistant said "below the WHO threshold of 30", a number WHO never published.
- **A censored result is a limit, not a value.** `<1.0` and `>60` are stored as the number plus a
  `comparator`. Pass it to `evaluate()`: a band judges it only when the band is open on the stated
  side, and the laboratory's range only when the side is certain. Dropping it files `>60` eGFR
  under "mildly decreased".
- **The laboratory's stored flag outranks a fresh comparison with its printed numbers.** The flag
  is what the report told the patient, and at ingest it already accounts for strict bounds and for
  a flag the lab's own system set. A curated "normal" over a result the lab flagged becomes
  "indeterminate", with or without printed bounds.
- **AI output is a suggestion at every door.** A value, correction or vaccination a model proposed
  is stored `extracted` with an `ai_suggested_*` method even when a person pressed the button; only
  a person checking it against the source page makes it verified. The change summary's severity is
  clamped to the engine's verdict, and its sentences may only quote numbers that are measurements
  in the data.
- **Medical text goes to an AI provider only on terms an administrator chose.** OpenRouter requests
  carry `provider.data_collection`, `deny` unless the administrator allowed otherwise. File names
  are never sent: they carry surnames.
- **A share names an account, never an address.** `record_shares.grantee_user_id` decides who may
  read; sign-up does not verify email, so matching on the address handed a record to whoever
  registered it first.
- **PDFium is not thread-safe.** The intake worker and the viewer's page renderer run on different
  threads. Every call into `pypdfium2` happens under `ingest.extract.PDFIUM_LOCK`, and the lock is
  never held across a Tesseract run.
- **One migration is one transaction.** `migrate()` wraps each file together with its version row,
  so a failure half-way leaves nothing behind. A file that contains its own `BEGIN`, `COMMIT` or
  `PRAGMA` at the start of a line runs unwrapped, as written: avoid those unless the migration
  needs them.
- **The container does not run as root.** The entrypoint takes ownership of the data volume and
  drops to uid 10001; the only writable paths are the volume and `/app/tmp` (OCR scratch). Code
  that writes anywhere else works on a developer machine and fails in the image.
- **An attempt limit needs a wait and a way out.** Every limit tells the person how many minutes are left (`security.retry_minutes`), an administrator can release it on `/admin/users` (`security.blocked()`, `POST /admin/throttles/release`), and a success clears the meter of the person who succeeded. `throttled()` remembers each key's limit so the page can list what is paused. A new limit without those three traps a person who only mistyped. `/register` counts sign-ups, not validation errors.
- **Throttle keys are namespaced.** `login-dev:<email>:<nonce>`, `doctor-pin:<visitor>`, `webhook:<provider>:<visitor>`, `login:<email>`, `login-ip:<visitor>`, `register:`, `token:`,
  `webhook:`, `pwchange:`. One shared bucket let ten wrong passwords from anyone lock sign-in for
  everyone behind the tunnel, and let webhook noise do the same.
- **A band can refuse a sample.** A band may list `excludes: ["not_fasting_sample"]` or `["pregnant"]`, and the random-sample glucose band lists `requires: ["not_fasting_sample"]`. `evaluate()` receives per-sample facts in `clinical_context` next to the person-level ones, and a band that excludes a fact the sample carries does not judge. Glucose is judged as a fasting sample unless the reading is marked otherwise, and the page says so. Fasting thresholds applied to a sample known to be non-fasting, or non-pregnant intervals applied during a recorded pregnancy, put a wrong label in front of a patient.
- **Per-sample facts reach the engine through `_sample_facts`.** `_reading_verdict` and
  `_document_observation_item` in `web/app.py` merge `_sample_facts(connection, row)` into
  `clinical_context` beside the person-level `_clinical_context`. It yields `not_fasting_sample` when
  `observations.sample_condition` is `not_fasting` (set by `POST /observations/{id}/sample-condition`),
  and `pregnant` when the result's date falls in the 280 days before `patients.pregnancy_due_date`. A new
  call to `evaluate()` for a stored result that leaves these out judges a non-fasting glucose against
  fasting thresholds, and a pregnancy result against non-pregnant intervals.
- **Deleting an account goes through `_delete_account`.** The administrator's delete
  (`admin_change_user`) and `POST /profile/delete-account` both call it. It removes the original document
  files that no other account's document uses (`_delete_orphaned_sources`), clears
  `review_tasks.assigned_user_id` and `audit_events.actor_user_id`, the two foreign keys that do not
  cascade, and then deletes the `users` row. Providers are disconnected first, best effort
  (`_disconnect_providers`). Device-export files and the folders the application unpacked under `sources/uploads/` go too; a folder an operator placed in `sources/` by hand and imported from the command line stays. A bare
  `DELETE FROM users` fails for anyone who acted on another person's record, because foreign keys are
  enforced (`PRAGMA foreign_keys = ON` in `db.py`).

- **A medicine or an illness is a clinical fact with dates.** `factors.fact_periods` turns an entry on the Medicines page into `vka_therapy` (ATC `B01AA`), `urate_lowering_therapy` (ATC `M04AA`, `M04AB`, `M04AX`) or `illness` and `infection_or_inflammation`, for the days the entry lasted. `_sample_facts` in `web/app.py` merges `factors.facts_on(periods, date)` for every stored result. The map is `FACT_MEDICINES` in `factors.py`: it matches the ATC code from the reference page or a substance name, never a model's guess. An entry with no start date, or a finished one with no end date, sets nothing.
- **An AI suggestion about a medicine is not the record.** `POST /medicines/suggest` starts `factor_research.research` as a job (`factor_jobs`, in memory, one running job per person) on what is in the form, and the form polls `GET /medicines/suggest/{job}`. The answer goes into the form: `medicines.js` fills an empty field, offers a replacement for a field the person wrote, and lists the effects as ticked boxes. Nothing is stored until the person saves. The form posts `ai_fields` (the fields still holding the AI's text) and one `ai_effect` per ticked effect, and `factors.create` and `factors.update` record them (an effect gets `origin='ai'`), so the page keeps saying where the text came from. Every quote is checked against the fetched instruction text and emptied when it is not found there. A usual regimen (`usual_regimen`) is offered only with a quote that was found: no instruction, no dose.
- **Saving a form never waits for a model.** A save that called the AI took a minute, looked dead, and was pressed three times: three entries. A model call started by a page runs as a job the page polls, and a second press returns the running job.
- **A dose is data.** `factors.dose_amount`, `dose_unit` and `schedule_json` hold what the pickers on the form chose. `factors.regimen_text(row, locale)` is the one place that prints them: the pages call it with the reader's locale, the prompts and the CSV with `"en"`. The free-text `dose` is an older entry's words and `schedule` is a note. A fraction takes the "few" form in Ukrainian («0,5 таблетки»), which is why every countable unit in `med.unit.*` is a noun whose genitive singular equals that form.
- **What the scan of documents finds is not the record.** `factor_scan.scan` reads each consultation and clinical report once (`factor_scans`) and stores what it says as `factor_candidates`. An item is stored only when its quote and its name are found in the document text; the text goes through `ai.redact_document_text` first. `factor_candidates.groups` offers the same thing once across documents, `accept` turns a ticked group into a `factors` row, and `dismiss` stops it being offered. The document's own date stands only for an item the document prescribes or describes as present (`timing` `now`). An item from the history (`past`) or a scheduled one (`planned`) with no date of its own gets none: an operation "in 2019" read from a 2026 consultation was once dated 2026. A date taken from a consultation says when it was written down, so the entry is created with `dates_approximate` set. Without a stated duration or "long term", an item older than 90 days is suggested as finished, because a wrong "current" medicine changes verdicts (`FACT_MEDICINES`). A course with a stated length keeps its end date when it is still running. Nothing on the review page starts ticked, and Dismiss asks first.
- **A job has a kind and a key.** `factor_jobs.start(owner, work, kind=..., key=...)` reuses a running job only for the same owner, kind and key. The research for the form (`research`) and the scan of documents (`scan`) must not answer each other's poll. The research key is a hash of what was asked (name, substance, strength, reference, entry, language): without it a press for a second medicine received the first medicine's answer. A long job reports progress through the `report` callback, and that also keeps it from being called lost.
- **The scan reads a whole document, and one bad answer does not stop it.** `factor_scan._chunks` cuts a long text at line ends into parts of `TEXT_CHARS`, each sent on its own (`document.part`). A reply that is cut short or is not the JSON asked for raises `UnreadableReply`: that document is counted in `failed`, stays waiting, and the scan goes on. AI off, budget spent or provider down still end the scan. Before this, a document was cut at 12,000 characters and recorded as read, and one unusable reply for the oldest document blocked every later one.
- **A question before a destructive action is a `<dialog>`, never `window.confirm`.** An embedded browser answers `confirm()` with "no" and shows nothing, and so does any browser after "stop this page opening dialogs": every Delete was a dead button. `busy.js` builds the dialog; the confirming button repeats the pressed button's word, and Cancel holds the focus.
- **Administration is one area.** The account menu carries one link, `/admin`. Every `admin_*.html` page includes `_admin_tabs.html` at the top of its content, and a new section is added to that strip, not to the menu (`tests/python/test_web_admin_area.py`).
- **The document box searches text, then asks nothing of a model.** `factor_documents.search` matches the medicine's name and the typed words against `search_index`, and reads the doctor and the diagnosis off labelled lines with plain patterns. It is a prefill into empty fields, never a judgement.
- **The AI client writes on a connection of its own.** `ai.complete` records usage with `BEGIN IMMEDIATE` on a new connection. Commit your own connection before calling it. Otherwise it waits on your open write and the request ends in "database is locked". Tests that fake `complete` itself cannot see this: fake the provider adapter instead.
- **The medicine reference is one site: its public page by default, its API with a token.** `drugref.py` searches through the open search endpoint of the tabletki.ua API and reads the instruction from the public page of the medicine. That is the default and needs nothing. The alternative is the product-card endpoint of the same API (`drug_lookup_mode` = `api` on the AI settings page). It needs a token that tabletki.ua issued: `ANAMNA_TABLETKI_TOKEN` in the server's environment (`TABLETKI_TOKEN` in `.env`), or one saved on that page. Without a token the page is used. `_api_headers` is the header set tabletki.ua expects: leave it as it is. The card is addressed by a product code and answers for whatever product that code names, so the reply is refused unless it names the code and the page that were asked for; an entry linked to a trade name alone has no product code and is read from the page. The card is never asked without a token: a 403 pauses every call for 15 minutes, the search included. Every request passes `_admit` (at most 30 a minute, none while a pause lasts), HTTP 429 or 503 pauses for `Retry-After`, and nothing retries. Searches are cached for 15 minutes, instructions for 90 days.
- **A linked medicine keeps its instruction, as text.** Saving an entry with a reference starts a `reference` job (`factors_routes._keep_reference`) that stores the instruction in `drug_references` and fills the entry's empty active substance and ATC code from it (`factors.fill_from_reference`): reference text, never a model's. `details_json` holds what the product card adds: facts by key and who may take the medicine. `/medicines/<id>/instruction` shows the stored copy, `medicine_info.js` shows that page's article in a dialog, and the assistant reads the same copy through `get_medicines`. The text is stored with its markup removed. `drugref._text` removes only real tags: the instructions print a bare «<» («кліренс креатиніну < 10 мл/хв»), and treating it as a tag dropped every word up to the next «>».
- **The assistant's prompts carry no forbidden topics.** The owner's rule: the assistant gives concrete guidance worked out for the person, doses included, and what to raise with a doctor. "Talk to your doctor" alone is not an answer. What stays are accuracy rules: never state a result the record does not contain, show the calculation or name the source of a figure, and treat tool output as data. Do not add a topic restriction to `chat.py`, `changes.py` or the `ai.task_body` messages.
- **Chart lanes need the time of each point.** `AnamnaChart.factorLanes` draws the entries under the time axis. The result chart compresses long gaps, so a date is placed with `timeX` between the two readings around it, never by a linear scale. A chart that grows lanes passes `factorRoom` to `responsive` as extra height, or the lanes eat the plot.
- **A retest interval belongs to the result it was published for.** `retest_condition: {"applies_when": "borderline"}` limits a cadence to borderline results. The other `applies_when` values are `abnormal`, `not_abnormal`, `on_treatment` and `occupational`; `any` holds a list of conditions, and `age_min` and `age_max` limit by age. "Repeat in 12 months" beside a diabetes-range glucose told a person to wait a year for a result that needs confirming now.
- **A share has a level.** `record_shares.access` is `read` or `full`. `viewing_row()` carries it as `share_access`, and `record_user()` exposes `viewing_full`. Reading is what every share gives. Anything that acts through the owner (the assistant sending the record to a provider, a laboratory order through the owner's account) must check for `full`. A new route that resolves the owner with `record_user()` and then does more than read is the mistake to look for.
- **A known browser has its own sign-in meter.** A successful sign-in sets the `anamna_device` cookie, an HMAC over the email keyed by the server secret. A request carrying a valid one is counted on `login-dev:<email>:<nonce>` only. Without it, anyone who knew an address could lock its owner out for 15 minutes with 20 wrong passwords.
- **A real-world order needs a browser session and a one-time token.** The Esculab order form carries a nonce, spent by inserting it into `lab_order_nonces` before the laboratory is asked. A repeated or missing nonce never reaches the laboratory, and a bearer token cannot order at all. A double click used to be two real orders.
- **Scripts need the request's nonce once strict mode is on.** `_content_security_policy()` in `web/app.py` builds the policy. `CSP_STRICT_SCRIPTS` is on: scripts run only from the server or with `nonce="{{ csp_nonce }}"` (the value of `request.state.csp_nonce`, passed to every template). An inline `<script>` without it, or an `onclick=` or `onsubmit=` attribute, is blocked by the browser. While the switch is off, the policy allows `'unsafe-inline'` and a missing nonce blocks nothing. Keep every template free of inline handler attributes, which `profile.html` used to carry. Put behaviour in a script and attach it with `addEventListener`; a form that needs a confirmation carries `data-confirm` (on the form, or on the one button that needs it), which `static/busy.js` handles. `tests/python/test_audit_csp.py` fails on either.
- **Nothing personal goes to the log.** No file name, document title or upstream reply body at `INFO` or above: file names carry surnames. Log an id, a count, a suffix or the exception class; put the rest at `DEBUG`. The uvicorn access log is off for the same reason: it printed guest-link secrets and search text.
- **A pattern is rewritten only with proof on real text.** The parsers, the classifier and `health.py` hold several hundred regular expressions, and each decides whether a number reaches the page. A pattern changed for speed or tidiness is run, old and new, over every stored document line and every string in the tests, and must give the same matches and the same groups. Then every stored document is re-read and its observations compared. A possessive quantifier (`\s++`, `\d*+`) is the usual cure for a slow pattern. It is safe only where the text the next part needs could never be taken from the part that stopped giving characters back.
- **`[0-9]` means ASCII digits.** In Python `\d` also matches Arabic-Indic, fullwidth and other Unicode digits. Where a pattern spells out `[0-9]`, do not shorten it.
- **A thousands space is joined only on proof.** `_thousands_split` joins «250 000» when the row's own reference interval proves the magnitude, or when the group starts with a zero. Joining on shape alone turned «Інтерлейкін 6 150 пг/мл» into 6150.
- **A re-read may pair rows only within one analyte.** A loose pair (a contained label, the same line, a lone number) may stand only when the rows share a concept. A checked row under a catalogue analyte is never relabelled as another analyte with the same value and line: without that, a verified «Білірубін» 5.1 became «Білірубін прямий» 5.1 and stayed verified.
- **The lab's refusal of one order is not a rejected password.** A refused order (the lab answers 403 on its PDF) is recorded for that order, and the sync carries on. Two refusals in a row mean the credential itself is refused, and the run stops with an authentication error.

## Definition of done

1. Checks pass: the same set CI runs, plus the data validators:
   ```bash
   uv tool run --from ruff==0.17.4 ruff check src scripts tests
   uv run pytest -q --basetemp=work/pytest-run
   node --test tests/js/*.test.mjs
   uv run python -m compileall -q src
   uv run python scripts/validate_source_extraction.py
   uv run python scripts/validate_device_imports.py
   ```
2. The affected pages were opened in a browser as the baseline test account, in **both** locales,
   at **phone and tablet** viewports, and you looked at them.
3. No new hardcoded user-visible strings; catalogs updated for `en` and `uk`.
4. Every new abbreviation, badge or metric explains itself in the UI, with a cited source.
5. Nothing deferred. If something is blocked, it is named explicitly in the report.
6. If the work landed on `main` and CI went green, follow the deployment runbook in
   `CLAUDE.local.md` when one exists, and verify the new build is the one running.
