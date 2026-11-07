-- Vaccinations, and the provenance every hand-entered datum carries.
--
-- Two things arrive together because they are the same problem seen twice.
--
-- 1. A dose of vaccine is not an observation.  `observations` stores a
--    measurement of the body: a number, a unit, a reference interval, a
--    verdict.  A vaccination is an event done *to* the body — a product, a
--    manufacturer, a lot, a place in a course of N doses — and forcing it into
--    the observation shape would put a lot number in `value_text` and lose
--    every question a person actually asks ("which dose was that?", "is the
--    course finished?", "when is the next one due?").  So: its own table.
--
-- 2. Until now, every clinical row in this database descended from a file.
--    `observations.document_id` was NOT NULL, which encoded an assumption that
--    is simply false: a person knows things about their own body that no
--    document in the ledger holds.  A vaccination given before the electronic
--    card existed, a blood pressure measured this morning, a childhood dose
--    remembered from a paper booklet — all real, none of them extracted from
--    anything.  The columns added below let a row say who entered it and when,
--    and `document_id` becomes optional so a person's own knowledge does not
--    need a fake document invented to hold it.
--
-- What must stay true after this migration:
--
--   * A row's provenance is never ambiguous.  `entry_source` is 'document' for
--     anything a parser produced and 'manual' for anything a person typed, and
--     'manual' rows always name `entered_by_user_id`.
--   * A hand-entered row is not more trusted for being hand-entered, and not
--     less.  It carries the person's own authority, which is exactly what
--     `verification_status='corrected'` and `extraction_method='human_entered'`
--     already meant on the one hand-entry path that existed (the "add a value
--     the parser missed" form on a document page).  Those markers are kept, so
--     nothing downstream has to learn a second vocabulary.
--   * Deleting a document deletes the rows read out of it, and leaves the rows
--     a person entered themselves standing.  That is why `immunizations`
--     references documents ON DELETE SET NULL rather than CASCADE: a dose
--     really was given whether or not the scan of the card is still on file.

-- --------------------------------------------------------------- observations

-- SQLite cannot drop a NOT NULL, so the table is rebuilt.  Column order,
-- types, defaults and the CHECK are reproduced exactly as 001/002 left them,
-- with `document_id` made nullable and the two provenance columns appended.
PRAGMA foreign_keys = OFF;

CREATE TABLE observations_new (
    id TEXT PRIMARY KEY,
    owner_user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    patient_id TEXT NOT NULL REFERENCES patients(id) ON DELETE CASCADE,
    document_id TEXT REFERENCES documents(id) ON DELETE CASCADE,
    page_number INTEGER NOT NULL,
    concept_id TEXT REFERENCES concepts(id),
    raw_name TEXT NOT NULL,
    value_type TEXT NOT NULL,
    value_numeric REAL,
    value_text TEXT,
    comparator TEXT,
    unit_raw TEXT,
    unit_canonical TEXT,
    observed_at TEXT,
    specimen TEXT,
    vendor_reference_text TEXT,
    vendor_reference_low REAL,
    vendor_reference_high REAL,
    vendor_reference_low_inclusive INTEGER,
    vendor_reference_high_inclusive INTEGER,
    vendor_interpretation TEXT,
    verification_status TEXT NOT NULL DEFAULT 'extracted',
    extraction_method TEXT NOT NULL,
    confidence REAL NOT NULL DEFAULT 0,
    evidence_text TEXT NOT NULL,
    evidence_bbox_json TEXT,
    parser_version TEXT NOT NULL,
    created_at TEXT NOT NULL,
    report_id TEXT REFERENCES reports(id),
    entry_source TEXT NOT NULL DEFAULT 'document',
    entered_by_user_id TEXT REFERENCES users(id) ON DELETE SET NULL,
    CHECK(value_numeric IS NOT NULL OR value_text IS NOT NULL),
    CHECK(entry_source IN ('document', 'manual')),
    CHECK(entry_source = 'document' OR entered_by_user_id IS NOT NULL)
);

-- The one existing hand-entry path stamped `extraction_method='human_entered'`
-- and `parser_version='human'`.  Those rows are manual entries that predate the
-- column, so they are labelled as what they always were rather than left
-- looking like parser output.  The person who entered them was not recorded at
-- the time and cannot be invented now; the owner is the only defensible answer,
-- and on a single-patient ledger it is also the right one.
INSERT INTO observations_new (
    id, owner_user_id, patient_id, document_id, page_number, concept_id, raw_name,
    value_type, value_numeric, value_text, comparator, unit_raw, unit_canonical,
    observed_at, specimen, vendor_reference_text, vendor_reference_low,
    vendor_reference_high, vendor_reference_low_inclusive, vendor_reference_high_inclusive,
    vendor_interpretation, verification_status, extraction_method, confidence,
    evidence_text, evidence_bbox_json, parser_version, created_at, report_id,
    entry_source, entered_by_user_id
)
SELECT
    id, owner_user_id, patient_id, document_id, page_number, concept_id, raw_name,
    value_type, value_numeric, value_text, comparator, unit_raw, unit_canonical,
    observed_at, specimen, vendor_reference_text, vendor_reference_low,
    vendor_reference_high, vendor_reference_low_inclusive, vendor_reference_high_inclusive,
    vendor_interpretation, verification_status, extraction_method, confidence,
    evidence_text, evidence_bbox_json, parser_version, created_at, report_id,
    CASE WHEN extraction_method = 'human_entered' THEN 'manual' ELSE 'document' END,
    CASE WHEN extraction_method = 'human_entered' THEN owner_user_id END
FROM observations;

DROP TABLE observations;
ALTER TABLE observations_new RENAME TO observations;

-- Dropping the table dropped its indexes with it. These four are 001's, name
-- for name and column for column: a rebuild that quietly loses an index turns
-- into a slow page nobody connects back to this migration.
CREATE INDEX IF NOT EXISTS idx_observations_owner_concept_date
    ON observations(owner_user_id, concept_id, observed_at);
CREATE INDEX IF NOT EXISTS idx_observations_document_page
    ON observations(document_id, page_number);
CREATE INDEX IF NOT EXISTS idx_observations_review
    ON observations(owner_user_id, verification_status);
CREATE INDEX IF NOT EXISTS idx_observations_report
    ON observations(report_id);

PRAGMA foreign_keys = ON;

-- ------------------------------------------------------------- immunizations

-- One row per dose given.
--
-- `vaccine_code` is the eHealth Ukraine dictionary code printed in brackets on
-- form 063/o — `DTaP`, `HepAHepB`, `Men_ACWY_135`.  It is stored because it is
-- the only machine-stable identifier on the page: the product name beside it is
-- a paragraph of Ukrainian marketing text that changes with every tender.  It
-- may be empty when a scan was too poor to read one.
--
-- `diseases` is what the dose actually protects against, as a sorted
-- comma-separated list of the keys in immunizations.DISEASES — 'diphtheria,
-- pertussis,tetanus' for a DTaP.  Denormalised on purpose: every question this
-- table exists to answer ("am I covered against tetanus?") is a question about
-- diseases, not products, and a child table of one-to-six rows per dose would
-- turn every read into a join for no gain.  It may be empty when neither the
-- code nor the printed text identified the vaccine — those doses are shown to
-- the person as needing identification rather than dropped.
--
-- `dose_number` / `doses_in_series` are the card's own "2/3": this dose was the
-- second of a three-dose course.  When they disagree with a guideline the card
-- wins here; the guideline's opinion belongs on the page, not in the record.
CREATE TABLE IF NOT EXISTS immunizations (
    id TEXT PRIMARY KEY,
    owner_user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    patient_id TEXT NOT NULL REFERENCES patients(id) ON DELETE CASCADE,
    document_id TEXT REFERENCES documents(id) ON DELETE SET NULL,
    page_number INTEGER,
    occurrence_date TEXT,
    vaccine_code TEXT NOT NULL DEFAULT '',
    diseases TEXT NOT NULL DEFAULT '',
    product_name TEXT NOT NULL DEFAULT '',
    manufacturer TEXT NOT NULL DEFAULT '',
    event_kind TEXT NOT NULL DEFAULT 'vaccination',
    dose_number INTEGER,
    doses_in_series INTEGER,
    dose_quantity REAL,
    dose_unit TEXT NOT NULL DEFAULT '',
    route TEXT NOT NULL DEFAULT '',
    lot_number TEXT NOT NULL DEFAULT '',
    site TEXT NOT NULL DEFAULT '',
    performer TEXT NOT NULL DEFAULT '',
    note TEXT NOT NULL DEFAULT '',
    entry_source TEXT NOT NULL DEFAULT 'document',
    entered_by_user_id TEXT REFERENCES users(id) ON DELETE SET NULL,
    verification_status TEXT NOT NULL DEFAULT 'extracted',
    evidence_text TEXT NOT NULL DEFAULT '',
    confidence REAL NOT NULL DEFAULT 0,
    extraction_method TEXT NOT NULL DEFAULT '',
    parser_version TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    CHECK(event_kind IN ('vaccination', 'revaccination')),
    CHECK(entry_source IN ('document', 'manual')),
    CHECK(entry_source = 'document' OR entered_by_user_id IS NOT NULL),
    CHECK(verification_status IN ('extracted', 'verified', 'corrected', 'rejected'))
);

CREATE INDEX IF NOT EXISTS idx_immunizations_owner_date
    ON immunizations(owner_user_id, occurrence_date);
CREATE INDEX IF NOT EXISTS idx_immunizations_document
    ON immunizations(document_id);

-- Re-reading the same card must not double the record.  A dose is identified by
-- when it was given and which vial it came from — the pair a nurse writes down
-- and the pair that is unique in practice.  Form 063/o prints several doses
-- twice, once in its per-disease section and once under «Інші щеплення», so
-- without this a single import of one card yields fifteen rows for thirteen
-- doses.  Partial, so the many doses with no readable lot do not collide with
-- each other.
CREATE UNIQUE INDEX IF NOT EXISTS uq_immunizations_dose
    ON immunizations(owner_user_id, occurrence_date, lot_number)
    WHERE lot_number <> '' AND occurrence_date IS NOT NULL;
