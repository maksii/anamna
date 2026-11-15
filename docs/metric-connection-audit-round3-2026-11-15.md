# Metric connection audit — third round, 2026-11-15

This round challenges the earlier audits' denominators. A mapped aggregate key does not prove that every raw field was imported; matching a maker and date does not prove duplicate acquisition; a successful parser run does not prove that every source result was captured. Earlier reports are checkpoints, superseded where this report records a correction.

All health-data work uses the disposable sandbox copy under ignored `work/metric-audit-round3/`. The immutable pre-refresh online backup is `work/db-archive/metric-audit-round3-before-refresh.sqlite3`. Hosted data is not changed. Private source evidence, identifiers and quantities stay in ignored artifacts; tests use synthetic records.

## Independent directions and evidence

| Direction | Previously insufficient proof | New evidence and correction |
| --- | --- | --- |
| Original documents | Local availability and retained parser text did not cover every original | All 300 originals independently hash checked: 192 initially fetched, 12 local substitutes replaced with exact sandbox originals, 96 matching local files. The 12 substitutes differ visibly/layout-wise, but exact replacements preserve parsed rows/references/notes. 202 PDFs / 398 PDF pages, 96 images, 2 JSON records; 496 stored pages and 308 report scopes. All 396 native-word pages match retained native text, with zero read failures. |
| OCR omissions | Re-running cached text could not expose source words that OCR missed | Fresh local OCR of all 96 images: 92 nonempty, four still unreadable, zero execution errors. Three additional quantities independently corroborated in three OCR modes, with normalized source boxes. One further quantity remains ambiguous and enters source review without an invented value. |
| Parser identity | Numeric/name-only deduplication could discard limits, times and qualifiers | Identity now retains comparator, exact acquisition time, text, unit and sample context. Numbered assay labels, English qualitative rows, bilateral BI-RADS and breast heading boundaries have focused synthetic regressions. |
| Raw devices | The existing 75 aggregate keys did not inventory their originating raw types | All 30 observed OpenWearables series / 7,467,033 retained raw samples checked, with zero unhandled series. The earlier 29-series count was an inventory error. Average MET aliases the existing physical-effort key; weather temperature/humidity get separate environmental keys. Additional raw HRV, oxygen, respiration and recovery ownership is connected through archive recomputation. |
| Apple source grammar | A line-based XML reader silently depended on pretty printing | Streaming XML parser accepts minified and wrapped records. Equivalence receipt covers 5,591,981 items, including 5,588,623 records, 48/48 record types, 300 workouts and 116 events; no unknown type in this retained export. No fabricated HealthKit version or undocumented scale correction. |
| Duration and acquisition | Arbitrary duration caps and overlapping Oura periods could destroy evidence | Removed unsourced duration caps. Identical acquisitions deduplicate; conflicting overlapping acquisitions fail transactionally instead of guessing a total or deleting unrelated valid measurements. |
| FIT versus JSON | Comparing calendar days hid distinct captures within the same day; an earlier validator guessed that absent captures had been deleted by a person | Official Garmin FIT SDK decodes 46 valid scale captures: 43 exact-UTC JSON matches, one additional accepted capture containing six standard quantities, two outside existing product bounds retained in diagnostics. No deletion intent is inferred. Three undocumented FIT fields remain uninterpreted, each present in 46 records. Same-device exclusions also govern the FIT source and BMI dependency paths. |
| Provider result context | Stored normalized orders lost explicit material, section and method notes | Audited 170 orders / 1,423 normalized rows. Preserve literal source section/method metadata, consistent writer/reread specimen identity, scientific notation, zero, comparator/text updates, valid dates and identifier zero. |
| Lab/PDF comparisons | Equal values and approximate labels could count as corroboration | Require result identity, unit, comparator, material and explicit method evidence. Unknown distinct labels and text with incompatible units cannot suppress an independent result. 77 independent comparisons, 1,273 matches, five missing, 41 extras; zero value/unit/name mismatches. Four missing rows are distinct explicit-method results across two orders; the fifth is already represented semantically. The other 93 orders lack independent comparison evidence. |
| Test ordering | A shared parameter ID could inherit one carrier's specimen or depend on catalog order | Audited 3,303 catalog items / 3,085 parameter IDs. Resolve conflicting equal-smallest carriers per item, including unspecified versus known material. Four owner/provider contexts and 6,606 item contexts agree in forward/reverse order; removed 14 false blood-count coverage claims from incompatible items. |
| Aliases and graph | Similar script/code, unknown method or specimen could imply the wrong quantity | Cyrillic BMI versus Latin arterial IMT is explicit; ambiguous mixed scripts and contradictory bracket codes refuse guesses. Contextual English aliases retain material. Cell-per-volume units alone cannot establish a strip method. Bare eGFR no longer claims CKD-EPI 2021; reported method wording remains in source context. |
| Panels and areas | Unpanelled imaging was omitted; collection membership looked like required testing | Added 12 collections covering imaging, EEG, radiation exposure, tumour markers and weather; 46 panels overall. Imaging/context collections do not imply a routine schedule or required missing tests. Radiation has a neutral imaging area. |
| Arithmetic | A preferred unit, inferred specimen or unchecked owner pointer was treated as an input fact | Calculations require explicit compatible source units and matching owner/patient/document/report. Preserve ambiguity, censored/text competitors, exact timed/specimen draws, complete dates and demographics at sample time. Exact cell-count, hematocrit/plateletcrit and creatinine unit conversions are tested. |
| eGFR applicability | Reading verification was conflated with assay/equation suitability | No reconstruction during a recorded pregnancy window. Reported eGFR is retained without staging or a normal verdict then. Generic reported eGFR prevents duplicate same-sample reconstruction. Standardized creatinine calibration and stable renal function are limitations, not facts established by checking a number. |
| Mutation and preferences | Zero-only series disappeared; pending rebuilds appeared complete; warm caches could hide edits | Keep legitimate zero, honor explicit valid-zero source preference, leave failed rebuilds pending with a visible warning, restore exclusions through retained sources, and avoid resurrecting superseded exports. Monotonic device and clinical-context revisions invalidate same-timestamp mutations. |
| Patient and presentation | Owner-scoped data could mix identities; date-only merging discarded source detail | Primary-patient device selection is explicit across cards, twins, correlation choices, details and UI exports. Independent home report acquisitions remain beside daily aggregates. Exact limits remain in history but are excluded from exact charts, changes and correlations. Specimen/isolate/laterality/method context remains visible. |
| Non-scalar source coverage | An image with no recognized organ/text vanished from first-class findings | Preserve an extracted imaging source-review entry without inventing date, organ or diagnosis. Any human ruling on that document prevents an extra unknown-area fallback. Machine review notes cannot become diagnosis candidates. English negation “No” survives OCR margin cleanup; retained-corpus replay finds zero changed clinical summaries from this guard. |

## Source-confirmed additions and deliberate uncertainty

Three document quantities are safe to append as **extracted/provisional**, never automatically verified: breast BI-RADS category, breast subcutaneous fat thickness and urine pH. The fat quantity has no assigned side and explicitly records that laterality could not be established. A separate specific-gravity OCR candidate remains a source review task; no uncertain number is added.

Four lab API method rows are independently preserved through the normal source writer: urine leukocyte and erythrocyte dipstick results in two orders. Explicit source method notes justify the distinction; the unit alone does not. Original PDF/order linkage and original reported clinical values are preserved.

Garmin's retained `weight.rawImpedance` field has undocumented unit/calibration. It remains in the original export, with an import diagnostic. It is not relabelled as ohms or manufactured into a clinical measurement. An older inspected subset has 39 occurrences (38 positive, one zero); the active latest export has 43 occurrences, all positive. Those are different source cohorts, not interchangeable counts.

Fresh OCR is **not** bulk-substituted: it loses 50 retained parse shapes while recovering four shapes. Four image sources remain unreadable. These limits and the explicit review candidate prevent a universal claim that no source value can remain unread.

The latest active Apple and Oura original exports were also fetched from the sandbox and matched against their importer fingerprints, then normally reimported twice. This closes the earlier local-file availability gap. The latest Apple export contains 5,605,538 raw items / 48 handled record types; its denominator differs from the older export used for the XML-equivalence proof. Oura covers 61 files / 1,467,678 rows, with zero unsupported populated files or unexpected columns in this retained source.

## Qualification artifacts

Ignored, private evidence retained for review:

- `work/round3-parser/FINAL_RECEIPT.json`: original inventory, full report comparison, fresh OCR denominator, source candidates and limitations.
- `work/round3-raw-devices/apple-xml-equivalence.json`: XML traversal equivalence.
- `work/round3-raw-devices/copied-db-device-refresh.json`: normal-writer device refresh and repeatability.
- `work/metric-audit-round3/qualification.json`: original-row preservation, semantic repair/recalculation idempotence and runtime linkage.
- `work/metric-audit-round3/source-validation.json`: source/extraction invariants; automated passing does not confer clinical verification.

## Final copied-record qualification

| Measure | Result |
| --- | --- |
| Original reported observation rows | All 3,094 retained; full-column comparison changes only two concept pointers, with all other original fields identical |
| Source-confirmed new observation rows | Seven, all provisional; repeat backfill adds zero |
| Active observations / all observations | 3,126 / 3,133 (seven previously rejected rows retained) |
| Documents / pages / report scopes after the two retained API sources | 302 / 498 / 310 |
| Clinical findings | 163, including one newly represented image source; original human rulings preserved |
| Device rows / metric keys | 193,155 / 77, versus 184,643 / 75 before this round: +8,512 net rows |
| Runtime primary-profile concept coverage | 1,117 owner/concept pairs: 1,114 visible and linked to panel/area; three intentionally suppressed pairs remain accounted for |
| Normal repair / calculation repeat | Zero semantic repairs and zero derived additions/updates/removals; complete finding rows unchanged on repeat (the sync function still executes upserts) |
| Source validator | Zero errors; 53 warnings retained explicitly; passing grants no human verification |
| Device validator | Zero errors; integrity OK; no foreign-key violations |
| Authenticated routes | 2,656 requests, evenly split EN/UK, zero failures across recorded metric/detail/source-comparison and panel routes |
| Final source serving | All 302 authenticated source responses match their original SHA256; 24 further final-state representative EN/UK routes pass |

All 158 original verified/corrected/rejected findings are identical in every column. The new unknown-image review task remains open; an audit-created parallel task beside an already corrected finding was withdrawn after the human-rule guard was added. Earlier resolved review history is preserved.

Device changes comprise 8,516 added rows, four removed rows and 922 updated existing rows. Three removals are stale UTC flight-summary days whose archived samples belong to already represented local dates; the other is an unsupported centimetre-magnitude correction. Device refresh repeats preserve exact normalized content, IDs and provenance. All 7,467,033 retained OpenWearables samples pass quantity/unit/numeric checks for the 30 observed series. No normalized percentage lies outside 0–100 in this copied corpus. Unknown source fields, invalid captures and inaccessible source interpretation are counted separately instead of being silently normalized.

Responsive synthetic browser verification covers 390×844, 375×667, 820×1180 and 1180×820 in both languages. Weather zero, imaging collections, censored history and the retained-impedance diagnostic were inspected; no horizontal page overflow was observed. Bilingual source-review/side/method notices also have focused regressions. The synthetic UI database and test scratch are removed after verification.

The diagnosis-page test fixture had a genuine race: its real background/GET collector deleted manually seeded candidates with no source findings. Disabling workers alone reproduced it deterministically. The page fixture now stubs the separately tested collector and disables workers; collector/job suites still exercise real behavior.

Final gates on the completed source tree:

- Python: **5,846 passed, one skipped** (`work/metric-audit-round3/accepted-pytest.log`).
- JavaScript: **38 passed**, zero failures (`js-final.log`).
- Ruff 0.17.5, compileall, lock consistency and diff whitespace checks passed.
- Standard copied-source validator: **zero errors**, 53 explicit warnings; local source validator also passes with zero errors.
- Standard device validator: **zero errors**, source-linked Kardia event, integrity OK and zero foreign-key violations.
- Normal source backfills repeated: zero extra observations, documents or review tasks; four independent method rows remain provisional.
- All 300 original document paths are unchanged. The copied source tree resolves every original through the normal resolver; the two newly created API JSON documents were relocated within that private tree with unchanged hashes.
- Baseline archive preserved. Original clinical observation fields and all 158 human-ruled findings retain the preservation proof above.
- Synthetic UI and owned test scratch removed; source/audit artifacts remain ignored and retained with cleanup notes. Local account inventory remains the two documented accounts.

At the audit checkpoint, no commit, push, deployment or hosted-database rewrite had been performed. Subsequent publication of the code and this report does not publish the private working copy or apply its backfills to the hosted database.

## Public method sources

- [OpenWearables series schema](https://github.com/the-momentum/open-wearables/blob/main/backend/app/schemas/enums/series_types.py): raw type vocabulary and average-MET alias.
- [OpenWearables nap classification](https://openwearables.io/blog/open-wearables-0-6-3-nap-detection-http-logs-middleware): source classification, not independent evidence of sensor accuracy.
- [Garmin official Python FIT SDK](https://github.com/garmin/fit-python-sdk): CRC validation, standard message fields and units; dependency pinned at 21.221.0.
- [NICE NG3, recommendation 1.3.30](https://www.nice.org.uk/guidance/ng3/chapter/Recommendations): eGFR pregnancy exclusion.
- [NIDDK clinical measurements and eGFR accuracy](https://www.niddk.nih.gov/research-funding/research-programs/kidney-clinical-research-epidemiology/laboratory/factors-affecting-egfr-accuracy/clinical-measurements): measurement standardization and clinical limitations.
- [ASE/EACVI chamber quantification](https://www.asecho.org/wp-content/uploads/2025/04/2015_ChamberQuantificationREV.pdf), [ACR ultrasound examination requirements](https://accreditationsupport.acr.org/support/solutions/articles/11000062867-exam-requirements-general-ultrasound-revised-9-19-2025-), [NCI tumour marker list](https://www.cancer.gov/about-cancer/diagnosis-staging/diagnosis/tumor-markers-list): collection vocabulary, without inventing required testing schedules.

Patient-facing guidance is recorded in `data/reference_library.json`, including provenance and both language catalogs. The conclusions concern this finite retained corpus and the exercised mutation paths; absent upstream payloads, unreadable sources and unmeasured external-device semantics are not silently counted as verified coverage.
