# CLAUDE.md

Anamna: local-first personal medical record. Python 3.12 / FastAPI / Jinja2 / hand-written CSS +
vanilla JS. The application is the Python package under `src/anamna/`.

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
uv run pytest --basetemp=work/pytest-run
node --test tests/js/*.test.mjs
```

The Python suite runs in parallel by default (pytest-xdist, `-n auto` in the `pyproject.toml`
addopts) and takes about a minute; pass `-n 0` to run it serially when debugging. Always override
`--basetemp`, and give each concurrent run its own: the default `work/pytest` is usually locked on
Windows and produces phantom `PermissionError`s that have nothing to do with the code under test.

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
- Interactive targets ≥44×44 CSS px with visible spacing between neighbours.
- Existing breakpoints in `web/static/app.css` are 620, 720, 760, 900, 980, 1100, 1120 and 1280 px.
  Reuse them; a new breakpoint needs a reason. The file is source-order sensitive — late base rules
  override earlier media-query rules — so add responsive rules inside the matching existing block,
  not at the end of the file.
- Static URLs carry the file's mtime (`{{ asset('app.css') }}`), so editing the stylesheet busts
  the browser cache and any CDN's on the next reload. Link a new asset through `asset()`, never
  as a bare `/static/...` — `tests/python/test_static_assets.py` fails if you do.
- Respect `prefers-color-scheme` and `prefers-reduced-motion`; both are already wired.

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

- Delegate mechanical or well-specified work to `claude-sonnet-5`; give reasoning-heavy work
  (clinical logic, reference bands, extraction correctness, architecture) to `claude-opus-5`.
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
- Current coverage, as a baseline to improve rather than a target already met: 187 sources
  (US 73, EU 64, INT 24, UA 18, 8 unregioned) across 263 analytes — 88 analytes cite a UA source and
  33 cite no region at all. Closing those gaps is in scope whenever you touch the analyte.

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

## Definition of done

1. Checks pass: the same set CI runs, plus the data validators:
   ```bash
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
