-- VolScope — Migration 006 — IV Robustness quality columns.
--
-- Adds per-ticker per-date quality metrics to daily_vol, produced by
-- volscope/analytics/iv_robustness.py::assess_iv_quality and the
-- daily compute job at scripts/compute/compute_iv_quality.py.
--
-- Why on daily_vol vs a side-table: every dashboard read already
-- pulls daily_vol for IV/HV; co-locating quality avoids a join on
-- every render. Storage cost is ~8 columns × tickers × days ≈ a few
-- hundred kB total.
--
-- All columns are nullable — back-fill happens by running
-- ``make compute-iv-quality`` after this migration applies.

ALTER TABLE daily_vol ADD COLUMN IF NOT EXISTS robust_iv_rank DOUBLE;
ALTER TABLE daily_vol ADD COLUMN IF NOT EXISTS contamination_level VARCHAR;
ALTER TABLE daily_vol ADD COLUMN IF NOT EXISTS ivr_ivp_divergence DOUBLE;
ALTER TABLE daily_vol ADD COLUMN IF NOT EXISTS structural_break_date DATE;
ALTER TABLE daily_vol ADD COLUMN IF NOT EXISTS structural_break_days_ago INTEGER;
ALTER TABLE daily_vol ADD COLUMN IF NOT EXISTS structural_break_magnitude DOUBLE;
ALTER TABLE daily_vol ADD COLUMN IF NOT EXISTS iv_quality_score INTEGER;
ALTER TABLE daily_vol ADD COLUMN IF NOT EXISTS iv_recommendation VARCHAR;
ALTER TABLE daily_vol ADD COLUMN IF NOT EXISTS iv_warnings JSON;

-- Fast filtering of tradable tickers (Discover, Scanner, Bot
-- Dashboard all need this).
CREATE INDEX IF NOT EXISTS idx_iv_recommendation
    ON daily_vol(iv_recommendation);
CREATE INDEX IF NOT EXISTS idx_iv_quality_score
    ON daily_vol(iv_quality_score);
