-- Which vaccine, by which maker, given where, and by whom.
--
-- Form 063/о names a dose by its eHealth code and a paragraph of description,
-- and until now `product_name` held whatever OCR made of that paragraph.  A
-- person looks for "Twinrix", not «Вакцина для профілактики гепатиту А та
-- гепатиту В GlaxoSmithKline», so the record now keeps the two apart:
--
--   * `trade_name` — the registered product (Twinrix, Gardasil 9), resolved
--     from the code plus the printed maker through the sourced catalogue in
--     `immunizations.PRODUCTS`; empty when that is not certain.
--   * `product_name` — unchanged in meaning, now shown only as "as printed".
--   * `manufacturer` — the marketing-authorisation holder (already a column).
--   * `facility` — the health facility the card names in its header.
--   * `clinician` — who gave it.  This is the `performer` column 023 created
--     and nothing ever wrote; renamed rather than duplicated.

ALTER TABLE immunizations ADD COLUMN trade_name TEXT NOT NULL DEFAULT '';
ALTER TABLE immunizations ADD COLUMN facility TEXT NOT NULL DEFAULT '';
ALTER TABLE immunizations RENAME COLUMN performer TO clinician;
