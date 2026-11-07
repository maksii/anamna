-- Oura average_hrv is RMSSD. HealthKit HeartRateVariabilitySDNN remains SDNN,
-- including records whose writer app has Oura in its name. Restrict this
-- repair to the two adapters whose input schema proves the method.
-- Source: Oura Cardiovascular Health white paper, February 2026, HRV section:
-- https://ouraring.com/blog/wp-content/uploads/2026/02/Cardiovascular-Health-white-paper-February-2026.pdf
-- If both keys already exist, retain BOTH original values, distinguishing the
-- corrected legacy source rather than silently discarding a historical row.
UPDATE device_metric_days AS old
SET source_name=source_name || ' · RMSSD ' || id
WHERE old.metric_key='heart_rate_variability' AND old.source_vendor='Oura'
  AND old.import_id IN (SELECT id FROM device_imports WHERE adapter_key IN ('oura','oura_api'))
  AND EXISTS (SELECT 1 FROM device_metric_days AS current
      WHERE current.owner_user_id=old.owner_user_id AND current.source_name=old.source_name
        AND current.day=old.day AND current.metric_key='heart_rate_variability_rmssd');

UPDATE device_metric_days
SET metric_key='heart_rate_variability_rmssd',
    metric_name='Heart rate variability (RMSSD)'
WHERE metric_key='heart_rate_variability' AND source_vendor='Oura'
  AND import_id IN (SELECT id FROM device_imports WHERE adapter_key IN ('oura','oura_api'));
