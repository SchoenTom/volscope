"""
Bidirectional IV mean-reversion signal generator.

Scans the universe and produces a list of trade signals tagged
``LONG_VOL`` / ``SHORT_VOL`` / ``NEUTRAL``. Each signal carries:

  - direction + confidence (0-100)
  - signal_type    (TRIPLE_CHEAP, LOW_RANK, TRIPLE_RICH, HIGH_RANK)
  - strategy       (Long Call (LEAPS), Iron Condor, …)
  - params         (strikes, DTE, estimated credit, POP, …)
  - reason         (human-readable one-liner)
  - earnings_warning (True when an upcoming print would filter out
                      short-vol trades)

Earnings filter rule (academic basis):
  Never recommend short premium when the next earnings event is
  within 14 days. The post-earnings IV crush is asymmetric and
  short-vol trades into binary catalysts have the worst
  risk-adjusted edge.

Column mapping vs spec:
  The original spec referenced ``iv_perc`` and ``hv_20d_yz``. In
  VolScope's actual schema these are ``iv_percentile`` and
  ``hv_yz_20d`` (with ``hv_20d`` as fallback). All other columns
  align.

References:
  Bali et al., *Idiosyncratic Volatility and the Cross-Section of
  Returns*, JFE (2008).
  Cohen & Donohue, *Iron Condor strategy outperforms naive premium
  selling*, MDPI Risks (2024).
"""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Optional

import pandas as pd

log = logging.getLogger(__name__)


# ── Thresholds (research-anchored, tunable) ──────────────────────────

_LONG_VOL_PERC_TRIPLE = 20.0     # IV percentile cutoff for "triple cheap"
_LONG_VOL_RATIO_TRIPLE = 0.75    # IV/HV ratio cutoff
_LONG_VOL_PERC_RANK   = 30.0     # IV percentile cutoff for "low rank" tier
_LONG_VOL_RANK_RANK   = 15.0

_SHORT_VOL_PERC_TRIPLE = 80.0
_SHORT_VOL_RATIO_TRIPLE = 1.20
_SHORT_VOL_PERC_RANK   = 70.0
_SHORT_VOL_RANK_RANK   = 50.0

_ER_FILTER_DAYS = 14


# ── Output type ──────────────────────────────────────────────────────

@dataclass(frozen=True)
class Signal:
    ticker:           str
    direction:        str            # 'LONG_VOL' | 'SHORT_VOL' | 'NEUTRAL'
    confidence:       float          # 0..100
    signal_type:      str            # e.g. 'TRIPLE_CHEAP'
    strategy:         str
    params:           dict
    reason:           str
    earnings_warning: bool
    days_to_earnings: Optional[int] = None
    sector:           Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "ticker":           self.ticker,
            "direction":        self.direction,
            "confidence":       self.confidence,
            "signal_type":      self.signal_type,
            "strategy":         self.strategy,
            "params":           self.params,
            "reason":           self.reason,
            "earnings_warning": self.earnings_warning,
            "days_to_earnings": self.days_to_earnings,
            "sector":           self.sector,
        }


# ── Public API ───────────────────────────────────────────────────────

def generate_signals(
    db,
    *,
    earnings_dates: Optional[dict[str, date]] = None,
    include_filtered_shortvol: bool = True,
) -> list[Signal]:
    """Scan the universe and return ranked-by-confidence signals.

    Parameters
    ----------
    db
        Open VolScopeDB instance.
    earnings_dates
        Optional pre-fetched mapping ``{ticker: next_er_date}``. When
        omitted, the function queries ``earnings`` itself once.
    include_filtered_shortvol
        When True (default), short-vol setups blocked by the earnings
        filter are still returned with ``direction='SHORT_VOL'`` and
        ``earnings_warning=True`` so the UI can show them as filtered.
        When False they are dropped entirely.
    """
    try:
        latest = db.get_all_latest()
    except Exception as exc:
        log.exception("get_all_latest failed: %s", exc)
        return []
    if latest is None or latest.empty:
        return []

    if earnings_dates is None:
        earnings_dates = _fetch_next_earnings_map(db)

    out: list[Signal] = []
    for _, row in latest.iterrows():
        sig = _classify_row(row, earnings_dates,
                              include_filtered_shortvol=include_filtered_shortvol)
        if sig is None:
            continue
        out.append(sig)
    return sorted(out, key=lambda s: s.confidence, reverse=True)


# ── Internal: classify one row ───────────────────────────────────────

def _classify_row(
    row: pd.Series,
    earnings_dates: dict[str, date],
    *,
    include_filtered_shortvol: bool,
) -> Optional[Signal]:
    ticker = row.get("ticker")
    if not isinstance(ticker, str):
        return None

    iv = _f(row.get("iv_30d"))
    # The spec used `hv_20d_yz` which in our schema is `hv_yz_20d`; fall
    # back to plain `hv_20d` when the Yang-Zhang variant is missing.
    hv = _f(row.get("hv_yz_20d")) or _f(row.get("hv_20d"))
    iv_rank = _f(row.get("iv_rank"))
    iv_perc = _f(row.get("iv_percentile"))
    spot = _f(row.get("spot_price"))
    sector = row.get("sector") if "sector" in row else None
    if isinstance(sector, float) and pd.isna(sector):
        sector = None

    # All five required for a signal
    if any(x is None for x in (iv, hv, iv_rank, iv_perc, spot)) or hv <= 0:
        return None

    iv_hv_ratio = iv / hv

    # Earnings filter
    has_upcoming = False
    days_to_er: Optional[int] = None
    next_er = earnings_dates.get(ticker)
    if next_er is not None:
        try:
            today = date.today()
            days_to_er = (next_er - today).days
            has_upcoming = 0 < days_to_er < _ER_FILTER_DAYS
        except Exception:
            pass

    # ── Long-vol signals ───────────────────────────────────────────
    if iv_perc < _LONG_VOL_PERC_TRIPLE and iv_hv_ratio < _LONG_VOL_RATIO_TRIPLE:
        # Hitting BOTH triple thresholds is already a high-quality signal,
        # so start at a base of 50 and award each axis on top.
        confidence = min(
            100.0,
            50.0
            + (_LONG_VOL_PERC_TRIPLE - iv_perc) * 2
            + (_LONG_VOL_RATIO_TRIPLE - iv_hv_ratio) * 80,
        )
        strategy = "Long Call (LEAPS)" if confidence > 70 else "Bull Call Spread"
        return Signal(
            ticker=ticker,
            direction="LONG_VOL",
            confidence=round(confidence, 1),
            signal_type="TRIPLE_CHEAP",
            strategy=strategy,
            params=compute_long_vol_params(spot, iv, iv_rank),
            reason=(
                f"IV Perc {iv_perc:.0f}% + IV/HV {iv_hv_ratio:.0%} — "
                f"options {(1 - iv_hv_ratio) * 100:.0f}% cheaper than "
                f"realised moves"
            ),
            earnings_warning=has_upcoming,
            days_to_earnings=days_to_er,
            sector=sector,
        )

    if iv_perc < _LONG_VOL_PERC_RANK and iv_rank < _LONG_VOL_RANK_RANK:
        confidence = min(
            80.0,
            (_LONG_VOL_PERC_RANK - iv_perc) * 2
            + (_LONG_VOL_RANK_RANK - iv_rank) * 2,
        )
        return Signal(
            ticker=ticker,
            direction="LONG_VOL",
            confidence=round(confidence, 1),
            signal_type="LOW_RANK",
            strategy="Long Call",
            params=compute_long_vol_params(spot, iv, iv_rank),
            reason=f"IV Rank {iv_rank:.0f} — near 52-week low",
            earnings_warning=has_upcoming,
            days_to_earnings=days_to_er,
            sector=sector,
        )

    # ── Short-vol signals ──────────────────────────────────────────
    if iv_perc > _SHORT_VOL_PERC_TRIPLE and iv_hv_ratio > _SHORT_VOL_RATIO_TRIPLE:
        if has_upcoming and not include_filtered_shortvol:
            return None
        confidence = min(
            100.0,
            (iv_perc - _SHORT_VOL_PERC_TRIPLE) * 3
            + (iv_hv_ratio - _SHORT_VOL_RATIO_TRIPLE) * 100,
        )
        return Signal(
            ticker=ticker,
            direction="SHORT_VOL",
            confidence=round(confidence, 1),
            signal_type="TRIPLE_RICH",
            strategy="Iron Condor",
            params=compute_iron_condor_params(spot, iv, iv_perc),
            reason=(
                f"IV Perc {iv_perc:.0f}% + IV/HV {iv_hv_ratio:.0%} — "
                f"options {(iv_hv_ratio - 1) * 100:.0f}% more expensive "
                f"than realised moves"
            ),
            earnings_warning=has_upcoming,
            days_to_earnings=days_to_er,
            sector=sector,
        )

    if iv_perc > _SHORT_VOL_PERC_RANK and iv_rank > _SHORT_VOL_RANK_RANK:
        if has_upcoming and not include_filtered_shortvol:
            return None
        confidence = min(
            80.0,
            (iv_perc - _SHORT_VOL_PERC_RANK) * 2
            + (iv_rank - _SHORT_VOL_RANK_RANK),
        )
        strategy = "Short Put Spread" if iv_perc < _SHORT_VOL_PERC_TRIPLE else "Iron Condor"
        return Signal(
            ticker=ticker,
            direction="SHORT_VOL",
            confidence=round(confidence, 1),
            signal_type="HIGH_RANK",
            strategy=strategy,
            params=compute_short_vol_params(spot, iv, iv_perc),
            reason=f"IV Rank {iv_rank:.0f} + IV Perc {iv_perc:.0f}% — premium elevated",
            earnings_warning=has_upcoming,
            days_to_earnings=days_to_er,
            sector=sector,
        )

    # Neutral — fall-through. We don't emit a NEUTRAL signal because
    # there's nothing to act on; the UI shows only LONG_VOL / SHORT_VOL.
    return None


# ── Strategy-parameter helpers ───────────────────────────────────────

def compute_iron_condor_params(spot: float, iv: float, iv_perc: float) -> dict:
    """Standard 16-delta, 45-DTE Iron Condor.

    Strikes derived from 1σ-move under BSM assumption. Wing width
    capped at 5 % of spot or $5, whichever is larger. Credit/loss
    estimates use the 30 %-of-wing rule-of-thumb for 16-delta IC.
    """
    days = 45
    sigma_move = spot * (iv / 100.0) * math.sqrt(days / 365.0)
    short_call = round(spot + sigma_move, 0)
    short_put = round(spot - sigma_move, 0)
    wing_width = max(5.0, round(spot * 0.05, 0))
    long_call = short_call + wing_width
    long_put = short_put - wing_width
    estimated_credit = wing_width * 0.30
    max_loss = wing_width - estimated_credit
    pop = 68

    return {
        "short_call":       short_call,
        "long_call":        long_call,
        "short_put":        short_put,
        "long_put":         long_put,
        "dte":              days,
        "estimated_credit": round(estimated_credit, 2),
        "max_loss":         round(max_loss, 2),
        "pop":              pop,
        "profit_target":    "50% of credit",
        "stop_loss":        "200% of credit",
        "management":       "Close at 21 DTE if not profitable",
        "wing_width":       wing_width,
    }


def compute_short_vol_params(spot: float, iv: float, iv_perc: float) -> dict:
    """Short Put Spread parameters for HIGH_RANK signals."""
    days = 45
    sigma_move = spot * (iv / 100.0) * math.sqrt(days / 365.0)
    short_put = round(spot - sigma_move, 0)
    wing_width = max(5.0, round(spot * 0.05, 0))
    long_put = short_put - wing_width
    estimated_credit = wing_width * 0.32   # short put spread captures more than IC wing
    max_loss = wing_width - estimated_credit
    pop = 70

    return {
        "short_put":        short_put,
        "long_put":         long_put,
        "dte":              days,
        "estimated_credit": round(estimated_credit, 2),
        "max_loss":         round(max_loss, 2),
        "pop":              pop,
        "profit_target":    "50% of credit",
        "stop_loss":        "200% of credit",
        "management":       "Close at 21 DTE if not profitable",
        "wing_width":       wing_width,
    }


def compute_long_vol_params(spot: float, iv: float, iv_rank: float) -> dict:
    """Long-vol option suggestions — two tiers, ATM vs OTM."""
    strike_atm = round(spot, 0)
    strike_otm = round(spot * 1.10, 0)
    return {
        "strategy_a": {
            "name":      "ATM Call (90 DTE)",
            "strike":    strike_atm,
            "dte":       90,
            "rationale": "Maximum delta exposure, moderate time decay",
        },
        "strategy_b": {
            "name":      "OTM Call (180 DTE)",
            "strike":    strike_otm,
            "dte":       180,
            "rationale": "Higher leverage, lower premium, needs bigger move",
        },
        # LEAPS variant — only sensible when iv_rank is very low
        "strategy_c": (
            {
                "name":      "Deep-OTM LEAPS (730 DTE)",
                "strike":    round(spot * 1.75, 0),
                "dte":       730,
                "rationale": "Asymmetric convexity bet; needs 18-24 m",
            }
            if iv_rank < 5 else None
        ),
    }


# ── Earnings lookup ──────────────────────────────────────────────────

def _fetch_next_earnings_map(db) -> dict[str, date]:
    """One-shot query to map ticker → next earnings_date (or none)."""
    out: dict[str, date] = {}
    try:
        df = db.con.execute(
            """
            SELECT ticker, MIN(earnings_date) AS next_er
            FROM earnings
            WHERE earnings_date >= CURRENT_DATE
            GROUP BY ticker
            """,
        ).fetchdf()
    except Exception:
        return out
    if df is None or df.empty:
        return out
    for _, row in df.iterrows():
        try:
            d = pd.to_datetime(row["next_er"]).date()
            out[str(row["ticker"])] = d
        except Exception:
            continue
    return out


# ── Helpers ──────────────────────────────────────────────────────────

def _f(v) -> Optional[float]:
    if v is None:
        return None
    try:
        f = float(v)
        if math.isnan(f) or math.isinf(f):
            return None
        return f
    except (TypeError, ValueError):
        return None


# ── Summary statistics ───────────────────────────────────────────────

def persist_signals(db, signals: list[Signal], snapshot_date: Optional[date] = None) -> int:
    """Upsert today's signals into ``signal_log``.

    Returns the number of rows touched. Idempotent — the same
    ``(date, ticker, signal_type)`` row is overwritten with the latest
    confidence so re-running during the day doesn't duplicate.

    Wire into the nightly cron after each ``make scrape`` so we build
    a corpus of historical signals for the future
    "signal-performance-over-time" view.
    """
    snapshot_date = snapshot_date or date.today()
    if not signals:
        return 0
    rows = 0
    for s in signals:
        try:
            db.con.execute(
                """
                INSERT INTO signal_log (snapshot_date, ticker, direction,
                    signal_type, strategy, confidence, reason,
                    earnings_warning)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (snapshot_date, ticker, signal_type) DO UPDATE SET
                    direction = EXCLUDED.direction,
                    strategy  = EXCLUDED.strategy,
                    confidence = EXCLUDED.confidence,
                    reason    = EXCLUDED.reason,
                    earnings_warning = EXCLUDED.earnings_warning
                """,
                [snapshot_date, s.ticker, s.direction, s.signal_type,
                 s.strategy, s.confidence, s.reason, s.earnings_warning],
            )
            rows += 1
        except Exception as exc:
            log.debug("persist_signals row failed for %s: %s", s.ticker, exc)
    return rows


def summarize(signals: list[Signal]) -> dict:
    """Aggregate counts + averages for the dashboard's stats footer."""
    n_long = sum(1 for s in signals if s.direction == "LONG_VOL")
    n_short = sum(1 for s in signals
                   if s.direction == "SHORT_VOL" and not s.earnings_warning)
    n_filtered = sum(1 for s in signals
                      if s.direction == "SHORT_VOL" and s.earnings_warning)
    avg_long_conf = (
        sum(s.confidence for s in signals if s.direction == "LONG_VOL")
        / max(1, n_long)
    )
    avg_short_conf = (
        sum(s.confidence for s in signals
             if s.direction == "SHORT_VOL" and not s.earnings_warning)
        / max(1, n_short)
    )
    return {
        "n_long":          n_long,
        "n_short":         n_short,
        "n_filtered_er":   n_filtered,
        "avg_long_conf":   round(avg_long_conf, 1),
        "avg_short_conf":  round(avg_short_conf, 1),
    }
