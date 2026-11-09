-- Labs' public price catalogues, kept for the test planner (/plan-tests).
--
-- Not patient data: what a lab sells, at what price, in which city.  One row
-- per (lab, city, what was fetched); `cache_key` is "catalog" for a whole
-- price list, or a lab-specific key for an on-demand lookup (a search query,
-- one panel's composition).  Rows are replaced when older than the reader's
-- time-to-live; deleting the table's rows only costs a refetch.
CREATE TABLE IF NOT EXISTS lab_catalog_cache (
    provider TEXT NOT NULL,
    region TEXT NOT NULL,
    cache_key TEXT NOT NULL,
    fetched_at TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    PRIMARY KEY (provider, region, cache_key)
);
