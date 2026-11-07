-- Garmin Health API: the latest copy of every summary Garmin has delivered.
--
-- Garmin pushes (or pings for) summaries; it cannot be asked "what is day X
-- now?" outside a ping's callback window, so the windowed recompute that
-- oura.py runs against the provider runs here against this local mirror
-- instead: a delivery upserts its summaries, then every (type, day) it touched
-- is rebuilt from all summaries of that type and day. Redeliveries and
-- revisions converge on the same rows; nothing depends on arrival order.
--
-- `record_key` is Garmin's summaryId for types that legitimately repeat within
-- a day (activities, body compositions, blood pressures, pulse-ox and
-- respiration windows). For one-per-day types (dailies, sleeps, HRV, stress
-- details, user metrics, skin temperature) it is the calendar date: Garmin
-- revises those in place and a revision may carry a new summaryId, which must
-- replace the earlier copy rather than be summed with it.
--
-- Deleting the person (users row) cascades. A Garmin deregistration or a
-- withdrawn permission deletes the matching rows here and in the device tables
-- (garmin.py) — Garmin's terms require that, and this table is health data.
CREATE TABLE IF NOT EXISTS garmin_summaries (
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    summary_type TEXT NOT NULL,
    record_key TEXT NOT NULL,
    day TEXT NOT NULL,
    payload TEXT NOT NULL,
    received_at TEXT NOT NULL,
    PRIMARY KEY (user_id, summary_type, record_key)
);

CREATE INDEX IF NOT EXISTS idx_garmin_summaries_day ON garmin_summaries(user_id, summary_type, day);
