-- VolScope — Migration 007 — Matched-horizon HV column.
--
-- The v0.7.x line addresses an academic-correctness concern in the
-- IV-HV spread metric. Up to v0.7.0, ``iv_hv_spread`` was defined as
-- ``iv_30d - hv_20d`` where ``hv_20d`` is close-to-close (Christensen-
-- Prabhala 1998 uses Parkinson HV at *22* trading days = ~1 calendar
-- month). Comparing 30-day implied vol against 20-day realised vol is
-- a horizon mismatch (~2 Vol-Punkte typischer Bias).
--
-- Fix: add ``hv_yz_30d`` (Yang-Zhang at the matched 30-day window) and
-- the derived ``iv_hv_spread_matched``. The legacy ``hv_20d`` and
-- ``iv_hv_spread`` columns stay so existing scanner / discover logic
-- keeps working until v0.8.0 migrates it. Backward-compatible.
--
-- Yang-Zhang as the estimator family: drift-independent, handles
-- overnight gaps, ~7x more efficient than close-close on the
-- Yang-Zhang 2000 efficiency derivation. Industry default for daily
-- OHLC equity data.
--
-- Defensive CREATE: same pattern as migration 006. On test DBs that
-- only run migrations (no production VolScopeDB bootstrap), this
-- creates the minimal table; on production it is a no-op.

CREATE TABLE IF NOT EXISTS daily_vol (
    ticker        VARCHAR NOT NULL,
    date          DATE NOT NULL,
    iv_30d        DOUBLE,
    iv_rank       DOUBLE,
    iv_percentile DOUBLE,
    PRIMARY KEY (ticker, date)
);

-- Matched-horizon HV (Yang-Zhang, 30 trading days).
ALTER TABLE daily_vol ADD COLUMN IF NOT EXISTS hv_yz_30d DOUBLE;

-- IV30 - HV_YZ_30d. Academically correct apples-to-apples spread.
ALTER TABLE daily_vol ADD COLUMN IF NOT EXISTS iv_hv_spread_matched DOUBLE;

-- Scanner-side index for the matched spread; cheap to add now while
-- the column is mostly NULL so it doesn't block backfill.
CREATE INDEX IF NOT EXISTS idx_iv_hv_spread_matched
    ON daily_vol (iv_hv_spread_matched);
