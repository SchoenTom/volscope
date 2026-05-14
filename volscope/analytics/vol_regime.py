"""
6-state Vol Regime engine + Crisis-tier override.

Adapts the Gelato 5-state HMM idea to a vol-research workbench. Each
ticker (or the cross-sectional median when fitting at the universe
level) gets a daily classification into one of six states ranked by
"how rich is implied vol":

    VOL_CRUSHED → VOL_CHEAP → VOL_FAIR → VOL_RICH → VOL_EXTREME

plus an out-of-band hard-coded **VOL_CRISIS** state that overrides
the HMM whenever VIX > 40 OR per-name IV-HV-spread breaks out beyond
its own 95th-percentile band. The Crisis tier is the safety layer
that prevents long-vega entries during a vol-explosion regime even
if individual names *look* cheap.

The HMM is trained with ``hmmlearn.GaussianHMM`` (Baum-Welch / EM)
on a 6-feature input::

    [IVR z-score, IV-HV spread z, term-slope, VIX level, VIX z, RV z]

Feature scaling is done in-module so callers get pre-scaled inputs
into ``predict_proba`` without re-thinking standardisation.

Pure analytics — no DB writes. ``scripts/compute/compute_vol_regime.py``
is the nightly job that calls this module + persists results.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Sequence

import numpy as np
import pandas as pd

# Display order — higher index = richer / more extreme.
VOL_REGIMES: tuple[str, ...] = (
    "VOL_CRUSHED",
    "VOL_CHEAP",
    "VOL_FAIR",
    "VOL_RICH",
    "VOL_EXTREME",
    "VOL_CRISIS",
)

# Crisis-trigger thresholds — hard-coded, not learned.
_VIX_CRISIS_LEVEL    = 40.0
_IV_HV_SPREAD_CRISIS = 15.0   # in vol points; widens far past the 95th pct.


@dataclass(frozen=True)
class VolRegimeReport:
    """Per-(ticker, date) classification + posteriors."""
    ticker: str
    date:   pd.Timestamp
    regime: str
    posteriors: dict[str, float]
    crisis_triggered: bool
    feature_vector: np.ndarray = field(default_factory=lambda: np.zeros(6))


# ── Feature engineering ────────────────────────────────────────────

def _z_score(series: pd.Series, *, window: int = 60) -> pd.Series:
    """Rolling z-score, centred on the trailing ``window`` observations."""
    s = pd.to_numeric(series, errors="coerce")
    mean = s.rolling(window=window, min_periods=10).mean()
    std  = s.rolling(window=window, min_periods=10).std(ddof=1)
    z = (s - mean) / std.replace(0.0, np.nan)
    return z.fillna(0.0)


def compute_vol_regime_features(
    history: pd.DataFrame,
    *,
    vix_history: pd.Series | None = None,
) -> pd.DataFrame:
    """Build the 6-feature matrix the HMM consumes.

    Columns:
      ``ivr_z``         — IV rank z-score (60d rolling)
      ``iv_hv_spread_z`` — IV-HV spread z-score (60d rolling)
      ``term_slope``    — iv_60d − iv_30d, raw points (positive = contango)
      ``vix_level``     — current VIX level, raw points
      ``vix_z``         — VIX 60d z-score
      ``rv_z``          — realised vol z-score (60d rolling on hv_20d)

    The HMM expects observed values per row, NaNs are not allowed — we
    fill with zeros (the post-z-score *mean* of each feature).
    """
    if history is None or history.empty:
        return pd.DataFrame()

    h = history.copy()
    if "date" in h.columns:
        h["date"] = pd.to_datetime(h["date"])
        h = h.sort_values("date").set_index("date")

    ivr   = pd.to_numeric(h.get("iv_rank"),         errors="coerce")
    spread = pd.to_numeric(
        h.get("iv_hv_spread_matched", h.get("iv_hv_spread")),
        errors="coerce",
    )
    iv30  = pd.to_numeric(h.get("iv_30d"), errors="coerce")
    iv60  = pd.to_numeric(h.get("iv_60d"), errors="coerce")
    hv20  = pd.to_numeric(h.get("hv_20d"), errors="coerce")

    features = pd.DataFrame(index=h.index)
    features["ivr_z"]         = _z_score(ivr)
    features["iv_hv_spread_z"] = _z_score(spread)
    features["term_slope"]    = (iv60 - iv30).fillna(0.0)
    features["rv_z"]          = _z_score(hv20)

    # VIX features — broadcast across the ticker's index. When VIX
    # history is unavailable, we substitute zeros (the broad-market
    # signal degrades gracefully to a single-name-only classification).
    if vix_history is not None and not vix_history.empty:
        vix = pd.to_numeric(vix_history, errors="coerce")
        if not isinstance(vix.index, pd.DatetimeIndex):
            vix.index = pd.to_datetime(vix.index)
        vix_aligned = vix.reindex(features.index).ffill()
        features["vix_level"] = vix_aligned.fillna(20.0)
        features["vix_z"]     = _z_score(vix_aligned)
    else:
        features["vix_level"] = 20.0
        features["vix_z"]     = 0.0

    return features.fillna(0.0)


# ── HMM fit + predict ──────────────────────────────────────────────

def fit_vol_regime_hmm(
    features: pd.DataFrame,
    *,
    n_components: int = 5,
    n_iter: int = 100,
    seed: int = 42,
):
    """Train a 5-state Gaussian HMM on the feature matrix.

    Note: we use *five* learned states (Crushed → Cheap → Fair →
    Rich → Extreme); the sixth Crisis state is applied as a hard
    overlay on top of the HMM output via :func:`apply_crisis_override`.
    Separating the two preserves the HMM's probabilistic semantics
    and makes the Crisis trigger auditable.

    Requires ``hmmlearn``. Returns the fitted model OR raises
    ``ImportError`` if the dep isn't available — caller's responsibility
    to fall back to a deterministic rule-based classifier.
    """
    try:
        from hmmlearn import hmm as _hmm
    except ImportError as exc:
        raise ImportError(
            "fit_vol_regime_hmm requires `hmmlearn`. "
            "pip install hmmlearn  # already a VolScope optional dep."
        ) from exc

    if features.empty or len(features) < n_components * 5:
        raise ValueError(
            f"Need ≥ {n_components * 5} feature rows to fit a "
            f"{n_components}-state HMM; got {len(features)}."
        )

    model = _hmm.GaussianHMM(
        n_components=n_components,
        covariance_type="diag",
        n_iter=n_iter,
        random_state=seed,
        tol=1e-3,
    )
    X = features.to_numpy()
    model.fit(X)
    return model


def _order_states_by_richness(
    model,
    features: pd.DataFrame,
) -> list[int]:
    """Sort HMM state indices by "richness" of the median IV-rank z.

    The HMM learns states with arbitrary numerical labels — we re-map
    them so state 0 always corresponds to "vol crushed" (lowest median
    IVR z) and state N-1 to "vol extreme". This makes the regime
    labels stable across retrains.
    """
    posteriors = model.predict_proba(features.to_numpy())
    # For each learned state, compute the IVR z-score *weighted by
    # its posterior probability* across rows. Highest weighted z =
    # most "rich-IV" state.
    ivr_col = features.columns.get_loc("ivr_z")
    weighted_z = []
    for state_idx in range(model.n_components):
        w = posteriors[:, state_idx]
        if w.sum() < 1e-9:
            weighted_z.append(0.0)
            continue
        weighted_z.append(float(np.average(features.iloc[:, ivr_col], weights=w)))
    order = np.argsort(weighted_z)
    return order.tolist()


def predict_vol_regime(
    model,
    features: pd.DataFrame,
) -> pd.DataFrame:
    """Return per-row most-likely regime + posteriors.

    Output columns:
      ``regime``           — VOL_CRUSHED / CHEAP / FAIR / RICH / EXTREME
      ``p_vol_crushed`` … ``p_vol_extreme`` — posterior per state
    Crisis-override is *not* applied here; caller passes the result
    through :func:`apply_crisis_override` to inject CRISIS state where
    needed.
    """
    if features.empty:
        return pd.DataFrame(index=features.index)
    state_order = _order_states_by_richness(model, features)
    # state_order[0] = "crushed", state_order[-1] = "extreme"
    learned_labels = ["VOL_CRUSHED", "VOL_CHEAP", "VOL_FAIR", "VOL_RICH", "VOL_EXTREME"]
    if len(state_order) != len(learned_labels):
        # Degenerate HMM (fewer states than expected): truncate.
        learned_labels = learned_labels[: len(state_order)]

    posteriors = model.predict_proba(features.to_numpy())
    # Re-order columns: posteriors[:, state_order[i]] → labelled label i.
    ordered = posteriors[:, state_order]

    out = pd.DataFrame(
        ordered,
        index=features.index,
        columns=[f"p_{lbl.lower()}" for lbl in learned_labels],
    )
    out["regime"] = [
        learned_labels[i] for i in np.argmax(ordered, axis=1)
    ]
    # Always add the crisis-posterior column (will be 0 here, filled
    # in by ``apply_crisis_override``).
    out["p_vol_crisis"] = 0.0
    return out


def apply_crisis_override(
    regime_df: pd.DataFrame,
    *,
    iv_hv_spread: pd.Series | None = None,
    vix_level: pd.Series | None = None,
) -> pd.DataFrame:
    """Inject VOL_CRISIS on top of the HMM output.

    Two trigger paths:
      • ``vix_level > 40`` — broad-market vol explosion
      • ``|iv_hv_spread| > 15`` — single-name vol blowout

    When triggered, the row's ``regime`` is rewritten to ``VOL_CRISIS``
    and ``p_vol_crisis`` is set to 1.0 (we treat the override as a
    hard certainty; the other posteriors are renormalised to zero).
    """
    if regime_df.empty:
        return regime_df

    out = regime_df.copy()
    trigger = pd.Series(False, index=out.index)

    if vix_level is not None and not vix_level.empty:
        vix_aligned = pd.to_numeric(vix_level, errors="coerce") \
                        .reindex(out.index).ffill()
        trigger |= (vix_aligned > _VIX_CRISIS_LEVEL).fillna(False)

    if iv_hv_spread is not None and not iv_hv_spread.empty:
        sp = pd.to_numeric(iv_hv_spread, errors="coerce").reindex(out.index)
        trigger |= (sp.abs() > _IV_HV_SPREAD_CRISIS).fillna(False)

    if not trigger.any():
        return out

    out.loc[trigger, "regime"] = "VOL_CRISIS"
    # Zero out other posteriors on crisis rows; set crisis to 1.
    posterior_cols = [c for c in out.columns if c.startswith("p_")]
    for col in posterior_cols:
        if col == "p_vol_crisis":
            out.loc[trigger, col] = 1.0
        else:
            out.loc[trigger, col] = 0.0
    return out


# ── Top-level orchestration ─────────────────────────────────────────

def classify_ticker(
    ticker: str,
    history: pd.DataFrame,
    *,
    vix_history: pd.Series | None = None,
    model=None,
) -> pd.DataFrame:
    """End-to-end: features → HMM predict → crisis override.

    Returns a DataFrame indexed by date with columns ``regime``,
    ``p_vol_crushed`` … ``p_vol_crisis``. Caller persists into
    ``daily_vol`` via the upsert path.

    If ``model`` is omitted a fresh HMM is fit on this ticker's own
    history; for production use the nightly compute-job should train
    one HMM at the universe-median level and pass it in to keep
    classifications comparable across tickers.
    """
    features = compute_vol_regime_features(history, vix_history=vix_history)
    if features.empty or len(features) < 30:
        return pd.DataFrame()

    if model is None:
        try:
            model = fit_vol_regime_hmm(features)
        except (ImportError, ValueError):
            return pd.DataFrame()

    regime_df = predict_vol_regime(model, features)

    # Crisis trigger inputs.
    iv_hv = pd.to_numeric(
        history.get("iv_hv_spread_matched", history.get("iv_hv_spread")),
        errors="coerce",
    )
    if "date" in history.columns:
        iv_hv = pd.Series(
            iv_hv.values,
            index=pd.to_datetime(history["date"]),
        )
    regime_df = apply_crisis_override(
        regime_df,
        iv_hv_spread=iv_hv,
        vix_level=vix_history,
    )
    regime_df["ticker"] = ticker
    return regime_df
