-- A document the person marked historical: the problem it describes is over.
-- It stays in the record and on the charts; its conclusions and the results
-- whose latest reading comes from it no longer raise attention.  NULL while
-- the document is current; the timestamp says when it was marked.
ALTER TABLE documents ADD COLUMN historical_at TEXT;
