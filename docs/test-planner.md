# Test planner (`/plan-tests`)

The person picks what they want measured again; the page finds the cheapest
combination of tests and panels that covers it at the labs whose price lists
we keep, and can file the order on their lab account.

| Piece | Where |
|---|---|
| Matching, optimiser, needs, catalogue cache | `src/anamna/testplan.py` |
| Esculab price list, collection points, web orders | `src/anamna/labsync/esculab_shop.py` |
| Synevo catalogue crawl and cart | `src/anamna/labsync/synevo_shop.py` |
| Page and order/cart routes | `src/anamna/web/testplan_routes.py`, `plan_tests.html`, `plan_tests_done.html` |
| Catalogue cache table | `lab_catalog_cache` (migration 047) |

A lab appears only while the administrator has it switched on at
`/admin/lab-connections`. Prices are public, so planning needs no lab sign-in;
ordering does.

## Catalogues are local

The optimiser never calls a lab. Each lab's whole catalogue is stored in
`lab_catalog_cache` and the plan runs against that copy:

- **Esculab** returns its whole price list for a city in one public request
  (`/api/site/price/get?regionId=`, about 20 MB, 2,650 items), re-read at most
  once a day.
- **Synevo** pages its catalogue ten services at a time, so it is crawled in a
  background thread at no more than one request a second, resumably, about
  once a week. Until the first crawl finishes the page says so and plans
  without Synevo.

Two live calls remain. A shown plan reads Esculab's preparation rules for its
items (`esculab_shop.details`: `info.ua_rules` exists only on the per-good
details endpoint), six in parallel, cached a week per good under
`detail:<id>`. Before an Esculab order is filed, the price list is re-read in
one request (the details endpoint carries no price). If the total moved,
nothing is ordered, the cached list is dropped and the plan is rebuilt from
today's prices.

## What "needs" means

From the record's metric cards: laboratory results whose cited retest
interval has passed or is about to (`staleness` `overdue` / `due_soon`), and
results whose latest value is outside its interval. Device and vital-sign
readings are left out. Allergen IgE and culture results are listed but not
pre-selected. A result no lab sells is still listed, unticked, with a note.
The person can untick anything and search to add more.

## Two modes

A switch under the title chooses the mode; switching starts that mode
fresh (the city and lab are remembered by cookie either way).

**Routine checks** (default) is the needs list above: results out of range
or due again, presets, the "skip recent" switch, one search box.

**Special tests** (`special=1`, `src/anamna/testplan_special.py`) starts from
a question. Five topics (allergy, your DNA, infections and immunity,
long-term conditions, feeling unwell now) each list entries. An entry is a
kind of test, not one lab's item, and stands for requirement keys:

- a key the labs already share (a concept, or a cross-lab `x:` key such as
  `x:ebv-vca-igg`), so the solver chooses among true equivalents;
- `sp:<marker>`, where a marker finds an item by its own name (a genetic
  test, an allergy panel, HIV). `testplan_special.tag` adds the key to every
  matching item's `keys` (never to `parameter_keys`, so it is covered but
  never counted as a result). A broad name is never a marker: «Епштейн-Барр»
  is twelve different tests, so EBV is three shared serology keys instead.

Pressing a topic (`preset=<topic>`) lists its entries (`topic=<topic>` keeps
them listed) and ticks the core ones (`sx=<entry id>`), except a DNA test
already done (germline DNA does not change), an allergy panel whose
allergens the record already holds, and anything measured in the last 14
days. `drop=<topic>` takes the topic and its picks away. The plan covers the
picked entries' keys with the same solver as routine checks, so a two-gene
package beats two single gene tests when it is cheaper. The search box finds
entries in either language and, below them, the labs' own packages and named
tests (the former "Panels and special tests" browser, now only here).

`testplan_routes.special_offers` prices any entries at each lab's default
city from the stored lists only; `/genetics` and `/allergy` use it.

A marker holds for an item when, within its kinds:

- the item's name meets its pattern, or **one of its rows does** (a package
  of the F5 and F2 tests is both; a check-up's HIV row counts whatever kind
  of item holds it);
- **every one of its genes is on the item's gene list and the panel is for
  that purpose** (BRCA and Lynch on inherited-cancer panels; BRCA2 on a
  Fanconi anaemia panel and CFTR on an immunodeficiency panel do not count);
- **its variant is in a description that lists variants** (three rs numbers
  or more: Esculab's «DNA Health» names HFE C282Y and LCT -13910 only
  there; a passing mention in a single test's text never counts);
- **the description states the standard** (GenPlan Baby: «рівень Tier 3
  згідно з рекомендаціями ACMG 2021»).

Gene lists and descriptions come from each lab's own page, read for every
complex item (genetic tests, packages of one row: `complex_item`) in a
background thread and cached a week (`esculab_shop.descriptions`, which
keeps `ua_definition`, `ua_marker`, `ua_general_characteristics` and the
`ua_measurement_range` gene list; `synevo_shop.descriptions`, whose pages
name diseases but no gene list, so Synevo descriptions feed search only).
Variant tests (F5 Leiden, F2, MTHFR, LCT, HLA, UGT1A1) never match by gene:
a carrier screen lists F5 and F2 for rare factor deficiencies.

**Standards** are presets beside the topics: ACMG 2021 carrier screening
Tier 1 (CFTR and SMA carrier tests), Tier 2 and Tier 3 (a panel whose page
states Tier 3; it holds Tier 2 and Tier 1; no lab sells Tier 2 alone), and
the GA²LEN pan-European set of 18 airborne allergens (EAACI's skin test
standard), which ALEX also answers.

## Search

**Find or add a test** (`q`, paged by `qp`) lists measurable results only, one row
per requirement key: the record's laboratory results, and every key a lab
sells as a `single` item (`testplan.item_kind`). A row carries the cheapest
single test per lab. Panels, packages and genetic tests never appear here.

**Lab packages and named tests** (special mode only; the box's text, paged
by `sp`) lists the rest. It can be
narrowed by the lab's own section (`sg=<lab>:<section>`), lab (`slab`), kind
(`skind=genetic|set`), price ceiling (`smax`) and order (`ssort=price`).
Filters alone list nothing: a text or a section is needed. A ticked item
travels as `include=<lab>:<id>`. It is bought at its lab
(`optimise(forced=)`), what it reports counts as covered, its fees are shared,
and another lab's plan says it is not sold there and plans its analytes
without it.

Both boxes use `/metrics`' matcher (`web/search.py`: whole words, case and
script folded, an abbreviation table). On top of that: our concept names in
both languages are searchable through an item's keys, plus the lab's site
synonyms and Russian name (`aka`). Apostrophes are ignored. A Latin
abbreviation printed in Cyrillic lookalikes («МСН») also matches as Latin
(MCH). A short Latin token keeps its "g", so «tTG» is not an answer to "TSH".
When nothing matches, words of five letters or more are corrected to the
nearest word in the catalogue (difflib, 0.8), and the page says so. The sets
box also takes a word found inside a longer one («холестерин» in
«гіперхолестеринемія»), ranked last.

## What each lab says about a test

| | Esculab | Synevo |
|---|---|---|
| Turnaround | `duritionDay` (`durationMin` for express tests) -> `days`, `minutes` | `readyAfter` -> `days` |
| Sample | `configs[0].materials[].name` -> `material` | `BioMaterialName` -> `material` |
| Preparation | `info.ua_rules` on the details endpoint, plus `note` and `ua_punkt_restriction` -> `prep` | `PrepRuleText` -> `prep` |
| English | none: Latin only in abbreviations and synonyms | `lang=en` for names, materials, preparation |

Each plan has a "How to prepare" list per lab: every rule once for the visit,
fasting first, then the longest abstention. It is the lab's own text in the
lab's language, labelled as Ukrainian on the English page unless the lab
publishes English.

## Matching an item to the record

Each analyte an item reports becomes a requirement key, tried in this order:

1. **What this lab's name meant in this record.** Synced orders pair the lab's
   rows with the parsed values of the same report (by name, else by the one
   equal value). Esculab's catalogue parameter ids are the `idtest` of its
   result rows, and the names match too.
2. The seeded concept definitions (`concept_for_alias`), with the specimen
   taken from the item's name, so «Глюкоза» in a urinalysis is urine glucose.
3. Aliases learned from imported reports, this lab's first.
4. For a one-analyte item, its own name and the lab's synonyms.
5. Otherwise a lab-specific key `"<lab>:<parameter id>"`.

Whole examinations reported as one text block (`WHOLE_TESTS`: Esculab's
«Копрограма», «Мікроскопія сечі») cover every concept of their category.

## The optimiser

Weighted set cover with shared fees. Cost is each item's price after the lab's
running discount, plus each distinct fee (Esculab's `takes`: sample
collection) once per order. A plan is an *irredundant* cover: every item is the
only one in the plan covering some need, so a single test is never bought next
to a panel that already measures it.

`testplan_value.py` solves it exactly as a mixed-integer program with HiGHS
(`highspy`): a binary per item, a variable per fee paid, per result reported,
and per item "owning" a need (the only item covering it), which is what keeps
the cover irredundant. Needs covered by the same items are merged, and so are
results reported by the same items, before the program is built. It is solved
one objective at a time, each later solve holding the earlier ones at their
optimum:

- **Cheapest**: lowest cost, then most value at that cost, then fewest
  duplicates (extra copies of a result reported by more than one item).
- **Alternatives**: the most valuable plan within +25 % of the cheapest, and
  the most valuable plan under caps spaced evenly below that bound, each made
  as cheap as its value allows; every one is worth strictly more than every
  cheaper one.
- **Most complete**: no budget and no price cap. Most value net of
  duplicates (each extra copy of a result counts against the results the plan
  adds, so a package earns its place only by bringing more new results than
  it repeats), then lowest cost, then fewest duplicates. `complete_options`
  adds cheaper frontier plans stepping down to the cheapest, for the person to
  switch between. Counted without the duplicates, the top plan at Esculab was
  85,320 UAH with 124 results measured twice and took 17 s to prove.

Value counts each result beyond the needs once, and twice when the record
already tracks it. Independent solves run side by side in threads. Each call
runs to a proven optimum; `TIME_LIMIT` (120 s) is only a runaway guard, after
which a solve returns its best plan with `exact` false and the page says so. On a
79-need check-up the cheapest plan is exact in about 0.3 s, the alternatives
in 1-2 s and the most complete plan with its options in 0.5-1.5 s. Tested against brute force
in `tests/python/test_testplan_value.py`.

Each lab gets its own plan; when splitting between labs is cheaper, that plan
is shown too, with a note that it means two visits and two collection fees.

## Esculab orders

`POST /api/customers/referral/create`, as the app's checkout sends it (see
`esculab_shop.py` for the body). Observed rules:

- the discount is whole hryvnias, rounded down (365 at 10% gives 36);
- each collection fee is its own service line (`confId` 0, no discount);
- items flagged `notsale` have no basket button in the app and are not offered.

The order lands on the person's account unpaid. "Online" asks Esculab for its
LiqPay link and shows it; "at the point" leaves payment to the visit. The
collection point defaults to the one on the person's latest web order.

## Synevo cart

`api/cart/add-item` with the person's stored session cookie puts the items in
their Synevo cart; they finish on synevo.ua. See `synevo_shop.py`.
