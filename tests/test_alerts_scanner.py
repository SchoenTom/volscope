"""Tests for the universe alerts scanner."""
from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
import pytest

from volscope.analytics.alerts_scanner import (
    ANOMALY,
    EARNINGS,
    FLOW,
    REGIME,
    Alert,
    count_by_category,
    rule_convergence_high,
    rule_earnings_imminent,
    rule_earnings_just_passed,
    rule_iv_crush,
    rule_iv_expansion,
    rule_iv_hv_cheap,
    rule_iv_hv_rich,
    rule_iv_percentile_high,
    rule_iv_percentile_low,
    rule_pcr_call_heavy,
    rule_pcr_put_heavy,
    rule_spread_signflip,
    rule_volume_spike,
    scan_alerts,
)


# ── Helpers ──────────────────────────────────────────────────────────

def _row(**kw) -> pd.Series:
    base = {
        "ticker": "TEST",
        "date": date.today(),
        "iv_30d": 25.0, "hv_20d": 22.0, "iv_percentile": 50.0, "iv_rank": 50.0,
        "put_call_ratio": 1.0,
        "total_call_volume": 1000, "total_put_volume": 800,
        "convergence_score": 50.0,
    }
    base.update(kw)
    return pd.Series(base)


def _hist(volume_each: int = 1000, iv30=25.0, hv20=22.0,
          ranks: list[float] | None = None) -> pd.DataFrame:
    rows = []
    for i in range(20):
        rows.append({
            "date": date.today() - timedelta(days=20 - i),
            "iv_30d": iv30, "hv_20d": hv20, "iv_rank": (ranks[i] if ranks else 50.0),
            "total_call_volume": volume_each, "total_put_volume": volume_each // 2,
        })
    return pd.DataFrame(rows)


# ── Anomaly rules ────────────────────────────────────────────────────

class TestAnomalyRules:
    def test_iv_perc_low_fires(self):
        a = rule_iv_percentile_low(_row(iv_percentile=3.0))
        assert a is not None and a.type == ANOMALY

    def test_iv_perc_low_silent(self):
        assert rule_iv_percentile_low(_row(iv_percentile=10.0)) is None

    def test_iv_perc_high_fires(self):
        a = rule_iv_percentile_high(_row(iv_percentile=98.0))
        assert a is not None and "Hoch" in a.message

    def test_iv_hv_cheap(self):
        a = rule_iv_hv_cheap(_row(iv_30d=12.0, hv_20d=20.0))
        assert a is not None and "günstiger" in a.message
        assert a.metric_value < 0.65

    def test_iv_hv_rich(self):
        a = rule_iv_hv_rich(_row(iv_30d=40.0, hv_20d=20.0))
        assert a is not None and "teurer" in a.message

    def test_iv_hv_zero_hv_skipped(self):
        assert rule_iv_hv_cheap(_row(hv_20d=0.0)) is None

    def test_convergence_high(self):
        a = rule_convergence_high(_row(convergence_score=90.0))
        assert a is not None and "Konvergenz" in a.message


class TestFlowRules:
    def test_pcr_put_heavy(self):
        a = rule_pcr_put_heavy(_row(put_call_ratio=2.5))
        assert a is not None and a.type == FLOW

    def test_pcr_call_heavy(self):
        a = rule_pcr_call_heavy(_row(put_call_ratio=0.2))
        assert a is not None and "Call" in a.message

    def test_volume_spike(self):
        hist = _hist(volume_each=1000)
        # Today: 5000 calls + 4000 puts = 9000 total vs 20d avg ~1500 → ~6×
        row = _row(total_call_volume=5000, total_put_volume=4000)
        a = rule_volume_spike(row, hist)
        assert a is not None and a.metric_value >= 3.0

    def test_volume_spike_no_history(self):
        assert rule_volume_spike(_row(), None) is None


class TestRegimeRules:
    def test_iv_expansion(self):
        # iv_rank goes from 15 → 60 over 5 days
        ranks = [15] * 15 + [15, 30, 45, 55, 60]
        hist = _hist(ranks=ranks)
        row = _row(iv_rank=60.0)
        a = rule_iv_expansion(row, hist)
        assert a is not None and "Expansion" in a.message

    def test_iv_crush(self):
        ranks = [85] * 15 + [85, 70, 60, 50, 40]
        hist = _hist(ranks=ranks)
        row = _row(iv_rank=40.0)
        a = rule_iv_crush(row, hist)
        assert a is not None and "Crush" in a.message

    def test_spread_signflip_rich_to_cheap(self):
        hist = pd.DataFrame([
            {"date": date.today() - timedelta(days=2), "iv_30d": 28.0, "hv_20d": 22.0},
            {"date": date.today() - timedelta(days=1), "iv_30d": 26.0, "hv_20d": 22.0},
        ])
        row = _row(iv_30d=20.0, hv_20d=22.0)
        a = rule_spread_signflip(row, hist)
        assert a is not None and "RICH → CHEAP" in a.message

    def test_spread_signflip_no_flip(self):
        hist = pd.DataFrame([
            {"date": date.today() - timedelta(days=2), "iv_30d": 28.0, "hv_20d": 22.0},
            {"date": date.today() - timedelta(days=1), "iv_30d": 26.0, "hv_20d": 22.0},
        ])
        row = _row(iv_30d=27.0, hv_20d=22.0)
        assert rule_spread_signflip(row, hist) is None


class TestEarningsRules:
    def test_imminent(self):
        a = rule_earnings_imminent("AAPL", days_to_er=3)
        assert a is not None and a.type == EARNINGS and "3d" in a.message

    def test_imminent_too_far(self):
        assert rule_earnings_imminent("AAPL", days_to_er=15) is None

    def test_just_passed(self):
        a = rule_earnings_just_passed("AAPL", days_to_er=-1)
        assert a is not None and "Crush" in a.message

    def test_just_passed_only_within_one_day(self):
        assert rule_earnings_just_passed("AAPL", days_to_er=-3) is None


class TestScannerIntegration:
    """End-to-end scan against a tiny fake DB."""

    class _FakeDB:
        def __init__(self, latest, history_map=None, earnings_map=None):
            self._latest = latest
            self._history_map = history_map or {}
            self._earnings_map = earnings_map or {}

        def get_all_latest(self):
            return self._latest

        def get_ticker_history(self, ticker):
            return self._history_map.get(ticker, pd.DataFrame())

        def get_upcoming_earnings(self, ticker, _since):
            return self._earnings_map.get(ticker, pd.DataFrame())

    def test_scan_aggregates_alerts(self):
        latest = pd.DataFrame([
            _row(ticker="AAA", iv_percentile=2.0).to_dict(),     # iv perc low
            _row(ticker="BBB", iv_30d=40.0, hv_20d=20.0).to_dict(),  # iv/hv rich
            _row(ticker="CCC").to_dict(),                          # nothing
        ])
        db = self._FakeDB(latest=latest)
        alerts = scan_alerts(db)
        tickers = {a.ticker for a in alerts}
        assert "AAA" in tickers and "BBB" in tickers
        assert "CCC" not in tickers

    def test_scan_sorts_by_severity_desc(self):
        latest = pd.DataFrame([
            _row(ticker="AAA", iv_percentile=2.0).to_dict(),
            _row(ticker="BBB", put_call_ratio=2.5).to_dict(),
        ])
        db = self._FakeDB(latest=latest)
        alerts = scan_alerts(db)
        # ANOMALY (sev 4) must come before FLOW (sev 3)
        assert alerts[0].type == ANOMALY

    def test_scan_empty_db_returns_empty(self):
        db = self._FakeDB(latest=pd.DataFrame())
        assert scan_alerts(db) == []


class TestCounter:
    def test_count_by_category(self):
        alerts = [
            Alert(ANOMALY, 4, "A", "msg", date.today()),
            Alert(ANOMALY, 4, "B", "msg", date.today()),
            Alert(FLOW, 3, "C", "msg", date.today()),
        ]
        counts = count_by_category(alerts)
        assert counts[ANOMALY] == 2
        assert counts[FLOW] == 1
        assert counts[REGIME] == 0
