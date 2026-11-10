-- One-time tokens on the Esculab order form (/plan-tests/order/esculab).
--
-- Each form the planner shows carries a random nonce.  The order POST spends
-- it before the lab is asked and never frees it again, so a second press of
-- the same form (a double click, a retry after a slow answer) cannot file a
-- second real order.  A row is only a record that the token was used; rows
-- older than two days are dropped by the order handler itself.
CREATE TABLE IF NOT EXISTS lab_order_nonces (
    nonce TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at TEXT NOT NULL
);
