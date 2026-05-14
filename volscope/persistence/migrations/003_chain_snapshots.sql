-- VolScope Bot — DuckDB schema migration 003.
-- Real option-chain snapshots — the quote source for the paper engine.
--
-- One row per (ticker, snapshot_ts, expiry, strike, right). Scraped
-- nightly via scripts/scrape/scrape_chains.py. The paper engine reads
-- the latest snapshot per ticker to build trades; the daily MTM job
-- reads each subsequent snapshot to mark trades to market.

CREATE TABLE IF NOT EXISTS bot_chain_snapshots (
    ticker        VARCHAR NOT NULL,
    snapshot_ts   TIMESTAMP NOT NULL,
    expiry        DATE NOT NULL,
    strike        DOUBLE NOT NULL,
    option_right  VARCHAR NOT NULL,       -- 'C' | 'P' (renamed: 'right' is SQL reserved)
    bid           DOUBLE,
    ask           DOUBLE,
    mid           DOUBLE,                 -- (bid+ask)/2; NULL if bid or ask missing
    last_price    DOUBLE,
    iv            DOUBLE,                 -- broker-reported IV (Yahoo); validate via own solver
    delta         DOUBLE,
    gamma         DOUBLE,
    theta         DOUBLE,
    vega          DOUBLE,
    volume        BIGINT,
    open_interest BIGINT,
    underlying_px DOUBLE,                 -- spot at snapshot time
    PRIMARY KEY (ticker, snapshot_ts, expiry, strike, option_right)
);

CREATE INDEX IF NOT EXISTS idx_chain_ticker_ts
    ON bot_chain_snapshots(ticker, snapshot_ts DESC);

CREATE INDEX IF NOT EXISTS idx_chain_lookup
    ON bot_chain_snapshots(ticker, expiry, strike, option_right);

-- A "latest snapshot per ticker" view — paper engine reads this for
-- entry quotes. View, not materialised; trades are infrequent enough
-- that the per-ticker DESC LIMIT 1 read is cheap.
CREATE OR REPLACE VIEW bot_chain_latest AS
SELECT s.*
FROM bot_chain_snapshots s
JOIN (
    SELECT ticker, MAX(snapshot_ts) AS max_ts
    FROM bot_chain_snapshots
    GROUP BY ticker
) m
ON s.ticker = m.ticker AND s.snapshot_ts = m.max_ts;
