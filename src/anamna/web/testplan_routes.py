"""/plan-tests: what to re-measure, and the cheapest way to order it from the
labs whose catalogues we keep (:mod:`..testplan`).  Wired by create_app.

One stateless GET page: the selection travels in the query string
(``need=<key>`` repeated, ``touched=1`` once the person has edited it), so a
plan is a link that can be reopened or shared with oneself.  The only writes
are the lab-side ones the person presses for: an Esculab web order, a Synevo
cart.
"""

from __future__ import annotations

import difflib
import logging
import re
from datetime import date, datetime
from urllib.parse import parse_qsl, quote, unquote, urlencode
from uuid import uuid4

from fastapi import HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from starlette.datastructures import QueryParams
from starlette.concurrency import run_in_threadpool

from .. import labsync, testplan, testplan_prep, testplan_special, testplan_value
from ..db import connect, transaction, utc_now
from ..health import concept_display_name
from ..i18n import format_number_localized, get_locale, t
from ..labsync import esculab_shop
from ..labsync.common import LabSyncError
from ..locales.concepts_en import CONCEPT_NAMES_EN
from ..locales.concepts_uk import CONCEPT_NAMES_UK
from . import search as record_search

logger = logging.getLogger("anamna.testplan")

try:  # the Synevo catalogue lives in its own module; absent, the planner is Esculab only
    from ..labsync import synevo_shop
except ImportError:  # pragma: no cover
    synevo_shop = None

#: Labs with a catalogue, in the order the page lists them.
SHOPS = {"esculab": esculab_shop}
if synevo_shop and all(hasattr(synevo_shop, name) for name in ("catalog", "ensure_fresh", "regions", "DEFAULT_REGION")):
    SHOPS["synevo"] = synevo_shop
VENDORS = {"esculab": "Esculab", "synevo": "Synevo"}
#: Why Synevo did not take an item into the cart (synevo_shop._refusal).
CART_REASONS = frozenset({"synevo_cart.in_package", "synevo_cart.refused", "synevo_cart.promo",
                          "synevo_cart.needs_confirmation", "synevo_cart.not_added", "labsync.error_reply",
                          "labsync.error_unreachable"})
_KEYED: dict[tuple, list[dict]] = {}

#: Ready-made selections for the usual reasons to see a lab ("the doctor
#: asked about sugar", "I feel unwell", the yearly check-up).  Each one covers
#: its area in full, the way the labs' own extended programmes for that area
#: do (Esculab and Synevo check-ups, "liver", "kidneys", "anaemia", "thyroid",
#: "heart and vessels", "vitamins and minerals" packages, read from the stored
#: catalogues in November 2026), so the person unticks what they do not want
#: rather than searching for what is missing.  Only keys both labs sell; a
#: preset adds to the selection and skips what no lab in the city sells.
_BLOOD_COUNT = ("hemoglobin", "red-blood-cell-count", "hematocrit", "mean-corpuscular-volume",
                "mean-corpuscular-hemoglobin", "mean-corpuscular-hemoglobin-concentration",
                "red-cell-distribution-width-cv", "red-cell-distribution-width-sd", "platelet-count",
                "mean-platelet-volume", "plateletcrit", "white-blood-cell-count", "neutrophils", "neutrophils-absolute",
                "lymphocytes", "lymphocytes-absolute", "monocytes", "monocytes-absolute", "eosinophils",
                "eosinophils-absolute", "basophils", "basophils-absolute", "erythrocyte-sedimentation-rate")
_URINE = ("urine-colour", "urine-appearance", "urine-specific-gravity", "urine-ph", "urine-protein", "urine-glucose",
          "urine-ketones", "urine-bilirubin", "urine-urobilinogen", "urine-nitrite", "urine-leukocytes",
          "urine-erythrocytes", "urine-bacteria")
_CLOTTING = ("prothrombin-time", "inr", "quick-prothrombin-index", "activated-partial-thromboplastin-time",
             "thrombin-time", "fibrinogen", "x:d-dimer")
PRESETS: dict[str, tuple[str, ...]] = {
    "basic": (*_BLOOD_COUNT, "c-reactive-protein", "blood-glucose", "creatinine", "urea", "alanine-aminotransferase",
              "aspartate-aminotransferase", "total-bilirubin", "potassium", "sodium", *_URINE),
    "blood": _BLOOD_COUNT,
    "sugar": ("blood-glucose", "hemoglobin-a1c", "insulin", "x:homa-ir", "c-peptide", "x:gad-antibodies"),
    "heart": ("total-cholesterol", "ldl-cholesterol", "hdl-cholesterol", "triglycerides", "apolipoprotein-a1",
              "apolipoprotein-b", "lipoprotein-a", "homocysteine", "c-reactive-protein", "x:creatine-kinase",
              "x:lactate-dehydrogenase", "potassium", "sodium", "magnesium", "fibrinogen"),
    "thyroid": ("thyroid-stimulating-hormone", "free-thyroxine", "free-triiodothyronine",
                "thyroid-peroxidase-antibodies", "thyroglobulin-antibodies", "x:thyroglobulin", "x:calcitonin"),
    "liver": ("alanine-aminotransferase", "aspartate-aminotransferase", "gamma-glutamyl-transferase",
              "alkaline-phosphatase", "total-bilirubin", "direct-bilirubin", "total-protein", "albumin",
              "prothrombin-time", "inr", "hepatitis-b-surface-antigen", "hepatitis-b-core-antigen-marker",
              "hepatitis-c-total-antibodies"),
    "kidneys": ("creatinine", "x:cystatin-c", "urea", "uric-acid", "potassium", "sodium", "x:chloride",
                "calcium-total", "albumin", "total-protein", "x:urine-albumin-creatinine-ratio", *_URINE),
    "iron": (*_BLOOD_COUNT, "ferritin", "serum-iron", "x:transferrin", "x:transferrin-saturation",
             "x:unsaturated-iron-binding-capacity", "vitamin-b12", "folate-serum", "c-reactive-protein"),
    "vitamins": ("25-hydroxyvitamin-d", "vitamin-b12", "folate-serum",
                 "ferritin", "serum-iron", "magnesium", "calcium-total",
                 "calcium-ionized", "x:phosphorus", "x:zinc", "potassium", "sodium",
                 "parathyroid-hormone"),
    "clotting": _CLOTTING,
    "men": ("x:psa-total", "x:psa-free", "total-testosterone", "x:free-testosterone", "x:sex-hormone-binding-globulin",
            "x:luteinizing-hormone", "x:follicle-stimulating-hormone", "x:prolactin", "x:estradiol",
            "x:dhea-sulfate"),
    "women": ("x:follicle-stimulating-hormone", "x:luteinizing-hormone", "x:estradiol", "x:progesterone",
              "x:prolactin", "total-testosterone", "x:sex-hormone-binding-globulin", "x:dhea-sulfate",
              "cancer-antigen-125-ca-125", "human-epididymis-protein-4-he4", "cancer-antigen-15-3-ca-15-3"),
}
#: Presets for one sex: offered to that sex, or to both when the sex is unknown.
PRESET_SEX = {"men": "M", "women": "F"}
#: The full check-up holds everything: every area preset (the person's own
#: sex for the hormone set; both when the sex is unknown), plus what the labs'
#: 19 general check-up programmes add beyond the areas (Synevo "Все під
#: контролем", "Щорічний контроль", "Повне обстеження"; Esculab "Check-UP
#: 35+/45+/50+", "Щорічне профілактичне", "Метаболічний Check-UP").  With it
#: on, every other preset is on too; the person unticks what they skip.
CHECKUP_EXTRA = ("alpha-amylase", "rheumatoid-factor", "antistreptolysin-o", "total-immunoglobulin-e",
                 "x:cortisol-serum", "x:alpha-fetoprotein", "x:cea")


def presets_for(sex: str | None) -> dict[str, tuple[str, ...]]:
    """The presets offered to a person of ``sex`` ("M", "F" or None), the
    full check-up first."""
    shown = {name: keys for name, keys in PRESETS.items() if sex is None or PRESET_SEX.get(name) in (None, sex)}
    return {"checkup": tuple(dict.fromkeys([*(k for keys in shown.values() for k in keys), *CHECKUP_EXTRA])),
            **shown}


#: A result measured this many days ago or less is not worth repeating yet;
#: the "skip recent" switch leaves it unticked.
RECENT_DAYS = 14


#: Analyte search rows sent to the page; past this the query is too vague to scroll.
SEARCH_CAP = 50


def uah(value: object) -> str:
    amount = float(value or 0)
    return t("plan.uah", amount=format_number_localized(amount, 0 if amount == int(amount) else 2))


def _lab_items(settings, connection, owner_id: str, key: str, region: str) -> list[dict] | None:
    """The lab's catalogue keyed to this record, or None while it has never
    been read.  Keying is memoised per catalogue copy and record size."""
    module = SHOPS[key]
    if key == "esculab":
        try:
            raw = module.catalog(settings, region)
        except LabSyncError:
            raw = None
    else:
        module.ensure_fresh(settings, region)
        raw = module.catalog(settings, region)
    if raw is None:
        return None
    raw, described = _described(settings, key, raw)
    stamp = (key, region, owner_id, testplan.fetched_at(settings, key, region), described,
             connection.execute("SELECT COUNT(*) FROM concept_aliases").fetchone()[0],
             connection.execute("SELECT COUNT(*) FROM lab_orders WHERE owner_user_id=? AND provider=?",
                                (owner_id, key)).fetchone()[0])
    if stamp not in _KEYED:
        # ponytail: a small dict, cleared when it grows; an LRU if many people plan at once.
        if len(_KEYED) > 16:
            _KEYED.clear()
        # Special tests (an allergy panel, a genetic test) carry their
        # ``sp:`` keys too, so the solver covers them like any analyte.
        _KEYED[stamp] = testplan_special.tag(testplan.keyed(
            raw, key, VENDORS[key], testplan.alias_index(connection),
            testplan.learned_names(connection, owner_id, key), testplan.category_index(connection)))
    return _KEYED[stamp]


_DESCRIBING: dict[str, object] = {}


def complex_item(item: dict) -> bool:
    """An item whose price-list rows do not say what it contains: a genetic
    test (a 252-gene panel is one row), or a package of one row."""
    kind = testplan.item_kind(item)
    return kind == "genetic" or (kind == "set" and len(item.get("parameters") or ()) <= 1)


def _described(settings, key: str, raw: list[dict]) -> tuple[list[dict], int]:
    """Complex items (:func:`complex_item`) with what the lab's own page says
    they contain (``description``, ``genes``), from the cache; whatever is
    not cached yet is read in a background thread, never while the page
    waits, and the items gain it on the next view.  Also how many are
    described, so keying is redone as descriptions arrive."""
    import threading

    module = SHOPS[key]
    if not hasattr(module, "descriptions"):
        return raw, 0
    wanted = [item for item in raw if complex_item(item)]
    found = module.descriptions(settings, wanted, fetch=False)
    missing = [item for item in wanted if str(item["id"]) not in found and str(item.get("code")) not in found]
    thread = _DESCRIBING.get(key)
    if missing and not (thread and thread.is_alive()):
        def read():
            try:
                module.descriptions(settings, missing)
            except Exception as exc:  # noqa: BLE001 -- a background thread has nobody to raise to
                logger.warning("%s descriptions not read: %s", key, getattr(exc, "key", type(exc).__name__))

        _DESCRIBING[key] = thread = threading.Thread(target=read, name=f"{key}-descriptions", daemon=True)
        thread.start()

    def own(item):
        return found.get(str(item["id"])) or found.get(str(item.get("code")))

    return [{**item, "description": own(item)["text"], "genes": own(item)["genes"]} if own(item) else item
            for item in raw], len(found)


def special_offers(settings, connection, owner_id: str, entries) -> dict[str, list[dict]]:
    """What each special test (:mod:`.testplan_special` entry) costs at each
    lab's default city today: the cheapest mix of that lab's items that
    answers it, draw fees included, from the stored price lists only (never
    waits on a lab).  ``{entry id: [{"lab", "vendor", "cost", "items": [names]}]}``,
    cheapest lab first; a lab that does not sell it, or whose list is being
    read, is absent."""
    out: dict[str, list[dict]] = {entry.id: [] for entry in entries}
    for key in SHOPS:
        items, _fetched = stored_lab_items(settings, connection, owner_id, key)
        if not items:
            continue
        for entry in entries:
            need = set(entry.keys)
            pool = [item for item in items if need & set(item["keys"])]
            if not need <= {k for item in pool for k in item["keys"]}:
                continue
            best = testplan_value.alternatives(pool, need, limit=0)[0]
            out[entry.id].append({"lab": key, "vendor": VENDORS[key], "cost": best["cost"],
                                  "items": [_label(item)["label"] for item in best["items"]]})
    for offers in out.values():
        offers.sort(key=lambda offer: offer["cost"])
    return out


_REREADING: dict[str, object] = {}


def stored_lab_items(settings, connection, owner_id: str, key: str) -> tuple[list[dict] | None, str | None]:
    """:func:`_lab_items` for the lab's default city, and when that copy was
    read, for a page that must not wait on a lab.  None while the catalogue
    has never been read, and while a day-old Esculab copy is re-read in a
    background thread: the page never waits for it and never shows a stale
    price.  Synevo already crawls in the background (``ensure_fresh``)."""
    import threading
    from datetime import UTC

    module = SHOPS[key]
    region = module.DEFAULT_REGION
    fetched = testplan.fetched_at(settings, key, region)
    if key == "esculab" and (fetched is None
                             or datetime.now(UTC) - datetime.fromisoformat(fetched) > module.CATALOG_TTL):
        def reread():
            try:
                module.catalog(settings, region)
            except Exception as exc:  # noqa: BLE001 -- a background thread has nobody to raise to
                logger.warning("esculab price list re-read failed: %s", getattr(exc, "key", type(exc).__name__))

        thread = _REREADING.get(region)
        if not (thread and thread.is_alive()):
            _REREADING[region] = thread = threading.Thread(target=reread, name="esculab-catalog", daemon=True)
            thread.start()
        return None, None
    items = _lab_items(settings, connection, owner_id, key, region)
    return items, fetched if items is not None else None


def _order_account(settings, user_id: str, owner_id: str, key: str) -> tuple[str, str | None]:
    """Whose lab account an order for ``owner_id``'s record goes through, and
    the owner's person on it.  One's own record: one's own account.  A record
    shared with ``user_id``: their own account when it holds the owner as a
    person (a family link the owner accepted), else the owner's.  The person
    is None when no account here holds the owner."""
    with connect(settings) as connection:
        for account_id in dict.fromkeys([user_id, owner_id]):
            row = connection.execute(
                """SELECT remote_person_id FROM lab_person_links WHERE account_user_id=? AND provider=?
                       AND target_user_id=? AND consent IN ('owner', 'accepted')""",
                (account_id, key, owner_id)).fetchone()
            if row:
                return account_id, str(row["remote_person_id"])
    return user_id, None


#: Query parameters a saved selection keeps: what is ticked, how and where to
#: plan, and the order edits.  Searches, filters and one-off presses are not.
SUGGESTION_KEEP = frozenset({"touched", "need", "add", "include", "sx", "topic", "special", "recent", "city", "pref",
                             "mode", "ex", "cut", "put"})


def suggestion_query(raw: str) -> str:
    """The query string a doctor's selection is saved as (:data:`SUGGESTION_KEEP`
    and each lab's chosen option), from the planner's own query string."""
    return urlencode([(name, value) for name, value in parse_qsl(raw, keep_blank_values=False)
                      if name in SUGGESTION_KEEP or re.fullmatch(r"alt_[a-z]+", name)])


# --- search: one matcher for both boxes ------------------------------------------
#
# Matching is /metrics' (web/search.py): whole words, case- and script-folded,
# its abbreviation table.  Two things are added on both sides here: apostrophes
# are dropped («зв’язок», "зв'язок" and «звʼязок» are one word, not two), and a
# Latin abbreviation spelled with Cyrillic lookalikes («МСН» for MCH, «LDLС»)
# also gets its Latin twin, which transliteration alone would read as "msn".

_APOSTROPHES = str.maketrans({**dict.fromkeys(map(ord, "'’ʼ`´")),
                              # Latin accents only: Cyrillic «й»/«ї» are letters of their own.
                              **{ord(a): b for a, b in zip("äöüéèêáàíóúçñÄÖÜÉÈÊÁÀÍÓÚÇÑ", "aoueeeaaioucnAOUEEEAAIOUCN")}})
_HOMOGLYPHS = str.maketrans("АВСЕНКМОРТХІаеорсхі", "ABCEHKMOPTXIaeopcxi")
_LOOKALIKE = frozenset("АВСЕНКМОРТХІ")
_LETTERS = re.compile(r"[^\W\d_]+")
_LATIN, _CYRILLIC = re.compile(r"[A-Za-z]"), re.compile(r"[А-Яа-яІіЇїЄєҐґ]")


def _latin_twin(token: str) -> str:
    mixed = _LATIN.search(token) and _CYRILLIC.search(token)
    disguised = len(token) >= 2 and set(token) <= _LOOKALIKE
    return token.translate(_HOMOGLYPHS) if mixed or disguised else token


#: A short Latin token with a "g" («tTG», "IgG"): the search key folds g into
#: h for "EKG"/«ЕКГ», which made «tTG» (tissue transglutaminase) an answer to
#: "TSH" by way of «ТТГ».  In a lab's names such a token keeps its g (as "ɡ",
#: U+0261, which the key leaves alone); a query is tried both ways.
_SHORT_LATIN = re.compile(r"\b[A-Za-z0-9]{1,4}\b")


def _keep_g(text: str) -> str:
    return _SHORT_LATIN.sub(lambda match: re.sub("[gG]", "ɡ", match.group()), text)


def _spellings(text: object, *, query: bool = False) -> list[str]:
    plain = str(text or "").translate(_APOSTROPHES)
    twin = _LETTERS.sub(lambda match: _latin_twin(match.group()), plain)
    out = list(dict.fromkeys([plain, twin]))
    if query:
        return list(dict.fromkeys(out + [_keep_g(s) for s in out]))
    return list(dict.fromkeys(_keep_g(s) for s in out))


def _terms(primary, secondary=()) -> record_search.Terms:
    return record_search.terms([s for text in primary for s in _spellings(text)],
                               [s for text in secondary for s in _spellings(text)])


def _item_terms(item: dict) -> record_search.Terms:
    """An item's own names, folded once and kept on the (memoised) item."""
    found = item.get("_terms")
    if found is None:
        # The lab's description of a complex item (a gene panel, a one-row
        # package) is context: «муковісцидоз» finds a carrier screen.
        found = item["_terms"] = _terms([item["name"], item.get("name_en"), item.get("code"),
                                         *item.get("synonyms", ()), *item.get("aka", ())],
                                        [item["description"]] if item.get("description") else ())
    return found


_KEY_TERMS: dict[str, record_search.Terms] = {}


def _key_terms(key: str, concepts: dict[str, str]) -> record_search.Terms:
    """Our concept's name in both languages, for the items that measure it."""
    name = concepts.get(key)
    if not name:
        return ()
    if name not in _KEY_TERMS:
        _KEY_TERMS[name] = _terms([name, CONCEPT_NAMES_EN.get(name), CONCEPT_NAMES_UK.get(name)])
    return _KEY_TERMS[name]


#: A query word found inside a longer word («холестерин» in
#: «гіперхолестеринемія»): the sets browser's last tier, below every word hit.
INFIX = record_search.PARTIAL + 3


def _rank(text: str, rows: list[tuple[record_search.Terms, object]], *,
          infix: bool = False) -> tuple[list[tuple[int, object]], bool]:
    """(score, row) best first, and whether the hits are close spellings
    because nothing matched as typed.  The typo pass corrects only words of
    five letters or more, to the nearest word the rows contain (difflib,
    ratio 0.8), so «ферретин» finds «феритин» and "TSH" never becomes "TSB".
    ``infix`` also takes rows where every query word of five letters or more
    sits inside a word, after all others."""
    def ranked(query_text: str):
        queries = [record_search.parse(spelling) for spelling in _spellings(query_text, query=True)]
        hits = []
        for index, (terms, row) in enumerate(rows):
            scores = [s for query in queries if (s := record_search.score(query, terms)) is not None]
            if scores:
                hits.append((min(scores), index, row))
        if any(value < record_search.PREFIX for value, _, _ in hits):
            cutoff = record_search.PREFIX if queries[0].short else record_search.PARTIAL
            hits = [hit for hit in hits if hit[0] < cutoff]
        return [(value, row) for value, _, row in sorted(hits, key=lambda hit: hit[:2])]

    hits = ranked(text)
    words = record_search.words(text.translate(_APOSTROPHES))
    long_words = [word for word in words if len(word) >= 5]
    if infix and long_words and len(long_words) == len(words):
        found = {id(row) for _, row in hits}
        hits += [(INFIX, row) for terms, row in rows if id(row) not in found
                 and all(any(word in have for term, _ in terms for keys in term for have in keys) for word in long_words)]
    if hits or not long_words:
        return hits, False
    # Each word of a term is the tuple of spellings it is found under.
    vocabulary = {word for terms, _ in rows for term, _ in terms for keys in term for word in keys}
    fixed = [word if len(word) < 5 or word in vocabulary
             else next(iter(difflib.get_close_matches(word, vocabulary, n=1, cutoff=0.8)), word) for word in words]
    return (ranked(" ".join(fixed)), True) if fixed != list(words) else ([], False)


def _search(text: str, cards: list[dict], labs: dict[str, list[dict]], names: dict[str, str],
            selected: set[str], from_labs: set[str], concepts: dict[str, str] | None = None) -> tuple[list[dict], bool]:
    """The "Add a test" box: measurable results only, one row per requirement
    key.  Rows are the record's laboratory results and every key a lab sells
    as a single test, found by the record's names, our concept names in both
    languages, and the labs' own names, codes and synonyms.  A row carries the
    cheapest single test per lab; panels, packages and genetic tests are never
    rows here (:func:`_sets` lists them).  An examination sold as one item
    that stands for several keys (a coprogram) is one row that adds them all.
    Returns the rows and whether they are close spellings of the query."""
    concepts = concepts or {}
    rows: dict[str, dict] = {}
    for card in cards:
        key = str(card["id"])
        if card.get("is_device") or key not in from_labs:
            continue
        rows[key] = {"label": card["name"], "detail": card.get("panel_name") or card.get("category_label") or "",
                     "keys": [key], "kind": "record", "price": 0.0,
                     "terms": [card.get("search_terms") or _terms([card["name"], *(card.get("aliases") or [])]),
                               _key_terms(key, concepts)]}
    singles: dict[str, dict[str, float]] = {}
    for lab, items in labs.items():
        for item in items:
            if testplan.item_kind(item) != "single":
                continue
            if len(item["keys"]) == 1:
                key = item["keys"][0]
                cheapest = singles.setdefault(key, {})
                cheapest[lab] = min(item["final_price"], cheapest.get(lab, item["final_price"]))
                row = rows.setdefault(key, {"label": names.get(key, key), "detail": "", "keys": [key], "kind": "lab",
                                            "price": item["final_price"], "terms": [_key_terms(key, concepts)]})
                row["terms"].append(_item_terms(item))
                row["price"] = min(row["price"], item["final_price"])
            elif item["keys"]:
                rows[f"{lab}:{item['id']}"] = {
                    "label": item["name"], "keys": item["keys"], "kind": "item", "price": item["final_price"],
                    "detail": t("plan.search_item", lab=VENDORS[lab], price=uah(item["final_price"]),
                                count=len(item["keys"])),
                    "terms": [_item_terms(item)]}
    order = {"record": 0, "lab": 1, "item": 2}
    by_id = {str(card["id"]): card for card in cards if not card.get("is_device")}
    hits, fuzzy = _rank(text, [(tuple(term for terms in row["terms"] for term in terms), row) for row in rows.values()])
    hits.sort(key=lambda hit: (hit[0], order[hit[1]["kind"]], hit[1]["price"]))
    out = []
    for _, row in hits:
        offers = singles.get(row["keys"][0], {}) if row["kind"] != "item" else {}
        card = by_id.get(row["keys"][0]) if len(row["keys"]) == 1 else None
        out.append({"label": row["label"], "detail": row["detail"], "kind": row["kind"], "keys": row["keys"],
                    "card": card,
                    "offers": ", ".join(f"{VENDORS[lab]} {uah(price)}" for lab, price in sorted(offers.items())),
                    "value": "|".join(row["keys"]), "names": [names.get(k, k) for k in row["keys"][:6]],
                    "chosen": set(row["keys"]) <= selected})
    return out, fuzzy


def _label(item: dict) -> dict:
    """The item's name for this page: the lab's own English one on the
    English page when it publishes one (Synevo), else its Ukrainian name."""
    if get_locale() == "en" and item.get("name_en"):
        return {"label": item["name_en"], "label_lang": "en"}
    return {"label": item["name"], "label_lang": "uk"}


def _set_row(lab: str, item: dict, names: dict[str, str], included: set[str]) -> dict:
    value = f"{lab}:{item['id']}"
    return {"value": value, "lab": lab, "vendor": VENDORS[lab], "id": item["id"], "name": item["name"],
            **_label(item),
            "code": item.get("code") or "", "url": item.get("url"), "price": item["price"],
            "final_price": item["final_price"], "kind": testplan.item_kind(item),
            "analytes": [parameter["name"] for parameter in item["parameters"]], "included": value in included}


def _sets(text: str, group: str, labs: dict[str, list[dict]], names: dict[str, str], included: set[str],
          concepts: dict[str, str]) -> tuple[list[dict], bool]:
    """"Panels and special tests": what is not one measurable result
    (``testplan.item_kind`` ``set`` / ``genetic``), every match: by text
    (names, codes, synonyms; the lab's shelves and the analytes reported
    count as context), within one of the lab's shelves (``group`` =
    ``<lab>:<shelf>``) when one is chosen, A to Z when there is no text.
    The page filters and pages them (:func:`_page`)."""
    pool = [(lab, item) for lab, items in labs.items() for item in items if testplan.item_kind(item) != "single"]
    if group:
        lab_key, _, shelf = group.partition(":")
        pool = [(lab, item) for lab, item in pool if lab == lab_key and shelf in (item.get("groups") or ())]
    if not text:
        pool.sort(key=lambda pair: testplan.alphabetical(pair[1]["name"]))
        return [_set_row(lab, item, names, included) for lab, item in pool], False
    rows = []
    for lab, item in pool:
        context = _terms(item.get("groups") or (), [n for k in item["keys"][:40] for n in (concepts.get(k),) if n])
        rows.append((_item_terms(item) + tuple((term, weight | 1) for term, weight in context), (lab, item)))
    hits, fuzzy = _rank(text, rows, infix=True)
    # Equally good matches: the smaller set first («Ліпідограма» before a
    # 66-result annual check-up that also measures cholesterol).
    hits.sort(key=lambda hit: (hit[0], len(hit[1][1]["parameters"])))
    return [_set_row(lab, item, names, included) for _, (lab, item) in hits], fuzzy


def _both(key: str) -> list[str]:
    """A message in both languages, for search terms: «лактоза» finds the
    test on the English page too."""
    from ..locales.messages import MESSAGES

    return list((MESSAGES.get(key) or {}).values())


#: Where a special test is explained at length.
SPECIAL_PAGES = {"allergy": "/allergy", "genetics": "/genetics"}


def _special(params, sex: str | None, ready: dict[str, list[dict]], cards: list[dict], *,
             skip_recent: bool, recent, query: str, sparkline, left_out=frozenset()) -> dict:
    """The planner's second mode (:mod:`.testplan_special`): entries picked
    (``sx``), topics open (``topic``; ``preset`` opens one and ticks its core
    entries, ``drop`` closes it with its entries), what each entry looks like
    on the list, and the requirement keys the picked ones stand for.

    An entry is "measured" when the record holds every key it stands for, or
    every result of a lab item that is one (the 7-infection PCR panel's
    seven), or, for an allergy panel, any allergen result at all (said on
    the row).  Topics tick and untick like routine presets.  An entry that
    needs a sample the person leaves out (``left_out``: keys no lab here
    sells any more) is neither listed nor picked."""
    entries = [entry for entry in testplan_special.for_sex(sex) if not set(entry.keys) & set(left_out)]
    by_id = {entry.id: entry for entry in entries}
    card_by = {str(card["id"]): card for card in cards if not card.get("is_device")}
    sold_at = {lab: {k for item in items for k in item["keys"]} for lab, items in ready.items()}
    # The record keys each marker's items report: how a marker counts as
    # measured.  Only an item whose every result the record can hold says
    # so: a genetic test's own result has no record key (a folate package
    # with MTHFR also measures B12, which says nothing about the gene).
    behind: dict[str, list[list[str]]] = {}
    for items in ready.values():
        for item in items:
            plain = [k for k in item["keys"] if not k.startswith("sp:")]
            if not plain or testplan.item_kind(item) == "genetic" \
                    or any(k.startswith(tuple(f"{lab}:" for lab in VENDORS)) for k in plain):
                continue
            for k in item["keys"]:
                if k.startswith("sp:"):
                    behind.setdefault(k, []).append(plain)
    # Results by category (an allergy test's allergens); total IgE is a
    # test of its own, not one of them.
    own = {key for entry in entries for key in entry.keys}
    categories: dict[str, list[str]] = {}
    for card in card_by.values():
        if card.get("category") and card.get("latest_date") and str(card["id"]) not in own:
            categories.setdefault(str(card["category"]), []).append(str(card["latest_date"])[:10])

    def latest(keys) -> str:
        return max(str(card_by[k].get("latest_date") or "")[:10] for k in keys)

    def measured(entry) -> dict | None:
        if all(k in card_by for k in entry.keys):
            return {"date": latest(entry.keys)}
        dates = []
        for key in entry.keys:
            found = [latest(plain) for plain in behind.get(key, ()) if all(k in card_by for k in plain)]
            if not found:
                break
            dates.append(max(found))
        else:
            return {"date": max(dates)}
        if entry.category and entry.category in categories:
            dates = categories[entry.category]
            return {"date": max(dates), "count": len(dates)}
        return None

    def fresh(entry) -> bool:
        """Measured days ago: most of its results were (a blood count whose
        ESR came from an older draw still counts)."""
        return 2 * sum(1 for k in entry.keys if k in card_by and recent(k)) >= len(entry.keys)

    touched = bool(params.get("touched"))
    picked = list(dict.fromkeys(v for v in params.getlist("sx") if v in by_id)) if touched else []
    # Presets: the topics, then the published standards (ACMG carrier
    # tiers, the GA²LEN allergen panel), each a group of entries.
    groups = {**{topic: [e for e in entries if e.topic == topic] for topic in testplan_special.TOPICS},
              **{std.id: [by_id[i] for i in std.entries if i in by_id] for std in testplan_special.STANDARDS}}
    topics = [t for t in dict.fromkeys(params.getlist("topic")) if t in groups]
    done = {entry.id: measured(entry) for entry in entries}
    sold = {entry.id: [lab for lab in ready if set(entry.keys) <= sold_at[lab]] for entry in entries}
    # A topic works as a routine preset does: pressed, it ticks every test
    # in it that a lab here sells, except what was measured days ago and a
    # DNA test already done (its result cannot change); pressed again
    # (``drop``), it takes them off the list, as a preset takes its results.
    wanted = {group: [e.id for e in members if sold[e.id]
                      and not (skip_recent and fresh(e)) and not (e.once and done[e.id])]
              for group, members in groups.items()}
    for topic in params.getlist("drop"):
        if topic in wanted:
            picked = [p for p in picked if p not in wanted[topic]]
            topics = [t for t in topics if t != topic]
    for value in params.getlist("preset"):
        if value in wanted:
            topics += [value] if value not in topics else []
            picked += [p for p in wanted[value] if p not in picked]
    # Rows: the open presets' entries, then what was picked elsewhere (the search).
    shown = list({entry.id: entry for group in topics for entry in groups[group]}.values())
    shown += [by_id[p] for p in picked if by_id[p] not in shown]
    opened = {entry.id for entry in shown}

    def row(entry) -> dict:
        keys = entry.keys
        card = card_by.get(keys[0]) if len(keys) == 1 else None
        if card:
            card.setdefault("spark", sparkline(card, None))
        page = SPECIAL_PAGES.get(entry.topic)
        # ``skipped``: left unticked only by the "skip recent" switch, so
        # turning it off ticks it, as on the routine list.
        recent_now = fresh(entry)
        return {"id": entry.id, "topic": entry.topic, "checked": entry.id in picked, "card": card,
                "recent": recent_now, "skipped": recent_now and skip_recent and entry.id not in picked
                and entry.id in opened and bool(sold[entry.id]) and not (entry.once and done[entry.id]),
                "name": t(f"special.{entry.id}"), "what": t(f"special.{entry.id}_what"),
                "done": done[entry.id], "once": entry.once, "labs": [VENDORS[lab] for lab in sold[entry.id]],
                "all_labs": len(sold[entry.id]) == len(ready),
                "page": (f"{page}#{entry.id}" if entry.topic == "genetics" else page) if page else None}

    rows = [row(entry) for entry in shown]
    listed = {entry.id for entry in shown}
    match, found = None, []
    if query:
        candidates = [(_terms([*_both(f"special.{e.id}")],
                              [*_both(f"special.{e.id}_what"), *_both(f"special.topic_{e.topic}")]), e)
                      for e in entries]
        hits, _fuzzy = _rank(query, candidates)
        match = [entry.id for _, entry in hits if entry.id in listed]
        found = [row(entry) for _, entry in hits if entry.id not in listed]
    keys = list(dict.fromkeys(k for p in picked for k in by_id[p].keys))
    standards = {std.id for std in testplan_special.STANDARDS}
    topics_view = [{"value": group, "keys": wanted[group], "count": len(wanted[group]),
                    "chosen": sum(1 for p in wanted[group] if p in picked), "standard": group in standards,
                    # left out by the switch, said on the tile
                    "recent": sum(1 for e in members if sold[e.id] and skip_recent
                                  and fresh(e) and not (e.once and done[e.id]))}
                   for group, members in groups.items() if wanted[group]]
    return {"picked": picked, "topics": topics_view, "open": topics, "rows": rows, "found": found,
            "match": match, "keys": keys, "recent_listed": sum(1 for r in rows if r["recent"]),
            "names": {marker.key: t(f"special.{marker.id}") for marker in testplan_special.MARKERS},
            # An allergen no lab sells alone (olive, t9: only inside ALEX)
            # has no lab row to name it; the lab's name still wins.
            "fallback_names": {f"x:sige:{code}": t(f"special.allergen_{code}") for code in testplan_special.ALLERGENS}}


#: Rows per page in every long list on the page.
PAGE_SIZE = 20


def _page(rows: list, raw: object, size: int = PAGE_SIZE) -> dict:
    """One page of ``rows``; ``raw`` is the query-string page number, read
    leniently and clamped to the pages there are."""
    pages = max(1, -(-len(rows) // size))
    try:
        page = min(max(1, int(str(raw or "1"))), pages)
    except ValueError:
        page = 1
    first = (page - 1) * size
    return {"rows": rows[first:first + size], "page": page, "pages": pages, "total": len(rows),
            "start": first + 1 if rows else 0, "end": min(first + size, len(rows))}


def _amount(raw: object) -> float | None:
    """A price ceiling from the query string: a positive number, else none."""
    text = "".join(str(raw or "").split()).replace(",", ".")
    try:
        value = float(text)
    except ValueError:
        return None
    return value if 0 < value < 1e9 else None


def page_url(params, key: str, page: int, anchor: str = "") -> str:
    """This page's address with ``key`` set to ``page``: every other choice
    (needs, included items, queries, filters, cities) is kept."""
    keep = [(name, value) for name, value in params.multi_items() if name not in {key, "notice"}]
    if page > 1:
        keep.append((key, str(page)))
    return "/plan-tests?" + urlencode(keep) + (f"#{anchor}" if anchor else "")


def _shelves(labs: dict[str, list[dict]], titles: dict[str, str]) -> list[dict]:
    """The labs' own shelves that hold panels or special tests, to browse by.
    Esculab files each item on one named shelf (its first group); Synevo puts
    an item on several, by rubric code, named through ``titles``
    (``synevo_shop.sections``).  A code without a name is not offered."""
    counts: dict[tuple[str, str], int] = {}
    for lab, items in labs.items():
        for item in items:
            groups = item.get("groups") or ()
            if not groups or testplan.item_kind(item) == "single":
                continue
            for group in (groups if lab == "synevo" else groups[:1]):
                if lab != "synevo" or group in titles:
                    counts[(lab, group)] = counts.get((lab, group), 0) + 1
    rows = [{"lab": lab, "vendor": VENDORS[lab], "name": titles.get(code, code) if lab == "synevo" else code,
             "count": count, "value": f"{lab}:{code}"} for (lab, code), count in counts.items()]
    return sorted(rows, key=lambda row: (row["lab"], testplan.alphabetical(row["name"])))


def _section_titles(settings) -> dict[str, str]:
    if "synevo" not in SHOPS or not hasattr(synevo_shop, "sections"):
        return {}
    try:
        return synevo_shop.sections(settings)
    except LabSyncError:
        return {}


# --- what to bring and when it is ready ---------------------------------------------

#: The lab's sample names a reader of the English page sees translated; any
#: other material is shown as the lab wrote it, marked as Ukrainian.
MATERIALS = {
    "сироватка крові": "plan.material_serum", "цільна кров": "plan.material_whole_blood",
    "цільна кров зак": "plan.material_whole_blood", "плазма крові": "plan.material_plasma",
    "сеча": "plan.material_urine", "сеча (добова)": "plan.material_urine_24h", "кал": "plan.material_stool",
    "ліквор": "plan.material_csf", "сперма": "plan.material_semen", "слина": "plan.material_saliva",
    "сироватка капілярної крові": "plan.material_capillary_serum", "капілярна кров": "plan.material_capillary_blood",
    "венозна кров": "plan.material_venous_blood", "секрет простати": "plan.material_prostate",
}


def _materials(item: dict, locale: str) -> list[dict]:
    """``[{text, lang}]``: the sample in the reader's language where we know
    the lab's word for it, else the lab's own words with their language."""
    own_en = item.get("material_en") or []
    out = []
    for index, name in enumerate(item.get("material") or []):
        key = MATERIALS.get(name.casefold().strip())
        if locale == "uk":
            out.append({"text": name, "lang": "uk"})
        elif key:
            out.append({"text": t(key), "lang": "en"})
        elif index < len(own_en) and own_en[index]:
            out.append({"text": own_en[index], "lang": "en"})
        else:
            out.append({"text": name, "lang": "uk"})
    return list({row["text"]: row for row in out}.values())


def _prep(items: list[dict], esculab_prep: dict[str, dict], sex: str | None, adult: bool) -> dict:
    """The plan's checklist for the visit (:func:`testplan_prep.checklist`),
    read from each item's own text: Esculab publishes it per good only
    (``esculab_prep``), Synevo with its price list."""
    texts = [{**item, "prep": ((esculab_prep.get(item["id"]) or {}).get("prep") if item["lab"] == "esculab" else None)
              or item.get("prep") or ""} for item in items]
    return testplan_prep.checklist(texts, sex=sex, adult=adult, vendors=VENDORS)


#: A split between labs costs a second visit and a second sample: shown only
#: when it saves at least this share of the best single-lab plan, and at
#: least SPLIT_MIN_SAVING hryvnias.
SPLIT_MARGIN = 0.10
SPLIT_MIN_SAVING = 150.0
#: The city and the lab last chosen, remembered for the next visit (a year).
REMEMBER = {"city": "plan_city", "pref": "plan_lab"}
#: The kinds of sample left out (``ex``), comma-joined, remembered the same way.
SAMPLES_COOKIE = "plan_samples"
REMEMBER_DAYS = 365


def _age(born) -> int:
    """Whole years since ``born`` (ISO date); -1 when unknown."""
    try:
        birth = date.fromisoformat(str(born)[:10])
    except ValueError:
        return -1
    today = date.today()
    return today.year - birth.year - ((today.month, today.day) < (birth.month, birth.day))


def _int(raw: object) -> int:
    try:
        return int(str(raw or "0"))
    except ValueError:
        return 0


def _result_name(key: str, names: dict[str, str], items: list[dict]) -> str:
    """A result's name for the page: our name for a requirement key, the
    examination's own name for ``whole:<name>``, the test's name for
    ``genetic:<lab>:<id>`` (:func:`testplan_value.measured`)."""
    if key in names:
        return names[key]
    kind, _, rest = key.partition(":")
    if kind == "whole":
        return rest[:1].upper() + rest[1:]
    if kind == "genetic":
        found = next((item for item in items if f"{item.get('lab')}:{item['id']}" == rest), None)
        if found:
            return _label(found)["label"]
    return key


def _option_view(index: int, option: dict, cheapest: dict, names: dict[str, str], chosen: int) -> dict:
    """One plan on a lab's list of options, as the page lists it: what it
    costs over the first plan and which results that buys (``gained``, those
    the record already holds first, each marked), and any the first plan
    reports that this one does not (``lost``)."""
    base, mine = set(cheapest.get("extra_keys") or ()), set(option.get("tracked_extra") or ())
    gained = sorted((k for k in option.get("extra_keys") or () if k not in base),
                    key=lambda k: (k not in mine, testplan.alphabetical(_result_name(k, names, option["items"]))))
    lost = base - set(option.get("extra_keys") or ())

    def source(key: str) -> str:
        # A lab's own row with no concept of ours is often a sub-row
        # («кількість», «лейкоцити»): the test it belongs to says what it is.
        if key.partition(":")[0] not in VENDORS:
            return ""
        found = next((item for item in option["items"] if key in item["keys"]), None)
        return _label(found)["label"] if found else ""

    return {"index": index, "chosen": index == chosen, "cost": option["cost"], "base": option is cheapest,
            "delta": round(option["cost"] - cheapest["cost"], 2),
            "gained": [{"name": _result_name(k, names, option["items"]), "source": source(k), "tracked": k in mine}
                       for k in gained],
            "tracked_count": len(set(gained) & mine),
            "lost": sorted((_result_name(k, names, cheapest["items"]) for k in lost), key=testplan.alphabetical)}


#: Tests the order box lists at once; past this the query is too vague.
ORDER_CAP = 20


def _edited(plan: dict, lab: str, items: list[dict], need: set[str], tracked, cuts: set[str],
            puts: list[str]) -> tuple[dict, list[dict]]:
    """``plan`` as the person edited it (:func:`testplan_value.fixed`): its
    items without the ones cut, then the ones put in from ``items`` (this
    lab's shelf), and the cut items.  ``plan`` itself when nothing of this
    lab's is edited."""
    def ref(item):
        return f"{lab}:{item['id']}"

    shelf = {ref(item): item for item in items}
    kept = [item for item in plan["items"] if ref(item) not in cuts]
    have = {ref(item) for item in kept}
    added = [{**shelf[value], "added": True} for value in puts if value in shelf and value not in have]
    if len(kept) == len(plan["items"]) and not added:
        return plan, []
    return (testplan_value.fixed([*kept, *added], need, tracked),
            [item for item in plan["items"] if ref(item) in cuts])


def _order_search(text: str, items: list[dict], concepts: dict[str, str]) -> list[dict]:
    """A lab's items for the order box, best first: by their own names,
    codes and synonyms, and by our names for what they measure, every kind
    of test (single, panel, genetic)."""
    rows = [(_item_terms(item) + tuple((term, weight | 1) for term, weight in
                                       _terms([], [n for k in item["keys"][:40] for n in (concepts.get(k),) if n])),
             item) for item in items]
    hits, _fuzzy = _rank(text, rows, infix=True)
    hits.sort(key=lambda hit: (hit[0], len(hit[1]["parameters"]), hit[1]["final_price"]))
    return [item for _, item in hits]


def edit_url(params, lab: str, *, cut: str = "", put: str = "", reset: bool = False, alt: int | None = None) -> str:
    """This plan's address with one lab's order edited, back at its tile:
    ``cut`` an item (an added one simply goes), ``put`` one in (a cut one
    simply comes back), ``reset`` every edit of the lab, ``alt`` one of its
    plans (which starts the edits over).  The tile's search is dropped."""
    pairs = list(params.multi_items())
    mine = f"{lab}:"
    reset = reset or alt is not None
    keep = []
    for name, value in pairs:
        if name in {"notice", "olab", "oq", "have"} or (alt is not None and name == f"alt_{lab}"):
            continue
        if name in {"cut", "put"} and value.startswith(mine) and (reset or value in {cut, put}):
            continue
        keep.append((name, value))
    if cut and ("put", cut) not in pairs:
        keep.append(("cut", cut))
    if put and ("cut", put) not in pairs:
        keep.append(("put", put))
    if alt and alt > 1:
        keep.append((f"alt_{lab}", str(alt)))
    return "/plan-tests?" + urlencode(keep) + f"#plan-{lab}"


def _plan_view(plan: dict, required: set[str], names: dict[str, str], selected: set[str] | None = None) -> dict:
    selected = required if selected is None else selected
    locale = get_locale()
    for item in plan["items"]:
        needed = [k for k in item["keys"] if k in required]
        item["covers_names"] = [names.get(k, k) for k in needed]
        # Counted on the lab's own list: a whole-examination row («Мікроскопія
        # сечі») stands for many of our concepts but is one thing it reports.
        # Counted on the lab's own rows that are results (a note or heading
        # row has no keys), each row once however many keys it stands for.
        rows = item.get("parameter_keys")
        item["extra_count"] = (sum(1 for keys in rows if keys and not set(keys) & required) if rows is not None
                               else max(0, len(item["parameters"]) - len(needed)))
        item["materials"] = _materials(item, locale)
        item["justified_names"] = [names.get(k, k) for k in item.get("justified_by") or ()]
        item.update(_label(item))
    plan["missing_names"] = [names.get(k, k) for k in plan["missing"] if k in selected]
    plan["missing_included"] = len([k for k in plan["missing"] if k not in selected])
    plan["required_count"] = len(required)
    plan["saving"] = round(plan["list_cost"] - plan["cost"], 2)
    return plan


def register_routes(app, settings, *, templates, template_context, require_user, record_user, require_csrf,
                    audit) -> None:
    templates.env.filters["uah"] = uah
    templates.env.filters["stamp"] = stamp
    templates.env.globals["plan_query"] = plan_query
    templates.env.globals["page_url"] = page_url
    templates.env.globals["edit_url"] = edit_url
    templates.env.filters["sample_name"] = lambda group: t(f"plan.sample_{group}_short")

    def build(request: Request, user, owner, params=None) -> dict:
        from .app import _metric_catalog, _sparkline

        params = request.query_params if params is None else params
        active = [key for key in SHOPS if labsync.active(settings, key)]
        # One city for the visit, typed or picked: each lab's own list is
        # matched by name (prefixes like «м.» and apostrophes aside).  A lab
        # with no point in that city sits this plan out and the page says so.
        # ``city_<lab>`` (a lab's own city id) still overrides, for old links.
        region_lists = {key: _regions(key) for key in active}
        remembered = {name: unquote(request.cookies.get(cookie, "")) for name, cookie in REMEMBER.items()}
        city = " ".join((params.get("city") if "city" in params else remembered["city"]).split())[:80]
        regions, no_city = {}, []
        for key, module in SHOPS.items():
            if params.get(f"city_{key}"):
                regions[key] = params.get(f"city_{key}")
            elif city:
                wanted = testplan.alphabetical(city)
                regions[key] = next((row["id"] for row in region_lists.get(key, [])
                                     if testplan.alphabetical(row["name"]) == wanted), None)
                if regions[key] is None and key in active:
                    no_city.append(key)
            else:
                regions[key] = module.DEFAULT_REGION
        if not city:
            city = next((row["name"] for key in active for row in region_lists.get(key, [])
                         if row["id"] == regions.get(key)), "")
        city_names = sorted({row["name"] for rows in region_lists.values() for row in rows}, key=testplan.alphabetical)
        with connect(settings) as connection:
            cards = _metric_catalog(connection, owner["id"])
            from_labs = testplan.lab_concepts(connection, owner["id"])
            needs = testplan.needs(cards, from_labs)
            labs = {key: _lab_items(settings, connection, owner["id"], key, regions[key])
                    for key in active if regions.get(key)}
            patient = connection.execute(
                "SELECT sex_at_birth, date_of_birth FROM patients WHERE owner_user_id=? ORDER BY created_at LIMIT 1",
                (owner["id"],)
            ).fetchone()
            concepts = {row[0]: row[1] for row in connection.execute("SELECT id, canonical_name FROM concepts")}
        # A lab sells some items to one sex only; with the sex unknown, all stay.
        sex = {"male": "M", "female": "F"}.get(str(patient["sex_at_birth"] or "") if patient else "")
        # Children's packages are not offered to an adult; with the age unknown, all stay.
        adult = _age(patient["date_of_birth"] if patient else None) >= testplan.ADULT_AGE
        ready = {key: [item for item in items if not (sex and item.get("sex") and item["sex"] != sex)
                       and not (adult and testplan.for_children(item))]
                 for key, items in labs.items() if items is not None}
        # Samples the person will not give ("blood tests only"): every item
        # that needs one leaves the labs' shelves, so a result only such an
        # item measures is neither suggested, ticked nor planned (``left_out``).
        # Remembered like the city; an untouched page starts from the cookie.
        if params.get("touched") or "ex" in params:
            excluded = list(dict.fromkeys(params.getlist("ex")))
        else:
            excluded = unquote(request.cookies.get(SAMPLES_COOKIE, "")).split(",")
        excluded = [group for group in testplan.SAMPLE_GROUPS if group in excluded]
        sold_anywhere = {k for items in ready.values() for item in items for k in item["keys"]}
        if excluded:
            ready = {key: [item for item in items if not testplan.samples(item) & set(excluded)]
                     for key, items in ready.items()}
        sold = {k for items in ready.values() for item in items for k in item["keys"]}
        left_out = sold_anywhere - sold
        # Which kinds of sample the labs here take at all: the choices offered.
        sample_groups = [group for group in testplan.SAMPLE_GROUPS if group in excluded or any(
            group in testplan.samples(item) for items in labs.values() if items for item in items)]
        names = {}
        for items in ready.values():
            for item in items:
                # Keys pair with parameters only when none were merged or
                # expanded (two rows of one concept, a whole examination);
                # pairing them anyway named AMH after a panel's ESR row.
                # ``parameter_keys`` is aligned with ``parameters``; a row that
                # stands for one key names it, a whole examination names none.
                for parameter, keys in zip(item["parameters"], item.get("parameter_keys") or ()):
                    if len(keys) == 1:
                        names.setdefault(keys[0], parameter["name"])
        for items in ready.values():
            for item in items:
                if len(item["keys"]) == 1:
                    names.setdefault(item["keys"][0], item["name"])
        # Our concept's name in the reader's language beats the lab's spelling;
        # failing that, the lab's own English name on the English page.
        if get_locale() == "en":
            names.update({item["keys"][0]: item["name_en"] for items in ready.values() for item in items
                          if len(item["keys"]) == 1 and item.get("name_en") and item["keys"][0] not in concepts})
        names.update({k: concept_display_name(concepts[k]) for k in names if k in concepts})
        names.update({str(card["id"]): str(card["name"]) for card in cards})
        for need in needs:
            need["sold"] = need["key"] in sold
            need["left_out"] = need["key"] in left_out
        # What can be planned first; what no lab sells last, still listed.
        needs.sort(key=lambda need: not need["sold"])
        # Days since each lab result was last measured; with the switch on
        # (the default), anything measured in the last RECENT_DAYS is left
        # unticked, from the first list and from presets alike.
        today = date.today()
        days = {}
        for card in cards:
            try:
                days[str(card["id"])] = (today - date.fromisoformat(str(card.get("latest_date") or "")[:10])).days
            except ValueError:
                continue
        skip_recent = params.get("recent") == "1" if params.get("touched") else True

        def recent(key: str) -> bool:
            return days.get(key, RECENT_DAYS + 1) <= RECENT_DAYS

        if params.get("touched"):
            selected = list(dict.fromkeys(params.getlist("need")))
        else:
            selected = [need["key"] for need in needs if need["preselected"] and need["sold"]
                        and not (skip_recent and recent(need["key"]))]
        for value in params.getlist("add"):
            selected += [k for k in value.split("|") if k and k not in selected]
        selected = [k for k in selected if k not in left_out]
        offered = presets_for(sex)
        # Rows past the pre-selected list (optional ones ticked, searched,
        # from a preset) are listed together under "Added by you".
        listed = {need["key"] for need in needs if need["preselected"]}
        # A preset is a toggle: pressed off it adds its results (``preset``),
        # pressed on it takes them away again (``drop``), except results the
        # page suggested on its own, which stay where the person left them.
        for value in params.getlist("drop"):
            dropping = set(offered.get(value, ())) - listed
            selected = [k for k in selected if k not in dropping]
        for value in params.getlist("preset"):
            selected += [k for k in offered.get(value, ()) if k in sold and k not in selected
                         and not (skip_recent and recent(k))]
        # Each preset's results as the page counts them: sold here, and not
        # measured too recently while the switch skips those.
        chosen_now = set(selected)
        presets = []
        for value, keys in offered.items():
            wanted = [k for k in keys if k in sold and not (skip_recent and recent(k))]
            if wanted:
                presets.append({"value": value, "keys": wanted, "count": len(wanted),
                                "chosen": sum(1 for k in wanted if k in chosen_now),
                                # left out by the switch, said on the tile
                                "recent": sum(1 for k in keys if k in sold and skip_recent and recent(k))})
        card_by = {str(card["id"]): card for card in cards if not card.get("is_device")}
        extra = [{"key": k, "name": names.get(k, k), "card": card_by.get(k), "sold": k in sold,
                  "flagged": False, "due": False, "added": True} for k in selected if k not in listed]
        # A small trend beside every listed result that has two readings or more.
        for card in {id(c): c for c in [*(n["card"] for n in needs), *(r["card"] for r in extra if r["card"])]}.values():
            card.setdefault("spark", _sparkline(card, None))
        query = (params.get("q") or "").strip()[:80]
        # Special tests (``special=1``): the list is entries picked by topic
        # or by the search, and the plan covers their keys alone.
        special = params.get("special") == "1"
        spec = _special(params, sex, ready, cards, skip_recent=skip_recent, recent=recent, query=query,
                        sparkline=_sparkline, left_out=left_out) if special else None
        if spec is not None:
            selected = spec["keys"]
            names.update(spec["names"])
            for key, name in spec["fallback_names"].items():
                names.setdefault(key, name)
        hits, fuzzy = _search(query, cards, ready, names, set(selected), from_labs, concepts) \
            if query and not special else ([], False)
        # A result only a left-out sample measures is not offered to add.
        hits = [hit for hit in hits if not set(hit["keys"]) <= left_out]
        # One box filters the list and finds what is not on it yet: a hit
        # already on the list (ticked or not) shows there, the rest below it.
        on_list = listed | set(selected)
        match = spec["match"] if spec is not None else \
            [hit["keys"][0] for hit in hits if len(hit["keys"]) == 1 and hit["keys"][0] in on_list]
        results = [hit for hit in hits if not set(hit["keys"]) <= on_list]
        # Panels and special tests the person chose to include: always bought
        # at their own lab (``include=<lab>:<item id>``).
        by_id = {f"{key}:{item['id']}": item for key, items in ready.items() for item in items}
        include = list(dict.fromkeys(value for value in params.getlist("include") if value))
        included = [by_id[value] for value in include if value in by_id]
        include_rows = [_set_row(item["lab"], item, names, set(include)) for item in included]
        # A panel that needs a left-out sample is dropped with it, not "gone".
        held = {f"{key}:{item['id']}" for key, items in labs.items() if items for item in items}
        include_gone = [value for value in include if value not in by_id and value.partition(":")[0] in ready
                        and not (excluded and value in held)]
        # In special mode the one search box also finds the labs' own packages.
        set_query = query if special else (params.get("sq") or "").strip()[:80]
        shelves = _shelves(ready, _section_titles(settings))
        typed = " ".join((params.get("sg") or "").split())[:160]
        set_group = next((row["value"] for row in shelves
                          if typed in (row["value"], f"{row['vendor']}: {row['name']}", row["name"])), "") if typed else ""
        found, sets_fuzzy = _sets(set_query, set_group, ready, names, set(include), concepts) \
            if set_query or set_group else ([], False)
        # Filters narrow what the text and the shelf found; none of them
        # lists anything alone, so the page never shows the whole catalogue.
        set_filters = {"lab": params.get("slab") if params.get("slab") in ready else "",
                       "kind": params.get("skind") if params.get("skind") in ("genetic", "set") else "",
                       "max": _amount(params.get("smax")),
                       "sort": "price" if params.get("ssort") == "price" else "relevance"}
        if set_filters["lab"]:
            shelves = [row for row in shelves if row["lab"] == set_filters["lab"]]
            if set_group and not set_group.startswith(set_filters["lab"] + ":"):
                set_group = ""
        found = [row for row in found if (not set_filters["lab"] or row["lab"] == set_filters["lab"])
                 and (not set_filters["kind"] or row["kind"] == set_filters["kind"])
                 and (set_filters["max"] is None or row["final_price"] <= set_filters["max"])]
        if set_filters["sort"] == "price":
            found.sort(key=lambda row: row["final_price"])
        sets = _page(found, params.get("sp"))
        results = {"rows": results[:SEARCH_CAP], "total": len(results)}
        for row in results["rows"]:
            if row["card"]:
                row["card"].setdefault("spark", _sparkline(row["card"], None))
        required = set(selected)
        # What the included items report is part of the plan everywhere: their
        # own lab buys them, another lab plans those analytes without them.
        everything = required | {k for item in included for k in item["keys"]}
        plans, best = [], None
        # How the person wants the plan chosen: the cheapest (with better-value
        # options beside it), or the most complete one (with cheaper ones
        # beside it); at every lab, or only the one they prefer.
        pref = params.get("pref") if "pref" in params else remembered["pref"]
        prefs = {"lab": pref if pref in ready else "",
                 "mode": "complete" if params.get("mode") == "complete" else "cheapest"}
        # The person's own edits of a lab's order: ``cut=<lab>:<id>`` takes an
        # item out, ``put=<lab>:<id>`` adds one from that lab's shelf.
        cuts = set(params.getlist("cut"))
        puts = [value for value in dict.fromkeys(params.getlist("put")) if value not in cuts]
        if params.get("plan") and everything:
            shown = {prefs["lab"]: ready[prefs["lab"]]} if prefs["lab"] else ready
            for key, items in shown.items():
                forced = [item for item in included if item["lab"] == key]
                # A panel bought here covers its own results; only what the
                # panels sold elsewhere report is planned here alongside the
                # person's needs (so a panel's results never count as needs).
                need = required | {k for item in included if item["lab"] != key for k in item["keys"]}
                # "Most complete" leads with the fullest plan the lab can
                # build, whatever it costs; the cheaper steps down to the
                # cheapest are its options, for the person to choose.
                options = (testplan_value.complete_options if prefs["mode"] == "complete"
                           else testplan_value.alternatives)(items, need, forced=forced, tracked=from_labs)
                chosen = min(max(_int(params.get(f"alt_{key}")) - 1, 0), len(options) - 1)
                shown_plan, cut_items = _edited(options[chosen], key, items, need, from_labs, cuts, puts)
                plan = _plan_view(shown_plan, need, names, required)
                plan.update(lab=key, name=VENDORS[key], region=regions[key],
                            edited=shown_plan is not options[chosen], cut_items=[
                                {**_label(item), "value": f"{key}:{item['id']}", "final_price": item["final_price"]}
                                for item in cut_items],
                            # Ranked and compared as planned, so an edit never
                            # moves the tile under the reader.
                            rank_missing=len(options[chosen]["missing"]), base_cost=options[chosen]["cost"],
                            separately=testplan.separately(items, required) if not forced else None,
                            fetched_at=testplan.fetched_at(settings, key, regions[key]),
                            not_here=[_label(item)["label"] for item in included if item["lab"] != key],
                            option_index=chosen, cheapest_cost=options[0]["cost"] if prefs["mode"] == "cheapest"
                            else min(o["cost"] for o in options), first_value=options[0].get("value", 0),
                            # Every option is told against the cheapest: first in
                            # "cheapest" mode, last in "most complete".
                            options=[_option_view(index, option, options[0 if prefs["mode"] == "cheapest" else -1],
                                                  names, chosen) for index, option in enumerate(options)])
                plans.append(plan)
            single = [plan["base_cost"] for plan in plans if not plan["rank_missing"]]
            if len(ready) > 1 and not prefs["lab"] and prefs["mode"] == "cheapest" and single:
                # A split between labs means two visits and two blood draws: it is
                # offered only when it beats the best single lab by SPLIT_MARGIN.
                ceiling = min(single)
                # Every included panel is bought at its own lab, so the needs are the person's own.
                both = testplan_value.alternatives([i for items in ready.values() for i in items], required,
                                                   forced=included, tracked=from_labs, limit=0)[0]
                labs_used = sorted({item["lab"] for item in both["items"]})
                saving = round(ceiling - both["cost"], 2)
                if len(labs_used) > 1 and not both["missing"] \
                        and saving >= max(SPLIT_MIN_SAVING, ceiling * SPLIT_MARGIN):
                    both = _plan_view(both, required, names, required)
                    both.update(lab="mixed", name=" + ".join(VENDORS[k] for k in labs_used), labs_used=labs_used,
                                not_here=[], split_saving=saving, options=[])
                    plans.append(both)
            # Ranked by each lab's first plan, not the option shown: switching
            # a lab to a fuller option never reorders the tiles under the reader.
            if prefs["mode"] == "complete":
                plans.sort(key=lambda plan: (plan.get("rank_missing", len(plan["missing"])),
                                             -plan.get("first_value", plan.get("value", 0)),
                                             plan.get("cheapest_cost", plan["cost"])))
            else:
                plans.sort(key=lambda plan: (plan.get("rank_missing", len(plan["missing"])),
                                             plan.get("cheapest_cost", plan["cost"])))
            best = plans[0] if plans else None
            ids = [item["id"] for plan in plans for item in plan["items"] if item["lab"] == "esculab"]
            try:
                esculab_prep = esculab_shop.details(
                    settings, ids, labsync.provider_settings(settings, "esculab").get("url") or esculab_shop.SITE)
            except Exception:  # noqa: BLE001 -- preparation text is a courtesy; the plan stands without it
                logger.warning("esculab preparation rules unavailable", exc_info=True)
                esculab_prep = {}
            for plan in plans:
                plan["prep"] = _prep(plan["items"], esculab_prep, sex, adult)
        # The box in a lab's tile: one field that filters the order and finds
        # that lab's tests to add (``olab``, ``oq``; ``have`` names the order's
        # items when no plan is built, as for /plan-tests/order-search).
        order = None
        order_lab = params.get("olab") if params.get("olab") in ready else ""
        order_query = " ".join((params.get("oq") or "").split())[:80] if order_lab else ""
        if order_query:
            in_order = next(({item["id"] for item in plan["items"]} for plan in plans if plan["lab"] == order_lab),
                            set(params.getlist("have")))
            ranked = _order_search(order_query, ready[order_lab], concepts)
            found = [item for item in ranked if item["id"] not in in_order]
            order = {"lab": order_lab, "query": order_query,
                     "match": [item["id"] for item in ranked if item["id"] in in_order],
                     "total": len(found), "rows": [{**_set_row(order_lab, item, names, set()),
                                                    "materials": _materials(item, get_locale())}
                                                   for item in found[:ORDER_CAP]]}
        return {"needs": needs, "selected": selected, "extra": extra, "query": query, "results": results,
                "order": order, "order_lab": order_lab, "order_query": order_query,
                "match": match, "presets": presets, "special": special, "spec": spec,
                "presets_open": bool(params.getlist("preset") or params.getlist("drop")),
                "days": days, "skip_recent": skip_recent, "recent_days": RECENT_DAYS,
                "recent_listed": sum(1 for key in {*(n["key"] for n in needs), *(r["key"] for r in extra)} if recent(key)),
                "fuzzy": fuzzy, "include": include, "include_rows": include_rows, "include_gone": include_gone,
                "set_query": set_query, "set_group": set_group, "sets": sets, "sets_fuzzy": sets_fuzzy,
                "set_filters": set_filters, "prefs": prefs,
                "shelves": shelves, "shelf_name": next((row["name"] for row in shelves if row["value"] == set_group), ""),
                "plans": plans, "best": best, "regions": regions, "labs_on": active,
                "crawling": [key for key in active if key in labs and labs[key] is None],
                "region_lists": region_lists, "lab_names": VENDORS,
                "city": city, "city_names": city_names, "no_city": no_city,
                "excluded": excluded, "sample_groups": sample_groups,
                # What the left-out samples took off this list: the record's
                # suggestions and what the person had ticked or added.
                "left_out_names": sorted({names.get(k, k) for k in left_out & {
                    *(n["key"] for n in needs if n["preselected"]), *params.getlist("need"),
                    *(k2 for value in params.getlist("add") for k2 in value.split("|"))}}, key=testplan.alphabetical)}

    def _regions(key: str) -> list[dict]:
        try:
            return sorted(SHOPS[key].regions(settings), key=lambda region: testplan.alphabetical(region["name"]))
        except LabSyncError:
            return []

    @app.get("/plan-tests", response_class=HTMLResponse)
    def plan_page(request: Request):
        user = require_user(request)
        owner = record_user(request, user)
        view = build(request, user, owner)
        # A doctor (a guest credential) plans and saves the selection for the
        # patient; ordering is the patient's, or anyone they share the record
        # with, through a lab account that holds them (_order_account).
        doctor = user.get("token_kind") == "guest"
        can_order = not doctor
        order_forms = {}
        if can_order and view["best"] is not None:
            for plan in view["plans"]:
                if plan["lab"] == "esculab":
                    order_forms["esculab"] = _esculab_form(user, owner, plan)
                elif plan["lab"] == "synevo":
                    account_id, _person = _order_account(settings, user["id"], owner["id"], "synevo")
                    row = labsync.account(settings, account_id, "synevo")
                    order_forms["synevo"] = {"connected": bool(row and row["secret"])}
        # What a doctor saved for this person: shown to the person alone.
        suggestions = []
        if not doctor and owner["id"] == user["id"]:
            with connect(settings) as connection:
                rows = connection.execute(
                    """SELECT id, query, test_count, author, created_at FROM plan_suggestions
                       WHERE owner_user_id=? AND dismissed_at IS NULL ORDER BY created_at DESC LIMIT 3""",
                    (owner["id"],)).fetchall()
            suggestions = [{"id": row["id"], "count": row["test_count"], "author": row["author"],
                            "special": "special=1" in row["query"].split("&"), "date": row["created_at"][:10],
                            "url": f"/plan-tests?{row['query']}&plan=1#plan-result"} for row in rows]
        response = templates.TemplateResponse(request, "plan_tests.html", template_context(
            request, active="plan_tests", can_order=can_order, order_forms=order_forms, doctor=doctor,
            suggestions=suggestions, suggestion_source=suggestion_query(str(request.url.query)),
            notice=request.query_params.get("notice", ""), today=date.today().isoformat(), **view))
        # The city, the lab and the samples chosen here are where the next visit starts.
        remember = {cookie: request.query_params[name][:80] for name, cookie in REMEMBER.items()
                    if name in request.query_params}
        if request.query_params.get("touched") or "ex" in request.query_params:
            remember[SAMPLES_COOKIE] = ",".join(view["excluded"])
        for cookie, value in remember.items():
            response.set_cookie(cookie, quote(value), max_age=REMEMBER_DAYS * 86400,
                                httponly=True, samesite="lax", secure=request.url.scheme == "https")
        return response

    @app.get("/plan-tests/live")
    def plan_live(request: Request):
        """The two search blocks re-rendered for the form as it stands, so
        typing a name or narrowing the panels never reloads the page.  Never
        builds a plan: that waits for the button."""
        user = require_user(request)
        owner = record_user(request, user)
        params = QueryParams([(k, v) for k, v in request.query_params.multi_items() if k != "plan"])
        view = build(request, user, owner, params)
        context = template_context(request, **view)
        parts = {name: templates.get_template(f"_plan_{name}.html").render(context) for name in ("found", "sets")}
        return {**parts, "match": view["match"] if view["query"] else None}

    @app.get("/plan-tests/order-search")
    def plan_order_search(request: Request):
        """A tile's box as the person types: that lab's tests to add, and
        which of the order's items (``have``) it matches.  Never builds a
        plan; the page's own query rides along for the "Add" links."""
        user = require_user(request)
        owner = record_user(request, user)
        params = QueryParams([(k, v) for k, v in request.query_params.multi_items() if k != "plan"])
        view = build(request, user, owner, params)
        page = QueryParams([(k, v) for k, v in request.query_params.multi_items() if k not in {"olab", "oq", "have"}])
        context = template_context(request, **view, lab=view["order_lab"], page_params=page)
        html = templates.get_template("_plan_order_add.html").render(context)
        return {"html": html, "match": view["order"]["match"] if view["order"] else None}

    def _esculab_form(user, owner, plan) -> dict:
        account_id, person = _order_account(settings, user["id"], owner["id"], "esculab")
        row = labsync.account(settings, account_id, "esculab")
        if not (row and row["secret"]):
            return {"connected": False}
        try:
            points = esculab_shop.points(settings, plan["region"])
        except LabSyncError:
            points = []
        last = None
        if person:
            client = labsync._client(settings, "esculab", row["secret"], row["phone"], row["refresh_secret"])
            last = esculab_shop.last_point(client, person)
        return {"connected": True, "person": person, "points": points,
                "point": last if any(p["id"] == last for p in points) else (points[0]["id"] if points else "")}

    def back(request_query: str, notice: str) -> RedirectResponse:
        return RedirectResponse(f"/plan-tests?{request_query}&notice={notice}#plan-result", status_code=303)

    @app.post("/plan-tests/suggest")
    async def plan_suggest(request: Request):
        """A doctor's selection, saved for the patient (a guest credential's
        one write).  ``query`` is the planner's query string as it stands."""
        user = await run_in_threadpool(require_user, request)
        form = await request.form()
        await run_in_threadpool(require_csrf, user, str(form.get("csrf_token") or ""))
        if user.get("token_kind") != "guest":
            raise HTTPException(403)
        query = suggestion_query(str(form.get("query") or ""))
        params = QueryParams(query)
        view = await run_in_threadpool(build, request, user, user, params)
        count = (len(view["spec"]["picked"]) if view["special"] else len(view["selected"])) + len(view["include_rows"])
        if not count:
            return RedirectResponse(f"/plan-tests?{query}&notice=suggestion_empty#plan-needs", status_code=303)
        suggestion_id = str(uuid4())
        with transaction(settings) as connection:
            connection.execute(
                """INSERT INTO plan_suggestions(id, owner_user_id, query, test_count, token_id, author, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (suggestion_id, user["id"], query, count, user.get("token_id"), user.get("token_label") or "",
                 utc_now()))
        audit(user["id"], user["id"], "plan_suggestion_saved", "plan_suggestion", suggestion_id, {"tests": count})
        return RedirectResponse(f"/plan-tests?{query}&notice=suggestion_saved#plan-needs", status_code=303)

    @app.post("/plan-tests/suggestion/{suggestion_id}/dismiss")
    async def plan_suggestion_dismiss(request: Request, suggestion_id: str):
        """The person puts a doctor's selection away (it stays in the audit trail)."""
        user = await run_in_threadpool(require_user, request)
        form = await request.form()
        await run_in_threadpool(require_csrf, user, str(form.get("csrf_token") or ""))
        if user.get("token_kind") == "guest":
            raise HTTPException(403)
        with transaction(settings) as connection:
            connection.execute("UPDATE plan_suggestions SET dismissed_at=? WHERE id=? AND owner_user_id=?",
                               (utc_now(), suggestion_id, user["id"]))
        return RedirectResponse("/plan-tests", status_code=303)

    @app.post("/plan-tests/order/esculab", response_class=HTMLResponse)
    async def esculab_order(request: Request):
        user = await run_in_threadpool(require_user, request)
        form = await request.form()
        await run_in_threadpool(require_csrf, user, str(form.get("csrf_token") or ""))
        if user.get("token_kind") == "guest" or not labsync.active(settings, "esculab"):
            raise HTTPException(403)
        region, plan_query = str(form.get("region") or ""), str(form.get("plan_query") or "")
        ids = [str(value) for value in form.getlist("item")]
        expected = float(str(form.get("expected") or "0").replace(",", "."))
        # For the record on screen: one's own, or one shared with this person.
        owner = await run_in_threadpool(record_user, request, user)
        account_id, person = _order_account(settings, user["id"], owner["id"], "esculab")
        row = labsync.account(settings, account_id, "esculab")
        if not (row and row["secret"] and person):
            return back(plan_query, "esculab_not_connected")
        catalogue = {item["id"]: item for item in esculab_shop.catalog(settings, region)}
        chosen = [catalogue[i] for i in ids if i in catalogue]
        if not chosen or len(chosen) != len(ids):
            return back(plan_query, "items_gone")
        fresh = await run_in_threadpool(esculab_shop.refresh_prices, region, chosen)
        total = round(sum(item["final_price"] for item in fresh)
                      + sum(fee["price"] for fee in esculab_shop.fees(fresh)), 2)
        if total != round(expected, 2):
            # A price moved since the list was read: drop the copy, so the plan
            # is recomputed from today's list before anything is ordered.
            with transaction(settings) as connection:
                connection.execute("DELETE FROM lab_catalog_cache WHERE provider='esculab' AND region=? AND cache_key='catalog'",
                                   (region,))
            return back(plan_query, "prices_changed")
        client = labsync._client(settings, "esculab", row["secret"], row["phone"], row["refresh_secret"])
        try:
            visit = date.fromisoformat(str(form.get("date") or ""))
        except ValueError:
            visit = date.today()
        try:
            created = await run_in_threadpool(
                esculab_shop.create_order, client, person, str(form.get("point") or ""), fresh,
                online=form.get("payment") == "online", day=max(visit, date.today()))
        except LabSyncError as exc:
            logger.warning("esculab order refused: %s", exc.key)
            return back(plan_query, "order_failed")
        audit(owner["id"], user["id"], "lab_order_created", "lab_order", f"esculab:{created['number']}",
              {"items": len(fresh), "total": total, "account": account_id})
        return templates.TemplateResponse(request, "plan_tests_done.html", template_context(
            request, active="plan_tests", lab="Esculab", number=created["number"], payment_url=created["payment_url"],
            items=fresh, fees=esculab_shop.fees(fresh), total=total, plan_query=plan_query, site=esculab_shop.SITE))

    @app.post("/plan-tests/cart/synevo", response_class=HTMLResponse)
    async def synevo_cart(request: Request):
        user = await run_in_threadpool(require_user, request)
        form = await request.form()
        await run_in_threadpool(require_csrf, user, str(form.get("csrf_token") or ""))
        if synevo_shop is None or user.get("token_kind") == "guest" or not labsync.active(settings, "synevo"):
            raise HTTPException(403)
        region, plan_query = str(form.get("region") or ""), str(form.get("plan_query") or "")
        owner = await run_in_threadpool(record_user, request, user)
        account_id, _person = _order_account(settings, user["id"], owner["id"], "synevo")
        catalogue = {item["id"]: item for item in synevo_shop.catalog(settings, region) or []}
        chosen = [catalogue[i] for i in form.getlist("item") if i in catalogue]
        if not chosen:
            return back(plan_query, "items_gone")
        try:
            result = await run_in_threadpool(lambda: synevo_shop.add_to_cart(settings, account_id, chosen, region=region))
        except LabSyncError as exc:
            logger.warning("synevo cart refused: %s", exc.key)
            return back(plan_query, "cart_failed")
        audit(owner["id"], user["id"], "lab_cart_filled", "lab_cart", "synevo",
              {"added": len(result.get("added") or []), "failed": len(result.get("failed") or [])})
        added_ids = {str(row.get("id")) for row in result.get("added") or []}
        added = [item for item in chosen if item["id"] in added_ids]
        fees = list({fee["id"]: fee for item in added for fee in item["fees"]}.values())
        return templates.TemplateResponse(request, "plan_tests_done.html", template_context(
            request, active="plan_tests", lab="Synevo", number=None, payment_url=None, cart_url=result.get("cart_url"),
            items=added, fees=fees, failed=result.get("failed") or [], cart_reasons=CART_REASONS,
            total=sum(item["final_price"] for item in added) + sum(fee["price"] for fee in fees),
            plan_query=plan_query, site=synevo_shop.SITE))


def plan_query(params) -> str:
    """The query string that reopens the same plan."""
    keep = [(name, value) for name, value in params.multi_items() if name not in {"notice", "add", "preset", "drop", "q", "sq", "sg", "sp", "slab", "skind", "smax", "ssort", "olab", "oq", "have"}]
    return urlencode(keep)


def stamp(value: str | None) -> str:
    return datetime.fromisoformat(value).date().isoformat() if value else ""
