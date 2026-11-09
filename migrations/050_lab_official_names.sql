-- Labs and clinics under the names they give themselves (docs/lab-names.md).
--
-- «EskuLab» was our spelling: the laboratory writes «Esculab» (esculab.com,
-- og:site_name) and «Ескулаб».  «Ekspert» was a transliteration of «Експерт»
-- the hospital never uses as its brand: it writes «EXPERT» / Expert Hospital
-- (experthospital.com.ua, its app «Лікарня ЕКСПЕРТ»).  «Veselka Medical
-- Center» was our description: the clinic writes «Veselka» / «Веселка»
-- (veselka.clinic).
--
-- Rewrites the stored provider keys (eskulab -> esculab, ekspert -> expert),
-- the operator's per-provider settings, the message keys a sync stored, and
-- re-keys the two renamed vendors: a vendor's id is the uuid5 of its name
-- (pipeline.stable_id), so the new name gets the id the code derives for it
-- and every row pointing at the old id follows.  File names on disk
-- («eskulab-<order>.pdf») are the person's sources and are left alone; the
-- classifier still recognises them.  audit_events is history and keeps what
-- happened under the names used at the time.

UPDATE lab_accounts SET provider = 'esculab' WHERE provider = 'eskulab';
UPDATE lab_accounts SET provider = 'expert' WHERE provider = 'ekspert';
UPDATE lab_person_links SET provider = 'esculab' WHERE provider = 'eskulab';
UPDATE lab_person_links SET provider = 'expert' WHERE provider = 'ekspert';
UPDATE lab_orders SET provider = 'esculab' WHERE provider = 'eskulab';
UPDATE lab_orders SET provider = 'expert' WHERE provider = 'ekspert';
UPDATE lab_catalog_cache SET provider = 'esculab' WHERE provider = 'eskulab';

UPDATE lab_accounts SET sync_summary_json = replace(replace(sync_summary_json,
        '"provider": "eskulab"', '"provider": "esculab"'), '"provider": "ekspert"', '"provider": "expert"')
    WHERE sync_summary_json LIKE '%"provider": "eskulab"%' OR sync_summary_json LIKE '%"provider": "ekspert"%';
UPDATE lab_accounts SET sync_detail_key = replace(replace(sync_detail_key,
        'labsync.eskulab_', 'labsync.esculab_'), 'labsync.ekspert_', 'labsync.expert_')
    WHERE sync_detail_key LIKE 'labsync.eskulab\_%' ESCAPE '\' OR sync_detail_key LIKE 'labsync.ekspert\_%' ESCAPE '\';
UPDATE lab_orders SET error_key = replace(replace(error_key,
        'labsync.eskulab_', 'labsync.esculab_'), 'labsync.ekspert_', 'labsync.expert_')
    WHERE error_key LIKE 'labsync.eskulab\_%' ESCAPE '\' OR error_key LIKE 'labsync.ekspert\_%' ESCAPE '\';

UPDATE OR IGNORE app_settings SET key = 'labsync_esculab_' || substr(key, length('labsync_eskulab_') + 1)
    WHERE key LIKE 'labsync\_eskulab\_%' ESCAPE '\';
UPDATE OR IGNORE app_settings SET key = 'labsync_expert_' || substr(key, length('labsync_ekspert_') + 1)
    WHERE key LIKE 'labsync\_ekspert\_%' ESCAPE '\';

-- Esculab: new row under the derived id, children repointed, old row removed.
-- The DELETE fails (foreign keys are on) if anything still points at the old id.
INSERT INTO vendors(id, canonical_name, website, created_at)
    SELECT 'a160a862-557a-5295-b8b0-481790f6ba5f', 'Esculab', website, created_at FROM vendors
    WHERE id = 'db590f97-b1bb-5631-9956-2db03e796b81'
      AND NOT EXISTS (SELECT 1 FROM vendors WHERE id = 'a160a862-557a-5295-b8b0-481790f6ba5f');
UPDATE documents SET vendor_id = 'a160a862-557a-5295-b8b0-481790f6ba5f' WHERE vendor_id = 'db590f97-b1bb-5631-9956-2db03e796b81';
UPDATE reports SET vendor_id = 'a160a862-557a-5295-b8b0-481790f6ba5f' WHERE vendor_id = 'db590f97-b1bb-5631-9956-2db03e796b81';
UPDATE clinical_findings SET vendor_id = 'a160a862-557a-5295-b8b0-481790f6ba5f' WHERE vendor_id = 'db590f97-b1bb-5631-9956-2db03e796b81';
UPDATE device_imports SET vendor_id = 'a160a862-557a-5295-b8b0-481790f6ba5f' WHERE vendor_id = 'db590f97-b1bb-5631-9956-2db03e796b81';
UPDATE OR IGNORE concept_aliases SET vendor_id = 'a160a862-557a-5295-b8b0-481790f6ba5f' WHERE vendor_id = 'db590f97-b1bb-5631-9956-2db03e796b81';
UPDATE OR IGNORE vendor_aliases SET vendor_id = 'a160a862-557a-5295-b8b0-481790f6ba5f' WHERE vendor_id = 'db590f97-b1bb-5631-9956-2db03e796b81';
DELETE FROM vendors WHERE id = 'db590f97-b1bb-5631-9956-2db03e796b81'
    AND EXISTS (SELECT 1 FROM vendors WHERE id = 'a160a862-557a-5295-b8b0-481790f6ba5f');

-- Veselka, the same way.
INSERT INTO vendors(id, canonical_name, website, created_at)
    SELECT 'd8795aad-e5de-5bd7-a90c-44ff9679632c', 'Veselka', website, created_at FROM vendors
    WHERE id = '04e03f22-fdca-58a4-b040-93437d10846b'
      AND NOT EXISTS (SELECT 1 FROM vendors WHERE id = 'd8795aad-e5de-5bd7-a90c-44ff9679632c');
UPDATE documents SET vendor_id = 'd8795aad-e5de-5bd7-a90c-44ff9679632c' WHERE vendor_id = '04e03f22-fdca-58a4-b040-93437d10846b';
UPDATE reports SET vendor_id = 'd8795aad-e5de-5bd7-a90c-44ff9679632c' WHERE vendor_id = '04e03f22-fdca-58a4-b040-93437d10846b';
UPDATE clinical_findings SET vendor_id = 'd8795aad-e5de-5bd7-a90c-44ff9679632c' WHERE vendor_id = '04e03f22-fdca-58a4-b040-93437d10846b';
UPDATE device_imports SET vendor_id = 'd8795aad-e5de-5bd7-a90c-44ff9679632c' WHERE vendor_id = '04e03f22-fdca-58a4-b040-93437d10846b';
UPDATE OR IGNORE concept_aliases SET vendor_id = 'd8795aad-e5de-5bd7-a90c-44ff9679632c' WHERE vendor_id = '04e03f22-fdca-58a4-b040-93437d10846b';
UPDATE OR IGNORE vendor_aliases SET vendor_id = 'd8795aad-e5de-5bd7-a90c-44ff9679632c' WHERE vendor_id = '04e03f22-fdca-58a4-b040-93437d10846b';
DELETE FROM vendors WHERE id = '04e03f22-fdca-58a4-b040-93437d10846b'
    AND EXISTS (SELECT 1 FROM vendors WHERE id = 'd8795aad-e5de-5bd7-a90c-44ff9679632c');

-- The search text names the vendor; the folded key is rewritten on start
-- (pipeline.backfill_search_keys) for every row left NULL here.
UPDATE search_index SET content = replace(content, 'EskuLab', 'Esculab'), content_folded = NULL
    WHERE instr(content, 'EskuLab') > 0;
UPDATE search_index SET content = replace(content, 'Veselka Medical Center', 'Veselka'), content_folded = NULL
    WHERE instr(content, 'Veselka Medical Center') > 0;
-- Cached AI summaries quote the vendor name.
UPDATE ai_document_hints SET content_json = replace(content_json, 'EskuLab', 'Esculab')
    WHERE instr(content_json, 'EskuLab') > 0;
