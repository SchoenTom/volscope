-- VolScope Bot — DuckDB schema migration 001 (Phase 1 scaffold).
--
-- Five tables that together form the immutable record of every trade
-- the bot considers, sizes, submits, manages, and closes. JSON columns
-- hold denormalised snapshots so an audit row can be replayed without
-- joining N tables. UUIDs are TEXT (DuckDB has no native UUID type).

-- Trades: one row per logical trade (a multi-leg combo is ONE trade).
CREATE TABLE IF NOT EXISTS bot_trades (
    trade_id          TEXT PRIMARY KEY,
    strategy          TEXT NOT NULL,
    underlying        TEXT NOT NULL,
    direction         TEXT NOT NULL,                    -- 'short_vol' | 'long_vol'
    status            TEXT NOT NULL,                    -- state-machine state
    composite_score   DOUBLE,
    size_fraction     DOUBLE,
    contracts         INTEGER,
    capital_at_risk   DOUBLE,
    credit_or_debit   DOUBLE,                           -- signed; + = credit collected
    opened_at         TIMESTAMP,
    closed_at         TIMESTAMP,
    realized_pnl      DOUBLE,
    legs_snapshot     JSON,                             -- full leg detail at open
    reason_block      TEXT,                             -- if status='ABANDONED'
    notes             TEXT
);

-- DuckDB does not support partial indexes; queries filter on status
-- in WHERE clauses and use the non-partial index below.
CREATE INDEX IF NOT EXISTS idx_bot_trades_status ON bot_trades(status);
CREATE INDEX IF NOT EXISTS idx_bot_trades_underlying ON bot_trades(underlying);

-- Legs: one row per option leg of a trade. Useful for assignment audit.
CREATE TABLE IF NOT EXISTS bot_legs (
    leg_id            TEXT PRIMARY KEY,
    trade_id          TEXT NOT NULL,
    side              TEXT NOT NULL,                    -- 'buy' | 'sell'
    option_type       TEXT NOT NULL,                    -- 'call' | 'put'
    strike            DOUBLE NOT NULL,
    expiry            DATE NOT NULL,
    contracts         INTEGER NOT NULL,
    open_premium      DOUBLE,                           -- per-contract $
    close_premium     DOUBLE,
    delta_at_open     DOUBLE,
    iv_at_open        DOUBLE,
    assigned          BOOLEAN DEFAULT FALSE,
    FOREIGN KEY (trade_id) REFERENCES bot_trades(trade_id)
);

CREATE INDEX IF NOT EXISTS idx_bot_legs_trade ON bot_legs(trade_id);

-- Daily P&L roll-up; one row per (account, date).
CREATE TABLE IF NOT EXISTS bot_pnl_daily (
    account_id        TEXT NOT NULL,
    date              DATE NOT NULL,
    nlv               DOUBLE,
    bpr_used          DOUBLE,
    cash              DOUBLE,
    realized_pnl      DOUBLE,
    unrealized_pnl    DOUBLE,
    portfolio_delta   DOUBLE,
    portfolio_vega    DOUBLE,
    portfolio_theta   DOUBLE,
    open_positions    INTEGER,
    PRIMARY KEY (account_id, date)
);

-- Signals log: every signal the engine produces, whether traded or not.
-- This is the auditable record of WHY the bot did (or didn't) act.
CREATE TABLE IF NOT EXISTS bot_signals_log (
    signal_id         TEXT PRIMARY KEY,
    snapshot_date     DATE NOT NULL,
    underlying        TEXT NOT NULL,
    direction         TEXT NOT NULL,
    composite_score   DOUBLE,
    factors_json      JSON,                             -- raw factor vector
    gates_json        JSON,                             -- list of {name, passed, reason}
    decision          TEXT NOT NULL,                    -- 'EXECUTE' | 'BLOCK' | 'WATCH'
    trade_id          TEXT,                             -- set if decision == EXECUTE
    created_at        TIMESTAMP DEFAULT current_timestamp,
    FOREIGN KEY (trade_id) REFERENCES bot_trades(trade_id)
);

CREATE INDEX IF NOT EXISTS idx_bot_signals_date
    ON bot_signals_log(snapshot_date DESC);
CREATE INDEX IF NOT EXISTS idx_bot_signals_underlying
    ON bot_signals_log(underlying, snapshot_date DESC);

-- Orders log: every order request sent to IBKR, every fill received.
CREATE TABLE IF NOT EXISTS bot_orders_log (
    order_event_id    TEXT PRIMARY KEY,
    trade_id          TEXT,
    order_ref         TEXT,                             -- IBKR client orderRef (idempotency)
    ts                TIMESTAMP DEFAULT current_timestamp,
    event_type        TEXT NOT NULL,                    -- 'SUBMIT'|'ACK'|'PARTIAL'|'FILL'|'CANCEL'|'REJECT'
    payload_json      JSON,                             -- raw IBKR payload
    FOREIGN KEY (trade_id) REFERENCES bot_trades(trade_id)
);

CREATE INDEX IF NOT EXISTS idx_bot_orders_trade ON bot_orders_log(trade_id, ts);
CREATE INDEX IF NOT EXISTS idx_bot_orders_ref ON bot_orders_log(order_ref);
