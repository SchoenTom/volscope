-- VolScope Bot — DuckDB schema migration 002.
-- Adds the bot_killswitch single-row state table.

CREATE TABLE IF NOT EXISTS bot_killswitch (
    id          INTEGER PRIMARY KEY DEFAULT 1,
    active      BOOLEAN NOT NULL DEFAULT FALSE,
    reason      VARCHAR,
    tripped_at  TIMESTAMP,
    reset_at    TIMESTAMP,
    CHECK (id = 1)
);

-- Seed the row. ON CONFLICT keeps this idempotent across re-runs.
INSERT INTO bot_killswitch (id, active) VALUES (1, FALSE)
ON CONFLICT (id) DO NOTHING;
