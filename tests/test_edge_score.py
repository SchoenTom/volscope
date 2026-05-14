"""Tests for analytics.edge_score — the composite long-vol entry score."""
from __future__ import annotations

import math

import pandas as pd
import pytest

from volscope.analytics.edge_score import (
    EdgeScore,
    compute_edge_score,
    compute_edge_table,
    rank_edges,
)
from volscope.analytics.ml_signal import MLPrediction


# ──────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────

def make_row(
    iv_30d=20.0, hv_20d=22.0, iv_percentile=15.0, iv_rank=18.0,
    total_open_interest=50_000,
):
    return pd.Series({
        "iv_30d": iv_30d,
        "hv_20d": hv_20d,
        "iv_percentile": iv_percentile,
        "iv_rank": iv_rank,
        "total_open_interest": total_open_interest,
    })


def make_ml(buy_prob: float, n_train: int = 200) -> MLPrediction:
    return MLPrediction(
        ticker="X",
        date="2026-04-30",
        buy_prob=buy_prob,
        n_train=n_train,
        features_used=("iv_percentile", "vrp"),
    )


# ──────────────────────────────────────────────────────────────────────────
# Output contract
# ──────────────────────────────────────────────────────────────────────────

class TestOutputContract:
    def test_returns_edge_score(self):
        e = compute_edge_score("AAPL", make_row())
        assert isinstance(e, EdgeScore)

    def test_frozen(self):
        e = compute_edge_score("AAPL", make_row())
        with pytest.raises(Exception):
            e.score = 99.9  # type: ignore[misc]

    def test_score_in_range(self):
        e = compute_edge_score("AAPL", make_row())
        assert 0.0 <= e.score <= 100.0

    def test_no_data_returns_zero(self):
        e = compute_edge_score("AAPL", None)
        assert e.score == 0.0
        assert e.confidence == 0.0
        assert "no data" in e.one_liner.lower()
        # No-data rows must be flagged illiquid so downstream filters skip them
        assert e.illiquid is True

    def test_all_nan_row_treated_as_illiquid(self):
        row = pd.Series({
            "iv_30d": float("nan"), "iv_percentile": float("nan"),
            "hv_20d": float("nan"), "iv_rank": float("nan"),
            "total_open_interest": float("nan"),
        })
        e = compute_edge_score("X", row)
        assert e.score == 0.0
        assert e.illiquid is True

    def test_partial_data_renormalises(self):
        # only iv_percentile present
        row = pd.Series({"iv_percentile": 10.0})
        e = compute_edge_score("AAPL", row)
        assert e.score > 0
        # only one component → its renormalised weight is 1.0
        assert math.isclose(sum(e.weights.values()), 1.0, abs_tol=5e-3)
        assert "iv_perc" in e.weights

    def test_confidence_reflects_completeness(self):
        # all 4 row-derived components + ml + regime + flow = 6 max
        e_full = compute_edge_score(
            "AAPL", make_row(),
            ml_pred=make_ml(0.30),
            sector_regime="COLD",
            flow_score=70.0,
        )
        assert e_full.confidence == 1.0

        e_partial = compute_edge_score("AAPL", make_row())  # 3/6 components
        assert e_partial.confidence < 1.0

    def test_drivers_subset_of_components(self):
        e = compute_edge_score(
            "AAPL", make_row(),
            ml_pred=make_ml(0.30),
            sector_regime="COLD",
            flow_score=70.0,
        )
        for d in e.drivers:
            assert d in e.components


# ──────────────────────────────────────────────────────────────────────────
# Component math — known inputs → known outputs
# ──────────────────────────────────────────────────────────────────────────

class TestComponentMath:
    def test_low_iv_perc_high_score(self):
        e_cheap = compute_edge_score("X", make_row(iv_percentile=5.0))
        e_rich  = compute_edge_score("X", make_row(iv_percentile=95.0))
        assert e_cheap.score > e_rich.score
        assert e_cheap.components["iv_perc"] == 95.0
        assert e_rich.components["iv_perc"]  == 5.0

    def test_vrp_below_one_scores_high(self):
        e = compute_edge_score("X", make_row(iv_30d=18.0, hv_20d=22.0))
        # vrp = 18/22 ≈ 0.818 → score ≈ 100 * (1.20 - 0.818) / 0.40 ≈ 95.5
        assert e.components["vrp"] > 90

    def test_vrp_above_one_scores_low(self):
        e = compute_edge_score("X", make_row(iv_30d=24.0, hv_20d=20.0))
        # vrp = 1.20 → score = 0
        assert e.components["vrp"] == 0.0

    def test_vrp_equal_one_is_fifty(self):
        e = compute_edge_score("X", make_row(iv_30d=22.0, hv_20d=22.0))
        assert math.isclose(e.components["vrp"], 50.0, abs_tol=0.5)

    def test_vrp_clipped_at_extreme_low(self):
        e = compute_edge_score("X", make_row(iv_30d=10.0, hv_20d=30.0))
        # vrp ≈ 0.33 → unclipped > 100
        assert e.components["vrp"] == 100.0

    def test_zero_hv_skips_vrp(self):
        e = compute_edge_score("X", make_row(iv_30d=20.0, hv_20d=0.0))
        assert "vrp" not in e.components

    def test_negative_hv_skips_vrp(self):
        e = compute_edge_score("X", make_row(iv_30d=20.0, hv_20d=-5.0))
        assert "vrp" not in e.components

    def test_rank_inverted(self):
        e_low  = compute_edge_score("X", make_row(iv_rank=10.0))
        e_high = compute_edge_score("X", make_row(iv_rank=90.0))
        assert e_low.components["rank"]  == 90.0
        assert e_high.components["rank"] == 10.0

    def test_ml_inverted_for_long_vol(self):
        # buy_prob = 0.30 → P(IV rises) = 0.70 → ml_score = 70
        e = compute_edge_score("X", make_row(), ml_pred=make_ml(0.30))
        assert math.isclose(e.components["ml"], 70.0, abs_tol=1.0)

    def test_ml_high_buy_prob_low_long_score(self):
        # buy_prob = 0.85 → ml_score = 15
        e = compute_edge_score("X", make_row(), ml_pred=make_ml(0.85))
        assert math.isclose(e.components["ml"], 15.0, abs_tol=1.0)

    def test_regime_cold_max(self):
        e = compute_edge_score("X", make_row(), sector_regime="COLD")
        assert e.components["regime"] == 100.0

    def test_regime_hot_zero(self):
        e = compute_edge_score("X", make_row(), sector_regime="HOT")
        assert e.components["regime"] == 0.0

    def test_regime_neutral_fifty(self):
        e = compute_edge_score("X", make_row(), sector_regime="NEUTRAL")
        assert e.components["regime"] == 50.0

    def test_regime_unknown_skipped(self):
        e = compute_edge_score("X", make_row(), sector_regime="WAT")
        assert "regime" not in e.components

    def test_regime_case_insensitive(self):
        e = compute_edge_score("X", make_row(), sector_regime="cold")
        assert e.components["regime"] == 100.0

    def test_flow_passthrough(self):
        e = compute_edge_score("X", make_row(), flow_score=72.5)
        assert math.isclose(e.components["flow"], 72.5, abs_tol=0.1)

    def test_flow_clipped(self):
        e = compute_edge_score("X", make_row(), flow_score=150.0)
        assert e.components["flow"] == 100.0
        e2 = compute_edge_score("X", make_row(), flow_score=-20.0)
        assert e2.components["flow"] == 0.0


# ──────────────────────────────────────────────────────────────────────────
# Weight math — must sum to 1, renormalisation correct
# ──────────────────────────────────────────────────────────────────────────

class TestWeightMath:
    def test_full_weights_sum_to_one(self):
        e = compute_edge_score(
            "X", make_row(),
            ml_pred=make_ml(0.5),
            sector_regime="NEUTRAL",
            flow_score=50.0,
        )
        assert math.isclose(sum(e.weights.values()), 1.0, abs_tol=5e-3)

    def test_partial_weights_sum_to_one(self):
        e = compute_edge_score("X", make_row())  # 3 components
        # weights are rounded for display so allow a 3-decimal-place tolerance
        assert math.isclose(sum(e.weights.values()), 1.0, abs_tol=5e-3)

    def test_score_with_only_iv_perc(self):
        row = pd.Series({"iv_percentile": 10.0})
        e = compute_edge_score("X", row)
        # only iv_perc, score should equal 100-10 = 90
        assert math.isclose(e.score, 90.0, abs_tol=0.1)

    def test_score_average_when_two_extreme(self):
        # row provides iv_perc + rank only (no iv/hv)
        row = pd.Series({"iv_percentile": 10.0, "iv_rank": 90.0})
        e = compute_edge_score("X", row)
        # iv_perc score=90, rank score=10
        # weights: 0.30/(0.30+0.15)=0.667, 0.15/(0.30+0.15)=0.333
        # combined = 90*0.667 + 10*0.333 = 60 + 3.33 = 63.33
        assert math.isclose(e.score, 63.3, abs_tol=0.5)


# ──────────────────────────────────────────────────────────────────────────
# Liquidity gate
# ──────────────────────────────────────────────────────────────────────────

class TestLiquidity:
    def test_high_oi_not_illiquid(self):
        e = compute_edge_score("X", make_row(total_open_interest=100_000))
        assert not e.illiquid

    def test_low_oi_flagged_illiquid(self):
        e = compute_edge_score("X", make_row(total_open_interest=500))
        assert e.illiquid

    def test_missing_oi_not_flagged(self):
        row = make_row()
        del row["total_open_interest"]
        e = compute_edge_score("X", row)
        assert not e.illiquid


# ──────────────────────────────────────────────────────────────────────────
# Edge cases — NaN, inf, missing
# ──────────────────────────────────────────────────────────────────────────

class TestEdgeCases:
    def test_nan_iv_perc_skipped(self):
        e = compute_edge_score("X", make_row(iv_percentile=float("nan")))
        assert "iv_perc" not in e.components

    def test_inf_skipped(self):
        e = compute_edge_score("X", make_row(iv_30d=float("inf"), hv_20d=20.0))
        assert "vrp" not in e.components

    def test_iv_perc_clipped_above_100(self):
        # If something passes iv_percentile = 120 (bad data), score clips at 0.
        e = compute_edge_score("X", make_row(iv_percentile=120.0))
        assert e.components["iv_perc"] == 0.0

    def test_iv_perc_clipped_below_zero(self):
        e = compute_edge_score("X", make_row(iv_percentile=-10.0))
        assert e.components["iv_perc"] == 100.0

    def test_string_iv_perc_skipped(self):
        row = pd.Series({"iv_percentile": "garbage"})
        e = compute_edge_score("X", row)
        assert "iv_perc" not in e.components


# ──────────────────────────────────────────────────────────────────────────
# Drivers + one-liner
# ──────────────────────────────────────────────────────────────────────────

class TestExplanation:
    def test_one_liner_contains_perc(self):
        e = compute_edge_score("X", make_row(iv_percentile=15.0))
        assert "perc 15" in e.one_liner

    def test_one_liner_contains_vrp(self):
        e = compute_edge_score("X", make_row(iv_30d=20.0, hv_20d=25.0))
        assert "VRP" in e.one_liner

    def test_one_liner_accumulation_label(self):
        e = compute_edge_score("X", make_row(), flow_score=80.0)
        assert "accumulation" in e.one_liner

    def test_one_liner_distribution_label(self):
        e = compute_edge_score("X", make_row(), flow_score=20.0)
        assert "distribution" in e.one_liner

    def test_drivers_top_two(self):
        e = compute_edge_score(
            "X", make_row(iv_percentile=5.0, iv_rank=5.0),
            ml_pred=make_ml(0.10),
            sector_regime="COLD",
            flow_score=80.0,
        )
        assert 1 <= len(e.drivers) <= 2


# ──────────────────────────────────────────────────────────────────────────
# Ranking + table
# ──────────────────────────────────────────────────────────────────────────

class TestRanking:
    def test_rank_descending(self):
        a = compute_edge_score("CHEAP",   make_row(iv_percentile=5.0))
        b = compute_edge_score("EXPENSIVE", make_row(iv_percentile=95.0))
        ranked = rank_edges([b, a])
        assert ranked[0].ticker == "CHEAP"

    def test_illiquid_sinks_to_bottom_when_score_lower(self):
        a = compute_edge_score("LIQ",   make_row(iv_percentile=10.0, total_open_interest=50_000))
        b = compute_edge_score("ILLIQ", make_row(iv_percentile=10.0, total_open_interest=100))
        ranked = rank_edges([b, a])
        # both same score, but liquid sorts first
        assert ranked[0].ticker == "LIQ"
        assert ranked[1].ticker == "ILLIQ"

    def test_compute_edge_table_returns_sorted(self):
        rows = {
            "A": make_row(iv_percentile=80.0),
            "B": make_row(iv_percentile=20.0),
            "C": make_row(iv_percentile=50.0),
        }
        edges = compute_edge_table(["A", "B", "C"], rows)
        scores = [e.score for e in edges]
        assert scores == sorted(scores, reverse=True)
        assert edges[0].ticker == "B"

    def test_compute_edge_table_handles_missing_row(self):
        rows = {"A": make_row(iv_percentile=20.0), "B": None}
        edges = compute_edge_table(["A", "B"], rows)
        assert len(edges) == 2
        assert edges[0].ticker == "A"

    def test_compute_edge_table_with_all_optional_inputs(self):
        rows = {"A": make_row(), "B": make_row()}
        edges = compute_edge_table(
            ["A", "B"], rows,
            ml_preds={"A": make_ml(0.20), "B": make_ml(0.80)},
            sector_regimes={"A": "COLD", "B": "HOT"},
            flow_scores={"A": 80.0, "B": 20.0},
        )
        assert edges[0].ticker == "A"


# ──────────────────────────────────────────────────────────────────────────
# Determinism
# ──────────────────────────────────────────────────────────────────────────

class TestDeterminism:
    def test_same_input_same_output(self):
        row = make_row()
        e1 = compute_edge_score("X", row)
        e2 = compute_edge_score("X", row)
        assert e1.score == e2.score
        assert e1.components == e2.components
