-- concept_aliases declares UNIQUE(vendor_id, normalized_alias), but every
-- seeded alias carries vendor_id NULL, and in SQLite NULL never equals NULL
-- inside a UNIQUE index. So the constraint held for vendor-scoped aliases
-- (616 rows, 616 distinct) and never fired for the rest: 166,278 rows for
-- 351 distinct names, re-appended in full by `INSERT OR IGNORE` on every
-- seed run. The OR IGNORE was correct; it had nothing to conflict against.
--
-- Aliases are derived data, regenerated from the seed catalogue, so collapsing
-- the duplicates loses nothing. The lowest id is kept for each group because
-- app.py:977 already reads them with SELECT DISTINCT and never depends on id.

DELETE FROM concept_aliases
WHERE id NOT IN (
    SELECT MIN(id) FROM concept_aliases
    GROUP BY concept_id, COALESCE(vendor_id, ''), normalized_alias
);

-- A partial unique index gives the NULL-vendor rows the guarantee the table
-- constraint cannot express, so INSERT OR IGNORE finally has something to
-- ignore. The existing UNIQUE(vendor_id, normalized_alias) keeps covering
-- rows that do name a vendor.
CREATE UNIQUE INDEX IF NOT EXISTS idx_concept_alias_seeded_unique
    ON concept_aliases(concept_id, normalized_alias)
    WHERE vendor_id IS NULL;
