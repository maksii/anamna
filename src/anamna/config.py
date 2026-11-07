from __future__ import annotations

import functools
import json
import logging
import os
import re
import sys
import time
from contextvars import ContextVar
from dataclasses import dataclass
from pathlib import Path, PurePath

from . import __version__


PACKAGE_DIR = Path(__file__).resolve().parent
_CHECKOUT_ROOT = PACKAGE_DIR.parent.parent
# Editable installs retain the familiar checkout paths. A wheel keeps immutable
# resources beside the package and writes private state beneath the working dir.
_IS_CHECKOUT = PACKAGE_DIR.parent.name == "src" and (_CHECKOUT_ROOT / "pyproject.toml").is_file()
ROOT = _CHECKOUT_ROOT if _IS_CHECKOUT else Path.cwd()


#: Frozen.  Stable row ids are uuid5 values under namespaces that begin with
#: the project's former name; changing it would re-key every stored record.
ID_NAMESPACE_PREFIX = "health-ledger"

def env(name: str, default: str | None = None) -> str | None:
    """The ``ANAMNA_<name>`` setting, or *default*."""
    return os.getenv("ANAMNA_" + name, default)


def load_integration_environment(path: Path | None = None) -> None:
    """Load only documented integration secrets at the executable entry point.

    Explicit process settings win. Importing helpers or constructing an isolated
    app never loads the operator's private .env into a test process.
    """
    aliases = {
        "telegram-bot-token": "ANAMNA_TELEGRAM_BOT_TOKEN",
        "telegram-bot-name": "ANAMNA_TELEGRAM_BOT_USERNAME",
        "openwearables-token": "ANAMNA_OPENWEARABLES_WEBHOOK_TOKEN",
    }
    allowed = set(aliases.values()) | {"ANAMNA_TELEGRAM_WEBHOOK_SECRET"}
    env_path = path or ROOT / ".env"
    if not env_path.is_file():
        return
    values = {}
    for line in env_path.read_text(encoding="utf-8-sig").splitlines():
        key, separator, value = line.strip().removeprefix("export ").partition("=")
        key = key.strip()
        if not separator or key not in allowed | aliases.keys():
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        values[key] = value
    for key in allowed:
        legacy = next((alias for alias, canonical in aliases.items() if canonical == key), "")
        value = values.get(key, values.get(legacy, ""))
        if value:
            os.environ.setdefault(key, value)


def resource_path(name: str) -> Path:
    if _IS_CHECKOUT:
        return ROOT / ("data/reference_library.json" if name == "reference_library.json" else name)
    return PACKAGE_DIR / "resources" / name

#: How this application identifies itself on every outbound request.
#:
#: Not cosmetic.  ``urllib`` defaults to ``Python-urllib/3.x``, and Cloudflare's
#: browser integrity check refuses that signature outright: a self-hosted
#: Paperless behind a Cloudflare tunnel answered every upload with 403 and
#: error 1010, which reads like a broken token or a server that is down.
#: Measured against a real tunnel on 2026-08-06 — `Python-urllib/3.12` was the
#: only agent blocked; this string, curl's default and a browser string all
#: reached the origin.  The same rule already applies to requests *into* this
#: application (see "Ship it" in CLAUDE.md).
USER_AGENT = f"Anamna/{__version__} (+https://github.com/maksii/anamna)"


@dataclass(frozen=True)
class Settings:
    database_path: Path
    source_dir: Path
    secret_key: str
    session_days: int = 14
    #: Whether the session cookie carries ``Secure``.  ``None`` decides per
    #: request from the scheme it arrived on, which is right for a local
    #: server and for a proxy uvicorn trusts.  It is *not* right otherwise:
    #: uvicorn only honours ``X-Forwarded-Proto`` from ``--forwarded-allow-ips``
    #: (127.0.0.1 by default), so a container behind a proxy on another address
    #: sees plain http and would quietly stop marking the cookie secure.
    #: Set ``ANAMNA_SECURE_COOKIES=1`` when TLS terminates upstream.
    secure_cookies: bool | None = None
    #: An agent credential pinned by the operator, kept present on every start.
    #: Empty unless ``ANAMNA_AGENT_TOKEN`` is set: a value shipped in the
    #: repository would be a working key in every clone.
    agent_token: str = ""
    #: The one-time code the first-run page asks for while the database has no
    #: accounts.  Empty means one is generated at startup and printed to the
    #: server log; set ``ANAMNA_SETUP_CODE`` to choose it in advance.
    setup_code: str = ""


def get_settings() -> Settings:
    database_path = Path(env("DB", ROOT / "data" / "anamna.sqlite3"))
    source_dir = Path(env("SOURCES", ROOT / "sources"))
    secret_key = env("SECRET", "local-development-only-change-me")
    return Settings(
        database_path=database_path,
        source_dir=source_dir,
        secret_key=secret_key,
        secure_cookies=_tri_state(env("SECURE_COOKIES")),
        agent_token=(env("AGENT_TOKEN") or "").strip(),
        setup_code=(env("SETUP_CODE") or "").strip(),
    )


#: Corrections that name one installation's own files and devices (a scan whose
#: pixels were reviewed by hand, a phone the owner renamed).  They are data about
#: one record, not code, so they live beside the database, in the gitignored
#: data directory, and an installation without the file simply has none.
LOCAL_OVERRIDES_FILE = "local_overrides.json"


def local_overrides() -> dict:
    """This installation's `local_overrides.json`; `{}` when there is none."""
    return _read_local_overrides(get_settings().database_path.parent / LOCAL_OVERRIDES_FILE)


@functools.cache
def _read_local_overrides(path: Path) -> dict:
    # A malformed file raises: silently ignoring it would reclassify documents.
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}


def _tri_state(value: str | None) -> bool | None:
    """``None`` when unset, so "decide from the request" stays distinguishable
    from an explicit "never"."""
    if value is None or not value.strip():
        return None
    return value.strip().casefold() in {"1", "true", "yes", "on"}


class _StdoutHandler(logging.StreamHandler):
    """Whatever ``sys.stdout`` is at the moment of writing, not at creation:
    a test runner swaps it per test, and a stale stream would be closed."""

    @property
    def stream(self):
        return sys.stdout

    @stream.setter
    def stream(self, value):
        """Ignored on purpose: the stream is always the live ``sys.stdout``."""


def configure_logging() -> None:
    """INFO and above from ``anamna.*`` to stdout, once per process.

    Uvicorn configures only its own loggers, so before this every module's
    INFO line was dropped and WARNINGs reached stderr through Python's
    last-resort handler with no time or source.  The container log is the
    only place an operator can see what the background loops did.
    ``ANAMNA_LOG_LEVEL`` overrides the level (``DEBUG``, ``WARNING``).
    """
    logger = logging.getLogger("anamna")
    if any(isinstance(handler, _StdoutHandler) for handler in logger.handlers):
        return
    handler = _StdoutHandler()
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    logger.addHandler(handler)
    logger.setLevel(env("LOG_LEVEL", "INFO").strip().upper() or "INFO")


_COUNT_KEY = re.compile(r"[a-z][a-z0-9_]{0,31}")


def run_summary(result: object) -> str:
    """Counts only, from whatever a background run returned: an int, or a dict
    whose integer values (one level of nesting) are tallies.  Text never
    passes, so neither a secret nor a value from the record reaches a log."""
    if isinstance(result, bool) or result is None:
        return ""
    if isinstance(result, int):
        return f"count={result}"
    if not isinstance(result, dict):
        return ""
    parts = []
    for key, value in result.items():
        if not isinstance(key, str) or not _COUNT_KEY.fullmatch(key):
            continue
        if isinstance(value, int) and not isinstance(value, bool):
            parts.append(f"{key}={value}")
        elif isinstance(value, dict):
            parts.extend(
                f"{key}.{inner}={count}" for inner, count in value.items()
                if isinstance(inner, str) and _COUNT_KEY.fullmatch(inner)
                and isinstance(count, int) and not isinstance(count, bool)
            )
    return " ".join(parts)


def log_run(logger: logging.Logger, loop: str, started: float, result: object = None, error: BaseException | None = None) -> None:
    """The one line a background loop writes per run: which loop, how long,
    the counts, or the class of the failure (never its message, which can
    carry an upstream URL or a value from the record)."""
    elapsed = time.monotonic() - started
    if error is not None:
        logger.warning("%s run failed after %.1fs: %s", loop, elapsed, type(error).__name__)
    else:
        logger.info("%s run done in %.1fs %s", loop, elapsed, run_summary(result))


#: Installed per request by the web layer (GET/HEAD only, which never write
#: settings), so a page that asks six helpers "is Paperless on?" reads
#: app_settings once.  Outside a request — CLI, background threads — it is
#: None and every call reads the database.
_request_memo: ContextVar[dict | None] = ContextVar("anamna_request_memo", default=None)


def per_request(func):
    """Memoise a ``(settings, *args)`` settings reader for the current request."""
    @functools.wraps(func)
    def wrapper(settings, *args):
        memo = _request_memo.get()
        if memo is None:
            return func(settings, *args)
        key = (func, str(settings.database_path), *args)
        if key not in memo:
            memo[key] = func(settings, *args)
        value = memo[key]
        return dict(value) if isinstance(value, dict) else value
    return wrapper


def resolve_source_path(settings: Settings, stored: str) -> Path:
    """The stored absolute path, or the same file under the configured sources
    directory.  A database created on one machine is served from another (a
    container mounting the copied files), so the prefix of a recorded path is
    not trustworthy — the tail below the sources directory is.

    Lives here rather than in the web layer because a rescan re-reads the same
    file the viewer serves, and the ingest package cannot import the app.
    """
    # The configured directory wins over the recorded prefix: a copied checkout
    # whose original still exists would otherwise keep reading the original's
    # files, and a file is a device export's unpacked directory as often as not.
    # ponytail: matches on a literal "sources" path segment; fails for a
    # custom-named local sources dir - store relative paths if that ever matters
    parts = PurePath(stored.replace("\\", "/")).parts
    if "sources" in parts:
        candidate = settings.source_dir.joinpath(*parts[parts.index("sources") + 1:])
        if candidate.exists():
            return candidate
    return Path(stored)
