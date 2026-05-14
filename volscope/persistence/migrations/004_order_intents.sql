-- VolScope Bot — DuckDB schema migration 004.
-- Order intents — the pre-trade idempotency table.
--
-- Every trade entered by the bot is FIRST recorded here with a UUID.
-- If the bot crashes / reconnects / restarts between intent creation
-- and order submission, the reconciler reads this table and resolves
-- pending intents against IBKR's open-orders + executions stream.
--
-- The intent_uuid is the idempotency key — same UUID, same trade.
-- Status transitions: PENDING → SUBMITTED → ACKED (or REJECTED).
-- Once ACKED, the row's permid is canonical (NOT order_ref, which is
-- per-session).
--
-- Pattern: Stripe Idempotency-Key.

CREATE TABLE IF NOT EXISTS bot_order_intents (
    intent_uuid          VARCHAR PRIMARY KEY,
    signal_id            VARCHAR,                  -- nullable; not all intents trace to a signal
    strategy             VARCHAR NOT NULL,
    underlying           VARCHAR NOT NULL,
    direction            VARCHAR NOT NULL,         -- 'short_vol' | 'long_vol'
    intended_legs_json   JSON NOT NULL,            -- list[{side, right, strike, expiry, contracts}]
    created_at           TIMESTAMP NOT NULL DEFAULT current_timestamp,
    status               VARCHAR NOT NULL DEFAULT 'PENDING',  -- PENDING | SUBMITTED | ACKED | REJECTED
    permid               BIGINT,                   -- IBKR's canonical fill ID (set when ACKED)
    order_ref            VARCHAR,                  -- per-session orderRef (set when SUBMITTED)
    submitted_at         TIMESTAMP,
    acked_at             TIMESTAMP,
    reject_reason        VARCHAR
);

CREATE INDEX IF NOT EXISTS idx_intent_status
    ON bot_order_intents(status, created_at);
CREATE INDEX IF NOT EXISTS idx_intent_underlying
    ON bot_order_intents(underlying);
