"""Synevo's public catalogue and the signed-in cart, for the test planner
(:mod:`anamna.testplan`).  Observed 2026-11-08.

Public, no sign-in (prices are per city: ``city`` is a Synevo location id):

* ``GET /api/locations?lang=uk`` -> ``[{id, name, slug, ...}]``, the cities
* ``GET /_next/data/<buildId>/uk/rubricator/top-tests.json`` -> the rubric
  tree (``pageProps.rubrics[].subrubrics[]``); ``buildId`` is in the home page
* ``GET /api/rubricator/services?rubric=&category=&lang=uk&page=&city=`` ->
  ``{services: [{id, name, code, price, active, ...}], options: {totalPages}}``,
  ten per page whatever ``limit`` says.  A service sits in several rubrics.
* ``GET /api/rubricator/service-details?serviceId=&lang=uk&city=`` -> ``data``
  with ``Components[].Name`` (what a panel reports), ``BioMaterialName``,
  ``BasePrice``, ``Active``/``Hidden``.  No sex restriction is published.
* ``POST /api/discount/get-list {lang, page}`` and
  ``/_next/data/<buildId>/uk/info/discounts/<url>.json`` -> the special
  offers, with ``servicesDetails.services[{code, basePrice, price,
  discountType, discountValue}]`` and the cities they hold in.

Signed in (the ``next-auth.session-token`` the results sync already keeps):
``GET /api/cart/get-cart`` -> the cart (``_id``, ``Items``, ``Intakes``,
``ServicesSum``, ``IntakesSum``, ``DiscountsSum``, ``TotalSum``, ``Location``);
``POST /api/cart/add-item {code, cartId, confirm, src, info, promoId,
isPackage}`` -> the cart again, or ``{error: 1001|1002|1003|2001}`` /
``{res: "error", status: 4010..4014}`` when refused;
``POST /api/cart/set-location {locationId, cartId}``.

**Fees.**  The cart prices sample collection as ``Intakes``: services with
``IsIntake`` that the server adds once per order.  A real cart holding a
venous-blood panel carried exactly one, «Взяття крові одноразовими системами»
(code 6001, 90 UAH), so every item whose biomaterial is venous blood shares
that one fee.  Synevo has other intakes (6003 urogenital swabs, 6004 transport
container) but which items trigger them is decided server-side and has not
been observed, so no fee is attached for them rather than a guessed one.

**Discounts.**  List prices carry no running markdown (listing ``price`` ==
details ``BasePrice``).  The monthly offer («Пропозиція місяця») is a percentage
off named services for any signed-in person who adds them from the offer page,
which sends the offer's id as ``promoId``; that is applied to ``final_price``
and carried in ``order["promo"]``.  Offers for a group (veterans, card holders)
need a status the person must prove, and are left out.
"""

from __future__ import annotations

import html
import json
import logging
import re
import threading
import time
import urllib.parse
from datetime import UTC, datetime, timedelta

from .. import testplan
from ..config import Settings
from ..db import connect, transaction, utc_now
from . import common, synevo
from .common import LabSyncError, name_key

logger = logging.getLogger("anamna.labsync")

PROVIDER = "synevo"
BASE = SITE = synevo.DEFAULT_URL
DEFAULT_REGION = "611b76e53254b616974143c3"  # Lviv (Kyiv is 611b76e43254b616974142d0)
#: A stored catalogue older than this is crawled again in the background.
TTL = timedelta(days=7)
REGIONS_TTL = timedelta(days=7)
OFFERS_TTL = timedelta(days=1)
#: A partial crawl older than this restarts: its prices are no longer worth resuming.
PARTIAL_TTL = timedelta(days=7)
#: A partial crawl saved more recently than this is somebody's live crawl.
LIVE_CRAWL = timedelta(minutes=10)
PARTIAL, PROGRESS = "catalog.partial", "catalog.progress"

DELAY = 1.0          # seconds between any two requests to Synevo
RETRIES = 5          # per request, on 429 / 5xx / unreachable
BACKOFF = 5.0        # seconds, doubled each retry
CHECKPOINT_EVERY = 20
MAX_PAGES = 200      # per category; the largest (blood) had 61

#: The one intake the cart was seen to add (see the module docstring).
BLOOD_DRAW = {"service_id": "5f7b080cf5456f51721692b8", "code": "6001"}
MONTHLY_OFFER = "пропозиція місяця"
_ERROR_REPLY = "labsync.error_reply"
_REFUSED = "synevo_cart.refused"

_ID_RE = re.compile(r"[0-9a-f]{24}")
_CODE_RE = re.compile(r"\d{1,10}")
_BUILD_RE = re.compile(rb'"buildId":"([A-Za-z0-9_-]{1,64})"')
_SLUG_RE = re.compile(r"[A-Za-z0-9_-]{1,80}")

# Test seams: the tests replace these so pacing never waits.
_sleep = time.sleep
_clock = time.monotonic
_pace_lock = threading.Lock()
_last_request = [float("-inf")]


def _pace() -> None:
    """At most one request per :data:`DELAY`, across every thread."""
    with _pace_lock:
        wait = _last_request[0] + DELAY - _clock()
        if wait > 0:
            _sleep(wait)
        _last_request[0] = _clock()


def _get_raw(path: str) -> bytes:
    status, _, body = common._http("GET", BASE + path, headers={"Accept": "text/html"})
    if not 200 <= status < 300:
        raise LabSyncError(_ERROR_REPLY, status)
    return body


def _transient(exc: LabSyncError) -> bool:
    return exc.key == "labsync.error_unreachable" or exc.status == 429 or (exc.status or 0) >= 500


def _get(path: str, *, payload: object | None = None, state: dict | None = None, raw: bool = False):
    """One paced public request, retried with backoff on 429, 5xx and network failure."""
    for attempt in range(RETRIES + 1):
        _pace()
        if state is not None:
            state["requests"] = state.get("requests", 0) + 1
        try:
            if raw:
                return _get_raw(path)
            reply, _ = common.call("POST" if payload is not None else "GET", BASE + path,
                                   headers={}, payload=payload)
            return reply
        except LabSyncError as exc:
            if not _transient(exc) or attempt == RETRIES:
                raise
            _sleep(BACKOFF * 2 ** attempt)
    raise AssertionError("unreachable")


def _city(region: str) -> str:
    if not _ID_RE.fullmatch(str(region or "")):
        raise ValueError("not a Synevo city id")
    return region


def _query(**params) -> str:
    return urllib.parse.urlencode(params)


# --- stored rows ------------------------------------------------------------------


def _row(settings: Settings, region: str, key: str):
    with connect(settings) as connection:
        return connection.execute(
            "SELECT fetched_at, payload_json FROM lab_catalog_cache WHERE provider=? AND region=? AND cache_key=?",
            (PROVIDER, region, key),
        ).fetchone()


def _store(settings: Settings, region: str, key: str, payload: object) -> None:
    with transaction(settings) as connection:
        connection.execute(
            """INSERT INTO lab_catalog_cache(provider, region, cache_key, fetched_at, payload_json)
               VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(provider, region, cache_key) DO UPDATE SET
                   fetched_at=excluded.fetched_at, payload_json=excluded.payload_json""",
            (PROVIDER, region, key, utc_now(), json.dumps(payload, ensure_ascii=False)),
        )


def _age(row) -> timedelta:
    return datetime.now(UTC) - datetime.fromisoformat(row["fetched_at"])


#: Characters of description kept per service, for search.
DESCRIPTION_LIMIT = 4000


def descriptions(settings: Settings, items: list[dict], *, fetch: bool = True) -> dict[str, dict]:
    """``{code: {"text": ..., "genes": []}}``: what each service's page
    says it is and for whom (``Descr``, ``Details``, ``ForWhom``).  Synevo
    publishes no gene lists (CarrierSeq names its diseases, not its 420
    genes), so this feeds search.  Cached a
    week per service; ``fetch`` False reads the cache only.  Requests go at
    Synevo's pace (:data:`DELAY`), one at a time."""
    wanted = {str(item["code"]): item["order"]["service_id"] for item in items
              if item.get("order", {}).get("service_id")}
    if not wanted:
        return {}
    since = (datetime.now(UTC) - TTL).replace(microsecond=0).isoformat()
    with connect(settings) as connection:
        rows = connection.execute(
            f"""SELECT cache_key, payload_json FROM lab_catalog_cache WHERE provider=? AND region='' AND fetched_at>?
                AND cache_key IN ({','.join('?' * len(wanted))})""",
            (PROVIDER, since, *(f"detail:{code}" for code in wanted))).fetchall()
    out = {row["cache_key"].removeprefix("detail:"): json.loads(row["payload_json"]) for row in rows}
    for code, service_id in wanted.items():
        if code in out or not fetch:
            continue
        try:
            reply = _get("/api/rubricator/service-details?" + _query(serviceId=service_id, lang="uk",
                                                                     city=DEFAULT_REGION))
        except LabSyncError:
            continue
        data = reply.get("data") if isinstance(reply, dict) and reply.get("res") == "ok" else None
        if not isinstance(data, dict):
            continue
        text = " ".join(part for part in (_plain(data.get(key)) for key in ("Descr", "Details", "ForWhom")) if part)
        # No gene list: a description names other genes in passing (the F2
        # test's mentions F5 and MTHFR), so none is taken from it.
        out[code] = {"text": text[:DESCRIPTION_LIMIT], "genes": []}
        _store(settings, "", f"detail:{code}", out[code])
    return out


# --- public API -------------------------------------------------------------------


def regions(settings: Settings) -> list[dict]:
    """Synevo's cities, ``[{"id", "name"}]``, read once a week."""
    def fetch():
        reply = _get("/api/locations?" + _query(lang="uk"))
        if not isinstance(reply, list):
            raise LabSyncError(_ERROR_REPLY)
        return [{"id": str(city["id"]), "name": " ".join(str(city.get("name") or "").split())}
                for city in reply if isinstance(city, dict) and _ID_RE.fullmatch(str(city.get("id") or ""))]
    return testplan.cached(settings, PROVIDER, "all", "regions", REGIONS_TTL, fetch)


def _rubric_sections(rubric: dict) -> dict[str, str]:
    names = {}
    title = " ".join(str(rubric.get("name") or "").split())
    for sub in rubric.get("subrubrics") or []:
        if isinstance(sub, dict) and sub.get("code"):
            own = " ".join(str(sub.get("name") or "").split())
            names[f"{rubric.get('code')}/{sub['code']}"] = own if own == title else f"{title} · {own}"
    return names


def _section_names(rubrics: list) -> dict[str, str]:
    names = {}
    for rubric in rubrics:
        if isinstance(rubric, dict):
            names.update(_rubric_sections(rubric))
    return names


def sections(settings: Settings) -> dict[str, str]:
    """The site's names for its shelves, ``"rubric/category" -> "Чекап · Жіночий"``
    (an item's ``groups`` are the codes), read once a week: two requests."""
    def fetch():
        reply = _get(f"/_next/data/{_build_id()}/uk/rubricator/top-tests.json")
        rubrics = ((reply or {}).get("pageProps") or {}).get("rubrics") if isinstance(reply, dict) else None
        if not isinstance(rubrics, list):
            raise LabSyncError(_ERROR_REPLY)
        return _section_names(rubrics)
    return testplan.cached(settings, PROVIDER, "all", "sections", REGIONS_TTL, fetch)


def catalog(settings: Settings, region: str) -> list[dict] | None:
    """The stored catalogue for a city in testplan's item shape; None until
    crawled (and for anything that is not a city id)."""
    if not _ID_RE.fullmatch(str(region or "")):
        return None
    row = _row(settings, region, "catalog")
    return json.loads(row["payload_json"]) if row else None


def catalog_status(settings: Settings, region: str) -> dict:
    """``{state: missing|crawling|ready, fetched_at, progress}`` for the page.
    ``crawling`` wins over ``ready``: an old catalogue is being replaced."""
    if not _ID_RE.fullmatch(str(region or "")):
        return {"state": "missing", "fetched_at": None, "progress": None}
    fetched = testplan.fetched_at(settings, PROVIDER, region)
    progress = _row(settings, region, PROGRESS)
    if _crawling(settings, region):
        state = "crawling"
    elif fetched:
        state = "ready"
    else:
        state = "missing"
    return {"state": state, "fetched_at": fetched,
            "progress": json.loads(progress["payload_json"]) if progress else None}


_threads: dict[str, threading.Thread] = {}
_threads_lock = threading.Lock()
_region_locks: dict[str, threading.Lock] = {}


def _crawling(settings: Settings, region: str) -> bool:
    thread = _threads.get(region)
    if thread and thread.is_alive():
        return True
    # A crawl in another process (the CLI) checkpoints at least every
    # CHECKPOINT_EVERY seconds; a partial row that recent is live.
    partial = _row(settings, region, PROGRESS)
    return bool(partial) and json.loads(partial["payload_json"]).get("stage") != "done" and _age(partial) < LIVE_CRAWL


def ensure_fresh(settings: Settings, region: str) -> None:
    """Start a background crawl when the catalogue is missing or older than
    :data:`TTL`; returns at once.  Never crawls inside the caller's request.
    Only a city Synevo lists is crawled (:func:`regions`, read weekly)."""
    if not _ID_RE.fullmatch(str(region or "")):
        return
    fetched = testplan.fetched_at(settings, PROVIDER, region)
    if fetched and datetime.now(UTC) - datetime.fromisoformat(fetched) < TTL:
        return
    if region not in {city["id"] for city in regions(settings)}:
        return
    with _threads_lock:
        if _crawling(settings, region):
            return
        thread = threading.Thread(target=_background, args=(settings, region),
                                  name=f"synevo-catalog-{region}", daemon=True)
        _threads[region] = thread
        thread.start()


def _background(settings: Settings, region: str) -> None:
    try:
        refresh_catalog(settings, region)
    except Exception as exc:  # noqa: BLE001 -- a background thread has nobody to raise to
        logger.warning("synevo catalogue crawl stopped (%s): %s", region, getattr(exc, "key", type(exc).__name__))


def refresh_catalog(settings: Settings, region: str) -> list[dict]:
    """Crawl the whole catalogue for one city and store it; blocking, paced,
    and resumable: progress is saved under ``catalog.partial``, and a restart
    continues from there.  Returns the stored items."""
    region = _city(region)
    with _threads_lock:
        lock = _region_locks.setdefault(region, threading.Lock())
    with lock:
        return _crawl(settings, region)


def _take_service(state: dict, service: object, rubric: str, category: str) -> None:
    if isinstance(service, dict) and _ID_RE.fullmatch(str(service.get("id") or "")) \
            and _CODE_RE.fullmatch(str(service.get("code") or "")):
        entry = state["services"].setdefault(service["id"], {
            "code": str(service["code"]), "name": " ".join(str(service.get("name") or "").split()),
            "price": service.get("price"), "active": bool(service.get("active")),
        })
        # Every shelf the site lists it on («genetic-tests», «check-up/…»):
        # what testplan.item_kind tells sets from single tests by.
        groups = entry.setdefault("groups", [])
        if f"{rubric}/{category}" not in groups:
            groups.append(f"{rubric}/{category}")


def _queue_pages(state: dict, rubric: str, category: str, reply: dict) -> None:
    pages = int((reply.get("options") or {}).get("totalPages") or 1)
    state["pages"] += [[rubric, category, n] for n in range(2, min(pages, MAX_PAGES) + 1)]


def _walk_listing(region: str, state: dict, checkpoint) -> None:
    while state["pages"]:
        rubric, category, page = state["pages"][0]
        reply = _get("/api/rubricator/services?" + _query(rubric=rubric, category=category, lang="uk",
                                                           page=page, city=region), state=state)
        if not isinstance(reply, dict) or reply.get("res") != "ok":
            raise LabSyncError(_ERROR_REPLY)
        for service in reply.get("services") or []:
            _take_service(state, service, rubric, category)
        if page == 1:
            _queue_pages(state, rubric, category, reply)
        state.setdefault("walked", []).append(state["pages"].pop(0))
        state["pages_done"] += 1
        checkpoint("listing", state["pages_done"], state["pages_done"] + len(state["pages"]))


def _walk_details(region: str, state: dict, checkpoint) -> None:
    todo = [sid for sid, service in state["services"].items()
            if service["active"] and sid not in state["details"]]
    total = len(state["details"]) + len(todo)
    for sid in todo:
        state["details"][sid] = _details(sid, region, state)
        checkpoint("details", len(state["details"]), total)


def _read_english_names(reply: object, services: dict, names: dict) -> None:
    for service in (reply.get("services") or []) if isinstance(reply, dict) else []:
        if isinstance(service, dict) and service.get("id") in services and service.get("name"):
            names[service["id"]] = " ".join(str(service["name"]).split())


def _walk_english(region: str, state: dict, checkpoint) -> None:
    # The site serves its own English names (lang=en): the same listing
    # pages again, ~400 requests, rather than a second details call per
    # service.  Names only; preparation text stays the lab's Ukrainian.
    english = state.setdefault("english", {"todo": None, "names": {}})
    if english["todo"] is None:
        english["todo"] = [list(page) for page in state.get("walked") or []]
    while english["todo"]:
        rubric, category, page = english["todo"][0]
        reply = _get("/api/rubricator/services?" + _query(rubric=rubric, category=category, lang="en",
                                                           page=page, city=region), state=state)
        _read_english_names(reply, state["services"], english["names"])
        english["todo"].pop(0)
        checkpoint("english", len(state.get("walked") or []) - len(english["todo"]), len(state.get("walked") or []))


def _read_intake(region: str, state: dict) -> None:
    if "intake" not in state:
        intake = _details(BLOOD_DRAW["service_id"], region, state, keep_inactive=True)
        state["intake"] = ({"id": f"{PROVIDER}:intake:{BLOOD_DRAW['code']}", "name": intake["name"],
                            "price": float(intake["price"])} if intake.get("price") is not None else None)


def _done_progress(state: dict, items: list[dict], started: int) -> dict:
    return {
        "stage": "done", "done": len(items), "total": len(items), "requests": state["requests"],
        "requests_this_run": state["requests"] - started, "started_at": state["started_at"], "finished_at": utc_now(),
        "packages": sum(1 for item in items if len(item["parameters"]) > 1),
        "with_fees": sum(1 for item in items if item["fees"]),
        "discounted": sum(1 for item in items if item["final_price"] < item["price"]),
    }


def _crawl(settings: Settings, region: str) -> list[dict]:
    row = _row(settings, region, PARTIAL)
    state = json.loads(row["payload_json"]) if row and _age(row) < PARTIAL_TTL else None
    if state is None:
        state = {"started_at": utc_now(), "requests": 0, "pages": None, "pages_done": 0,
                 "services": {}, "details": {}, "build": None}
    since_save = [0]
    started = state["requests"]

    def checkpoint(stage: str, done: int, total: int, force: bool = False) -> None:
        since_save[0] += 1
        if force or since_save[0] >= CHECKPOINT_EVERY:
            since_save[0] = 0
            _store(settings, region, PARTIAL, state)
            _store(settings, region, PROGRESS, {"stage": stage, "done": done, "total": total,
                                                "requests": state["requests"], "started_at": state["started_at"]})

    try:
        if state["pages"] is None:
            state["build"] = _build_id(state)
            state["pages"] = [[rubric, category, 1] for rubric, category in _categories(state["build"], state)]
        _walk_listing(region, state, checkpoint)
        _walk_details(region, state, checkpoint)
        _walk_english(region, state, checkpoint)
        _read_intake(region, state)
    finally:
        _store(settings, region, PARTIAL, state)
    try:
        offers = _offers(settings, region)
    except LabSyncError as exc:
        # List prices are never wrong, only sometimes higher than today's.
        logger.warning("synevo offers unavailable: %s", exc.key)
        offers = {}
    items = _items(state, offers)
    _store(settings, region, "catalog", items)
    _store(settings, region, PROGRESS, _done_progress(state, items, started))
    with transaction(settings) as connection:
        connection.execute("DELETE FROM lab_catalog_cache WHERE provider=? AND region=? AND cache_key=?",
                           (PROVIDER, region, PARTIAL))
    return items


def _build_id(state: dict | None = None) -> str:
    match = _BUILD_RE.search(_get("/", raw=True, state=state))
    if not match:
        raise LabSyncError(_ERROR_REPLY)
    return match.group(1).decode("ascii")


def _rubric_pairs(rubric: object) -> list[tuple[str, str]]:
    pairs = []
    for sub in (rubric.get("subrubrics") or []) if isinstance(rubric, dict) else []:
        pair = (str(rubric.get("code") or ""), str(sub.get("code") or "") if isinstance(sub, dict) else "")
        if all(_SLUG_RE.fullmatch(part) for part in pair):
            pairs.append(pair)
    return pairs


def _categories(build: str, state: dict) -> list[tuple[str, str]]:
    reply = _get(f"/_next/data/{build}/uk/rubricator/top-tests.json", state=state)
    rubrics = ((reply or {}).get("pageProps") or {}).get("rubrics") if isinstance(reply, dict) else None
    if not isinstance(rubrics, list):
        raise LabSyncError(_ERROR_REPLY)
    pairs = []
    for rubric in rubrics:
        pairs.extend(_rubric_pairs(rubric))
    if not pairs:
        raise LabSyncError(_ERROR_REPLY)
    return list(dict.fromkeys(pairs))


def _details(service_id: str, region: str, state: dict | None = None, keep_inactive: bool = False) -> dict:
    """What the planner needs from one service's page: ``{}`` when Synevo has none."""
    reply = _get("/api/rubricator/service-details?" + _query(serviceId=service_id, lang="uk", city=region), state=state)
    data = reply.get("data") if isinstance(reply, dict) and reply.get("res") == "ok" else None
    if not isinstance(data, dict):
        return {}
    return {
        "name": " ".join(str(data.get("Name") or "").split()),
        "price": data.get("BasePrice"),
        "active": keep_inactive or (bool(data.get("Active")) and not data.get("Hidden")),
        "components": [" ".join(str(part.get("Name") or "").split()) for part in data.get("Components") or []
                       if isinstance(part, dict) and str(part.get("Name") or "").strip()],
        "bio": [str(material) for material in data.get("BioMaterialName") or [] if material],
        "days": _int(data.get("readyAfter")),
        "prep_title": " ".join(str(data.get("PrepRuleDescr") or "").split()),
        "prep": " ".join(part for part in (_plain(data.get("PrepRuleText")), _plain(data.get("Remarks"))) if part),
    }


def _int(value: object) -> int | None:
    try:
        number = int(str(value).strip())
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def _plain(markup: object) -> str:
    """The lab's HTML as one line of text."""
    text = html.unescape(re.sub(r"<[^>]+>", " ", str(markup or "")))
    return " ".join(text.split())


def _venous_blood(details: dict) -> bool:
    return any("венозна кров" in material.casefold() for material in details.get("bio") or [])


def _discounted(price: float, promo: dict | None) -> float:
    return round(price * (100 - promo["percent"]) / 100, 2) if promo else price


#: Synevo publishes no sex restriction, and its "for women" / "for men"
#: shelves are not one either: they list lipid and thyroid packages too.  A
#: package is one sex's only when its own name says so («Здоров'я жінки»,
#: «Пренатальний скринінг I триместра», «Для чоловіків віком 40+»).
_WOMEN_NAME = re.compile(r"жін|жiн|вагітн|триместр|менструал|\bмц\b|овуляц|prisca", re.IGNORECASE)
_MEN_NAME = re.compile(r"чолов|сперм|простат", re.IGNORECASE)


def _sex(name: str, parameters: list) -> str | None:
    if len(parameters) < 2:
        return None
    women, men = bool(_WOMEN_NAME.search(name)), bool(_MEN_NAME.search(name))
    if women and not men:
        return "F"
    if men and not women:
        return "M"
    return None


def _name_codes(services: dict) -> dict[str, str | None]:
    by_name: dict[str, str | None] = {}
    for service in services.values():
        key = name_key(service["name"])
        by_name[key] = service["code"] if by_name.get(key, service["code"]) == service["code"] else None
    return by_name


def _service_item(state: dict, sid: str, service: dict, found: dict, by_name: dict, intake: dict | None,
                  offers: dict[str, dict]) -> dict:
    code, name, price = service["code"], service["name"], float(service["price"])
    parameters = list({(by_name.get(name_key(part)) or "name:" + name_key(part)): part
                       for part in found.get("components") or []}.items()) or [(code, name)]
    promo = offers.get(code)
    return {
        "id": code,
        "code": code,
        "name": name,
        "url": f"{BASE}/tests/{code}",
        "price": price,
        "final_price": _discounted(price, promo),
        "fees": [dict(intake)] if intake and _venous_blood(found) else [],
        "parameters": [{"id": pid, "name": pname} for pid, pname in parameters],
        "synonyms": [],
        "sex": _sex(name, parameters),
        "groups": list(service.get("groups") or []),
        "name_en": (state.get("english") or {}).get("names", {}).get(sid) or None,
        "days": found.get("days"),
        "material": list(found.get("bio") or []),
        "prep": found.get("prep") or "",
        "prep_title": found.get("prep_title") or "",
        "order": {"code": code, "service_id": sid, **({"promo": promo} if promo else {})},
    }


def _items(state: dict, offers: dict[str, dict]) -> list[dict]:
    services, details = state["services"], state["details"]
    # A panel lists its members by name only; a member that is also sold on
    # its own takes that test's code, so the panel and the single test cover
    # the same requirement.  An ambiguous name keeps a name key instead.
    by_name = _name_codes(services)
    intake = state.get("intake")
    items = []
    for sid, service in services.items():
        found = details.get(sid) or {}
        if not service["active"] or found.get("active") is False or not isinstance(service["price"], (int, float)):
            continue
        items.append(_service_item(state, sid, service, found, by_name, intake, offers))
    return sorted(items, key=lambda item: int(item["code"]))


# --- offers -----------------------------------------------------------------------


def _offer_listing() -> list[dict]:
    items, page, pages = [], 1, 1
    while page <= min(pages, 20):
        reply = _get("/api/discount/get-list", payload={"lang": "uk", "page": page})
        data = reply.get("data") if isinstance(reply, dict) and reply.get("res") == "ok" else None
        if not isinstance(data, dict):
            raise LabSyncError(_ERROR_REPLY)
        items += [item for item in data.get("items") or [] if isinstance(item, dict)]
        pages, page = int(data.get("pagesCount") or 1), page + 1
    return items


def _skip_offer(item: dict, name: str, now: float) -> bool:
    # ponytail: "the monthly offer" is read off its name; anything else is
    # targeted (veterans, card holders) or unknown, and stays at list price.
    return (MONTHLY_OFFER not in name.casefold() or (item.get("statusLabel") or {}).get("statusFlag") != 0
            or float(item.get("endDate") or 0) < now or not _SLUG_RE.fullmatch(str(item.get("url") or "")))


def _percent_discounts(details: dict) -> dict[str, float]:
    return {str(service.get("code")): float(service["discountValue"])
            for service in details.get("services") or []
            if isinstance(service, dict) and service.get("discountType") == "percentage"
            and isinstance(service.get("discountValue"), (int, float)) and 0 < service["discountValue"] < 100}


def _offer_record(item: dict, name: str, info: dict, percent: dict[str, float]) -> dict:
    return {
        "id": info["_id"], "name": name, "url": item["url"],
        "until": datetime.fromtimestamp(float(item["endDate"]) / 1000, UTC).isoformat(timespec="seconds"),
        "percent": percent,
        "cities": [str(city.get("_id")) for city in info.get("availableCities") or [] if isinstance(city, dict)],
        "excluded": [str(city.get("_id")) for city in info.get("unavailableCities") or [] if isinstance(city, dict)],
    }


def _offer_from_page(item: dict, name: str, build: str) -> dict | None:
    reply = _get(f"/_next/data/{build}/uk/info/discounts/{item['url']}.json")
    info = ((reply or {}).get("pageProps") or {}).get("discountInfoData") if isinstance(reply, dict) else None
    details = (info or {}).get("servicesDetails") or {}
    if not isinstance(info, dict) or details.get("appliesFor") != "Include":
        return None
    percent = _percent_discounts(details)
    if not percent or not _ID_RE.fullmatch(str(info.get("_id") or "")):
        return None
    return _offer_record(item, name, info, percent)


def _fetch_offers() -> list[dict]:
    items = _offer_listing()
    now = datetime.now(UTC).timestamp() * 1000
    build, offers = None, []
    for item in items:
        name = " ".join(synevo._text(item.get("nameRegional")).split())
        if _skip_offer(item, name, now):
            continue
        build = build or _build_id()
        offer = _offer_from_page(item, name, build)
        if offer:
            offers.append(offer)
    return offers


def _offers(settings: Settings, region: str) -> dict[str, dict]:
    """Running monthly offers in this city: ``{code: promo}``."""
    now = datetime.now(UTC).isoformat(timespec="seconds")
    found = {}
    for offer in testplan.cached(settings, PROVIDER, "all", "offers", OFFERS_TTL, _fetch_offers):
        if offer["until"] < now or region in offer["excluded"] or (offer["cities"] and region not in offer["cities"]):
            continue
        for code, percent in offer["percent"].items():
            found[code] = {"id": offer["id"], "name": offer["name"], "url": offer["url"],
                           "percent": percent, "until": offer["until"]}
    return found


# --- after a plan -----------------------------------------------------------------


def _current_promo(offers: dict | None, fresh: dict) -> dict | None:
    promo = offers.get(fresh["code"]) if offers is not None else fresh["order"].get("promo")
    fresh["order"].pop("promo", None)
    if promo and promo["until"] >= datetime.now(UTC).isoformat(timespec="seconds"):
        fresh["order"]["promo"] = promo
        return promo
    return None


def _refresh_item(item: dict, region: str, offers: dict | None, fee: float | None) -> dict:
    fresh = {**item, "order": dict(item.get("order") or {}), "fees": [dict(f) for f in item.get("fees") or []]}
    sid = str(fresh["order"].get("service_id") or "")
    try:
        found = _details(sid, region) if _ID_RE.fullmatch(sid) else {}
    except LabSyncError:
        return {**fresh, "checked": False}
    if not found or not found["active"] or not isinstance(found.get("price"), (int, float)):
        return {**fresh, "available": False, "checked": True}
    fresh["price"] = float(found["price"])
    promo = _current_promo(offers, fresh)
    fresh["final_price"] = _discounted(fresh["price"], promo)
    if fee is not None:
        for entry in fresh["fees"]:
            if entry["id"] == f"{PROVIDER}:intake:{BLOOD_DRAW['code']}":
                entry["price"] = fee
    return {**fresh, "available": True, "checked": True}


def refresh_prices(settings: Settings, region: str, items: list[dict]) -> list[dict]:
    """Re-read today's price of just these items (one request each, plus the
    blood-draw fee once).  Each copy gains ``available`` and ``checked``; an
    item that could not be read keeps its stored price with ``checked`` False."""
    region = _city(region)
    try:
        offers = _offers(settings, region)
    except LabSyncError:
        offers = None
    fee = None
    if any(item.get("fees") for item in items):
        try:
            intake = _details(BLOOD_DRAW["service_id"], region, keep_inactive=True)
            fee = float(intake["price"]) if intake.get("price") is not None else None
        except LabSyncError:
            fee = None
    return [_refresh_item(item, region, offers, fee) for item in items]


_REFUSALS = {1001: "synevo_cart.in_package", 1002: _REFUSED, 1003: _REFUSED,
             2001: _REFUSED}


def _refusal(reply: object, code: str) -> str | None:
    """Why add-item did not add ``code``, or None when the cart now holds it."""
    if not isinstance(reply, dict):
        return _ERROR_REPLY
    if reply.get("error") in _REFUSALS:
        return _REFUSALS[reply["error"]]
    if reply.get("res") == "error":
        return "synevo_cart.promo" if reply.get("status") in (4010, 4011, 4013, 4014) else _REFUSED
    if reply.get("requred_confirm"):  # sic: Synevo's spelling
        return "synevo_cart.needs_confirmation"
    held = {str((entry.get("Service") or {}).get("Code")) for entry in reply.get("Items") or [] if isinstance(entry, dict)}
    return None if code in held else "synevo_cart.not_added"


def _open_cart(client, region: str | None) -> tuple[dict, str]:
    _pace()
    cart = client._call("GET", "/api/cart/get-cart")
    if isinstance(cart, dict) and isinstance(cart.get("cart"), dict):
        cart = cart["cart"]
    cart_id = str(cart.get("_id") or "") if isinstance(cart, dict) else ""
    if not _ID_RE.fullmatch(cart_id):
        raise LabSyncError(_ERROR_REPLY)
    if region and (cart.get("Location") or {}).get("_id") != _city(region):
        _pace()
        client._call("POST", "/api/cart/set-location", payload={"locationId": region, "cartId": cart_id})
    return cart, cart_id


def _add_item(client, cart_id: str, item: dict, added: list, failed: list, cart: object) -> object:
    """Add one item to the cart; returns the cart as Synevo last returned it."""
    order = item.get("order") or {}
    code = str(order.get("code") or item.get("code") or "")
    entry = {"id": item.get("id"), "code": code, "name": item.get("name")}
    if not _CODE_RE.fullmatch(code):
        failed.append({**entry, "reason": _ERROR_REPLY})
        return cart
    promo = order.get("promo") or {}
    # What Synevo's own pages send: a catalogue add, or an add from the
    # offer page carrying the offer's id.  isPackage is always false there.
    body = {"code": int(code), "cartId": cart_id, "confirm": False,
            "src": "akcii" if promo else "sc",
            "info": f"/info/discounts/{promo['url']}" if promo else f"/tests/{code}",
            "promoId": promo.get("id") or None, "isPackage": False}
    _pace()
    try:
        reply = client._call("POST", "/api/cart/add-item", payload=body)
    except LabSyncError as exc:
        if exc.key == "labsync.error_auth":
            raise
        failed.append({**entry, "reason": exc.key})
        return cart
    reason = _refusal(reply, code)
    if reason:
        failed.append({**entry, "reason": reason})
        return cart
    added.append(entry)
    return reply


def add_to_cart(settings: Settings, user_id: str, items: list[dict], *, region: str | None = None) -> dict:
    """Put these items into the person's own Synevo cart, with their stored
    session cookie; ``region`` moves the cart to that city first, so it
    prices what the plan priced.  The person checks out on Synevo's site."""
    from .. import labsync  # the package imports the results client; this module stays importable on its own

    if not labsync.active(settings, PROVIDER):
        raise LabSyncError("labsync.error_off")
    row = labsync.account(settings, user_id, PROVIDER)
    if not row or not row["secret"]:
        raise LabSyncError("labsync.error_no_credentials")
    if labsync._expired(row["secret_expires_at"]):
        raise LabSyncError("labsync.error_expired")
    client = synevo.Client(labsync.provider_settings(settings, PROVIDER)["url"], row["secret"])
    added, failed, cart = [], [], None
    try:
        cart, cart_id = _open_cart(client, region)
        for item in items:
            cart = _add_item(client, cart_id, item, added, failed, cart)
    finally:
        labsync._store_rolled_secret(settings, user_id, PROVIDER, row["secret"], client)
    totals = {name: cart.get(key) for name, key in (("services", "ServicesSum"), ("fees", "IntakesSum"),
                                                     ("discounts", "DiscountsSum"), ("total", "TotalSum"))}
    return {"added": added, "failed": failed, "cart_url": f"{client.base_url}/ordering", "cart": totals}
