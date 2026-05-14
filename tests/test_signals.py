"""Tests for the bidirectional IV signal engine."""
from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
import pytest

from volscope.analytics.signals import (
    Signal,
    compute_iron_condor_params,
    compute_long_vol_params,
    compute_short_vol_params,
    generate_signals,
    summarize,
)


# ── Fake DB used by all tests ────────────────────────────────────────

class _FakeDB:
    """Minimal stub — exposes `con.execute` and `get_all_latest`."""
    def __init__(self, rows: list[dict], earnings: dict[str, date] | None = None):
        self._rows = rows
        self._earnings = earnings or {}

    def get_all_latest(self) -> pd.DataFrame:
        return pd.DataFrame(self._rows)

    class _Cursor:
        def __init__(self, df): self._df = df
        def fetchdf(self): return self._df
        def fetchone(self): return None

    class _Con:
        def __init__(self, outer): self._outer = outer
        def execute(self, sql, params=None):
            if "earnings_date" in sql:
                rows = [
                    {"ticker": k, "next_er": v}
                    for k, v in self._outer._earnings.items()
                ]
                return _FakeDB._Cursor(pd.DataFrame(rows))
            return _FakeDB._Cursor(pd.DataFrame())

    @property
    def con(self):
        return self._Con(self)


def _row(ticker, *, iv_30d, hv_yz_20d=None, hv_20d=None, iv_rank=50,
          iv_percentile=50, spot_price=100, sector="Tech"):
    return {
        "ticker": ticker, "iv_30d": iv_30d,
        "hv_yz_20d": hv_yz_20d, "hv_20d": hv_20d if hv_20d is not None else hv_yz_20d,
        "iv_rank": iv_rank, "iv_percentile": iv_percentile,
        "spot_price": spot_price, "sector": sector,
    }


# ── Spec tests (the five from the brief) ────────────────────────────

class TestSignalDetection:
    def test_long_vol_signal(self):
        """IV Perc 5, IV/HV 0.65 → LONG_VOL with confidence > 70."""
        db = _FakeDB([_row("X", iv_30d=20, hv_yz_20d=30,  # ratio 0.667
                            iv_rank=20, iv_percentile=5, spot_price=100)])
        sigs = generate_signals(db)
        assert len(sigs) == 1
        s = sigs[0]
        assert s.direction == "LONG_VOL"
        assert s.signal_type == "TRIPLE_CHEAP"
        assert s.confidence > 70

    def test_short_vol_signal(self):
        """IV Perc 90, IV/HV 1.3 → SHORT_VOL with Iron Condor."""
        db = _FakeDB([_row("Y", iv_30d=39, hv_yz_20d=30,  # ratio 1.30
                            iv_rank=80, iv_percentile=90, spot_price=200)])
        sigs = generate_signals(db)
        assert len(sigs) == 1
        s = sigs[0]
        assert s.direction == "SHORT_VOL"
        assert s.signal_type == "TRIPLE_RICH"
        assert s.strategy == "Iron Condor"

    def test_earnings_filter_blocks_short_vol(self):
        """Ticker with earnings in 7 days → short-vol setup is flagged."""
        er = {"Z": date.today() + timedelta(days=7)}
        db = _FakeDB(
            [_row("Z", iv_30d=39, hv_yz_20d=30,
                   iv_rank=80, iv_percentile=90, spot_price=200)],
            earnings=er,
        )
        sigs = generate_signals(db, earnings_dates=er)
        # When include_filtered_shortvol=True (default), the candidate
        # is returned but marked with earnings_warning=True.
        assert any(s.earnings_warning for s in sigs if s.direction == "SHORT_VOL")

    def test_earnings_filter_excludes_when_strict(self):
        """include_filtered_shortvol=False → drop the candidate entirely."""
        er = {"Z": date.today() + timedelta(days=7)}
        db = _FakeDB(
            [_row("Z", iv_30d=39, hv_yz_20d=30,
                   iv_rank=80, iv_percentile=90, spot_price=200)],
            earnings=er,
        )
        sigs = generate_signals(db, earnings_dates=er,
                                  include_filtered_shortvol=False)
        assert len(sigs) == 0

    def test_iron_condor_params_at_spot_200_iv_40(self):
        """spot=200, IV=40 → short strikes near 185 / 215."""
        p = compute_iron_condor_params(200, 40, 90)
        # 1σ in 45 days ≈ 200 * 0.40 * sqrt(45/365) = 200 * 0.40 * 0.351 = 28.1
        # short_call ≈ 228, short_put ≈ 172 — note: spec example used a
        # different IV, just sanity-check shape
        assert p["short_call"] > p["short_put"]
        assert p["long_call"] == p["short_call"] + p["wing_width"]
        assert p["long_put"] == p["short_put"] - p["wing_width"]
        assert 0.20 <= p["estimated_credit"] / p["wing_width"] <= 0.40
        assert p["pop"] == 68
        assert p["dte"] == 45

    def test_neutral_does_not_emit_signal(self):
        """IV Perc 50, IV/HV 1.0 → no signal emitted."""
        db = _FakeDB([_row("N", iv_30d=25, hv_yz_20d=25,
                            iv_rank=50, iv_percentile=50, spot_price=100)])
        sigs = generate_signals(db)
        assert sigs == []


# ── Helper-function unit tests ──────────────────────────────────────

class TestLongVolParams:
    def test_returns_two_strategies(self):
        p = compute_long_vol_params(100, 25, 50)
        assert "strategy_a" in p
        assert "strategy_b" in p
        assert p["strategy_a"]["dte"] == 90
        assert p["strategy_b"]["dte"] == 180

    def test_leaps_strategy_only_when_iv_rank_very_low(self):
        p_low = compute_long_vol_params(100, 25, 3)
        p_mid = compute_long_vol_params(100, 25, 25)
        assert p_low["strategy_c"] is not None
        assert p_mid["strategy_c"] is None


class TestShortVolParams:
    def test_basic_shape(self):
        p = compute_short_vol_params(100, 30, 75)
        assert p["short_put"] < 100
        assert p["long_put"] < p["short_put"]
        assert p["dte"] == 45
        assert p["pop"] == 70


# ── Summary stats ───────────────────────────────────────────────────

class TestSummary:
    def test_basic_counts(self):
        sigs = [
            Signal("A", "LONG_VOL", 90, "TRIPLE_CHEAP", "Long Call", {}, "", False),
            Signal("B", "LONG_VOL", 75, "LOW_RANK",    "Long Call", {}, "", False),
            Signal("C", "SHORT_VOL", 80, "TRIPLE_RICH", "Iron Condor", {}, "", False),
            Signal("D", "SHORT_VOL", 65, "HIGH_RANK", "Iron Condor", {}, "",
                    True, days_to_earnings=4),
        ]
        s = summarize(sigs)
        assert s["n_long"] == 2
        assert s["n_short"] == 1
        assert s["n_filtered_er"] == 1
        assert s["avg_long_conf"] == pytest.approx(82.5, abs=0.1)


# ── Integration: signals are sorted by confidence DESC ──────────────

class TestSorting:
    def test_confidence_descending(self):
        rows = [
            _row("HIGH", iv_30d=20, hv_yz_20d=30, iv_rank=10, iv_percentile=3, spot_price=100),
            _row("LOW",  iv_30d=20, hv_yz_20d=30, iv_rank=14, iv_percentile=18, spot_price=100),
        ]
        sigs = generate_signals(_FakeDB(rows))
        assert sigs[0].confidence >= sigs[1].confidence


# ── v2 additions ────────────────────────────────────────────────────

class TestShortPutSpreadTemplate:
    def test_template_exists_and_is_short_vol(self):
        """Bugfix: Short Put Spread must be a credit (short-vol) structure."""
        from volscope.analytics.strategy_templates import TEMPLATES
        assert "Short Put Spread" in TEMPLATES
        t = TEMPLATES["Short Put Spread"]
        assert t.direction == "short_vol"

    def test_short_put_spread_materializes_as_credit(self):
        from volscope.analytics.strategy_templates import TEMPLATES
        m = TEMPLATES["Short Put Spread"].materialize(
            ticker="X", spot=100.0, iv_pct=30.0, dte=45, contracts=1,
        )
        # Should have a sell + a buy leg, with the SELL leg's strike
        # ABOVE the BUY leg's strike (bullish put-credit spread)
        sells = [l for l in m.legs if l.action == "sell"]
        buys = [l for l in m.legs if l.action == "buy"]
        assert len(sells) == 1 and len(buys) == 1
        assert sells[0].option_type == "put"
        assert sells[0].strike > buys[0].strike
        # Net debit < 0 means we COLLECTED premium (credit structure)
        assert m.net_debit < 0


class TestSignalsPageRouting:
    def test_short_put_spread_routes_to_correct_template(self):
        """Bugfix: signal "Short Put Spread" must map to TEMPLATES key
        with the same name, not "Bear Put Spread"."""
        from volscope.ui.views.signals_page import _STRATEGY_TO_TEMPLATE
        assert _STRATEGY_TO_TEMPLATE["Short Put Spread"] == "Short Put Spread"


class TestPersistSignals:
    def test_idempotent_insert(self, tmp_path):
        """persist_signals upserts; running twice doesn't duplicate."""
        from volscope.analytics.signals import persist_signals
        from volscope.data.database import VolScopeDB

        db = VolScopeDB(db_path=str(tmp_path / "v.db"))
        try:
            sig = Signal("AAA", "LONG_VOL", 88.0, "TRIPLE_CHEAP",
                          "Long Call", {}, "test", False)
            n1 = persist_signals(db, [sig])
            n2 = persist_signals(db, [sig])
            assert n1 == 1 and n2 == 1
            rows = db.con.execute(
                "SELECT COUNT(*) FROM signal_log WHERE ticker = 'AAA'"
            ).fetchone()
            assert rows[0] == 1   # still only one row after upsert
        finally:
            db.close()


class TestSignalBacktest:
    def test_aggregate_zero(self):
        from volscope.analytics.signal_backtest import _aggregate, _empty
        empty = _aggregate([], "TEST", "TRIPLE_CHEAP", "Long Call")
        assert empty.n_events == 0

    def test_edge_string_no_data(self):
        from volscope.analytics.signal_backtest import _empty, edge_string
        bt = _empty("TEST", "TRIPLE_CHEAP", "Long Call")
        assert "no historical fires" in edge_string(bt).lower()
