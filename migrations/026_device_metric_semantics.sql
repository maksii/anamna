-- Similar labels from different ecosystems do not guarantee the same
-- measurement. Oura's exported field is explicitly the lowest heart rate
-- captured during sleep; Apple estimates resting heart rate from sedentary
-- samples across the day. OpenWearables' activity contract says only
-- `active_minutes`, not Apple Exercise ring minutes. Keep both concepts
-- distinct before the multi-source comparison UI puts them side by side.

UPDATE device_metric_days
SET metric_key='lowest_sleeping_heart_rate',
    metric_name='Lowest sleeping heart rate',
    aggregation='latest'
WHERE source_vendor='Oura' AND metric_key='resting_heart_rate';

UPDATE device_metric_days
SET metric_key='active_minutes',
    metric_name='Active minutes',
    aggregation='sum'
WHERE source_vendor='OpenWearables' AND metric_key='exercise_minutes';
