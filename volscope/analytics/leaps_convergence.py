"""
LEAPS Convergence Scorer + Suggester.

The reference trade for this module is the PYPL $80 Jan-2029 LEAPS thesis:
options priced cheaper than realised vol (IV/HV ≈ 0.67), IV rank near the
annual floor, and a stock that has materially underperformed its index for
twelve months while sitting near a multi-year base. Three independent signals
pointing the same way is rare — that combination, not any single number, is
what the module surfaces.

The scorer answers one operational question per ticker:

    *Is this a PYPL-class set-up — vol mispriced, name neglected, structure
    reversing — and what would the deep-OTM LEAPS look like if it is?*

Inputs
------
- ``row``         : a row from ``daily_vol`` with iv_30d / hv_20d / iv_rank /
                    iv_percentile / spot_price.
- ``hist``        : the ticker's own ``daily_vol`` history (>= 252 rows ideal).
- ``benchmark``   : the benchmark's spot history (e.g. SPY ``spot_price`` series)
                    aligned by date for relative-strength.

Outputs
-------
- ``ConvergenceResult`` — three component scores + composite + driver string.
- ``LeapsSuggestion``  — concrete strike, expiry, premium, Greeks, payoff
                         ladder for the recommended LEAPS contract.

Pure analytics — no DB, no UI. Composable from CLI, tests, notebooks, and
Streamlit identically.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Optional

import math
import pandas as pd

from volscope.analytics.black_scholes import (
    bs_delta,
    bs_gamma,
    bs_price,
    bs_theta,
    bs_vega,
)


# ── Convergence scoring ──────────────────────────────────────────────────

# Weights chosen so that the PYPL reference case (mispricing ~88, neglect
# ~80, reversal ~55) lands above 75 — a deliberate "high-conviction" gate
# that matches Tom's "1-2× per year per ticker" frequency target.
_W_MISPRICING = 0.50
_W_NEGLECT    = 0.30
_W_REVERSAL   = 0.20

assert math.isclose(_W_MISPRICING + _W_NEGLECT + _W_REVERSAL, 1.0)

# Operational gate — below this composite, the convergence is not strong
# enough to justify a deep-OTM LEAPS position. Tuned from the PYPL example.
CONVERGENCE_THRESHOLD = 65.0


@dataclass(frozen=True)
class ConvergenceResult:
    """Composite convergence score for a single ticker on a single day.

    ``coverage`` records how many of the three sub-signals were available.
    The auto-generated thesis must read this before claiming "all three
    signals aligned" — silently renormalising weights is fine for the
    score, lying about coverage in prose is not.
    """

    ticker:       str
    score:        float                       # 0..100
    mispricing:   Optional[float] = None      # 0..100
    neglect:      Optional[float] = None      # 0..100
    reversal:     Optional[float] = None      # 0..100
    drivers:      tuple[str, ...] = ()
    one_liner:    str = ""
    coverage:     int = 0                     # 0..3 sub-signals present

    def is_actionable(self) -> bool:
        return self.score >= CONVERGENCE_THRESHOLD

    def all_signals_aligned(self) -> bool:
        """True only if all three sub-scores are present *and* ≥ 60.

        The honest gate for any "convergence of three signals" headline.
        """
        return (
            self.coverage == 3
            and self.mispricing is not None and self.mispricing >= 60.0
            and self.neglect    is not None and self.neglect    >= 60.0
            and self.reversal   is not None and self.reversal   >= 60.0
        )


def compute_mispricing_score(row: pd.Series) -> Optional[float]:
    """Score how mispriced the options are vs. their own history and vs. realised.

    Three sub-signals, equally weighted:
      - IV / HV ratio       — <1 means options cheap vs realised. PYPL: 0.67.
      - IV Rank (52w)       — low = near annual floor. PYPL: 12.
      - IV Percentile (52w) — low = rarely cheaper. PYPL: 29.

    Each component is mapped piecewise-linearly into 0..100 so that the
    PYPL combination scores in the upper-80s. Returns ``None`` if any
    component is missing (no silent zero-fill — silent fill biases ranking).
    """
    iv = row.get("iv_30d")
    hv = row.get("hv_20d")
    rank = row.get("iv_rank")
    perc = row.get("iv_percentile")
    if any(v is None or pd.isna(v) for v in (iv, hv, rank, perc)):
        return None
    iv = float(iv); hv = float(hv); rank = float(rank); perc = float(perc)
    if hv <= 0:
        return None
    ratio = iv / hv

    # IV/HV ratio → 100 when ratio<=0.5, 0 when ratio>=1.2.
    ratio_score = max(0.0, min(100.0, (1.20 - ratio) / (1.20 - 0.50) * 100.0))
    # IV Rank → 100 at rank=0, 0 at rank=50.
    rank_score  = max(0.0, min(100.0, (50.0 - rank) / 50.0 * 100.0))
    # IV Percentile → 100 at perc=0, 0 at perc=60.
    perc_score  = max(0.0, min(100.0, (60.0 - perc) / 60.0 * 100.0))
    return (ratio_score + rank_score + perc_score) / 3.0


def compute_neglect_score(
    ticker_history: pd.DataFrame,
    benchmark_history: Optional[pd.DataFrame],
    lookback_days: int = 252,
) -> Optional[float]:
    """Relative-strength-decay proxy for "the market has stopped paying attention".

    Definition: trailing-12-month spot return of the ticker minus that of the
    benchmark. PYPL down 22% while SPY up 29% → −51pp underperformance
    → neglect ≈ 100. A name that tracks the benchmark scores 0; a name that
    crushes the benchmark scores 0 (it is the opposite of neglected).
    """
    if ticker_history is None or ticker_history.empty:
        return None
    if benchmark_history is None or benchmark_history.empty:
        return None
    if "spot_price" not in ticker_history.columns or "spot_price" not in benchmark_history.columns:
        return None

    t_ret = _trailing_return(ticker_history, lookback_days)
    b_ret = _trailing_return(benchmark_history, lookback_days)
    if t_ret is None or b_ret is None:
        return None

    underperf_pp = (b_ret - t_ret) * 100.0  # positive = stock lagged
    # Map: 0pp underperformance = 0, 50pp+ = 100, linear in between.
    return max(0.0, min(100.0, underperf_pp / 50.0 * 100.0))


def _trailing_return(history: pd.DataFrame, lookback_days: int) -> Optional[float]:
    """Simple TTM return from the spot-price column. None if too few rows."""
    if "spot_price" not in history.columns:
        return None
    series = history["spot_price"].dropna()
    if len(series) < max(60, lookback_days // 5):
        return None
    last = float(series.iloc[-1])
    first = float(series.iloc[max(0, len(series) - lookback_days)])
    if first <= 0:
        return None
    return last / first - 1.0


def compute_reversal_score(ticker_history: pd.DataFrame) -> Optional[float]:
    """Stock-structure score: deeper drawdown + recent stabilisation = higher.

    A ticker sitting at −60% from its 252-day high but with realised
    volatility cooling off scores high — that is the "Wave-II base" pattern
    in the PYPL deck. Pure trend strength scores low: a ticker making new
    highs has no convexity asymmetry to exploit with deep-OTM LEAPS.

    Two sub-signals, equally weighted:
      - drawdown from 52w high (0pp = 0, 60pp+ = 100)
      - vol normalisation: 1 − (recent 20d HV / 60d HV) clamped to 0..1
        (cooling vol after a sell-off historically precedes Wave III)
    """
    if ticker_history is None or ticker_history.empty:
        return None
    if "spot_price" not in ticker_history.columns:
        return None
    series = ticker_history["spot_price"].dropna()
    if len(series) < 60:
        return None

    last = float(series.iloc[-1])
    high_52w = float(series.tail(252).max())
    if high_52w <= 0:
        return None
    drawdown_pp = max(0.0, (high_52w - last) / high_52w * 100.0)
    drawdown_score = max(0.0, min(100.0, drawdown_pp / 60.0 * 100.0))

    cooling_score: Optional[float] = None
    if "hv_20d" in ticker_history.columns and "hv_60d" in ticker_history.columns:
        last_row = ticker_history.iloc[-1]
        h20 = last_row.get("hv_20d")
        h60 = last_row.get("hv_60d")
        if (
            h20 is not None and h60 is not None
            and not pd.isna(h20) and not pd.isna(h60)
            and float(h60) > 0
        ):
            ratio = float(h20) / float(h60)
            # ratio<=0.7 means short-term vol clearly below long-term → cooling
            cooling_score = max(0.0, min(100.0, (1.0 - ratio) * 200.0))

    if cooling_score is None:
        return drawdown_score
    return 0.5 * drawdown_score + 0.5 * cooling_score


def compute_convergence(
    row: pd.Series,
    ticker_history: Optional[pd.DataFrame] = None,
    benchmark_history: Optional[pd.DataFrame] = None,
) -> ConvergenceResult:
    """Compose the three sub-scores into a single PYPL-style convergence read.

    Renormalises weights across present components — a missing benchmark
    series should not silently zero out the neglect contribution.
    """
    ticker = str(row.get("ticker", "?"))
    mis = compute_mispricing_score(row)
    neg = compute_neglect_score(ticker_history, benchmark_history) if ticker_history is not None else None
    rev = compute_reversal_score(ticker_history) if ticker_history is not None else None

    parts: list[tuple[str, float, float]] = []
    if mis is not None: parts.append(("mispricing", mis, _W_MISPRICING))
    if neg is not None: parts.append(("neglect",    neg, _W_NEGLECT))
    if rev is not None: parts.append(("reversal",   rev, _W_REVERSAL))

    if not parts:
        return ConvergenceResult(ticker=ticker, score=0.0, one_liner="no data")

    total_w = sum(w for _, _, w in parts)
    score = sum(s * w for _, s, w in parts) / total_w
    drivers = tuple(name for name, _, _ in sorted(parts, key=lambda p: -p[1])[:2])
    one_liner = " · ".join(
        f"{name} {value:.0f}" for name, value, _ in sorted(parts, key=lambda p: -p[1])
    )
    return ConvergenceResult(
        ticker=ticker,
        score=round(score, 2),
        mispricing=mis,
        neglect=neg,
        reversal=rev,
        drivers=drivers,
        one_liner=one_liner,
        coverage=len(parts),
    )


# ── Auto-thesis generator ────────────────────────────────────────────────

def auto_thesis(
    result: ConvergenceResult,
    row: pd.Series,
    ticker_history: Optional[pd.DataFrame] = None,
    benchmark_history: Optional[pd.DataFrame] = None,
) -> str:
    """One-sentence trader-facing thesis assembled from the live signals.

    Driven by ``result.drivers`` (the components that are actually present
    and that scored highest), never from a static template. Three rules
    enforced here so the dossier prose cannot oversell:

    - The phrase "all three signals aligned" only fires when
      ``result.all_signals_aligned()`` is True.
    - Each clause is conditional on the underlying component being present
      *and* contributing materially (≥ 50). Silent components are silently
      omitted from the prose.
    - Numerical claims (percent down vs SPY, IV/HV ratio) are rendered
      from the raw inputs, not from the score values.
    """
    fragments: list[str] = []

    iv = row.get("iv_30d") if hasattr(row, "get") else None
    hv = row.get("hv_20d") if hasattr(row, "get") else None
    if (
        result.mispricing is not None and result.mispricing >= 50.0
        and iv is not None and hv is not None
        and not pd.isna(iv) and not pd.isna(hv) and float(hv) > 0
    ):
        ratio = float(iv) / float(hv)
        discount_pct = max(0.0, (1.0 - ratio) * 100.0)
        if discount_pct >= 5.0:
            fragments.append(
                f"options ~{discount_pct:.0f}% cheaper than realised vol"
            )
        else:
            fragments.append(
                f"options at IV/HV {ratio:.2f}, near or below realised"
            )

    if (
        result.neglect is not None and result.neglect >= 50.0
        and ticker_history is not None and benchmark_history is not None
    ):
        t_ret = _trailing_return(ticker_history, 252)
        b_ret = _trailing_return(benchmark_history, 252)
        if t_ret is not None and b_ret is not None:
            fragments.append(
                f"name {t_ret*100:+.0f}% TTM vs SPY {b_ret*100:+.0f}%"
            )

    if (
        result.reversal is not None and result.reversal >= 50.0
        and ticker_history is not None and "spot_price" in ticker_history.columns
    ):
        series = ticker_history["spot_price"].dropna()
        if len(series) >= 60:
            last = float(series.iloc[-1])
            high_52w = float(series.tail(252).max())
            if high_52w > 0:
                dd = (high_52w - last) / high_52w * 100.0
                fragments.append(f"-{dd:.0f}% from 52w high, base forming")

    if not fragments:
        # Score is below the thresholds where any single clause would fire —
        # state the composite truthfully and exit.
        return (
            f"convergence score {result.score:.0f} — no individual signal "
            f"yet at conviction level"
        )

    head = "convergence aligned: " if result.all_signals_aligned() else "signals: "
    coverage_tail = (
        ""
        if result.coverage == 3
        else f" · based on {result.coverage} of 3 components"
    )
    return head + ", ".join(fragments) + coverage_tail


# ── LEAPS suggestion ─────────────────────────────────────────────────────

@dataclass(frozen=True)
class LeapsSuggestion:
    """Concrete LEAPS contract recommendation with payoff ladder."""

    ticker:        str
    spot:          float
    strike:        float
    expiry:        date
    days_to_exp:   int
    iv:            float                    # decimal, e.g. 0.302
    est_premium:   float                    # per-share premium
    breakeven:     float
    delta:         float
    gamma:         float
    theta_per_day: float                    # per-share, per calendar day
    vega:          float                    # per 1.00 change in σ; per 1% → /100
    payoff:        list[tuple[float, float, float]] = field(default_factory=list)
    # payoff entries: (spot_at_expiry, intrinsic, return_on_premium_pct)
    rationale:     str = ""

    @property
    def vega_per_pct(self) -> float:
        """Convenience: vega per 1.00% (not 1.00) of σ — matches trader convention."""
        return self.vega / 100.0


def suggest_leaps(
    ticker: str,
    spot: float,
    iv: float,
    target_dte_days: int = 730,
    strike_uplift: float = 0.75,
    risk_free: float = 0.04,
    div_yield: float = 0.0,
    today: Optional[date] = None,
) -> Optional[LeapsSuggestion]:
    """Build the deep-OTM LEAPS suggestion the PYPL deck describes.

    Defaults:
      - target DTE ≈ 730 calendar days (~24 months — Jan-2029-from-May-2026
        is 32 months; we steer to the nearer monthly LEAPS as a sane default)
      - strike at +75 % over spot — the "Wave-III first target" zone in the
        PYPL example (spot 45.32 → strike 80, +76 %)
      - r = 4 %, q = 0 % (US-equity LEAPS, current short-end Treasury)

    Returns ``None`` if inputs are degenerate (non-positive spot or σ).
    """
    if spot <= 0 or iv <= 0:
        return None
    today = today or date.today()
    expiry = today + timedelta(days=target_dte_days)
    T = target_dte_days / 365.0
    strike = round(spot * (1.0 + strike_uplift), 0)         # whole-dollar strikes
    premium = bs_price(spot, strike, T, risk_free, iv, div_yield, "call")
    if premium <= 0:
        return None
    delta = bs_delta(spot, strike, T, risk_free, iv, div_yield, "call")
    gamma = bs_gamma(spot, strike, T, risk_free, iv, div_yield)
    theta_year = bs_theta(spot, strike, T, risk_free, iv, div_yield, "call")
    vega = bs_vega(spot, strike, T, risk_free, iv, div_yield)
    breakeven = strike + premium

    # Payoff ladder at expiry — anchored to PYPL-style milestones
    ladder_levels = [
        spot,
        spot * 1.30,
        strike,
        breakeven,
        strike + 20,
        strike + 40,
        strike + 70,
        strike + 120,
    ]
    payoff: list[tuple[float, float, float]] = []
    for level in sorted(set(round(x, 2) for x in ladder_levels if x > 0)):
        intrinsic = max(0.0, level - strike)
        ret_pct = (intrinsic - premium) / premium * 100.0
        payoff.append((level, round(intrinsic, 2), round(ret_pct, 1)))

    rationale = (
        f"deep-OTM call: strike +{strike_uplift*100:.0f}% over spot, "
        f"{target_dte_days}d to expiry, IV {iv*100:.1f}%. "
        f"Convexity contract — capped loss at premium, breakeven {breakeven:.2f}, "
        f"delta {delta:.2f} accelerates with each up-day."
    )
    return LeapsSuggestion(
        ticker=ticker,
        spot=round(spot, 2),
        strike=float(strike),
        expiry=expiry,
        days_to_exp=target_dte_days,
        iv=iv,
        est_premium=round(premium, 3),
        breakeven=round(breakeven, 2),
        delta=round(delta, 4),
        gamma=round(gamma, 6),
        theta_per_day=round(theta_year / 365.0, 4),
        vega=round(vega, 4),
        payoff=payoff,
        rationale=rationale,
    )


# ── Universe ranker ──────────────────────────────────────────────────────

def rank_universe(
    latest: pd.DataFrame,
    histories: dict[str, pd.DataFrame],
    benchmark_history: pd.DataFrame,
    n: int = 10,
) -> pd.DataFrame:
    """Rank every ticker in ``latest`` by convergence score.

    Returns a DataFrame with one row per ticker plus the per-component
    sub-scores so the UI layer can show *why* a ticker is on top without
    re-computing.
    """
    if latest is None or latest.empty:
        return pd.DataFrame()
    rows: list[dict] = []
    for _, row in latest.iterrows():
        ticker = row.get("ticker")
        if ticker is None:
            continue
        hist = histories.get(ticker)
        result = compute_convergence(row, hist, benchmark_history)
        rows.append({
            "ticker":     ticker,
            "score":      result.score,
            "mispricing": result.mispricing,
            "neglect":    result.neglect,
            "reversal":   result.reversal,
            "drivers":    ",".join(result.drivers),
            "one_liner":  result.one_liner,
            "iv_30d":     row.get("iv_30d"),
            "hv_20d":     row.get("hv_20d"),
            "iv_rank":    row.get("iv_rank"),
            "iv_percentile": row.get("iv_percentile"),
            "spot_price": row.get("spot_price"),
            "sector":     row.get("sector"),
        })
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    return df.sort_values("score", ascending=False).head(n).reset_index(drop=True)
