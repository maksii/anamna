# Metric connection audit — third round, 2026-11-15

This round challenges the earlier audits' denominators. A mapped aggregate key does not prove that every raw field was imported; matching a maker and date does not prove duplicate acquisition; a successful parser run does not prove that every source result was captured. Earlier reports are checkpoints, superseded where this report records a correction.

All health-data work uses the disposable sandbox copy under ignored `work/metric-audit-round3/`. The immutable pre-refresh online backup is `work/db-archive/metric-audit-round3-before-refresh.sqlite3`. Hosted data is not changed. Private source evidence, identifiers and quantities stay in ignored artifacts; tests use synthetic records.

## Independent directions and evidence

| Direction | Previously insufficient proof | New evidence and correction |
| --- | --- | --- |
| Original documents | Local availability and retained parser text did not cover every original | Every original independently hash checked; local substitutes were replaced with exact sandbox originals. The substitutes differ visibly/layout-wise, but exact replacements preserve parsed rows/references/notes. Every native-word page matches retained native text, with zero read failures. |
| OCR omissions | Re-running cached text could not expose source words that OCR missed | Fresh local OCR of every image source, with zero execution errors; some images remain unreadable. An additional quantity is accepted only when independently corroborated in three OCR modes, with normalized source boxes. An ambiguous quantity enters source review without an invented value. |
| Parser identity | Numeric/name-only deduplication could discard limits, times and qualifiers | Identity now retains comparator, exact acquisition time, text, unit and sample context. Numbered assay labels, English qualitative rows, bilateral BI-RADS and breast heading boundaries have focused synthetic regressions. |
| Raw devices | The existing aggregate keys did not inventory their originating raw types | Every retained raw series and sample checked against the OpenWearables schema, with zero unhandled series. The earlier series count was an inventory error. Average MET aliases the existing physical-effort key; weather temperature/humidity get separate environmental keys. Additional raw HRV, oxygen, respiration and recovery ownership is connected through archive recomputation. |
| Apple source grammar | A line-based XML reader silently depended on pretty printing | Streaming XML parser accepts minified and wrapped records. An equivalence receipt over a retained export covers every item, record type, workout and event, with no unknown type. No fabricated HealthKit version or undocumented scale correction. |
| Duration and acquisition | Arbitrary duration caps and overlapping Oura periods could destroy evidence | The 16-hour heuristic is gone; a sleep interval or daily total above 24 hours is refused as physically impossible. Identical acquisitions deduplicate; a day with conflicting overlapping acquisitions is withheld and reported instead of guessing a total, and the rest of the import proceeds. |
| FIT versus JSON | Comparing calendar days hid distinct captures within the same day; an earlier validator guessed that absent captures had been deleted by a person | A CRC-checking reader decodes the scale captures and matches them to JSON by exact UTC time. A capture absent from the account's JSON cannot be attributed to the person (the scale's archive also holds other users' weigh-ins), so it is counted in diagnostics and never imported. Undocumented FIT fields remain uninterpreted. Same-device exclusions also govern the FIT source and BMI dependency paths. |
| Provider result context | Stored normalized orders lost explicit material, section and method notes | Audited every stored order and normalized row. Preserve literal source section/method metadata, consistent writer/reread specimen identity, scientific notation, zero, comparator/text updates, valid dates and identifier zero. |
| Lab/PDF comparisons | Equal values and approximate labels could count as corroboration | Require result identity, unit, comparator, material and explicit method evidence. Unknown distinct labels and text with incompatible units cannot suppress an independent result. The independent comparisons show zero value/unit/name mismatches. A missing row that is a distinct explicit-method result is preserved; one already represented semantically is not duplicated. Orders without independent comparison evidence are not counted as corroborated. |
| Test ordering | A shared parameter ID could inherit one carrier's specimen or depend on catalog order | Audited 3,303 catalog items / 3,085 parameter IDs. Resolve conflicting equal-smallest carriers per item, including unspecified versus known material. Every owner/provider and item context agrees in forward/reverse order; removed 14 false blood-count coverage claims from incompatible items. |
| Aliases and graph | Similar script/code, unknown method or specimen could imply the wrong quantity | Cyrillic BMI versus Latin arterial IMT is explicit; ambiguous mixed scripts and contradictory bracket codes refuse guesses. Contextual English aliases retain material. A generic cell-per-volume unit alone cannot establish a strip method; the strip's own unit (Leu/µL, Ery/µL) does. Bare eGFR no longer claims CKD-EPI 2021; reported method wording remains in source context. |
| Panels and areas | Unpanelled imaging was omitted; collection membership looked like required testing | Added 12 collections covering imaging, EEG, radiation exposure, tumour markers and weather; 46 panels overall. Imaging/context collections do not imply a routine schedule or required missing tests. Radiation has a neutral imaging area. |
| Arithmetic | A preferred unit, inferred specimen or unchecked owner pointer was treated as an input fact | Calculations require explicit compatible source units and matching owner/patient/document/report. Preserve ambiguity, censored/text competitors, exact timed/specimen draws, complete dates and demographics at sample time. Exact cell-count, hematocrit/plateletcrit and creatinine unit conversions are tested. |
| eGFR applicability | Reading verification was conflated with assay/equation suitability | No reconstruction during a recorded pregnancy window. Reported eGFR is retained without staging or a normal verdict then. Generic reported eGFR prevents duplicate same-sample reconstruction. Standardized creatinine calibration and stable renal function are limitations, not facts established by checking a number. |
| Mutation and preferences | Zero-only series disappeared; pending rebuilds appeared complete; warm caches could hide edits | Keep legitimate zero, honor explicit valid-zero source preference, leave failed rebuilds pending with a visible warning, restore exclusions through retained sources, and avoid resurrecting superseded exports. Monotonic device and clinical-context revisions invalidate same-timestamp mutations. |
| Patient and presentation | Owner-scoped data could mix identities; date-only merging discarded source detail | Primary-patient device selection is explicit across cards, twins, correlation choices, details and UI exports. Independent home report acquisitions remain beside daily aggregates. Exact limits remain in history but are excluded from exact charts, changes and correlations. Specimen/isolate/laterality/method context remains visible. |
| Non-scalar source coverage | An image with no recognized organ/text vanished from first-class findings | Preserve an extracted imaging source-review entry without inventing date, organ or diagnosis. Any human ruling on that document prevents an extra unknown-area fallback. Machine review notes cannot become diagnosis candidates. English negation “No” survives OCR margin cleanup; retained-corpus replay finds zero changed clinical summaries from this guard. |

## Source-confirmed additions and deliberate uncertainty

A document quantity confirmed by fresh OCR is appended only as **extracted/provisional**, never automatically verified. A quantity with no assigned side explicitly records that laterality could not be established. An uncertain OCR candidate remains a source review task; no uncertain number is added.

Lab API rows that differ by method are independently preserved through the normal source writer. Explicit source method notes justify the distinction; the unit alone does not. Original PDF/order linkage and original reported clinical values are preserved.

Garmin's `weight.rawImpedance` field has undocumented unit/calibration. It stays in the original export, with an import diagnostic. It is not relabelled as ohms or manufactured into a clinical measurement.

Fresh OCR is **not** bulk-substituted: it loses more retained parse shapes than it recovers. Some image sources remain unreadable. These limits and the explicit review candidate prevent a universal claim that no source value can remain unread.

The latest active device exports were also fetched from the sandbox and matched against their importer fingerprints, then normally reimported twice. This closes the earlier local-file availability gap. Every record type is handled, with zero unsupported populated files or unexpected columns in the retained sources.

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
| Original reported observation rows | All retained; full-column comparison changes only two concept pointers, with all other original fields identical |
| Source-confirmed new observation rows | All provisional; repeat backfill adds zero |
| Active observations / all observations | Previously rejected rows retained |
| Documents / pages / report scopes after the retained API sources | Consistent; originals unchanged |
| Clinical findings | An image source with no recognized content is newly represented; original human rulings preserved |
| Device rows / metric keys | Two metric keys added; row changes are described below |
| Runtime primary-profile concept coverage | Every owner/concept pair is visible and linked to panel/area, or intentionally suppressed and accounted for |
| Normal repair / calculation repeat | Zero semantic repairs and zero derived additions/updates/removals; complete finding rows unchanged on repeat (the sync function still executes upserts) |
| Source validator | Zero errors; warnings retained explicitly; passing grants no human verification |
| Device validator | Zero errors; integrity OK; no foreign-key violations |
| Authenticated routes | Requests evenly split EN/UK, zero failures across recorded metric/detail/source-comparison and panel routes |
| Final source serving | Every authenticated source response matches its original SHA256; further final-state representative EN/UK routes pass |

All original verified/corrected/rejected findings are identical in every column. The new unknown-image review task remains open; an audit-created parallel task beside an already corrected finding was withdrawn after the human-rule guard was added. Earlier resolved review history is preserved.

Device changes comprise added, removed and updated rows. A removal is either a stale UTC summary day whose archived samples belong to an already represented local date, or an unsupported centimetre-magnitude correction. Device refresh repeats preserve exact normalized content, IDs and provenance. Every retained raw sample passes quantity/unit/numeric checks. No normalized percentage lies outside 0–100 in the audited copy. Unknown source fields, invalid captures and inaccessible source interpretation are counted separately instead of being silently normalized.

Responsive synthetic browser verification covers 390×844, 375×667, 820×1180 and 1180×820 in both languages. Weather zero, imaging collections, censored history and the retained-impedance diagnostic were inspected; no horizontal page overflow was observed. Bilingual source-review/side/method notices also have focused regressions. The synthetic UI database and test scratch are removed after verification.

The diagnosis-page test fixture had a genuine race: its real background/GET collector deleted manually seeded candidates with no source findings. Disabling workers alone reproduced it deterministically. The page fixture now stubs the separately tested collector and disables workers; collector/job suites still exercise real behavior.

Final gates on the completed source tree:

- Python: **5,846 passed, one skipped** (`work/metric-audit-round3/accepted-pytest.log`).
- JavaScript: **38 passed**, zero failures (`js-final.log`).
- Ruff 0.17.5, compileall, lock consistency and diff whitespace checks passed.
- Standard copied-source validator: **zero errors**, explicit warnings retained; local source validator also passes with zero errors.
- Standard device validator: **zero errors**, integrity OK and zero foreign-key violations.
- Normal source backfills repeated: zero extra observations, documents or review tasks; independent method rows remain provisional.
- All original document paths are unchanged. The copied source tree resolves every original through the normal resolver; the newly created API JSON documents were relocated within that private tree with unchanged hashes.
- Baseline archive preserved. Original clinical observation fields and all human-ruled findings retain the preservation proof above.
- Synthetic UI and owned test scratch removed; source/audit artifacts remain ignored and retained with cleanup notes. Local account inventory is unchanged.

At the audit checkpoint, no commit, push, deployment or hosted-database rewrite had been performed. Subsequent publication of the code and this report does not publish the private working copy or apply its backfills to the hosted database.

## Public method sources

- [OpenWearables series schema](https://github.com/the-momentum/open-wearables/blob/main/backend/app/schemas/enums/series_types.py): raw type vocabulary and average-MET alias.
- [OpenWearables nap classification](https://openwearables.io/blog/open-wearables-0-6-3-nap-detection-http-logs-middleware): source classification, not independent evidence of sensor accuracy.
- [Garmin FIT protocol](https://developer.garmin.com/fit/protocol/): file structure, CRC and the weight-scale message. The SDK itself is not a dependency: its licence does not allow redistribution with this application.
- [NICE NG3, recommendation 1.3.30](https://www.nice.org.uk/guidance/ng3/chapter/Recommendations): eGFR pregnancy exclusion.
- [NIDDK clinical measurements and eGFR accuracy](https://www.niddk.nih.gov/research-funding/research-programs/kidney-clinical-research-epidemiology/laboratory/factors-affecting-egfr-accuracy/clinical-measurements): measurement standardization and clinical limitations.
- [ASE/EACVI chamber quantification](https://www.asecho.org/wp-content/uploads/2025/04/2015_ChamberQuantificationREV.pdf), [ACR ultrasound examination requirements](https://accreditationsupport.acr.org/support/solutions/articles/11000062867-exam-requirements-general-ultrasound-revised-9-19-2025-), [NCI tumour marker list](https://www.cancer.gov/about-cancer/diagnosis-staging/diagnosis/tumor-markers-list): collection vocabulary, without inventing required testing schedules.

Patient-facing guidance is recorded in `data/reference_library.json`, including provenance and both language catalogs. The conclusions concern this finite retained corpus and the exercised mutation paths; absent upstream payloads, unreadable sources and unmeasured external-device semantics are not silently counted as verified coverage.
