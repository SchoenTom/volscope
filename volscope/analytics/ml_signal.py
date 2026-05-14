"""
ML Mean-Reversion Signal — logistic regression on vol features.

Answers: "Based on historical patterns, how likely is it that IV falls
over the next 10 trading days?"

Two signals already tell the trader whether vol is cheap today (IV percentile
+ VRP). This module adds a THIRD: does the data historically support IV
mean-reverting from the current level?

The model is a L2-regularised logistic regression trained per-ticker on the
full local history.  It is retrained on every call so there is nothing to
serialize — the model is always fresh, always reflects the current DB state.
No internet access needed at inference time.

Dependencies: numpy + scipy only (no scikit-learn).

Design decisions
----------------
- One model per ticker (not cross-ticker) — vol regimes differ too much.
- Training minimum: 60 rows after valid-target masking.  Below that, return
  None rather than produce unreliable estimates.
- Features are standardised (zero-mean, unit-variance) before fitting.
  NaN features are imputed with the column median from the training set.
- L2 penalty (λ=0.1) prevents overfitting on short histories.
- Output: P(IV falls in next 10 trading days) ∈ [0, 1].
"""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from typing import Optional

import numpy as np
import pandas as pd
from scipy.optimize import minimize
from scipy.special import expit  # numerically-stable sigmoid

log = logging.getLogger(__name__)

# ── Tuning knobs ──────────────────────────────────────────────────────────
_MIN_TRAIN_ROWS = 60    # fewer valid training rows → refuse to predict
_HOLD_DAYS      = 10    # forecast horizon: "does IV fall in the next N days?"
_L2_LAMBDA      = 0.1   # L2 regularization strength (C = 1/λ ≈ 10 in sklearn terms)

# Features extracted from daily_vol history (in order).
# vrp and iv_change_7d are derived columns added by _build_features().
_FEATURE_COLS: tuple[str, ...] = (
    "iv_percentile",
    "vrp",
    "iv_rank",
    "iv_change_7d",
    "put_call_ratio",
)


# ---------------------------------------------------------------------------
# Output type
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class MLPrediction:
    """
    Immutable ML signal output for a single ticker.

    Attributes
    ----------
    ticker        : Ticker symbol.
    date          : Date of the feature vector (most recent row in history).
    buy_prob      : P(IV falls in next 10d) ∈ [0, 1].
    n_train       : Number of rows used in training (after NaN/target masking).
    features_used : Names of features that were non-null in the latest row.
    """
    ticker:        str
    date:          object
    buy_prob:      float
    n_train:       int
    features_used: tuple[str, ...]


# ---------------------------------------------------------------------------
# Feature engineering
# ---------------------------------------------------------------------------

def _build_features(history: pd.DataFrame) -> pd.DataFrame:
    """
    Derive the feature matrix from a ticker's daily_vol history.

    Adds two derived columns:
      - vrp           = iv_30d / hv_20d  (NaN when hv_20d == 0)
      - iv_change_7d  = iv_percentile.diff(7)

    Selects _FEATURE_COLS that are present in the DataFrame.
    Returns a DataFrame with columns ['date'] + available feature columns,
    sorted by date ascending.

    Parameters
    ----------
    history : pd.DataFrame
        Full daily_vol history for one ticker.

    Returns
    -------
    pd.DataFrame
    """
    df = history.copy().sort_values("date").reset_index(drop=True)

    # Variance Risk Premium
    if "iv_30d" in df.columns and "hv_20d" in df.columns:
        iv_arr = df["iv_30d"].values.astype(float)
        hv_arr = df["hv_20d"].values.astype(float)
        with np.errstate(divide="ignore", invalid="ignore"):
            vrp = np.where(hv_arr > 0, iv_arr / hv_arr, np.nan)
        df["vrp"] = vrp
    else:
        df["vrp"] = np.nan

    # 7-day IV percentile momentum
    if "iv_percentile" in df.columns:
        df["iv_change_7d"] = df["iv_percentile"].diff(7)
    else:
        df["iv_change_7d"] = np.nan

    available = [c for c in _FEATURE_COLS if c in df.columns]
    return df[["date"] + available].copy()


# ---------------------------------------------------------------------------
# Target construction
# ---------------------------------------------------------------------------

def _build_targets(history: pd.DataFrame, hold_days: int = _HOLD_DAYS) -> pd.Series:
    """
    Build binary classification targets.

    y[i] = 1  if  iv_30d[i + hold_days] < iv_30d[i]   (IV mean-reverted down)
    y[i] = 0  if  iv_30d[i + hold_days] >= iv_30d[i]
    y[i] = NaN for the last `hold_days` rows (no future data).

    Parameters
    ----------
    history : pd.DataFrame
        Daily_vol history sorted by date.
    hold_days : int
        Forward window (default: 10 trading days).

    Returns
    -------
    pd.Series
        Float series with same index as history (after sorting).
        NaN for rows without a valid future target.
    """
    if "iv_30d" not in history.columns:
        return pd.Series(dtype=float)

    df = history.copy().sort_values("date").reset_index(drop=True)
    iv = df["iv_30d"].values.astype(float)
    target = np.full(len(iv), np.nan)

    for i in range(len(iv) - hold_days):
        curr = iv[i]
        futr = iv[i + hold_days]
        if math.isnan(curr) or curr == 0 or math.isnan(futr):
            continue
        target[i] = 1.0 if futr < curr else 0.0

    return pd.Series(target, index=df.index)


# ---------------------------------------------------------------------------
# Logistic regression kernel (pure numpy / scipy)
# ---------------------------------------------------------------------------

def _nll_l2(theta: np.ndarray, X: np.ndarray, y: np.ndarray, lam: float) -> float:
    """Negative log-likelihood + L2 penalty (bias excluded from penalty)."""
    z = X @ theta
    p = np.clip(expit(z), 1e-10, 1 - 1e-10)
    nll = -np.mean(y * np.log(p) + (1 - y) * np.log(1 - p))
    reg = lam * float(np.dot(theta[1:], theta[1:]))  # bias at index 0
    return nll + reg


def _nll_l2_grad(theta: np.ndarray, X: np.ndarray, y: np.ndarray, lam: float) -> np.ndarray:
    """Gradient of NLL + L2."""
    z   = X @ theta
    err = expit(z) - y
    grad = X.T @ err / len(y)
    reg_grad = np.concatenate([[0.0], 2.0 * lam * theta[1:]])
    return grad + reg_grad


def _fit_logistic(
    X: np.ndarray,
    y: np.ndarray,
    lam: float = _L2_LAMBDA,
) -> Optional[np.ndarray]:
    """
    Fit L2-regularised logistic regression via L-BFGS-B.

    Parameters
    ----------
    X : np.ndarray, shape (n_samples, n_features)
        Design matrix.  Column 0 must be the bias (all ones).
    y : np.ndarray, shape (n_samples,)
        Binary labels (0.0 or 1.0).
    lam : float
        L2 regularisation strength.

    Returns
    -------
    np.ndarray | None
        Coefficient vector theta (intercept first), or None on failure /
        degenerate input (< 2 rows).
    """
    if X.shape[0] < 2 or X.ndim != 2 or X.shape[1] < 1:
        return None

    theta0 = np.zeros(X.shape[1])
    try:
        result = minimize(
            fun=_nll_l2,
            x0=theta0,
            args=(X, y, lam),
            jac=_nll_l2_grad,
            method="L-BFGS-B",
            options={"maxiter": 300, "ftol": 1e-9, "gtol": 1e-6},
        )
        if result.success or result.fun < 2.0:
            return result.x
    except Exception as exc:
        log.debug("Logistic regression failed: %s", exc)
    return None


# ---------------------------------------------------------------------------
# Standardisation helpers
# ---------------------------------------------------------------------------

def _standardize(
    X: np.ndarray,
    mean: np.ndarray,
    std: np.ndarray,
) -> np.ndarray:
    """Standardise X using pre-computed mean and std (safe: std=0 → no scaling)."""
    safe_std = np.where(std > 0, std, 1.0)
    return (X - mean) / safe_std


def _impute_median(
    X: np.ndarray,
    medians: np.ndarray,
) -> np.ndarray:
    """Replace NaN entries with column medians."""
    out = X.copy()
    for col in range(X.shape[1]):
        mask = np.isnan(out[:, col])
        if mask.any():
            out[mask, col] = medians[col]
    return out


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def predict_buy_prob(
    ticker: str,
    history: pd.DataFrame,
    hold_days: int = _HOLD_DAYS,
) -> Optional[MLPrediction]:
    """
    Train a logistic regression on the ticker's full history and predict
    P(IV falls in next ``hold_days`` trading days) for the most recent row.

    The model is trained fresh on every call — no serialisation or caching.
    This keeps predictions current with the latest DB state and avoids
    stale-model issues after new scrapes.

    Parameters
    ----------
    ticker : str
        Ticker symbol (stored in the output for display).
    history : pd.DataFrame
        Full daily_vol history for this ticker (from db.get_ticker_history or
        db.get_recent_for_tickers with a long lookback).
        Must contain at least iv_30d plus some feature columns.
    hold_days : int
        Forward window in trading days.  Default: 10.

    Returns
    -------
    MLPrediction | None
        None when:
        - history is empty
        - iv_30d column is missing (can't build targets)
        - fewer than _MIN_TRAIN_ROWS valid training rows remain after masking
        - the optimiser fails to converge
    """
    if history is None or history.empty:
        return None

    feat_df = _build_features(history)
    target  = _build_targets(history, hold_days)

    if feat_df.empty or target.empty:
        return None

    feat_cols = [c for c in feat_df.columns if c != "date"]
    if not feat_cols:
        return None

    X_raw = feat_df[feat_cols].values.astype(float)
    y_raw = target.values.astype(float)

    # Rows where target is labelled AND at least one feature is non-NaN
    valid_target = ~np.isnan(y_raw)
    any_feature  = ~np.all(np.isnan(X_raw), axis=1)
    train_mask   = valid_target & any_feature

    X_train_raw = X_raw[train_mask]
    y_train     = y_raw[train_mask]

    if len(y_train) < _MIN_TRAIN_ROWS:
        log.debug(
            "Skipping ML for %s: only %d valid training rows (need %d)",
            ticker, len(y_train), _MIN_TRAIN_ROWS,
        )
        return None

    # Impute missing features with column medians from training set.
    # ``nanmedian`` warns "All-NaN slice encountered" when a feature column
    # is entirely NaN (sparse-feature ticker on first few days). The
    # subsequent np.where replaces those NaN medians with 0, which is the
    # correct silent fallback — suppress the warning so it does not noise
    # production logs.
    with np.errstate(all="ignore"):
        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", category=RuntimeWarning)
            col_medians = np.nanmedian(X_train_raw, axis=0)
    col_medians = np.where(np.isnan(col_medians), 0.0, col_medians)
    X_train_imp = _impute_median(X_train_raw, col_medians)

    # Standardise
    mean = X_train_imp.mean(axis=0)
    std  = X_train_imp.std(axis=0)
    X_train_std = _standardize(X_train_imp, mean, std)

    # Add bias column
    X_train = np.column_stack([np.ones(len(X_train_std)), X_train_std])

    theta = _fit_logistic(X_train, y_train)
    if theta is None:
        return None

    # Predict for the most recent row
    latest_raw = X_raw[-1]
    latest_imp = _impute_median(latest_raw.reshape(1, -1), col_medians)[0]
    latest_std = _standardize(latest_imp, mean, std)
    latest_x   = np.concatenate([[1.0], latest_std])

    buy_prob = float(expit(np.dot(theta, latest_x)))

    # Which features were non-null in the latest row?
    features_used = tuple(
        feat_cols[j] for j in range(len(feat_cols))
        if not np.isnan(latest_raw[j])
    )

    latest_date = history.sort_values("date").iloc[-1]["date"]

    return MLPrediction(
        ticker=ticker,
        date=latest_date,
        buy_prob=round(buy_prob, 4),
        n_train=int(len(y_train)),
        features_used=features_used,
    )


# ---------------------------------------------------------------------------
# Display
# ---------------------------------------------------------------------------

_BADGE_MONO = "JetBrains Mono, SF Mono, Menlo, monospace"


def ml_badge_html(pred: Optional[MLPrediction]) -> str:
    """
    Return a compact HTML badge showing the ML buy probability.

    Designed to sit as a small subtitle below the VolSignal badge on
    Command Center cards.  Returns an empty string when pred is None
    so callers can safely concatenate without branching.

    Colour coding:
      p ≥ 0.65  → green  · "ML BUY · XX%"
      p ≥ 0.50  → blue   · "ML LEAN · XX%"
      p ≥ 0.35  → muted  · "ML NEUTRAL · XX%"
      p <  0.35 → amber  · "ML WAIT · XX%"

    Parameters
    ----------
    pred : MLPrediction | None

    Returns
    -------
    str
        Self-contained ``<div>`` HTML fragment, or "" if pred is None.
    """
    if pred is None:
        return ""

    pct = int(round(pred.buy_prob * 100))

    if pred.buy_prob >= 0.65:
        color = "#00d4aa"   # green
        label = f"ML BUY · {pct}%"
    elif pred.buy_prob >= 0.50:
        color = "#7db4ff"   # blue-ish
        label = f"ML LEAN · {pct}%"
    elif pred.buy_prob >= 0.35:
        color = "#8a8f9e"   # muted gray
        label = f"ML NEUTRAL · {pct}%"
    else:
        color = "#ff9f43"   # amber
        label = f"ML WAIT · {pct}%"

    return (
        f'<div style="display:flex;align-items:center;gap:6px;margin:2px 0 8px 0;'
        f'font-family:{_BADGE_MONO};font-size:10px;">'
        f'<div style="background:{color}22;border-left:2px solid {color};'
        f'border-radius:3px;padding:3px 8px;color:{color};font-weight:600;'
        f'letter-spacing:0.02em;">'
        f'{label}'
        f'</div>'
        f'<span style="color:#8a8f9e;font-size:9px;">'
        f'n={pred.n_train}'
        f'</span>'
        f'</div>'
    )
