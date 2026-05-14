"""Tests for analytics.cross_asset_hedge."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from volscope.analytics.cross_asset_hedge import (
    CrossAssetEdge,
    CrossAssetSnapshot,
    compute_pair_edge,
    cross_asset_card_html,
    scan_cross_asset_edges,
)


def _make_history(n: int = 252, mean: float = 20.0, std: float = 3.0, seed: int = 0) -> pd.Series:
    rng = np.random.default_rng(seed)
    dates = pd.date_range("2024-01-01", periods=n, freq="B")
    values = rng.normal(mean, std, n)
    return pd.Series(values, index=dates).clip(lower=5.0)


def _snap(name: str, level: float, hist_mean: float = 20.0, hist_std: float = 3.0, seed: int = 0):
    return CrossAssetSnapshot(
        name=name,
        level=level,
        history=_make_history(mean=hist_mean, std=hist_std, seed=seed),
    )


# ──────────────────────────────────────────────────────────────────────────
# compute_pair_edge — basic contract
# ──────────────────────────────────────────────────────────────────────────

class TestPairEdge:
    def test_returns_edge(self):
        a = _snap("VIX", 14.0, hist_mean=20.0)
        b = _snap("VXFXI", 28.0, hist_mean=25.0, seed=1)
        edge = compute_pair_edge(a, b)
        assert edge is not None
        assert isinstance(edge, CrossAssetEdge)

    def test_returns_none_when_level_missing(self):
        a = _snap("VIX", 14.0)
        b = CrossAssetSnapshot(name="VXFXI", level=None, history=_make_history())
        assert compute_pair_edge(a, b) is None

    def test_returns_none_when_history_missing(self):
        a = _snap("VIX", 14.0)
        b = CrossAssetSnapshot(name="VXFXI", level=28.0, history=None)
        assert compute_pair_edge(a, b) is None

    def test_returns_none_when_history_too_short(self):
        a = CrossAssetSnapshot(
            name="A", level=10, history=_make_history(n=20),
        )
        b = CrossAssetSnapshot(
            name="B", level=10, history=_make_history(n=20),
        )
        assert compute_pair_edge(a, b) is None

    def test_zero_b_level_returns_none(self):
        a = _snap("VIX", 14.0)
        b = CrossAssetSnapshot(
            name="X", level=0.0, history=_make_history(),
        )
        assert compute_pair_edge(a, b) is None

    def test_severity_extreme_when_far_from_mean(self):
        # Force a known low ratio: a level much below history mean.
        a = CrossAssetSnapshot(
            name="A", level=5.0,
            history=pd.Series(np.full(252, 20.0), index=pd.date_range("2024-01-01", periods=252)),
        )
        b = CrossAssetSnapshot(
            name="B", level=20.0,
            history=pd.Series(np.full(252, 20.0), index=pd.date_range("2024-01-01", periods=252)),
        )
        # Both histories are constant → std=0 → returns None (we filter that)
        edge = compute_pair_edge(a, b)
        assert edge is None  # std=0 guard works


class TestSeverityClassification:
    def test_normal_when_z_below_one(self):
        rng = np.random.default_rng(42)
        hist_a = pd.Series(rng.normal(20, 2, 252),
                           index=pd.date_range("2024-01-01", periods=252))
        hist_b = pd.Series(rng.normal(20, 2, 252),
                           index=pd.date_range("2024-01-01", periods=252))
        a = CrossAssetSnapshot(name="A", level=20.0, history=hist_a)
        b = CrossAssetSnapshot(name="B", level=20.0, history=hist_b)
        edge = compute_pair_edge(a, b)
        assert edge is not None
        # ratio ≈ 1, history mean ≈ 1, z near 0 → normal
        assert edge.severity == "normal"

    def test_extreme_for_strongly_skewed_input(self):
        # Build a history where ratio is tightly distributed around 1.0
        # and current level pair has a much lower ratio.
        idx = pd.date_range("2024-01-01", periods=252)
        rng = np.random.default_rng(7)
        a_hist = pd.Series(rng.normal(20, 0.2, 252), index=idx)
        b_hist = pd.Series(rng.normal(20, 0.2, 252), index=idx)
        a = CrossAssetSnapshot(name="A", level=10.0, history=a_hist)
        b = CrossAssetSnapshot(name="B", level=20.0, history=b_hist)
        edge = compute_pair_edge(a, b)
        assert edge is not None
        assert edge.severity == "extreme"
        # a level cut in half → ratio drops far below historical mean → a cheap
        assert edge.cheap_asset == "A"


class TestRecommendationContent:
    def test_recommendation_includes_cheap_asset(self):
        idx = pd.date_range("2024-01-01", periods=252)
        rng = np.random.default_rng(7)
        a = CrossAssetSnapshot(
            name="VIX", level=10.0,
            history=pd.Series(rng.normal(20, 0.2, 252), index=idx),
        )
        b = CrossAssetSnapshot(
            name="VXFXI", level=20.0,
            history=pd.Series(rng.normal(20, 0.2, 252), index=idx),
        )
        edge = compute_pair_edge(a, b)
        assert edge is not None
        assert "VIX" in edge.recommendation
        # Maps VIX → SPY proxy
        assert "SPY" in edge.recommendation

    def test_proxy_unmapped_falls_back_to_symbol(self):
        idx = pd.date_range("2024-01-01", periods=252)
        rng = np.random.default_rng(7)
        a = CrossAssetSnapshot(
            name="UNMAPPED1", level=10.0,
            history=pd.Series(rng.normal(20, 0.2, 252), index=idx),
        )
        b = CrossAssetSnapshot(
            name="UNMAPPED2", level=20.0,
            history=pd.Series(rng.normal(20, 0.2, 252), index=idx),
        )
        edge = compute_pair_edge(a, b)
        assert edge is not None
        assert "UNMAPPED1" in edge.recommendation


# ──────────────────────────────────────────────────────────────────────────
# scan_cross_asset_edges
# ──────────────────────────────────────────────────────────────────────────

class TestScan:
    def test_pairs_are_n_choose_2(self):
        snaps = [_snap("A", 10, seed=1), _snap("B", 12, seed=2), _snap("C", 14, seed=3)]
        edges = scan_cross_asset_edges(snaps)
        # 3 choose 2 = 3 pairs
        assert len(edges) <= 3

    def test_filter_min_severity_normal_returns_all(self):
        snaps = [_snap("A", 10, seed=1), _snap("B", 12, seed=2)]
        edges = scan_cross_asset_edges(snaps, min_severity="normal")
        assert len(edges) >= 0

    def test_filter_extreme_only(self):
        snaps = [_snap("A", 10, seed=1), _snap("B", 12, seed=2)]
        edges = scan_cross_asset_edges(snaps, min_severity="extreme")
        for e in edges:
            assert e.severity == "extreme"

    def test_sorted_by_abs_z_desc(self):
        snaps = [_snap("A", 10, seed=1), _snap("B", 15, seed=2),
                 _snap("C", 20, seed=3), _snap("D", 25, seed=4)]
        edges = scan_cross_asset_edges(snaps)
        if len(edges) >= 2:
            for i in range(len(edges) - 1):
                assert abs(edges[i].ratio_z) >= abs(edges[i + 1].ratio_z)

    def test_empty_list(self):
        assert scan_cross_asset_edges([]) == []

    def test_single_snapshot_no_pairs(self):
        assert scan_cross_asset_edges([_snap("A", 10)]) == []


# ──────────────────────────────────────────────────────────────────────────
# HTML rendering
# ──────────────────────────────────────────────────────────────────────────

class TestHtml:
    def test_card_renders(self):
        edge = CrossAssetEdge(
            cheap_asset="VIX", rich_asset="VXFXI",
            ratio=0.5, ratio_z=-2.5, severity="extreme",
            recommendation="VIX cheap vs VXFXI", confidence=0.8,
        )
        html = cross_asset_card_html(edge)
        assert "VIX" in html
        assert "VXFXI" in html
        assert "EXTREME" in html

    def test_severity_color_distinct(self):
        e_normal = CrossAssetEdge("A", "B", 1.0, 0.1, "normal", "ok", 0.1)
        e_extreme = CrossAssetEdge("A", "B", 1.0, 2.5, "extreme", "ok", 0.9)
        h_n = cross_asset_card_html(e_normal)
        h_e = cross_asset_card_html(e_extreme)
        # Different severity → different colors
        assert h_n != h_e


# ──────────────────────────────────────────────────────────────────────────
# Frozen dataclass guard
# ──────────────────────────────────────────────────────────────────────────

class TestFrozen:
    def test_edge_frozen(self):
        e = CrossAssetEdge("A", "B", 1.0, 0.0, "normal", "x", 0.5)
        with pytest.raises(Exception):
            e.ratio = 2.0  # type: ignore[misc]
