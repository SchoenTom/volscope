-- VolScope — Migration 008 — 6-state Vol Regime classification.
--
-- Stores the most-likely regime label for each (ticker, date) plus the
-- six per-regime posterior probabilities so the operator can see how
-- *confident* the HMM is, not just its mode.
--
-- The six states are vol-semantic, not equity-rotation-semantic:
--   1. VOL_CRUSHED    — IV rank < 10, IVR z < -1.5
--   2. VOL_CHEAP      — IV rank 10–30
--   3. VOL_FAIR       — IV rank 30–70
--   4. VOL_RICH       — IV rank 70–90
--   5. VOL_EXTREME    — IV rank > 90, IVR z > +2
--   6. VOL_CRISIS     — VIX > 40 OR single-name IV-HV breakout
--
-- Source of truth for the labels: ``volscope.analytics.vol_regime``.
-- The Crisis tier is a *hard override* — when triggered it
-- supersedes the HMM's chosen state and the Discover page filters
-- long-vega entries from the Cheap / Crushed signals.
--
-- Defensive CREATE for test-DB compatibility (same pattern as 006 / 007).

CREATE TABLE IF NOT EXISTS daily_vol (
    ticker VARCHAR NOT NULL,
    date   DATE NOT NULL,
    PRIMARY KEY (ticker, date)
);

-- Most-likely state label.
ALTER TABLE daily_vol ADD COLUMN IF NOT EXISTS vol_regime VARCHAR;

-- HMM posterior probabilities for each state, in display order.
ALTER TABLE daily_vol ADD COLUMN IF NOT EXISTS p_vol_crushed DOUBLE;
ALTER TABLE daily_vol ADD COLUMN IF NOT EXISTS p_vol_cheap   DOUBLE;
ALTER TABLE daily_vol ADD COLUMN IF NOT EXISTS p_vol_fair    DOUBLE;
ALTER TABLE daily_vol ADD COLUMN IF NOT EXISTS p_vol_rich    DOUBLE;
ALTER TABLE daily_vol ADD COLUMN IF NOT EXISTS p_vol_extreme DOUBLE;
ALTER TABLE daily_vol ADD COLUMN IF NOT EXISTS p_vol_crisis  DOUBLE;

-- Scanner-side index — Discover page filters rows by regime cheaply.
CREATE INDEX IF NOT EXISTS idx_vol_regime ON daily_vol (vol_regime);
