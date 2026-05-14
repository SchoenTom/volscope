-- VolScope — Migration 009 — actor column on bot_trades.
--
-- v0.9.1: the bot_trades table mixed two semantically distinct
-- trade populations:
--
--   1. **User-initiated** paper trades — what the operator clicked
--      "BUY" on from Pre-Trade / Options Lab.
--   2. **Bot-initiated** autonomous trades — what the daily scheduler
--      generated via the signal engine.
--
-- Up to v0.9.0 the Portfolio and Bot Dashboard pages both queried
-- the same table without distinction, so the operator's manually-
-- placed trades cluttered the Bot Dashboard and the Bot's
-- autonomous trades cluttered the Portfolio. The actor column
-- separates them while keeping a single physical table (joins on
-- trade_id stay simple, no double-bookkeeping).
--
-- Convention:
--   actor = 'user'    — operator clicked BUY (Pre-Trade, Options Lab)
--   actor = 'bot'     — daily scheduler / signal engine
--   actor = 'unknown' — legacy rows from before migration 009;
--                       treated as user-trades on Portfolio for
--                       backward-compat (less surprising than
--                       sending them to the Bot view).
--
-- Defensive CREATE for test-DB compatibility (same pattern as 006-008).

CREATE TABLE IF NOT EXISTS bot_trades (
    trade_id   TEXT PRIMARY KEY,
    strategy   TEXT NOT NULL,
    underlying TEXT NOT NULL,
    direction  TEXT NOT NULL,
    status     TEXT NOT NULL
);

ALTER TABLE bot_trades ADD COLUMN IF NOT EXISTS actor VARCHAR DEFAULT 'user';

-- Backfill any pre-existing NULL rows to 'unknown' so downstream
-- filters never see NaN. Idempotent — re-running the migration is
-- a no-op for rows already labelled.
UPDATE bot_trades SET actor = 'unknown' WHERE actor IS NULL;

-- Query-side index — Portfolio and Bot Dashboard hit this on every render.
CREATE INDEX IF NOT EXISTS idx_bot_trades_actor ON bot_trades (actor);
