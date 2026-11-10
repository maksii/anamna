# AGENTS.md

The engineering rules for this repository, for people and for coding agents of any kind, are in
[CLAUDE.md](CLAUDE.md). Read it before changing anything; it is the single source and this file
only points to it.

The parts that most often go wrong, in one screen:

- `data/` and `sources/` hold real health information. Never commit them, never copy them into an
  image, a log, an issue or a test. Tests use synthetic data only.
- Assume someone else is editing this working tree right now. Never run a command that discards or
  rewrites work you did not write (`git stash`, `git reset`, `git checkout -- <path>`, `git clean`).
- Every user-visible string ships in English and Ukrainian, through the message catalogs.
- Never invent a medical number, interval, schedule or source. Every claim shown to a patient is
  traceable to an official publication recorded in `data/reference_library.json`, and where
  jurisdictions disagree both positions are shown.
- A value read by software or proposed by a model stays provisional until a person checks it
  against the source page.
- Phone and tablet come first: check 390×844, 375×667, 820×1180 and 1180×820, in both languages.

Checks to run before calling work finished:

    uv tool run --from ruff==0.17.4 ruff check src scripts tests
    uv run pytest -q --basetemp=work/pytest-run
    node --test tests/js/*.test.mjs
    uv run python -m compileall -q src
