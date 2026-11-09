# What the lab catalogues can give the record

Report for the owner, 2026-11-08. Sources studied:

- Esculab: `work/esculab-apk/live/price-3201.json` (Lviv price list, 123 groups,
  2,649 goods), `punkts.json` (230 collection points), `regions.json`.
- Synevo: `work/synevo-shop/` captures (service details `d_*.json`,
  `locations.json`, offers) and the crawl state (`state.json`, 1,485 services),
  plus the cached catalogue in `lab_catalog_cache`.
- Cross-referenced against the development record (577 concepts a laboratory has
  reported) through the planner's own matching (`testplan.keyed`, the
  memoised copy in `testplan_routes`). Read-only; nothing was written.

## What the data actually holds

| Field | Esculab | Synevo |
|---|---|---|
| Price, today's discount | every good (`price`, `discount`); `notdisc` on 1,606 | `BasePrice` plus the monthly offer |
| Description of the test | `info.ua_definition` on 1,405 goods, median about 2,000 characters, Ukrainian (845 also Russian) | `Descr`, `Details`, `ForWhom` per service, Ukrainian |
| When to test | `info.ua_when` on **18** goods only | `ForWhom` on most services |
| Deviations, lab intervals | `info.ua_deviation` on **3** goods ("Дорослі: < 5 мг/л" for CRP) | `InterpretationInc` flag, no text |
| Preparation | almost none in `info`; operational notes in `note` on 341 goods (weekdays, "the doctor takes the sample", which bottle) | `PrepRuleDescr` / `PrepRuleText` per service (fasting, medication, dental work before saliva) |
| Turnaround | `duritionDay` on every good (461 one day, 389 two days, 255 seven days) | `readyAfter` in days per service |
| Sampling days | `opt`: `nosun` (2,682 incl. fees), `nosat` (1,075) | not seen |
| Home sampling | `opt: home_take` on 1,251 goods | per city `nurseAvailible` (28 of 164 cities, Lviv included); per service `MaterialTakingRules.AtHome` |
| Specimen, tube | `configs[].materials`, `tubes[].color` | `BioMaterialName`, `TransportationRules` |
| Collection points | 230, 195 with coordinates, opening and sampling hours, `opt` such as `child1year` (175), `urogenital` (146) | cities only in the captures |

Two things the cached copies throw away: Esculab's `item()` keeps neither
`duritionDay`, `note` nor `opt` beyond sex and `notsale`, and the Synevo crawl
fetches every service's details (1,485 requests) but stores only name,
specimen, price and components. Every Synevo idea below needs the crawl to
keep more of what it already downloads; no extra requests to Synevo.

## Rule 8 in one paragraph

A lab's text is the lab speaking about its own service. It is authoritative
for **how that lab handles the sample** (fasting it requires, days it takes
samples, which bottle, how long it takes, whether it comes to your home) and
may be shown as exactly that: attributed ("Esculab asks..."), dated, linked to
the lab's page. It is **not** an official reference source: its descriptions
and the three `ua_deviation` intervals must never enter
`data/reference_library.json`, never judge a value through `evaluate()`, and
never stand in for the cited "what it measures" text. Its descriptions are
also Ukrainian only, so an English page could show them only as a quoted
Ukrainian original, which rule 4 makes awkward.

## Ranked improvements

### 1. Fix the matching before anything trusts "not sold" (prerequisite)

- **Data:** the keyed catalogues themselves.
- **Evidence:** of 577 lab concepts in the record, 214 are matched to a sold
  item at either lab, 363 are not. 296 of those are allergen components and 44
  microbiology results, but real, common tests are among the misses: thyroid
  peroxidase antibodies and thyroglobulin antibodies are sold by both labs
  («Антитіла до тиреоїдної пероксидази (АТ до ТПО, Anti-TPO)» 383 UAH;
  «Пероксидаза щитоподібної залози, антитіла (АТПО)» 450 UAH) yet keyed as
  `esculab:5` and `synevo:1001`. Synevo's «Т4 вільний» stays `synevo:1005` in
  its thyroid panels. Unresolved analyte keys: Esculab 4,229 of 14,314 (30%),
  Synevo 2,359 of 3,432 (69%), Synevo's panel components being the weak part.
- **Page:** none new. It decides what the planner and the new "Measure this
  again" box on `/metrics/<id>` can show: today the box is missing on the TPO
  and thyroglobulin antibody pages although both labs sell the test.
- **Gain:** correct plans and correct prices for the results people repeat
  most (thyroid, CBC components).
- **Effort:** medium. Aliases for the missed names in the seeded concept
  definitions, plus a report listing unresolved keys whose name looks like a
  record concept, to drive the next round. Owned by `testplan.py` /
  concept definitions.
- **Risk:** a loose match is worse than none (a urine glucose priced as blood
  glucose). Add names one by one with the item that proves them, as the
  `UNIT_PATTERN` rule does.

### 2. Preparation and sampling rules with the plan

- **Data:** Synevo `PrepRuleText`, `Remarks`; Esculab `note` (341 goods) and
  the `nosat` / `nosun` flags, `ua_punkt_restriction` (5 goods, weekdays only).
- **Page:** each item of a plan on `/plan-tests`, the order confirmation page,
  and the new box on a result's page: "Before you go: fasting 8 to 12 hours"
  or "Not taken on Saturdays" or "Only Monday to Thursday" (ImuPro).
- **Gain:** the plan stops being only a price. A wasted visit (ate breakfast
  before lipids, came on a Saturday for an ImuPro test, needed a special
  bottle the point does not have) costs more than the discount saved. The app
  has no preparation guidance at all today (no fasting string in the catalog).
- **Effort:** medium. Keep the fields in both caches, sanitise the lab's HTML
  to plain text, show it attributed and dated. Flags (`nosat`, `nosun`) are
  structured and easy; free text is the lab's own words.
- **Risks:** Ukrainian-only text on an English page (show it quoted, labelled
  as the lab's text in Ukrainian); stale text (re-read with the catalogue);
  never phrase it as medical advice of ours.

### 3. Turnaround: when the result will be ready

- **Data:** Esculab `duritionDay` (every good), Synevo `readyAfter`.
- **Page:** plan items and the plan total ("results within 2 days; the slowest
  item takes 7"), the new box, and the dashboard's "due" list ("ready about 1
  day after the visit").
- **Gain:** someone due a test before a doctor's appointment can pick the lab
  or panel that is back in time. Evidence: within the Lviv list, 461 goods
  report in one day and 255 take seven, so the choice is real.
- **Effort:** small. One field per item, already in the raw replies.
- **Risk:** whether "days" are calendar or working days is not stated by
  either lab; say "about N days, as the lab states".

### 4. Home sampling

- **Data:** Esculab `home_take` on 1,251 goods; Synevo `nurseAvailible` per
  city and `MaterialTakingRules.AtHome` per service.
- **Evidence:** 194 of the record's 577 lab concepts have an Esculab item that
  can be taken at home; Synevo's nurse visits are offered in Lviv.
- **Page:** a planner filter "can be taken at home" and a line on plan items.
- **Gain:** for someone ill, with a child, or caring for a parent, whether the
  plan can be done at home matters more than 50 UAH.
- **Effort:** small for the flag, medium if the plan must be optimised for
  home-only.
- **Risks:** neither catalogue carries the home-visit fee, so the total would
  be wrong; show "home visit fee not included, ask the lab" rather than a
  number. Availability can be per point, not per city.

### 5. "Repeat this report" from a past document

- **Data:** the record's own lab documents plus the planner.
- **Evidence:** 55 laboratory documents in the record have 38 distinct sets of
  analytes; 13 sets were done more than once. The person repeats the same
  bundles.
- **Page:** a link on a lab document's page and on `/plan-tests`: "Plan the
  same tests as on <date>" (the query string the planner already takes, with
  every concept of that document). The optimiser then finds the cheapest
  equivalent today, panel or singles, at either lab.
- **Gain:** one tap to re-order a checkup without picking 30 analytes.
- **Effort:** small (a link that builds `need=` from the document).
- **Risk:** I tried to measure the saving on the four Esculab web orders and
  it is not measurable yet: a past order's panel no longer in the list (Пакет
  № 280) and whole-examination expansion (a urinalysis counts as 55 concepts)
  make the comparison meaningless. Do not advertise a saving until item 1 is
  done.

### 6. Collection points that can do this sample

- **Data:** Esculab points with coordinates (195 of 230), hours, sampling
  hours (`zWork`), capability flags (`urogenital` 146, `child1year` 175).
- **Page:** the Esculab order form's point picker: show hours and hide points
  that cannot take the chosen sample (urogenital swab, a child under one).
- **Gain:** fewer orders filed to a point that turns the person away.
- **Effort:** small for filtering and hours.
- **"Nearest point":** low value and a privacy cost. The record holds no
  address, and asking the browser for location to rank 48 Lviv points saves
  little; the person knows their neighbourhood. Sorting by address text is
  enough.

### 7. Price memory and the monthly offers

- **Data:** each catalogue refresh overwrites the previous copy; Synevo's
  "пропозиція місяця" offers change monthly, Esculab discounts move too.
- **Page:** a due test on the dashboard could say "on offer this month at
  Synevo".
- **Gain:** modest; the planner already picks the cheapest today.
- **Effort:** medium (keep a small price history table).
- **Risk:** nudging people to test because it is discounted is not a medical
  reason; show it only for tests that are already due.

### 8. Explaining unexplained analytes (low value now)

- **Evidence:** only 9 of the 577 lab concepts lack a description in
  `concept_guidance`: eight urine crystal types and one "Еритроцити, стан".
  None of them has an Esculab single test with a definition (they come from
  the urinalysis microscopy block). The lab descriptions do not close the gap
  that exists.
- **Use allowed:** as a curator's drafting aid to find the right official
  source, never as the shown explanation (rule 8).

### 9. Flagging record analytes no lab sells (do not build yet)

- **Evidence:** today it would flag 363 of 577 analytes, most of them wrongly
  (item 1). After matching is fixed, what remains is legitimately useful:
  results that were point-of-care rapid tests (`hiv-i-ii-rapid-test`,
  `hepatitis-c-antibody-rapid-test`) and manual differential cells
  (`myelocytes`, `promyelocytes`) that no lab sells as a test because they come
  out of another one. The useful message is "comes with <parent test>", which
  needs a mapping, not a "not sold" badge.

### Not recommended

- Using `ua_deviation` intervals (3 goods) or descriptions as reference text:
  rule 8.
- Region and lab-site lists (`labs` per good: which city's lab performs it):
  no person-facing question they answer.
