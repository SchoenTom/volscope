"""
Signal ranking — composite-score sort + universe and risk caps.

Phase 1 finishing module. Takes a list of `SignalCandidate` objects
(produced by the factor → composite → gates chain), sorts by composite
score, and enforces hard portfolio caps from `config/risk.yaml`:

- max_concurrent (default 12)
- max_per_underlying_pct (≤ 20% NLV in any single ticker)
- max_per_sector_pct (≤ 30% NLV in any single sector)
- max_index_vs_single_name_pct (≤ 50% of premium-sold in indices)

Blocked candidates remain in the returned list with `blocked_reason`
set — the Bot Dashboard renders them so the operator can audit why a
signal didn't make it through.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from volscope.signals.filters import GateResult

Direction = Literal["short_vol", "long_vol"]


@dataclass(frozen=True)
class SignalCandidate:
    """Input to the ranker. Produced by the signal-engine upstream."""
    ticker: str
    direction: Direction
    composite_score: float
    factors: dict[str, float]
    gates: list[GateResult]
    sector: str | None = None
    is_index: bool = False
    notional: float = 0.0          # expected $-at-risk for this trade


@dataclass(frozen=True)
class RankedSignal:
    """Output of the ranker. One per candidate; never drops a row."""
    ticker: str
    direction: Direction
    composite_score: float
    size_fraction: float
    factors: dict[str, float]
    gates: list[GateResult] = field(default_factory=list)
    blocked_reason: str | None = None
    sector: str | None = None
    is_index: bool = False
    rank: int = 0                  # 1-based; 0 if blocked


def _size_from_score(score: float) -> float:
    """Mirror of `signals.composite.size_from_score`; duplicated here to
    avoid a circular import. The values must stay in sync.
    """
    import math
    if not math.isfinite(score) or score < 50:
        return 0.0
    if score < 65:
        return 0.25
    if score < 80:
        return 0.50
    if score < 90:
        return 0.75
    return 1.00


def rank_signals(
    candidates: list[SignalCandidate],
    *,
    universe_config: dict,
    risk_config: dict,
    p_calm: float,                              # noqa: ARG001  (reserved)
) -> list[RankedSignal]:
    """
    Sort candidates by composite_score (descending) and enforce caps.

    Returns one `RankedSignal` per input — blocked ones get
    `blocked_reason` populated and `rank=0`.
    """
    pos_cfg = risk_config.get("position_sizing", {})
    nlv = float(risk_config.get("nlv", 0.0)) or 1.0   # default 1 means caps in fractions
    max_concurrent = int(pos_cfg.get("max_concurrent_positions", 12))
    max_per_under = float(pos_cfg.get("max_per_underlying_pct", 0.20))
    max_per_sector = float(pos_cfg.get("max_per_sector_pct", 0.30))
    max_index_total = float(pos_cfg.get("max_index_vs_single_name_pct", 0.50))

    # Sort: gate-passing first, then by score DESC, stable on ticker for ties.
    passing = [c for c in candidates if all(g.passed for g in c.gates)]
    blocked = [c for c in candidates if not all(g.passed for g in c.gates)]
    passing.sort(key=lambda c: (-c.composite_score, c.ticker))

    notional_per_under: dict[str, float] = {}
    notional_per_sector: dict[str, float] = {}
    notional_index_total = 0.0
    selected: list[RankedSignal] = []
    rank_counter = 0

    for cand in passing:
        size_frac = _size_from_score(cand.composite_score)
        trade_notional = cand.notional or (size_frac * 0.02 * nlv)   # default 2% NLV slice
        reason: str | None = None

        # Cap checks
        if rank_counter >= max_concurrent:
            reason = f"max_concurrent={max_concurrent} reached"
        elif (notional_per_under.get(cand.ticker, 0.0) + trade_notional) / nlv > max_per_under:
            reason = f"per-underlying cap {max_per_under:.0%} exceeded"
        elif cand.sector and (
            (notional_per_sector.get(cand.sector, 0.0) + trade_notional) / nlv > max_per_sector
        ):
            reason = f"per-sector cap {max_per_sector:.0%} exceeded ({cand.sector})"
        elif cand.is_index and (notional_index_total + trade_notional) / nlv > max_index_total:
            reason = f"index-vs-single-name cap {max_index_total:.0%} exceeded"

        if reason is None:
            rank_counter += 1
            notional_per_under[cand.ticker] = (
                notional_per_under.get(cand.ticker, 0.0) + trade_notional
            )
            if cand.sector:
                notional_per_sector[cand.sector] = (
                    notional_per_sector.get(cand.sector, 0.0) + trade_notional
                )
            if cand.is_index:
                notional_index_total += trade_notional

        selected.append(RankedSignal(
            ticker=cand.ticker,
            direction=cand.direction,
            composite_score=cand.composite_score,
            size_fraction=size_frac if reason is None else 0.0,
            factors=cand.factors,
            gates=cand.gates,
            blocked_reason=reason,
            sector=cand.sector,
            is_index=cand.is_index,
            rank=rank_counter if reason is None else 0,
        ))

    # Blocked-by-gates: preserve reason from first failing gate.
    for cand in blocked:
        failing = next((g for g in cand.gates if not g.passed), None)
        reason = f"gate:{failing.name}:{failing.reason}" if failing else "gate failure"
        selected.append(RankedSignal(
            ticker=cand.ticker,
            direction=cand.direction,
            composite_score=cand.composite_score,
            size_fraction=0.0,
            factors=cand.factors,
            gates=cand.gates,
            blocked_reason=reason,
            sector=cand.sector,
            is_index=cand.is_index,
            rank=0,
        ))

    return selected
