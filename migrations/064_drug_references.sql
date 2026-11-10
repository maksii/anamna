-- Cache of public reference text for medicines (tabletki.ua instruction for
-- medical use, one row per page).  It is not personal data and has no owner.
CREATE TABLE IF NOT EXISTS drug_references (
    source TEXT NOT NULL,
    url TEXT NOT NULL,
    shown_for TEXT NOT NULL DEFAULT '',
    atc_codes TEXT NOT NULL DEFAULT '',
    sections_json TEXT NOT NULL,
    fetched_at TEXT NOT NULL,
    PRIMARY KEY (source, url)
);
