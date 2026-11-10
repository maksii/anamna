# Contributing to Anamna

Thank you for helping. Anamna is a personal medical record, so two rules come before everything
else: never commit real patient data, and every user-visible string ships in both English and
Ukrainian.

## Setup

You need [uv](https://docs.astral.sh/uv/), Python 3.12 and Node.js 22 (for the JavaScript tests).
Tesseract with the `ukr` and `eng` language data is needed to run the OCR tests; without it they
skip.

```bash
uv sync --locked --all-extras
uv run anamna-web
```

Open http://127.0.0.1:8000. On an empty database you are sent to `/setup`; the one-time code is in
the server output. For experiments, point `ANAMNA_DB` at a throwaway file such as
`work/sandbox.sqlite3`.

## Tests

```bash
uv tool run --from ruff==0.17.4 ruff check src scripts tests
uv run pytest --basetemp=work/pytest-run
node --test tests/js/*.test.mjs
uv run python -m compileall -q src
```

The lint step checks correctness only (undefined names, unused imports, repeated dictionary keys);
style is not gated.

The Python suite runs in parallel by default (`-n auto`) and takes about a minute. Pass `-n 0` to
run serially while debugging. Use your own `--basetemp`, and a different one for each concurrent
run: two runs sharing a temp directory fail on each other's locked SQLite files.

Add a regression test with every fix. Tests use synthetic data only.

## Bilingual rule

Every user-visible string ships in `en` and `uk`; a hardcoded literal in a template or handler is a
defect even when it reads fine in English.

- Interface text goes in `MESSAGES` in `src/anamna/locales/messages.py`, used through `t("key")`.
  Counts use `t_plural()`: Ukrainian has three plural forms.
- English phrases stored in code or the database go in `PHRASES` in
  `src/anamna/locales/phrases.py`, rendered with `translate_phrase()`.
- Strings used by browser scripts must be listed in `JS_KEYS`.
- Format numbers and dates with `format_number_localized()` and `format_date_localized()`.
- Ukrainian text is written in Ukrainian, not translated word for word.

`tests/python/test_i18n.py` and the `test_web_i18n*.py` tests guard this.

## Patient data

- `data/` (except `data/reference_library.json`), `sources/`, `work/` and `.env` are gitignored.
  Keep it that way, and never force-add anything from them.
- Never commit real documents, exports, screenshots, database files, names, dates of birth or
  values from a real record, including in tests, fixtures, issues and pull requests. Write
  synthetic fixtures instead.
- The reference library holds published clinical guidance only. Every interval cites its source;
  never invent a number.
- Log lines must not contain file names, document titles or the text of an upstream reply. Log an
  id, a count, a file suffix or the exception class.

## Pull requests

- Keep each change focused, and explain what it changes for the person using the app.
- Check pages you touched at phone and tablet widths, in both languages.
- CI lints, runs the Python and JavaScript tests, builds the container image and starts it once to
  check that it serves, runs unprivileged and offers first-run setup. CI also starts the image a
  second time with the hardened settings from `compose.yaml`: read-only root filesystem, all Linux
  capabilities dropped except the four the entrypoint needs. It must be green.

By contributing you agree that your contribution is licensed under the
[GNU AGPL v3.0 only](LICENSE).

See [CLAUDE.md](CLAUDE.md) for the full engineering rules, which apply to human and agent
contributors alike.
