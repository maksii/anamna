# Device, calculation and panel connection audit — 2026-11-15

Second-round corrections and current qualification are recorded in
[the adversarial re-audit](metric-connection-audit-round2-2026-11-15.md).
In particular, automatic indirect-bilirubin subtraction was withdrawn and
source-unit, citation, sample-identity and provenance assumptions were corrected.
The counts below describe the first-round checkpoint.

The audit reviewed imports, concept aliases, units, specimen/method distinctions,
calculations, panels, body-system navigation, laboratory ordering, caches and
exports. A consistent online snapshot was taken from the hosted development
sandbox at the owner's request. All changes to records were exercised on a
local working copy; the hosted database was not rewritten.

This report contains public catalogue information and aggregate evidence only.
Private source text, measurements and identifiers remain under ignored `work/`.
Tests and browser verification use synthetic measurements.

## Corpus evidence

| Check | Before | After |
| --- | ---: | ---: |
| Documents | 300 | 300 |
| Observations | 3,102 | 3,124 |
| Active observations classified as unmapped | 79 | 0 |
| Device-day rows | 184,630 | 184,643 |
| Distinct device metrics | 75 | 75 |
| Observed device metrics without a panel/twin connection | 0 | 0 |
| Calculated device BMI rows | 0 | 13 |
| Foreign-key errors | 0 | 0 |

The 79 observations represented 76 legacy labels. They now resolve to 74 public
targets: 73 newly defined concepts and the existing breath-hydrogen concept.
Equivalent labels were joined; distinct assays, fractions, specimens and score
models were kept apart. Catalogue facts and a blood-count comment are included
in that concept count; they are not all quantitative tests.

The working-copy refresh added these provisional clinical calculations:

| Calculation | Added rows |
| --- | ---: |
| Albumin/globulin ratio | 3 |
| Clinical BMI | 3 |
| Automated differential absolute counts | 7 |
| Indirect bilirubin | 1 |
| Non-HDL cholesterol | 5 |
| Plateletcrit | 3 |
| **Total** | **22** |

Original reported numeric/text values, raw units, observation dates, ownership
and verification states were compared by content fingerprint and remained
unchanged. Original device measurements also remained unchanged. The final
refresh was idempotent: zero additions, updates or removals. SQLite integrity
was `ok`.

The snapshot is `work/db-archive/sandbox-2026-11-15-device-audit.sqlite3`;
the pre-refresh backup is `work/db-archive/device-audit-before-refresh.sqlite3`;
the working copy is `work/device-audit/anamna.sqlite3`. Retention notes are in
the archive README. The aggregate receipt is
`work/device-audit/final-receipt.json`.

## Resolved connections

- Canonical English concept names now participate in alias lookup and database
  seeding. Previously, 229 canonical names did not resolve through that path.
  Eight duplicate definition objects were consolidated without losing aliases.
- Added unambiguous CBC aliases and removed the ambiguous bare "atherogenic
  index" alias. The coefficient, Castelli ratios and logarithmic atherogenic
  index of plasma are different quantities.
- Added serum/plasma amino acids and related metabolites, reticulocyte
  measurements, hormones, coeliac antibodies, infection tests, folate-pathway
  genotypes, coagulation stages and reported score concepts. Every new concept
  has English and Ukrainian naming and sourced guidance.
- Added amino-acid, coeliac, folate-genetics and ovarian-risk panels, plus the
  missing members of existing panels and their body-system links.
- Kept ROMA pre/postmenopausal scores apart, preserved reported HOMA's
  unspecified model, and retained an unspecified H. pylori method where the
  source does not establish one. AMH assay context is retained. Gliadin IgG is
  not substituted for deamidated gliadin IgG.
- Kept reticulocyte percentage, absolute count, reticulocyte index and
  fluorescence fractions separate. Preserved explicit count-unit prefixes.
- Separated lupus-anticoagulant screening time, confirmation time and index;
  kept D-dimer FEU units explicit; distinguished pancreatic from total amylase.
- Imported HealthKit body temperature, linked it to clinical body temperature,
  and kept wrist temperature and temperature deviation separate. Connected
  Garmin fitness age to its panel.
- Added definitions for 13 previously undocumented device quantities, including
  proprietary scores. Manufacturer scores retain their original values and
  methods; no universal target or interchangeable score scale was invented.
- Migrated 28 laboratory provider parameters across 13 newly catalogued
  analytes into canonical planner keys, corrected electrophoresis albumin and
  updated panel/preset/special-test references. Generic order titles no longer
  conceal a more specific parameter such as RET-He or a saliva assay.
- Exported calculation methods, evidence, sources and device dependencies.
  Public `metric_key` and `adapter_key` identifiers are retained; credential
  filtering remains in place.

## Calculation coverage and rules

The laboratory registry supports 29 targets in addition to the existing adult
CKD-EPI 2021 eGFR calculation:

| Family | Supported calculations |
| --- | --- |
| Red cells | MCV, MCH, MCHC, hematocrit from independently reported RBC and MCV |
| Platelets | Plateletcrit from platelet count and MPV |
| Automated white-cell differential | Absolute count or percentage for neutrophils, lymphocytes, monocytes, eosinophils, basophils, immature granulocytes, granulocytes and mixed white cells |
| Reticulocytes | Absolute count, percentage, immature fraction from medium + high fluorescence fractions |
| Chemistry | Non-HDL cholesterol, indirect bilirubin, albumin/globulin ratio, atherogenic coefficient |
| Body measurements | BMI from confirmed same-sample clinical weight and height |

New or changed calculations stay provisional. They require independent,
confirmed, finite, uncensored inputs with explicit compatible units. Inputs
cannot be borrowed across owners, patients, orders, exact observation times,
specimens or sample conditions. Ambiguous duplicate inputs suppress arithmetic.
Calculated results do not feed other equations. Reported results take precedence;
a person's unchanged review decision or correction is retained. Input changes,
deletion or rejection refresh or remove dependent results.

Device BMI follows the selected weight source and an eligible height belonging
to the same patient. It records both dependency values and dates. A future
height is never backdated. Carrying a dated height forward requires adulthood
at both dates; otherwise it must come from the same day. An undated adult
profile-height assumption is explicitly labelled. Exclusions are respected,
including a BMI-only exclusion. The monotonic calculation revision invalidates
device caches even if the source timestamps do not change.

A profile-only weight also supports a separately labelled, provisional BMI
estimate. It uses the available height and has no invented observation date.
It is visible in the profile and on the BMI/body views, and is excluded from
historical charts and trends.

Formula publications and input identities are recorded in the reference library
and the calculation registries. No pre-existing clinical band was changed.

## Evidence that cannot support a calculation

Four weight-days in the copied corpus have no qualifying height evidence.
They remain uncalculated. A current or future height was not silently assigned
to those historical days.

| Candidate | Missing prerequisite or distinction |
| --- | --- |
| RDW-SD/CV, PDW, P-LCR | Cell-volume distributions and analyser definitions; these cannot be reconstructed from a count and mean alone |
| HOMA1/HOMA2 | A reported unspecified index does not establish the model; fasting matched inputs and model identity are required |
| LDL/VLDL estimates | Named equation and its applicability context; reported LDL is not silently replaced by an arbitrarily selected estimator |
| Red-cell folate | Whole-blood versus haemolysate identity and dilution correction |
| QTc | Same-trace preceding RR and suitable rhythm; watch resting or mean ECG heart rate is not a substitute |
| LV mass/index and ejection fraction | Acquisition/geometry method, required cardiac measurements and, for indexation, an established body-surface-area method |
| Organ volumes, gallbladder ejection fraction | Matched dimensions/volumes, anatomical side and timing |
| Vertebral resistive index | End-diastolic velocity |
| INR/Quick index | Laboratory control, ISI and calibration |
| Transferrin saturation | Transferrin or iron-binding capacity, which ferritin cannot replace |
| Urine ACR/PCR | Matched urine quantities; serum measurements and dipstick protein cannot substitute |
| Electrophoresis fractions | Method-specific fraction measurements; chemistry albumin/total protein does not recreate electrophoresis |

These are explicit data/method limitations, not estimates filled with assumed
numbers. This audit qualifies the current code and copied corpus; it does not
claim coverage of future provider schemas or every possible medical model.

## Verification

- Ruff correctness gate and Python compilation passed.
- Full Python suite: 5,427 passed, one skipped. Focused bilingual/profile
  checks were also rerun after the final wording/layout corrections.
- JavaScript suite: 38 passed.
- Source-extraction validator: zero errors; device-import validator: zero
  errors. Both reported SQLite integrity `ok` and no foreign-key violations.
  These source-file validators used the existing local source corpus; the
  hosted database snapshot was audited separately using its retained page text.
- Old/new unit-pattern comparison covered 17,850 retained source lines and
  56,282 test strings: zero unexpected changes. Re-parsing retained text from
  all 300 hosted documents removed no results and added one complete
  reticulocyte parse. That result already existed exactly once in the stored
  record, so no duplicate was inserted.
- Synthetic browser checks used the documented baseline account, English and
  Ukrainian, at 390×844, 375×667, 820×1180 and 1180×820. Calculated BMI,
  laboratory calculation provenance, amino-acid panel and profile estimate
  were visually inspected. No horizontal page overflow was observed.
- Nothing was committed, pushed or deployed. Hosted patient records were not
  rewritten.
