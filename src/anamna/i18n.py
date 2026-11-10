from __future__ import annotations

from contextvars import ContextVar, Token
from datetime import date, datetime
import re
from typing import Any

from .locales.messages import MESSAGES
from .locales.phrases import PHRASES
from .locales.source_policy import MESSAGES as SOURCE_POLICY_MESSAGES
from .locales.openwearables_webhooks import MESSAGES as OW_HOOK_MESSAGES
from .locales.telegram import MESSAGES as TELEGRAM_MESSAGES
from .locales.messages_allergy import MESSAGES as ALLERGY_MESSAGES
from .locales.messages_factors import MESSAGES_FACTORS
from .locales.messages_genetics import MESSAGES as GENETICS_MESSAGES

MESSAGES.update(SOURCE_POLICY_MESSAGES)
MESSAGES.update(OW_HOOK_MESSAGES)
MESSAGES.update(TELEGRAM_MESSAGES)
MESSAGES.update(ALLERGY_MESSAGES)
MESSAGES.update(GENETICS_MESSAGES)
MESSAGES.update(MESSAGES_FACTORS)


SUPPORTED_LOCALES = ("en", "uk")
DEFAULT_LOCALE = "en"
#: What a visitor who has not picked a language sees: the audience is
#: Ukrainian.  DEFAULT_LOCALE stays English -- it is the source language every
#: catalog falls back to, not a display preference.
VISITOR_LOCALE = "uk"
#: Written only when a person picks a language.  Renamed from ``anamna_locale``,
#: which was stamped "en" on every first visit, so nobody keeps English they
#: never chose.
LOCALE_COOKIE = "anamna_lang"
BABEL_LOCALE = {"en": "en_GB", "uk": "uk_UA"}

_locale: ContextVar[str] = ContextVar("anamna_locale", default=DEFAULT_LOCALE)

# CLDR abbreviated month names. JavaScript's toLocaleDateString('uk-UA') emits
# these, so Python must use the same forms or one page shows two spellings of
# the same month (the old table produced "сер" against the chart's "серп.").
# U+00A0. Ukrainian groups thousands with a non-breaking space, which also
# keeps a long number from wrapping mid-value.
UK_GROUP_SEPARATOR = "\u00a0"

UK_MONTHS_SHORT = (
    "січ.", "лют.", "бер.", "квіт.", "трав.", "черв.",
    "лип.", "серп.", "вер.", "жовт.", "лист.", "груд.",
)

# Send the same explicit spellings to charts; en-GB Intl can abbreviate
# September as "Sept" while Python's English strftime uses "Sep".
EN_MONTHS_SHORT = (
    "Jan", "Feb", "Mar", "Apr", "May", "Jun",
    "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
)


def normalize_locale(value: str | None) -> str:
    if not value:
        return DEFAULT_LOCALE
    raw = value.strip().lower().replace("_", "-")
    if raw.startswith("uk") or raw.startswith("ua"):
        return "uk"
    if raw.startswith("en"):
        return "en"
    return DEFAULT_LOCALE


def get_locale() -> str:
    return _locale.get()


def set_locale(locale: str) -> str:
    normalized = normalize_locale(locale)
    _locale.set(normalized)
    return normalized


def activate_locale(locale: str) -> Token[str]:
    """Set a request locale and return the token needed to restore its context."""
    return _locale.set(normalize_locale(locale))


def reset_locale(token: Token[str]) -> None:
    _locale.reset(token)


def t(key: str, **kwargs: Any) -> str:
    entry = MESSAGES.get(key)
    if entry is None:
        text = key
    else:
        text = entry.get(get_locale()) or entry.get(DEFAULT_LOCALE) or key
    if kwargs:
        try:
            return text.format(**kwargs)
        except (KeyError, ValueError):
            return text
    return text


def plural_form(count: int) -> str:
    """Return the Ukrainian plural category for ``count``.

    Ukrainian selects between three forms, so a single ``{count} результати``
    string is wrong for two thirds of the numbers it will be given. English
    always resolves to ``one``/``many``, which maps onto its two forms.
    """
    if get_locale() != "uk":
        return "one" if count == 1 else "many"
    if count % 10 == 1 and count % 100 != 11:
        return "one"
    if count % 10 in (2, 3, 4) and count % 100 not in (12, 13, 14):
        return "few"
    return "many"


def t_plural(key: str, count: int, **kwargs: Any) -> str:
    """Resolve ``key`` against the plural form of ``count``.

    Looks for ``key_one`` / ``key_few`` / ``key_many`` and falls back to the
    bare key, so a caller never breaks when only one form has been written.
    """
    variant = f"{key}_{plural_form(count)}"
    chosen = variant if variant in MESSAGES else key
    return t(chosen, count=count, **kwargs)


def decimal_separator() -> str:
    return "," if get_locale() == "uk" else "."


def format_number_localized(
    value: float | int | None, decimals: int | None = None, *, keep_trailing_zeros: bool = False
) -> str:
    """Format a number with the locale's decimal separator and digit grouping.

    Python's ``%g`` and JavaScript's ``toLocaleString`` disagree about the
    Ukrainian decimal separator, which is why the same page could show ``5,66``
    on a chart axis and ``4.42`` in the table beneath it. Both sides now format
    through this contract.
    """
    if value is None:
        return t("em.dash")
    number = float(value)
    if decimals is None:
        magnitude = abs(number)
        if magnitude >= 100:
            decimals = 0
        elif magnitude >= 10:
            decimals = 1
        else:
            decimals = 2
    text = f"{number:,.{decimals}f}"
    # A value read off a page keeps the zeros the laboratory printed («1,80»).
    if "." in text and not keep_trailing_zeros:
        text = text.rstrip("0").rstrip(".")
    if text == "-0":
        text = "0"
    if get_locale() == "uk":
        # Swap via a placeholder so the two separators cannot collide.
        text = text.replace(",", "\x00").replace(".", ",").replace("\x00", UK_GROUP_SEPARATOR)
    return text


def translate_phrase(text: str | None, *, fallback: str | None = None) -> str:
    if text is None:
        return fallback if fallback is not None else ""
    if get_locale() == DEFAULT_LOCALE:
        return text
    return PHRASES.get(text, text)


def translate_review_reason(reason: str | None) -> str:
    if not reason:
        return ""
    if get_locale() == DEFAULT_LOCALE:
        return reason
    parts = [_translate_reason_piece(chunk.rstrip(".")) for chunk in reason.split(". ")]
    return ". ".join(parts) + ("." if reason.endswith(".") else "")


def _translate_reason_piece(piece: str) -> str:
    match = re.fullmatch(
        r"Verify (\d+) extracted observation\(s\) against page evidence before marking trusted",
        piece,
    )
    if match:
        return t_plural("review.verify_n", int(match.group(1)))
    # A re-read composes its own reason around a version and a count, so it
    # can never be a key in the phrase table; it has to be read back apart.
    rescanned = re.fullmatch(
        r"Re-read with parser (?P<version>\S+): verify (?P<count>\d+) observation\(s\) "
        r"the earlier parse did not produce",
        piece,
    )
    if rescanned:
        return t_plural(
            "review.rescanned_n",
            int(rescanned.group("count")),
            version=rescanned.group("version"),
        ).rstrip(".")
    gone = re.fullmatch(
        r"(?P<count>\d+) observation\(s\) the earlier parse produced are not in this one, "
        r"so check the page to see whether they are really absent",
        piece,
    )
    if gone:
        return t_plural("review.vanished_n", int(gone.group("count"))).rstrip(".")
    unfiled = re.fullmatch(
        r"(?P<count>\d+) checked observation\(s\) could not be re-filed: the page they were "
        r"read from is no longer in this document, so check where they belong",
        piece,
    )
    if unfiled:
        return t_plural("review.unfiled_n", int(unfiled.group("count"))).rstrip(".")
    translated = PHRASES.get(piece) or PHRASES.get(f"{piece}.")
    if translated:
        return translated.rstrip(".")
    return piece


def localize_mapping(values: dict[str, object] | None) -> dict[str, object]:
    if not values:
        return {}
    if get_locale() == DEFAULT_LOCALE:
        return values
    return {
        translate_phrase(str(key).replace("_", " ")) if isinstance(key, str) else key: (
            translate_phrase(str(value)) if isinstance(value, str) else value
        )
        for key, value in values.items()
    }


def format_date_localized(value: str | None, fallback_key: str = "date.unknown") -> str:
    if not value:
        return t(fallback_key)
    try:
        parsed = date.fromisoformat(value[:10])
    except ValueError:
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00")).date()
        except ValueError:
            return value
    if get_locale() == "uk":
        return f"{parsed.day:02d} {UK_MONTHS_SHORT[parsed.month - 1]} {parsed.year}"
    return f"{parsed.day:02d} {EN_MONTHS_SHORT[parsed.month - 1]} {parsed.year}"


# Only strings a script actually reads from `window.__HL_I18N__`. The card
# vocabulary that used to live here — statuses, staleness, authorities, panel
# footers — went out with the live-search JS renderer that cloned a blank card
# and filled the slots it remembered. Search results are server-rendered now, so
# a string needed by a card belongs in the template, not in this payload.
JS_KEYS = (
    "med.lookup.none", "med.lookup.unavailable", "med.lookup.trade_name", "med.lookup.linked",
    "med.lookup.searching", "med.lookup.paused",
    # The site-wide progress bar (busy.js).
    "busy.loading",
    # /metrics type-ahead chrome (the results themselves arrive as HTML).
    "metrics.matches_for",
    "metrics.recent",
    "metrics.shown",
    "metrics.search_unavailable",
    "metrics.search_failed",
    # Chart tooltips and annotations.
    "chart.open_evidence",
    "chart.new_tab",
    "chart.averaged",
    "chart.averaged_point",
    "chart.band_here",
    "chart.axis_compressed",
    "chart.bands_unlabelled",
    "device.samples",
    "device.range",
    # Correlation explorer. The two counted phrases it prints -- the day count
    # and the sampling note -- are pluralised on the server and travel in the
    # API response instead, because Ukrainian picks between three forms and a
    # flat string table cannot.
    "corr.chart_aria",
    "corr.scatter_aria",
    "corr.legend_primary",
    "corr.legend_companion",
    "corr.legend_scaled",
    "corr.smoothed_avg7",
    "corr.smoothed_avg30",
    "corr.stat_companion",
    "corr.stat_too_few",
    "corr.stat_no_overlap",
    "corr.reading_positive",
    "corr.reading_negative",
    "corr.reading_none",
    "corr.strength_negligible",
    "corr.strength_weak",
    "corr.strength_moderate",
    "corr.strength_strong",
    "corr.strength_very_strong",
    "corr.remove",
    "corr.none_selected",
    "corr.scatter_needs_one",
    "corr.loading",
    "corr.nothing_to_draw",
    "corr.error",
    # Source viewer.
    "viewer.source_fallback",
    "viewer.page",
    # AI hand-off modal.  The prompt body is assembled on the server; these are
    # the states only the browser knows about.
    "ai.loading",
    "ai.error",
    "ai.copied",
    "ai.copy_failed",
    "ai.size",
    # The record chat (chat.js): states only the streaming page knows about.
    "chat.you",
    "chat.assistant",
    "chat.thinking",
    "chat.writing",
    "chat.reading",
    "chat.error_network",
    "chat.answer_ready",
    # The upload page (uploads.js): said once when every file is in.
    "upload.announce_done",
)


def js_strings() -> dict[str, Any]:
    """Strings and format rules handed to the browser.

    ``_formats`` exists so client-side rendering cannot drift from the server's:
    both must spell a month and a decimal the same way on the same page.
    """
    payload: dict[str, Any] = {key: t(key) for key in JS_KEYS}
    payload["_formats"] = {
        "decimal": decimal_separator(),
        "group": UK_GROUP_SEPARATOR if get_locale() == "uk" else ",",
        "months_short": list(UK_MONTHS_SHORT if get_locale() == "uk" else EN_MONTHS_SHORT),
    }
    return payload
