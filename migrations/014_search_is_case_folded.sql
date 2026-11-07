-- Searching for «мрт» found nothing while «МРТ» found eight documents.
--
-- The query is `content LIKE '%...%'`, and SQLite's LIKE folds case for ASCII
-- only: every Cyrillic search term was effectively case-sensitive, so whether
-- a person found their own MRI reports depended on whether they had held shift.
-- Latin "MRT" found one document and Cyrillic «МРТ» found eight, because the
-- two spellings are different strings that look identical on the page.
--
-- SQLite cannot fold either of those itself -- `lower()` is ASCII-only too --
-- so the folded form is stored beside the content and both sides of the
-- comparison are folded in Python by `search_key()`.  Left NULL here and
-- backfilled from the code that owns the rule, rather than by a SQL expression
-- that would be a second copy of it and free to drift.
ALTER TABLE search_index ADD COLUMN content_folded TEXT;
CREATE INDEX IF NOT EXISTS idx_search_folded ON search_index(owner_user_id, content_folded);
