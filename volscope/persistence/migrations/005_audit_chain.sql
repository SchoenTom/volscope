-- VolScope Bot — DuckDB schema migration 005.
-- Hash-chained tamper-evident audit log.
--
-- Every signal emission, order intent, fill, kill-switch trip/reset
-- appends one row here. The chain is SHA-256(canonical_json(payload) +
-- prev_hash); breaking it requires rewriting every subsequent row.
--
-- §147 AO (German tax) requires 10-year retention of trade records
-- when activity could be deemed gewerblich. This chain is the
-- defensible source of truth.

CREATE SEQUENCE IF NOT EXISTS bot_audit_seq;

CREATE TABLE IF NOT EXISTS bot_audit_chain (
    seq        BIGINT PRIMARY KEY DEFAULT nextval('bot_audit_seq'),
    ts         TIMESTAMP NOT NULL DEFAULT current_timestamp,
    kind       VARCHAR NOT NULL,    -- 'signal' | 'order_intent' | 'order_submitted' | 'fill' | 'kill_trip' | 'kill_reset'
    payload    JSON NOT NULL,        -- the event body, deterministically serialized
    prev_hash  VARCHAR NOT NULL,     -- hex SHA-256 of previous row's entry_hash; genesis = 64 zeros
    entry_hash VARCHAR NOT NULL      -- hex SHA-256 of canonical(payload) || prev_hash
);

CREATE INDEX IF NOT EXISTS idx_audit_seq ON bot_audit_chain(seq);
CREATE INDEX IF NOT EXISTS idx_audit_kind ON bot_audit_chain(kind, ts DESC);
