"""Tests for volscope/signals/ranking.py."""
from __future__ import annotations

from volscope.signals.filters import GateResult
from volscope.signals.ranking import SignalCandidate, rank_signals


def _passing_gates() -> list[GateResult]:
    return [GateResult(name=n, passed=True) for n in
            ("persistence", "volume", "open_interest", "bas",
             "earnings", "macro", "regime", "consensus")]


def _failing_gate(name: str, reason: str) -> list[GateResult]:
    g = _passing_gates()
    g[0] = GateResult(name=name, passed=False, reason=reason)
    return g


def test_sort_by_score_desc():
    cands = [
        SignalCandidate("A", "short_vol", 70, {}, _passing_gates()),
        SignalCandidate("B", "short_vol", 90, {}, _passing_gates()),
        SignalCandidate("C", "short_vol", 80, {}, _passing_gates()),
    ]
    out = rank_signals(cands, universe_config={},
                       risk_config={"position_sizing": {}}, p_calm=0.8)
    passing = [r for r in out if r.blocked_reason is None]
    assert [r.ticker for r in passing] == ["B", "C", "A"]
    assert passing[0].rank == 1


def test_blocked_signals_retain_reason():
    cands = [
        SignalCandidate("X", "short_vol", 95, {},
                         _failing_gate("earnings", "earnings in 5d")),
    ]
    out = rank_signals(cands, universe_config={},
                       risk_config={"position_sizing": {}}, p_calm=0.8)
    assert len(out) == 1
    assert out[0].blocked_reason is not None
    assert "earnings" in out[0].blocked_reason


def test_max_concurrent_cap():
    cands = [
        SignalCandidate(f"T{i}", "short_vol", 90 - i, {}, _passing_gates())
        for i in range(20)
    ]
    out = rank_signals(cands, universe_config={},
                       risk_config={"position_sizing":
                                     {"max_concurrent_positions": 5}},
                       p_calm=0.8)
    selected = [r for r in out if r.blocked_reason is None]
    assert len(selected) == 5
    blocked = [r for r in out if r.blocked_reason
               and "max_concurrent" in r.blocked_reason]
    assert len(blocked) == 15


def test_per_sector_cap():
    # 4 Tech candidates with high score, 30% cap, ~2% notional per trade
    # → only some Tech survives.
    cands = [
        SignalCandidate(f"T{i}", "short_vol", 90, {}, _passing_gates(),
                          sector="Tech", notional=10_000.0)
        for i in range(10)
    ]
    cfg = {"position_sizing": {"max_per_sector_pct": 0.30}, "nlv": 100_000.0}
    out = rank_signals(cands, universe_config={}, risk_config=cfg, p_calm=0.8)
    selected = [r for r in out if r.blocked_reason is None]
    sector_total = sum(10_000 for r in selected if r.sector == "Tech")
    # 30% of $100k = $30k → max 3 trades
    assert sector_total <= 30_000


def test_empty_list_returns_empty():
    assert rank_signals([], universe_config={},
                         risk_config={"position_sizing": {}}, p_calm=0.8) == []


def test_score_tiebreak_is_stable_by_ticker():
    cands = [
        SignalCandidate("Z", "short_vol", 80, {}, _passing_gates()),
        SignalCandidate("A", "short_vol", 80, {}, _passing_gates()),
        SignalCandidate("M", "short_vol", 80, {}, _passing_gates()),
    ]
    out = rank_signals(cands, universe_config={},
                       risk_config={"position_sizing": {}}, p_calm=0.8)
    passing = [r for r in out if r.blocked_reason is None]
    assert [r.ticker for r in passing] == ["A", "M", "Z"]
