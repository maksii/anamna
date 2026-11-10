-- What a product card says besides the instruction: facts by key and who may take it, as JSON.
--
-- details_json   '' no card was read for this copy (a page copy, or one made before the card
--                was switched on); {"via": "page"} the card was tried and the page was used;
--                {"via": "api", "facts": [...], "warnings": [...]} read from the card.
ALTER TABLE drug_references ADD COLUMN details_json TEXT NOT NULL DEFAULT '';

-- Copies stored before this migration were read by a parser that dropped the text between a "<"
-- and the next ">" («кліренс креатиніну < 10 мл/хв … > 10 мл/хв»). Mark them old, so each is read
-- again at its next use; the old copy still answers when the site cannot be reached.
UPDATE drug_references SET fetched_at = '2000-01-01T00:00:00+00:00';
