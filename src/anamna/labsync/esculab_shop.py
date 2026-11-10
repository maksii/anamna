"""Esculab's price list and web orders, for the test planner (/plan-tests).

Observed from the Esculab Android app 3.0.6 (``com.mak.elab``) and its public
endpoints on 2026-11-08.  Prices are per city and public; a web order needs
the person's Esculab sign-in (the same bearer token and ``AccessPhone`` header
:mod:`.esculab` keeps).

* ``GET /api/customers/getRegions`` → cities (``idReg``), public
* ``GET /api/site/price/get?regionId=<idReg>`` → the whole price list of one
  city in one reply (~20 MB, ~2,650 items): groups with ``goods``, each with
  ``price``, ``discount`` (a percentage), ``parameters`` (the analytes, whose
  ids are the ``idtest`` of result rows), ``takes`` (sample collection
  charges, added to the basket once however many items need them), ``opt``
  flags and ``configs`` (the material variant an order names)
* ``GET /api/site/price/details/get?goodId=<id>`` → ``{goodId, info}`` only,
  no price: the item's texts, of which ``info.ua_rules`` (preparation) is the
  one the price list lacks.  The price list's own ``info`` has synonyms and
  definitions; ``duritionDay`` / ``durationMin`` are the turnaround and
  ``configs[].materials`` the sample.  No English name anywhere: Latin appears
  only as abbreviations in names («(ТТГ, TSH)») and in the synonym lists.
* ``GET /api/customers/getPunkts`` → collection points (``idCity`` = city)
* ``POST /api/customers/referral/create`` → a web order: ``{referralId: 0,
  orderId: 0, punktId, clientId, doctorId: 0, promo, note, num, status, date,
  payment: "CARD"|"CASH", services: [{goodId, confId, price, discount, amount,
  name}], channels}``.  ``price`` is the list price, ``discount`` the amount
  in UAH (an existing order: 4875.0 and 487.0).  The order then shows in the
  person's Esculab app and site, where it is paid online or at the point.
* ``GET https://payment-lique.esculab.com/payment/link?identifier=<referralId>``
  → the LiqPay link the app opens for paying online.

The app's own basket rules, kept here: an item flagged ``notsale`` has no
basket button (it is ordered at a point, not online), so the planner does not
offer it; each distinct ``take`` is charged once per order and is sent as a
service of its own (``confId`` 0, no discount).  The discount is whole
hryvnias, rounded down: every service of the account's 2026 orders reads that
way (365 at 10% -> 36, 4875 -> 487, 695 -> 69).
"""

from __future__ import annotations

import html
import math
import re
from datetime import UTC, date, datetime, timedelta

from ..config import Settings
from . import common
from .common import LabSyncError, digits

KEY = "esculab"
NAME = "Esculab"
SITE = "https://esculab.com"
PAYMENT_LINK = "https://payment-lique.esculab.com/payment/link?identifier="
CATALOG_TTL = timedelta(days=1)
REGIONS_TTL = timedelta(days=7)
DEFAULT_REGION = "3201"  # Lviv
_CATALOG_LIMIT = 64 * 1024 * 1024
_TAG_RE = re.compile(r"<[^>]+>")
_ERROR_REPLY = "labsync.error_reply"


def _get(base_url: str, path: str, *, limit: int | None = None, timeout: int | None = None):
    reply, _ = common.call("GET", base_url.rstrip("/") + path, headers={}, limit=limit, timeout=timeout)
    return reply


_BLOCK_TAG = re.compile(r"</?(?:p|br|li|ul|ol|div|h\d|tr|td|table)\b", re.IGNORECASE)


def _plain(text: object) -> str:
    """HTML as one line of text: a block tag is a space, an inline one
    («(<span>Serum</span> ferritin)») nothing."""
    return " ".join(html.unescape(_TAG_RE.sub(lambda tag: " " if _BLOCK_TAG.match(tag.group()) else "",
                                              str(text or ""))).split())


def _money(value: float) -> float:
    return round(float(value) + 1e-9, 2)


def _discounted(price: float, percent: float) -> float:
    return _money(price - math.floor(price * percent / 100 + 1e-9))


def regions(settings: Settings, base_url: str = SITE) -> list[dict]:
    from ..testplan import cached

    def fetch():
        reply = _get(base_url, "/api/customers/getRegions")
        if not isinstance(reply, list):
            raise LabSyncError(_ERROR_REPLY)
        return sorted(({"id": str(row["idReg"]), "name": str(row.get("name") or "").strip()}
                       for row in reply if isinstance(row, dict) and row.get("idReg")),
                      key=lambda row: row["name"])

    return cached(settings, KEY, "", "regions", REGIONS_TTL, fetch)


def _good_configs(good: dict) -> list[dict]:
    return [c for c in good.get("configs") or [] if isinstance(c, dict) and c.get("id")]


def _good_parameters(good: dict) -> list[dict]:
    seen, parameters = set(), []
    for parameter in good["parameters"]:
        key = str(parameter.get("id"))
        if key not in seen:
            seen.add(key)
            parameters.append({"id": key, "name": str(parameter.get("name") or "").strip()})
    return parameters


def _good_fees(good: dict) -> list[dict]:
    return [{"id": str(take["id"]), "name": " ".join(str(take.get("name") or "").split()),
             "price": _discounted(float(take.get("price") or 0), float(take.get("discount") or 0))}
            for take in good.get("takes") or [] if isinstance(take, dict) and take.get("id")]


def _good_sex(opts: set) -> str | None:
    men, women = "forman" in opts, "forwoman" in opts
    if men and not women:
        return "M"
    if women and not men:
        return "F"
    return None


def _good_url(good: dict) -> str | None:
    return SITE + good["path"] if str(good.get("path") or "").startswith("/") else None


def _good_synonyms(info: dict) -> list[str]:
    return [part.strip() for part in _plain(info.get("ua_synonyms")).split(",") if part.strip()]


def _good_search_names(info: dict, good: dict) -> list[str]:
    # Search-only names: the site's synonym line («Сироватковий феритин (Serum
    # ferritin); Білок депо заліза») and the Russian name.  Kept apart from
    # ``synonyms``, which testplan.keyed also resolves concepts by.
    aka = [part.strip(" .") for part in re.split(r"[;,]", _plain(info.get("ua_synonyms_site"))) if len(part.strip(" .")) > 1]
    aka += [" ".join(str(good.get("nameRu") or "").split())]
    return list(dict.fromkeys(part for part in aka if part))[:30]


def _good_materials(configs: list[dict]) -> list[str]:
    materials = [" ".join(str(m.get("name") or "").split()) for m in configs[0].get("materials") or []
                 if isinstance(m, dict) and str(m.get("name") or "").strip()]
    return list(dict.fromkeys(materials))


def item(good: dict) -> dict | None:
    """One price-list good in the planner's item shape, or None when it
    cannot be ordered online or reports nothing."""
    opts = set(good.get("opt") or [])
    price = float(good.get("price") or 0)
    if "notsale" in opts or price <= 0 or not good.get("parameters"):
        return None
    configs = _good_configs(good)
    if not configs:
        return None
    parameters = _good_parameters(good)
    discount = float(good.get("discount") or 0)
    info = good.get("info") or {}
    synonyms = _good_synonyms(info)
    aka = _good_search_names(info, good)
    materials = _good_materials(configs)
    return {
        "id": str(good["id"]),
        "code": str(good.get("code") or ""),
        "name": " ".join(str(good.get("name") or "").split()),
        "url": _good_url(good),
        "price": _money(price),
        "final_price": _discounted(price, discount),
        "discount_pct": discount,
        "fees": _good_fees(good),
        "parameters": parameters,
        "synonyms": synonyms[:30],
        "aka": aka,
        "sex": _good_sex(opts),
        # Turnaround as the app prints it ("1 дн"); express tests give minutes.
        "days": int(good.get("duritionDay") or 0) or None,
        "minutes": int(good.get("durationMin") or 0) or None,
        # The sample the ordered variant (``configs[0]``) is taken from.
        "material": materials,
        "prep": prep(info, good.get("note")),
        "order": {"confId": str(configs[0]["id"])},
    }


#: Characters of preparation text kept per item, cut at a sentence end.
PREP_LIMIT = 1200
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+")


def prep(info: dict | None, note: object = "") -> str:
    """The lab's own preparation and collection rules, as plain Ukrainian
    text.  ``ua_rules`` is carried only by the per-good details reply
    (:func:`details`); the price list has the note and point restrictions."""
    info = info or {}
    text = " ".join(part for part in (_plain(info.get("ua_rules")), _plain(info.get("ua_recommendations")),
                                      _plain(note), _plain(info.get("ua_punkt_restriction"))) if len(part) > 2)
    if len(text) <= PREP_LIMIT:
        return text
    kept = ""
    for sentence in _SENTENCE_END.split(text):
        if len(kept) + len(sentence) + 1 > PREP_LIMIT:
            break
        kept = f"{kept} {sentence}".strip()
    return kept or text[:PREP_LIMIT]


DETAIL_TTL = timedelta(days=7)
_DETAIL_WORKERS = 6
#: A gene symbol as Esculab lists them («BRCA1, BRCA2, MLH1»); other
#: capitals in the same text (NGS, PCR) are harmless, since a gene is only
#: ever looked up, never listed.
_GENE = re.compile(r"\b[A-Z][A-Z0-9]{1,9}\b")
#: Characters of description kept per good, for search.
DESCRIPTION_LIMIT = 4000


def describe(info: dict | None) -> dict:
    """What a good's details say it contains: ``text`` (its definition,
    marker and contents, plain, for search) and ``genes`` (every gene symbol
    its contents, method and synonyms list: «Методом NGS секвенування
    цільових генів: AAS, AASS, ...»).  The price list carries neither: a
    252-gene panel is one row there."""
    info = info or {}
    contents = " ".join(_plain(info.get(key)) for key in ("ua_measurement_range", "ua_method", "ua_synonyms"))
    # The general description is where a panel states its standard («рівень
    # Tier 3 згідно з рекомендаціями ACMG 2021»); the gene list goes last.
    text = " ".join(part for part in (_plain(info.get("ua_definition")), _plain(info.get("ua_marker")),
                                      _plain(info.get("ua_general_characteristics"))[:1500],
                                      _plain(info.get("ua_measurement_range"))) if part)
    return {"text": text[:DESCRIPTION_LIMIT], "genes": sorted(set(_GENE.findall(contents)))}


def details(settings: Settings, ids: list[str], base_url: str = SITE) -> dict[str, dict]:
    """``{good id: {"prep": text, "text": ..., "genes": [...]}}`` from each
    good's own details reply, the only place Esculab publishes preparation
    rules and what a panel contains (:func:`describe`).  Cached a week per
    good (not per city: the rules are the lab's, not the point's), fetched in
    parallel; a good that fails to read is simply absent and is tried again
    next time."""
    return _details(settings, ids, base_url, fetch=True)


def descriptions(settings: Settings, items: list[dict], *, fetch: bool = True) -> dict[str, dict]:
    """:func:`details` for these items, from the lab address set for
    Esculab; ``fetch`` False reads the cache only."""
    from .. import labsync

    base = SITE
    if fetch:
        try:
            base = labsync.provider_settings(settings, "esculab").get("url") or SITE
        except LabSyncError:
            return {}
    return _details(settings, [item["id"] for item in items], base, fetch=fetch)


def _details(settings: Settings, ids: list[str], base_url: str, *, fetch: bool) -> dict[str, dict]:
    import json
    from concurrent.futures import ThreadPoolExecutor

    from ..db import connect, transaction, utc_now

    ids = list(dict.fromkeys(str(i) for i in ids if str(i).isdigit()))
    if not ids:
        return {}
    keys = {f"detail:{i}": i for i in ids}
    since = (datetime.now(UTC) - DETAIL_TTL).replace(microsecond=0).isoformat()
    with connect(settings) as connection:
        rows = connection.execute(
            f"""SELECT cache_key, payload_json FROM lab_catalog_cache WHERE provider=? AND region='' AND fetched_at>?
                AND cache_key IN ({','.join('?' * len(keys))})""", (KEY, since, *keys)).fetchall()
    # A copy cached before descriptions were kept counts as missing.
    out = {keys[row["cache_key"]]: payload for row in rows
           if "genes" in (payload := json.loads(row["payload_json"]))}

    def read(good_id: str) -> tuple[str, dict | None]:
        try:
            reply = _get(base_url, f"/api/site/price/details/get?goodId={good_id}", timeout=15)
        except LabSyncError:
            return good_id, None
        return good_id, ({"prep": prep(reply.get("info")), **describe(reply.get("info"))}
                         if isinstance(reply, dict) else None)

    missing = [i for i in ids if i not in out]
    if missing and fetch:
        with ThreadPoolExecutor(min(_DETAIL_WORKERS, len(missing))) as pool:
            fetched = {good_id: found for good_id, found in pool.map(read, missing) if found is not None}
        if fetched:
            with transaction(settings) as connection:
                connection.executemany(
                    """INSERT INTO lab_catalog_cache(provider, region, cache_key, fetched_at, payload_json)
                       VALUES (?, '', ?, ?, ?) ON CONFLICT(provider, region, cache_key) DO UPDATE SET
                       fetched_at=excluded.fetched_at, payload_json=excluded.payload_json""",
                    [(KEY, f"detail:{i}", utc_now(), json.dumps(found, ensure_ascii=False)) for i, found in fetched.items()])
            out.update(fetched)
    return out


def _catalog_items(reply: list) -> list[dict]:
    items = []
    for group in reply:
        if isinstance(group, dict):
            items.extend(_group_items(group))
    return items


def _group_items(group: dict) -> list[dict]:
    # The lab's own shelves («Генетичні дослідження», «Пакетні
    # пропозиції»): what testplan.item_kind tells sets from single tests by.
    groups = [" ".join(str(name).split()) for name in (group.get("superGroupName"), group.get("name")) if name]
    items = []
    for good in group.get("goods") or []:
        found = item(good) if isinstance(good, dict) else None
        if found:
            items.append({**found, "groups": groups})
    return items


def catalog(settings: Settings, region: str, base_url: str = SITE) -> list[dict]:
    """The whole price list of one city, as items; one request a day."""
    from ..testplan import cached

    def fetch():
        reply = _get(base_url, f"/api/site/price/get?regionId={digits(region)}", limit=_CATALOG_LIMIT, timeout=120)
        if not isinstance(reply, list):
            raise LabSyncError(_ERROR_REPLY)
        return _catalog_items(reply)

    return cached(settings, KEY, str(region), "catalog", CATALOG_TTL, fetch)


def refresh_prices(region: str, items: list[dict], base_url: str = SITE) -> list[dict]:
    """The chosen items re-read from today's price list: the cached copy is a
    day old at most, a discount can end sooner.  One request for the whole
    list, because the per-good details reply carries no price at all (only
    ``goodId`` and ``info``, checked 2026-11-08).  An item that fails to
    re-read keeps the catalogue's price (``checked`` False)."""
    try:
        reply = _get(base_url, f"/api/site/price/get?regionId={digits(region)}", limit=_CATALOG_LIMIT, timeout=120)
    except LabSyncError:
        reply = None
    goods = {str(good.get("id")): good for group in reply if isinstance(group, dict)
             for good in group.get("goods") or [] if isinstance(good, dict)} if isinstance(reply, list) else {}
    out = []
    for found in items:
        fresh = item(goods[found["id"]]) if found["id"] in goods else None
        if fresh:
            out.append({**found, "price": fresh["price"], "final_price": fresh["final_price"],
                        "discount_pct": fresh["discount_pct"], "checked": True})
        else:
            out.append({**found, "checked": False})
    return out


def points(settings: Settings, region: str, base_url: str = SITE) -> list[dict]:
    """Collection points in one city."""
    from ..testplan import cached

    def fetch():
        reply = _get(base_url, "/api/customers/getPunkts")
        if not isinstance(reply, list):
            raise LabSyncError(_ERROR_REPLY)
        return [{"id": str(row.get("idPunkt") or row.get("id")), "city": str(row.get("idCity") or ""),
                 "address": " ".join(str(row.get("address") or "").split()),
                 "hours": " ".join(str(row.get("hWork") or "").split())}
                for row in reply if isinstance(row, dict) and row.get("active") and row.get("onsite")]

    return [row for row in cached(settings, KEY, "", "points", REGIONS_TTL, fetch) if row["city"] == str(region)]


def _authed(client, method: str, url: str, payload=None):
    reply, _ = common.call(method, url, payload=payload,
                           headers={"Authorization": f"Bearer {client.secret}", "AccessPhone": client.phone})
    return reply


def last_point(client, person_id: str) -> str | None:
    """The collection point of the person's latest web order, for a default."""
    try:
        reply = _authed(client, "GET", f"{client.base_url}/api/customers/referral/get?patientId={digits(person_id)}")
    except LabSyncError:
        return None
    rows = [row for row in reply or [] if isinstance(row, dict) and row.get("punktId")]
    rows.sort(key=lambda row: str(row.get("createdAt") or ""), reverse=True)
    return str(rows[0]["punktId"]) if rows else None


def fees(items: list[dict]) -> list[dict]:
    """The distinct collection charges these items bring, each once."""
    return list({fee["id"]: fee for found in items for fee in found["fees"]}.values())


def create_order(client, person_id: str, point_id: str, items: list[dict], *, online: bool,
                 day: date | None = None) -> dict:
    """File a web order on the person's Esculab account; returns its number
    and, when paying online, the LiqPay link.  Nothing is paid here."""
    body = {
        "referralId": 0, "orderId": 0, "punktId": int(digits(point_id)), "clientId": int(digits(person_id)),
        "doctorId": 0, "promo": "string", "note": "", "num": "string", "status": "string",
        "date": f"{(day or date.today()).isoformat()}T00:00:00.000Z",
        "payment": "CARD" if online else "CASH",
        "services": [{"goodId": int(digits(found["id"])), "confId": int(digits(found["order"]["confId"])),
                      "price": found["price"], "discount": _money(found["price"] - found["final_price"]),
                      "amount": 1, "name": found["name"]} for found in items]
        + [{"goodId": int(digits(fee["id"])), "confId": 0, "price": fee["price"], "discount": 0.0, "amount": 1,
            "name": fee["name"]} for fee in fees(items)],
        "channels": "SMS_VIBER",
    }
    reply = _authed(client, "POST", f"{client.base_url}/api/customers/referral/create", body)
    number = reply.get("referralId") if isinstance(reply, dict) else reply
    if isinstance(reply, dict) and isinstance(reply.get("data"), dict):
        number = reply["data"].get("referralId") or number
    try:
        number = digits(number)
    except LabSyncError:
        raise LabSyncError(_ERROR_REPLY) from None
    return {"number": number, "payment_url": payment_link(client, number) if online else None}


def payment_link(client, number: str) -> str | None:
    """The app opens this reply's body as a URL (axios ``.data``), so it is
    read as text: a bare URL, or one JSON-quoted."""
    try:
        status, _, body = common._http("GET", PAYMENT_LINK + digits(number), headers={
            "Authorization": f"Bearer {client.secret}", "AccessPhone": client.phone, "Accept": "*/*"})
    except LabSyncError:
        return None
    text = body.decode("utf-8", "replace").strip().strip('"').replace("\\/", "/") if 200 <= status < 300 else ""
    return text if re.fullmatch(r"https://[^\s\"'<>]{8,2000}", text) else None
