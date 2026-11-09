"""The test planner: which lab items cover what a person needs re-measured,
at the lowest price the labs charge today.

Labs (``CATALOGS``) publish what they sell as *items*.  An item is one thing
that can be ordered and paid for -- a single test or a panel -- as a dict:

``id``           the lab's own id for the item (str), what its cart takes
``code``         the code the lab prints (str, may be "")
``name``         the lab's name for it (Ukrainian)
``url``          the item's page on the lab's site, or None
``price``        list price, UAH (float)
``final_price``  what it costs today after the lab's own running discount
``fees``         ``[{"id", "name", "price"}]``: charges the lab adds once per
                 order however many items need them (taking a blood sample);
                 two items with the same fee id pay it once
``parameters``   ``[{"id", "name"}]``: the analytes the item reports; a single
                 test lists itself
``synonyms``     other names the lab gives it (search only)
``sex``          "M" / "F" when the lab sells it to one sex only, else None
``order``        lab-specific data its cart needs (opaque here)

The optimiser never sees a lab: it covers *requirement keys* -- a concept id
when an item's analyte resolves to one of ours, else ``"<lab>:<parameter
id>"`` -- with the cheapest set of items, counting each fee once.
"""

from __future__ import annotations

import json
import re
import threading
import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from .config import Settings
from .db import connect, transaction, utc_now

_FETCH_LOCK = threading.Lock()


def cached(settings: Settings, provider: str, region: str, key: str, ttl: timedelta,
           fetch: Callable[[], object]) -> object:
    """``fetch()``'s JSON-able result, reused for ``ttl``.  A failed refetch
    of a stale row serves the stale row: last week's prices beat none, and the
    page says when they were read (:func:`fetched_at`)."""
    def read():
        with connect(settings) as connection:
            return connection.execute(
                "SELECT fetched_at, payload_json FROM lab_catalog_cache WHERE provider=? AND region=? AND cache_key=?",
                (provider, region, key),
            ).fetchone()

    row = read()
    if row and datetime.fromisoformat(row["fetched_at"]) > datetime.now(UTC) - ttl:
        return json.loads(row["payload_json"])
    # ponytail: one process-wide lock, so two people opening the planner at
    # once download a price list once; per-key locks if that ever queues.
    with _FETCH_LOCK:
        fresh = read()
        if fresh and fresh is not row and fresh["fetched_at"] != (row["fetched_at"] if row else None):
            return json.loads(fresh["payload_json"])
        try:
            payload = fetch()
        except Exception:
            if row:
                return json.loads(row["payload_json"])
            raise
        with transaction(settings) as connection:
            connection.execute(
                """INSERT INTO lab_catalog_cache(provider, region, cache_key, fetched_at, payload_json)
                   VALUES (?, ?, ?, ?, ?)
                   ON CONFLICT(provider, region, cache_key) DO UPDATE SET
                       fetched_at=excluded.fetched_at, payload_json=excluded.payload_json""",
                (provider, region, key, utc_now(), json.dumps(payload, ensure_ascii=False)),
            )
        return payload


def fetched_at(settings: Settings, provider: str, region: str, key: str = "catalog") -> str | None:
    with connect(settings) as connection:
        row = connection.execute(
            "SELECT fetched_at FROM lab_catalog_cache WHERE provider=? AND region=? AND cache_key=?",
            (provider, region, key),
        ).fetchone()
    return row["fetched_at"] if row else None


# --- what an item measures, in our terms ------------------------------------------

#: Urine named in a label or item: «сеча», «сечі», but not «сечова кислота»
#: or «сечовина», which are blood tests.
_URINE = re.compile(r"сеч(?!ов)|urine")


def alias_index(connection) -> dict[str, list[tuple[str | None, str]]]:
    """Every learned and seeded alias: ``normalized_alias -> [(vendor, concept)]``."""
    index: dict[str, list[tuple[str | None, str]]] = {}
    for row in connection.execute(
        """SELECT a.normalized_alias, v.canonical_name vendor, a.concept_id FROM concept_aliases a
           LEFT JOIN vendors v ON v.id=a.vendor_id"""
    ):
        index.setdefault(row["normalized_alias"], []).append((row["vendor"], row["concept_id"]))
    return index


def _specimen_key(label: str, context: str) -> str:
    """A name with its specimen: a bare «Лейкоцити» in a urinalysis is not
    the blood count of the same spelling."""
    from .ingest.text import normalized_key

    urine = bool(_URINE.search(normalized_key(f"{label} {context}")))
    return ("urine:" if urine else "") + normalized_key(label)


#: Labs whose result rows carry the catalogue's parameter id (Esculab's
#: ``idtest``), so a synced row teaches the parameter itself, not only its name.
_ROW_ID_IS_PARAMETER = frozenset({"esculab"})


def learned_names(connection, owner_user_id: str, lab: str) -> dict[str, str]:
    """What this lab's own analyte names meant in this person's record:
    ``normalized name -> concept`` from every synced order whose report was
    imported, pairing the lab's row with the parsed value of the same report
    by name, else by the one value that is equal.  The lab's price list uses
    the names its results do; where the row also carries the catalogue's
    parameter id (Esculab: the ``idtest``), ``"id:<id>" -> concept`` too, so
    a test the person has had there is recognised however the catalogue
    spells it."""
    from .ingest.concepts import clean_label
    from .ingest.text import normalized_key
    from .labsync.common import parse_result

    learned: dict[str, str] = {}
    for order in connection.execute(
        """SELECT rows_json, document_id FROM lab_orders
           WHERE provider=? AND owner_user_id=? AND rows_json IS NOT NULL AND document_id IS NOT NULL""",
        (lab, owner_user_id),
    ):
        observations = connection.execute(
            "SELECT raw_name, concept_id, value_numeric FROM observations WHERE document_id=? AND verification_status<>'rejected'",
            (order["document_id"],),
        ).fetchall()
        by_name = {normalized_key(clean_label(row["raw_name"] or "")): row["concept_id"] for row in observations}
        by_value: dict[float, list[str]] = {}
        for row in observations:
            if row["value_numeric"] is not None:
                by_value.setdefault(round(float(row["value_numeric"]), 6), []).append(row["concept_id"])
        for lab_row in json.loads(order["rows_json"]):
            label = clean_label(str(lab_row.get("test") or ""))
            name = _specimen_key(label, str(lab_row.get("packet") or ""))
            row_id = f"id:{lab_row['idtest']}" if lab in _ROW_ID_IS_PARAMETER and lab_row.get("idtest") else None
            if not label or (name in learned and (row_id is None or row_id in learned)):
                continue
            concept = by_name.get(normalized_key(label))
            if not concept:
                _, number = parse_result(lab_row.get("result"))
                matches = set(by_value.get(round(number, 6), [])) if number is not None else set()
                concept = matches.pop() if len(matches) == 1 else None
            if concept:
                learned.setdefault(name, concept)
                if row_id:
                    learned.setdefault(row_id, concept)
    return learned


#: A blood specimen named in the label: «Калій (сироватка)», «Глюкоза (плазма
#: крові)», «Залізо в сироватці крові».  Serum and plasma are what a bare
#: name already means; whole blood («цільна кров») is not, and stays.
_SERUM = re.compile(r"\s*\(\s*(?:сироватк\w*|плазм\w*)(?:\s+крові)?\s*\)|\s+(?:в|у)\s+(?:сироватці|плазмі)(?:\s+крові)?\b",
                    re.IGNORECASE)
_BRACKET = re.compile(r"\(([^()]*)\)")
#: An antibody named in the label.  Its own bracketed code can be a code of
#: something else entirely: anti-MCV («Цитрульований віментин (MCV)») is not
#: the mean corpuscular volume.
_ANTIBODY = re.compile(r"антитіл|antibod|\banti-|\bат до\b|\big\s?[gmae]\d?\b", re.IGNORECASE)
_ANTIBODY_CATEGORIES = frozenset({"autoimmune", "infection", "allergy", "immunology"})
#: A specimen other than blood or urine: a name resolved by its parts alone
#: would land on the blood concept of the same word.
_OTHER_SPECIMEN = re.compile(
    r"слин|сперм|еякулят|ліквор|спинномозков|\bкал\b|фекал|випорожн|мазок|мазк|зішкріб|виділен|мокротин"
    r"|волосс|нігт|амніот|навколоплідн|молок|цільн\w* кров|добов", re.IGNORECASE)


def _fits(definition: dict, label: str) -> bool:
    """A resolution that does not contradict the label: an antibody name is
    an antibody concept."""
    if not _ANTIBODY.search(label):
        return True
    name = str(definition["name"]).casefold()
    return definition["category"] in _ANTIBODY_CATEGORIES or "antibod" in name or "anti-" in name


#: Gene panels and genotyping: their bracketed gene lists are full of symbols
#: that spell an analyte («EGFR» is a gene, not the eGFR).
_GENETIC = re.compile(r"\bген\w*|генетич|генотип|мутац|поліморф|\bngs\b|\bднк\b|\bdna\b|\bпл[рp]\b|\bpcr\b", re.IGNORECASE)
#: An index, ratio or calculation is not any of the analytes it is built from.
_DERIVED = re.compile(r"індекс|співвідношен|коефіцієнт|розрахун|\bratio\b|\bindex\b", re.IGNORECASE)
#: More comma-separated parts than this in one bracket is a list (a panel's
#: members, a gene list), not the analyte's other names.
_MAX_PARTS = 4


def _initialism(part: str, base: str) -> bool:
    """«РФ» abbreviates «Ревматоїдний фактор», «ЛГ» «Лютеїнізуючий гормон»:
    the part's letters run through the base in order, from its first letter."""
    letters = [ch for ch in part.casefold() if ch.isalpha()]
    text = base.casefold()
    if not 2 <= len(letters) <= 6 or letters[0] != text[:1]:
        return False
    position = 0
    for letter in letters:
        position = text.find(letter, position) + 1
        if not position:
            return False
    return True


def _by_parts(label: str, urine: bool, context: str) -> dict | None:
    """The definition a label's parts agree on, when the whole label is not
    an alias: the label with its serum/plasma qualifier dropped («Калій
    (сироватка)»); else the bracketed abbreviations («(T4 вільний)») and the
    name outside the brackets, all that resolve naming one thing.  The name
    outside alone counts only when each bracket holds its initialism
    («Ревматоїдний фактор (РФ)»): «Гемоглобін (RET-He)» is reticulocyte
    haemoglobin, not haemoglobin.  Parts that name two different things (a
    prothrombin test's «(ПЧ, % за Квіком, МНВ / INR)», hs-CRP's «(C-Reactive
    Protein, High Sensitivity)») name none.  Never for a specimen other than
    blood and urine or a genetic test, and a urine label only ever finds a
    urine concept."""
    from .ingest.concepts import concept_for_alias

    if _OTHER_SPECIMEN.search(f"{label} {context}") or _GENETIC.search(label) or _DERIVED.search(label):
        return None

    def look(text: str) -> dict | None:
        definition = concept_for_alias(text, None, category="urinalysis" if urine else None) if text else None
        if definition is None or not _fits(definition, label) or (definition["category"] == "urinalysis") != urine:
            return None
        return definition

    bare = " ".join(_SERUM.sub(" ", label).split())
    if bare != label and (definition := look(bare)):
        return definition
    groups = [[part.strip() for part in re.split(r"[,;]", group) if part.strip()] for group in _BRACKET.findall(bare)]
    if not groups or any(len(parts) > _MAX_PARTS for parts in groups):
        return None
    base = " ".join(_BRACKET.sub(" ", bare).split())
    found = {str(d["name"]): d for parts in groups for part in parts if (d := look(part))}
    # «МНВ / INR» beside «ПЧ» names a second analyte; one side of a slash
    # never names the analyte on its own («тестостерон загальний/SHBG» is
    # the free androgen index, not testosterone), it only rules one out.
    found.update({str(d["name"]): d for parts in groups for part in parts if "/" in part
                  for side in part.split("/") if found and (d := look(side.strip()))})
    outside = look(base)
    if outside is not None:
        if found and set(found) != {str(outside["name"])}:
            return None
        if found or all(any(_initialism(part, base) for part in parts) for parts in groups):
            return outside
        return None
    return next(iter(found.values())) if len(found) == 1 else None


def resolve(name: str, context: str, vendor: str, aliases: dict, learned: dict | None = None) -> str | None:
    """The concept an analyte name means, read-only: what this lab's name
    meant in the record, then the seeded definitions (as :mod:`ingest.pipeline`
    does), then the aliases learned from imported reports, this lab's own
    before anyone else's (Latin/Cyrillic homoglyphs folded: «(МСН)» is MCH),
    then the label's parts (:func:`_by_parts`).  ``context`` names the
    specimen: the lab's own smallest item carrying the analyte."""
    from .ingest.concepts import clean_label, concept_for_alias, label_key, stable_concept_id
    from .ingest.text import normalized_key

    label = clean_label(name)
    if not label:
        return None
    specimen = _specimen_key(label, context)
    if learned and specimen in learned:
        return learned[specimen]
    urine = specimen.startswith("urine:")
    definition = concept_for_alias(label, None, category="urinalysis" if urine else None)
    if definition and _fits(definition, label):
        return stable_concept_id(str(definition["name"]))
    found = aliases.get(normalized_key(label)) or aliases.get(label_key(label)) or []
    found = sorted(found, key=lambda pair: (pair[0] != vendor, pair[0] is None))
    if found:
        return found[0][1]
    definition = _by_parts(label, urine, context)
    return stable_concept_id(str(definition["name"])) if definition else None


#: Analyte names that are a whole examination reported as one text block,
#: with the concepts it reports.  Esculab and Synevo both sell the coprogram
#: as one row «Копрограма», where another lab files each finding as its own
#: row (stool pH, muscle fibres).  Listed, not "the stool category": a stool
#: calprotectin or occult-blood concept added later is not in a coprogram.
#: Esculab's «Мікроскопія сечі» is not one: it is the heading above the
#: sediment rows its urinalysis lists one by one (result «-»), so it covered
#: every urine concept -- dipstick, colour, volume -- while measuring none of
#: them (:data:`.testplan_aliases.NOT_ANALYTES`).
WHOLE_TESTS: dict[str, tuple[str, ...]] = {"копрограма": (
    "stool-colour", "stool-form", "stool-consistency", "stool-odour", "stool-undigested-food-residue",
    "stool-food-residue", "stool-mucus", "stool-blood", "stool-pus", "stool-tissue-fragments", "stool-concretions",
    "stool-ph", "stool-muscle-fibres-altered", "stool-muscle-fibres-slightly-altered",
    "stool-muscle-fibres-unaltered", "stool-plant-fibre-undigested", "stool-plant-fibre-digested",
    "stool-starch-intracellular", "stool-starch-extracellular", "stool-neutral-fat", "stool-fatty-acids",
    "stool-soaps", "stool-crystals", "stool-epithelium", "stool-leukocytes", "stool-erythrocytes",
    "stool-cells-with-malignant-features", "stool-iodophilic-flora", "stool-protozoa", "stool-helminth-eggs",
    "stool-yeast-like-fungal-elements",
)}


def category_index(connection) -> dict[str, list[str]]:
    """The record's stool concepts by category.  :func:`keyed` no longer
    needs it (whole examinations list their concepts); kept for callers."""
    index: dict[str, list[str]] = {}
    for row in connection.execute("SELECT id, category FROM concepts WHERE category='stool'"):
        index.setdefault(row["category"], []).append(row["id"])
    return index


#: The sample a 24-hour urine collection is, in Esculab's ``material``.
_DAILY_URINE = re.compile(r"добов", re.IGNORECASE)


def _daily_urine(item: dict) -> bool:
    """An item collected over 24 hours and no spot urine beside it: its urine
    rows are daily totals, whatever their names.  Esculab gives the 24-hour
    test (F6003) the same parameter ids as the urinalysis in its packages."""
    materials = [str(m) for m in item.get("material") or []]
    return any(_DAILY_URINE.search(m) for m in materials) and not any(
        _URINE.search(m) and not _DAILY_URINE.search(m) for m in materials)


def _folded(aliases: dict) -> dict:
    """``aliases`` with every key also under its homoglyph-folded spelling."""
    from .ingest.concepts import label_key

    out = dict(aliases)
    for key, pairs in aliases.items():
        folded = label_key(key)
        if folded != key:
            out[folded] = out.get(folded, []) + [pair for pair in pairs if pair not in out.get(folded, [])]
    return out


def keyed(items: list[dict], lab: str, vendor: str, aliases: dict, learned: dict | None = None,
          categories: dict[str, list[str]] | None = None) -> list[dict]:
    """Items with ``keys``: the requirement keys their analytes stand for,
    and ``parameter_keys``, the same per parameter (aligned with
    ``parameters``; a heading or note row stands for nothing).  Per analyte,
    the first of these that decides:

    1. a heading or note field (:func:`.testplan_aliases.is_note`): nothing,
       unless it is all the item reports;
    2. the curated table (:mod:`.testplan_aliases`): a concept, a cross-lab
       ``x:`` key, a whole examination's keys, or the lab's own key;
    3. a specific-IgE test by its allergen code or molecule
       (:func:`.testplan_aliases.allergen_key`), the same key at every lab;
    4. a whole examination by name (``WHOLE_TESTS``);
    5. what this parameter id meant in the person's synced results;
    6. its name (:func:`resolve`), with the specimen of the lab's smallest
       item carrying it: «глюкоза» in a package is urine glucose when a
       urinalysis is the smallest item that lists it;
    7. when that smallest item reports nothing else, the item's own name;
    8. ``"<lab>:<parameter id>"``.

    A parameter id gets the same keys in every item that lists it, and a
    key the record derives from another (creatinine's eGFR,
    :data:`.testplan_aliases.IMPLIED`) comes with it.  One exception: in an
    item collected over 24 hours (:func:`_daily_urine`) a spot-urine concept
    becomes ``"<lab>:24h:<parameter id>"``, so a 24-hour glucose never covers
    the urinalysis's.  The lab's search synonyms are not names: «CRP» is a
    synonym of a skin genetics panel, «еозинофіли» of eosinophil cationic
    protein.  Fee ids get the lab's prefix unless they carry it already, so
    two labs' blood draws are two fees.  ``categories`` is unused (whole
    examinations list their concepts) and kept for callers."""
    from . import testplan_aliases
    from .ingest.concepts import CONCEPT_DEFINITIONS, stable_concept_id
    from .ingest.text import normalized_key

    aliases = _folded(aliases)
    smallest: dict[str, dict] = {}
    for item in items:
        for parameter in item["parameters"]:
            held = smallest.get(parameter["id"])
            if held is None or len(item["parameters"]) < len(held["parameters"]):
                smallest[parameter["id"]] = item

    def analyte(parameter: dict) -> list[str]:
        """Keys for one parameter id, the same in every item that lists it."""
        chosen = testplan_aliases.curated(lab, parameter["id"])
        if chosen is not None:
            return list(chosen) or [f"{lab}:{parameter['id']}"]
        own = smallest[parameter["id"]]
        single = len(own["parameters"]) == 1
        allergen = testplan_aliases.allergen_key(f"{parameter['name']} {own['name']}" if single else parameter["name"])
        if allergen:
            return [allergen]
        whole = WHOLE_TESTS.get(normalized_key(parameter["name"]))
        if whole:
            return list(whole)
        key = (learned or {}).get(f"id:{parameter['id']}") or resolve(
            parameter["name"], own["name"], vendor, aliases, learned)
        if not key and single:
            key = resolve(own["name"], own["name"], vendor, aliases, learned)
        key = key or f"{lab}:{parameter['id']}"
        return [key, *testplan_aliases.IMPLIED.get(key, ())]

    by_id: dict[str, list[str]] = {}
    spot_urine = {stable_concept_id(str(definition["name"])) for definition in CONCEPT_DEFINITIONS
                  if definition["category"] == "urinalysis"}
    out = []
    for item in items:
        daily = _daily_urine(item)
        per_parameter = []
        for parameter in item["parameters"]:
            if testplan_aliases.is_note(normalized_key(parameter["name"])) and len(item["parameters"]) > 1:
                per_parameter.append([])
                continue
            if parameter["id"] not in by_id:
                by_id[parameter["id"]] = analyte(parameter)
            found = by_id[parameter["id"]]
            if daily:
                found = [f"{lab}:24h:{parameter['id']}" if key in spot_urine else key for key in found]
            per_parameter.append(found)
        keys = [key for found in per_parameter for key in found]
        out.append({**item, "lab": lab, "keys": list(dict.fromkeys(keys)), "parameter_keys": per_parameter,
                    "fees": [{**fee, "id": fee["id"] if str(fee["id"]).startswith(f"{lab}:") else f"{lab}:{fee['id']}"}
                             for fee in item["fees"]]})
    return out


# --- the cheapest cover -------------------------------------------------------------

#: Branch-and-bound nodes before the best plan found so far is returned as is.
NODE_LIMIT = 200_000
#: Seconds one search may take, for the same reason: a full check-up asks for
#: over a hundred results and an exact search would run for minutes.
TIME_LIMIT = 0.25


def optimise(items: list[dict], required: set[str], *, forced: list[dict] = (),
             ceiling: float | None = None, node_limit: int = NODE_LIMIT,
             time_limit: float = TIME_LIMIT) -> dict:
    """The cheapest set of items covering every coverable key in ``required``.

    Cost is each item's ``final_price`` plus each distinct fee once.  Exact
    (branch and bound over the scarcest uncovered key, bounded below by the
    dearest single key still to cover) unless ``node_limit`` runs out, when
    ``exact`` is False and the plan is the best one found, never worse than
    the greedy start.  ``time_limit`` seconds end the search the same way.

    ``forced`` items (a panel or genetic test the person chose to include)
    are in the plan whatever they cost: what they report counts as covered
    and their fees as paid, so the search only buys what is still missing.
    Returned items are copies, marked ``forced`` where the person chose them.

    ``ceiling`` is a total already on offer elsewhere (the best single-lab
    plan, when this is the split between labs): branches that cannot beat it
    are pruned from the start, so the search proves quickly whether anything
    cheaper exists.  ``beats_ceiling`` says whether the plan returned does.
    """
    forced = list({(item.get("lab"), item["id"]): item for item in forced}.values())
    forced_ids = {(item.get("lab"), item["id"]) for item in forced}
    forced_fees = {fee["id"]: float(fee["price"]) for item in forced for fee in item["fees"]}
    forced_cover = frozenset(k for item in forced for k in item["keys"]) & required
    forced_cost = sum(float(item["final_price"]) for item in forced) + sum(forced_fees.values())
    open_keys = required - forced_cover
    cands = []
    for item in items:
        if (item.get("lab"), item["id"]) in forced_ids:
            continue
        cover = frozenset(item["keys"]) & open_keys
        if cover:
            cands.append((item, cover, float(item["final_price"]),
                          {fee["id"]: float(fee["price"]) for fee in item["fees"]}))
    # Dominated: another item covers at least as much, costs no more and adds
    # no fee this one does not.  Exact ties keep the earlier item.
    kept = []
    for index, (item, cover, price, fees) in enumerate(cands):
        if not any(o_cover >= cover and o_price <= price and o_fees.keys() <= fees.keys()
                   and (o_cover != cover or o_price < price or len(o_fees) < len(fees) or other < index)
                   for other, (_, o_cover, o_price, o_fees) in enumerate(cands) if other != index):
            kept.append((item, cover, price, fees))
    coverable = frozenset().union(*(cand[1] for cand in kept))
    by_key = {key: [cand for cand in kept if key in cand[1]] for key in coverable}

    def marginal(cand, fees_paid):
        return cand[2] + sum(price for fee, price in cand[3].items() if fee not in fees_paid)

    # Greedy start: the best price per newly covered key, repeatedly.
    chosen, covered, fees_paid, cost = [], frozenset(), set(forced_fees), 0.0
    while covered != coverable:
        cand = min((c for c in kept if c[1] - covered),
                   key=lambda c: (marginal(c, fees_paid) / len(c[1] - covered), -len(c[1] - covered)))
        chosen.append(cand)
        cost += marginal(cand, fees_paid)
        covered |= cand[1]
        fees_paid |= cand[3].keys()
    best = {"cost": cost, "chosen": list(chosen)}
    # Pruning bound: the cheaper of the greedy plan and the outside offer.
    # The plan returned is still a real cover (the greedy one if nothing
    # under the ceiling exists), never the outside offer itself.
    bound_cost = [min(cost, ceiling - forced_cost) if ceiling is not None else cost]
    nodes = 0
    deadline = time.monotonic() + time_limit

    def search(chosen, covered, fees_paid, cost):
        nonlocal nodes
        nodes += 1
        if not nodes & 255 and time.monotonic() > deadline:
            nodes = node_limit + 1
        if nodes > node_limit:
            return
        missing = coverable - covered
        if not missing:
            if cost < bound_cost[0] - 1e-6:
                best.update(cost=cost, chosen=list(chosen))
                bound_cost[0] = cost
            return
        bound = max(min(marginal(c, fees_paid) for c in by_key[key]) for key in missing)
        if cost + bound >= bound_cost[0] - 1e-6:
            return
        key = min(missing, key=lambda k: len(by_key[k]))
        for cand in sorted(by_key[key], key=lambda c: marginal(c, fees_paid) / len(c[1] & missing)):
            chosen.append(cand)
            search(chosen, covered | cand[1], fees_paid | cand[3].keys(), cost + marginal(cand, fees_paid))
            chosen.pop()

    search([], frozenset(), set(forced_fees), 0.0)
    fees: dict[str, dict] = {}
    for item in [*forced, *(cand[0] for cand in best["chosen"])]:
        for fee in item["fees"]:
            fees.setdefault(fee["id"], fee)
    picked = [{**item, "forced": True} for item in forced] + sorted(
        ({**cand[0], "forced": False} for cand in best["chosen"]), key=lambda item: -len(set(item["keys"]) & required))
    fee_total = sum(float(fee["price"]) for fee in fees.values())
    return {
        "items": picked,
        "fees": list(fees.values()),
        "items_cost": round(sum(float(item["final_price"]) for item in picked), 2),
        "fees_cost": round(fee_total, 2),
        "cost": round(best["cost"] + forced_cost, 2),
        "list_cost": round(sum(float(item["price"]) for item in picked) + fee_total, 2),
        "covered": sorted(coverable | forced_cover),
        "missing": sorted(required - coverable - forced_cover),
        "exact": nodes <= node_limit,
        "beats_ceiling": ceiling is None or best["cost"] + forced_cost < ceiling - 1e-6,
    }


#: The labs' own shelves for things that are not one measurable result:
#: genetic testing, and bundles sold as a programme or check-up.
GENETIC_GROUPS = frozenset({
    "Генетичні дослідження",                       # Esculab superGroupName
    "what-to-check/genetic-tests", "disease/genetic-diseases", "panel/karyotyping",  # Synevo rubric/category
})
BUNDLE_GROUPS = frozenset({
    "Пакетні пропозиції", "Спеціальні пропозиції", "Програми з консультацією лікаря",
    "Консультація лікарів", "Обов’язкові профілактичні медичні огляди", "Програми «Оцінка ризиків для здоров'я»",
})
_BUNDLE_PREFIXES = ("check-up/",)
#: A bundle by its own name, even when the lab reports it as one text row
#: (Esculab's «Панель целіакії» has a single result line).
_BUNDLE_NAME = re.compile(r"\s*(панель|пакет|програма|комплекс|check-?up)\b", re.IGNORECASE)


def item_kind(item: dict) -> str:
    """``single`` (one measurable result), ``set`` (several, or a programme)
    or ``genetic``, by the lab's own grouping first and the number of
    analytes second.  The builder's analyte search lists singles only."""
    groups = set(item.get("groups") or ())
    if groups & GENETIC_GROUPS:
        return "genetic"
    if len(item.get("parameters") or ()) > 1 or groups & BUNDLE_GROUPS \
            or any(group.startswith(_BUNDLE_PREFIXES) for group in groups) \
            or _BUNDLE_NAME.match(str(item.get("name") or "")):
        return "set"
    return "single"


# Packages made for children, by name.  No shelf decides it: Synevo's "for
# children" shelf also holds plain ferritin and glucose, and its children's
# check-up shelf the ALEX3 allergy test and the FOX food test, which adults
# take as much.  A paternity or kinship DNA test names a child but is taken
# by adults too.
_CHILD_NAME = re.compile(r"дитяч|у дітей|для дітей|дитин[аиіу]\b|малюк|дитячий садок|в школу|pediatric|infant", re.I)
_NOT_CHILD_ONLY = re.compile(r"батьківств|спорідненост", re.I)
ADULT_AGE = 18


def for_children(item: dict) -> bool:
    """Whether the lab sells this for children only (not offered to an adult)."""
    name = str(item.get("name") or "")
    return bool(_CHILD_NAME.search(name)) and not _NOT_CHILD_ONLY.search(name)


def separately(items: list[dict], required: set[str]) -> float | None:
    """What the same keys cost bought one test at a time (the cheapest
    single-analyte item for each, fees once): the yardstick a panel beats.
    None when some coverable key has no single test of its own."""
    singles: dict[str, dict] = {}
    for item in items:
        if len(item["keys"]) == 1 and item["keys"][0] in required:
            key = item["keys"][0]
            if key not in singles or item["final_price"] < singles[key]["final_price"]:
                singles[key] = item
    covered = set().union(*(set(item["keys"]) for item in items)) & required
    if not covered or set(singles) != covered:
        return None
    fees = {fee["id"]: float(fee["price"]) for item in singles.values() for fee in item["fees"]}
    return round(sum(float(item["final_price"]) for item in singles.values()) + sum(fees.values()), 2)


# --- what the person needs ------------------------------------------------------------

_UK_ALPHABET = "абвгґдеєжзиіїйклмнопрстуфхцчшщьюя"
_UK_ORDER = {letter: index for index, letter in enumerate(_UK_ALPHABET)}
_SETTLEMENT_PREFIX = ("смт.", "смт ", "м.", "с.")


def alphabetical(text: str) -> tuple:
    """A sort key in Ukrainian alphabet order («І» after «И», not before
    «А» as code points put it), Latin and Greek after Cyrillic, and a
    settlement's «м.»/«с.»/«смт.» prefix ignored."""
    text = str(text or "").strip().casefold().replace("'", "").replace("’", "")
    for prefix in _SETTLEMENT_PREFIX:
        if text.startswith(prefix):
            text = text[len(prefix):].lstrip()
            break
    return tuple((0, _UK_ORDER[ch]) if ch in _UK_ORDER else (1, ord(ch)) for ch in text)

#: Results that are flagged often and re-tested rarely: listed, not pre-selected.
OPTIONAL = frozenset({"allergy", "microbiology"})


#: Report types a laboratory issues.  A result only ever read off an
#: ultrasound, an ECG or a cuff is not something a lab test re-measures.
LAB_DOCUMENT_TYPES = ("laboratory", "allergy", "microbiology", "pathology")


def lab_concepts(connection, owner_user_id: str) -> set[str]:
    """Concepts this person has had measured by a laboratory at least once."""
    marks = ",".join("?" * len(LAB_DOCUMENT_TYPES))
    return {row[0] for row in connection.execute(
        f"""SELECT DISTINCT o.concept_id FROM observations o JOIN documents d ON d.id=o.document_id
            WHERE o.owner_user_id=? AND d.clinical_type IN ({marks}) AND o.verification_status<>'rejected'""",
        (owner_user_id, *LAB_DOCUMENT_TYPES))}


def needs(cards: list[dict], from_labs: set[str]) -> list[dict]:
    """The record's laboratory results that ask for a new measurement, and
    why: ``due`` (a cited retest cadence has run out or is about to) and
    ``flagged`` (the latest value is outside its interval).  Only results a
    laboratory reported (``from_labs``): an echo index or a blood pressure is
    not re-measured by ordering a lab test.  Allergen and microbiology results
    are listed but not pre-selected: one raised value is rarely a reason to
    repeat them."""
    from .panels import ATTENTION_INTERPRETATIONS

    out = []
    for card in cards:
        if card.get("is_device") or str(card["id"]) not in from_labs:
            continue
        state = str((card.get("staleness") or {}).get("state") or "")
        reading = str((card.get("verdict") or {}).get("interpretation") or "")
        due = state in {"overdue", "due_soon"}
        flagged = reading in ATTENTION_INTERPRETATIONS or reading in {"critical_low", "critical_high"}
        if due or flagged:
            out.append({"key": str(card["id"]), "card": card, "due": due, "flagged": flagged,
                        "preselected": card.get("category") not in OPTIONAL})
    out.sort(key=lambda need: (not need["preselected"], alphabetical(need["card"].get("name") or "")))
    return out
