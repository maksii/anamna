# Second metric-connection audit — 2026-11-15

Further source, raw-device, method-identity and presentation corrections are recorded in [the third-round audit](metric-connection-audit-round3-2026-11-15.md). Treat this report as a checkpoint where those later findings supersede it.

This is an adversarial review of the first audit, including its code, source
attributions, calculation assumptions and copied sandbox results. Six agents
worked independently on laboratory mathematics, device selection, catalog and
ordering identity, published evidence, lifecycle/export behavior, and patient
surfaces. The orchestrator reviewed the changes, ran the full suite and checked
the rendered bilingual interfaces. This report supersedes conflicting claims
in the first-round report; the earlier report remains a historical receipt.

Only public vocabulary and method appear here. All new
regressions and browser records are synthetic. No source record was committed,
and no hosted database was rewritten.

## Confirmed misses and corrections

| Finding | Correction |
| --- | --- |
| Blood equations accepted matching nonblood specimens | Refuse explicitly incompatible specimens, even if both inputs agree with one another |
| Source owner/patient and document/report pointers could disagree | Validate the patient, document, report and report-document identity before calculating |
| Empty sample identifiers, report/document ID collisions and invalid timestamp tails could create a false sample match | Require usable provenance, namespace the identifiers, and validate complete dates/timestamps |
| Input provenance recorded converted numbers but missed equivalent raw edits | Preserve exact raw values, units, dates, sample context and identities; changed evidence resets review |
| Calculated outputs lost specimen and sample condition | Carry their exact input context into the result |
| Calculated total globulin was absent | Add a distinct mass-concentration concept, calculation, liver-panel membership, bilingual explanation and published source |
| Indirect bilirubin subtraction assumed compatible total/direct assays | Disable automatic reconstruction without established assay compatibility; retract the previous provisional output while preserving reported bilirubin |
| Apparent source-unit errors were silently treated as exact aliases | Remove count-to-fraction, percentage-to-INR, duration-to-rate and density-to-relative-density relabeling; preserve the written units and explain incompatible comparisons |
| Old blood concepts lacked the specimen restrictions added to newer concepts | Apply explicit specimen binding to established CBC, serum chemistry and endocrine quantities as well |
| Ukrainian urea wording could be mistaken for urine context | Distinguish analyte names from specimen words |
| Bracketed codes, learned aliases and planner fallbacks could discard specimen or assay qualifiers | Carry qualifiers through all matching paths and retain distinct unresolved quantities when identity is unsupported |
| Equal result numbers could teach unrelated provider parameters the same identity | Require name/identity evidence; conflicting learned mappings no longer use the first row encountered |
| ANA immunoassay, IFT titre and fluorescence pattern shared an ordering requirement | Separate the assay, titre and pattern requirements |
| A celiac preset still used an obsolete IgA requirement | Link the canonical total-IgA requirement |
| Another patient's preferred device could hide the primary patient's value before filtering | Filter patient identity before daily source and sleep-cohort selection |
| Observation deduplication could merge equal numbers across patients, units or sample contexts | Include patient, written unit, comparator, specimen and sample condition in evidence identity; primary-profile series retain their own patient's readings |
| Garmin removal could leave a BMI dependent on a removed weight or a height in another import | Refresh dependent device calculations after partial and full envelope purges |
| Historical summaries could conceal calculated days behind a reported latest result | Retain per-day methods/dependencies and calculated-day counts in monthly/yearly summaries, AI copies and chat |
| Sparse histories dropped years after the first recorded day | Keep full dates across gaps |
| Calculated sources were described as direct physical devices | Label the calculated source explicitly |
| Manual profile weight could not use a confirmed clinical height | Connect confirmed clinical heights with explicit units, identity and source links |
| Profile BMI could reuse future, childhood, unknown-age or conflicting dated heights | Reject unsupported carry-forward; display conflicts, preserve existing manual data on unrelated saves, and state the unchanged-height assumption |
| Human-reviewed calculations were still labelled provisional | Display the retained human verification/correction state alongside calculation provenance |
| Clinical input values were stored only in evidence text | Add structured dependencies with source IDs, original values/units/dates, visible document links and portable export JSON |
| In-place edits could leave another process's catalog cache unchanged | Add monotonic observation revisions maintained by insert/update/delete triggers |
| An unrelated parser-version release reset unchanged calculation reviews | Compare equation/input evidence independently of the ingestion parser release |
| A reconstructed value could count as printed evidence when discarding duplicate documents | Exclude calculated outputs from source-document containment and duplicate-result proof |
| No-band concepts lost most citations and jurisdiction/assay caveats during seeding | Preserve all source IDs and bilingual limitations; expose them on metric and panel pages |
| A paper's title and publisher were fabricated in citation metadata | Correct the PMC9812546 citation to the actual Cureus publication |
| Adult BMI guidance falsely implied CDC agreement from age 18 | Attribute the retained 18+ framework to WHO/UA and explicitly distinguish CDC adult categories from age 20 and BMI-for-age at ages 2–19; numerical thresholds remain unchanged |
| Missing library cadence was presented as proof that no professional body publishes one | Say that this record has no sourced routine interval; do not claim universal absence |
| Calculated results were called measurements and no-band source sections implied numeric intervals | Use result wording and explain that sources may describe a method without supplying a universal range |

## Published evidence behind the substantive corrections

Calculated globulin is total protein minus albumin; it is separate from
electrophoresis fractions. The new entry adopts no laboratory-specific interval
as a universal target. [Corewell Health Laboratory](https://www.beaumontlaboratory.com/lab-test-directory/detail?URL=albumin-globulin-ratio&itemID=1)

Subtraction is not valid for every total/direct bilirubin assay pair. The NHS
laboratory publication explicitly describes incompatible methods, so sample
matching alone is insufficient evidence for universal automatic subtraction.
[Peterborough Pathology Services](https://pch-pathlab.com/cms/?q=test-rep-dbil)

INR requires the PT relationship and ISI; a prothrombin percentage cannot be
renamed INR with the same number. Specific gravity is a ratio of densities,
whereas a density unit carries mass per volume. These findings justify refusing
silent source correction. [NICE coagulometer assessment](https://www.nice.org.uk/guidance/DG14/documents/pointofcare-coagulometers-the-coaguchek-xs-system-and-the-inratio2-ptinr-monitor-overview-2),
[IUPAC relative density](https://goldbook.iupac.org/terms/view/R05262/pdf)

CDC adult BMI categories begin at 20; WHO's adult indicator includes ages 18+.
The Ukrainian obesity guideline supplies the retained local adult framework.
The difference is now visible in both languages.
[CDC](https://www.cdc.gov/bmi/adult-calculator/bmi-categories.html),
[WHO](https://www.who.int/data/gho/indicator-metadata-registry/imr-details/2389),
[Ukrainian guideline](https://www.dec.gov.ua/wp-content/uploads/2023/03/2023-kn-ozhyrinnya.pdf)

The corrected paper is *A Descriptive Study of Atherogenic Indices in Patients
Admitted to a Tertiary Care Hospital*, in Cureus. It is not the diabetes-specific
article or journal named in the earlier metadata.
[Actual publication](https://pmc.ncbi.nlm.nih.gov/articles/PMC9812546/)

Adult height carry-forward remains an explicitly labelled application policy,
not a claim that a publication guarantees unchanged stature after a particular
age. An undated profile weight does not acquire the height's measurement date.

## Sandbox-copy comparison

The immutable first-round hosted snapshot remains in
`work/db-archive/sandbox-2026-11-15-device-audit.sqlite3`.
An online backup of the first-round working result was taken before this
round's migrations and refresh:
`work/db-archive/device-audit-round2-before-refresh.sqlite3`.
The second-round working database is
`work/metric-audit-round2/anamna.sqlite3`; its aggregate receipt is
`work/metric-audit-round2/receipt.json`. Retention notes are in the archive README.

After this round the audited copy has the same documents and device rows, no
active unmapped observation, no observed device metric without a panel/twin
connection, no automatically reconstructed indirect bilirubin, and no
foreign-key errors. Every clinical calculation, the existing eGFR results
included, now carries structured dependencies.

The registry now contains 30 named targets, of which 29 are automatic;
indirect bilirubin remains a recognized legacy method solely for provenance
and retraction.

Reported rows with unsupported canonical-unit relabels were repaired. Their
reported numbers, raw units and verification states did not change. Where the
native source text itself contains a unit inconsistency, this is not proof
of a parser defect or permission to invent corrected units. Such rows are now
visible as incompatible comparisons for source review.

Original reported observation values/text, raw units, dates, ownership and
review states remained unchanged by content fingerprint. Original device
values remained unchanged. Final semantic repair and the subsequent refresh
were idempotent; additions, updates and removals were all zero. Integrity was
`ok`. Weight-days without eligible height evidence remain uncalculated.

## Verification and limits

- Full Python suite: **5,545 passed, one skipped**. Focused rendering and
  regression checks were rerun after final wording and profile-spacing edits.
- JavaScript suite: **38 passed**. Ruff, compilation and whitespace checks passed.
- Source validator: **zero errors**, warnings retained; device validator: **zero
  errors**. Both reported intact SQLite/FK checks. These validators use the
  existing local source-file corpus; the hosted snapshot was audited using its
  retained database/page evidence.
- Synthetic browser inspection covered English and Ukrainian at 390×844,
  375×667, 820×1180 and 1180×820. Checked calculation/source details, human
  review labels, unit warnings, no-band panel sources and profile estimates.
  No horizontal page overflow was observed. A tablet unit-wrap defect found
  during inspection was corrected and checked again.
- Tests that had encoded unsafe specimen or unit assumptions were replaced
  with explicit positive and negative evidence cases; the safety guards were
  retained.
- Calculations and human source verification remain separate. A passing audit
  does not verify a patient measurement or resolve an inconsistent source unit.
- This qualifies the current implementation and the audited copy. It does not
  claim universal coverage of future device schemas, every assay or every
  possible medical equation.

The hosted sandbox database was not modified.
