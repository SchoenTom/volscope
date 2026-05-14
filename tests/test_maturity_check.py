"""Tests for scripts/audit/maturity_check.py — the loop's quantitative oracle."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

# Allow importing the script as a module
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import maturity_check as mc  # type: ignore  # noqa: E402


# ──────────────────────────────────────────────────────────────────────────
# Weights
# ──────────────────────────────────────────────────────────────────────────

class TestWeights:
    def test_weights_sum_to_one(self):
        assert abs(sum(mc.WEIGHTS.values()) - 1.0) < 1e-6

    def test_six_dimensions(self):
        assert len(mc.WEIGHTS) == 6


# ──────────────────────────────────────────────────────────────────────────
# Audit findings — zero-data honesty
# ──────────────────────────────────────────────────────────────────────────

class TestAuditFindings:
    def test_no_audits_yields_zero_score(self, tmp_path, monkeypatch):
        """When data/audit/ has no agent JSONs, score must be 0 (not 100)."""
        empty = tmp_path / "audit"
        empty.mkdir()
        monkeypatch.setattr(mc, "AUDIT_DIR", empty)

        d = mc.measure_audit_findings()
        assert d.score == 0.0
        assert any("no audit data" in g for g in d.gaps)

    def test_clean_audits_yields_full_score(self, tmp_path, monkeypatch):
        """4 agents reporting 0 issues → 100."""
        audit = tmp_path / "audit"
        audit.mkdir()
        for agent in ["ui", "math", "universe", "ideas"]:
            (audit / f"{agent}_20260501_1200.json").write_text(json.dumps({
                "bugs": [],
                "feature_gaps": [],
            }))
        monkeypatch.setattr(mc, "AUDIT_DIR", audit)
        d = mc.measure_audit_findings()
        assert d.score == 100.0

    def test_critical_finding_zeroes_critical_band(self, tmp_path, monkeypatch):
        audit = tmp_path / "audit"
        audit.mkdir()
        # Only ui audit, with one critical finding
        (audit / "ui_20260501_1200.json").write_text(json.dumps({
            "bugs": [{"severity": "critical", "description": "x"}],
        }))
        # Other three agents clean
        for agent in ["math", "universe", "ideas"]:
            (audit / f"{agent}_20260501_1200.json").write_text(json.dumps({
                "bugs": [],
            }))
        monkeypatch.setattr(mc, "AUDIT_DIR", audit)
        d = mc.measure_audit_findings()
        # Bands: 0+30(high)+15(medium)+0(sum>0) = 45
        assert d.score == pytest.approx(45.0, abs=0.1)
        assert any("CRITICAL" in g for g in d.gaps)

    def test_high_finding_zeroes_high_band(self, tmp_path, monkeypatch):
        audit = tmp_path / "audit"
        audit.mkdir()
        (audit / "ui_20260501_1200.json").write_text(json.dumps({
            "bugs": [{"severity": "high", "description": "x"}],
        }))
        for agent in ["math", "universe", "ideas"]:
            (audit / f"{agent}_20260501_1200.json").write_text(json.dumps({
                "bugs": [],
            }))
        monkeypatch.setattr(mc, "AUDIT_DIR", audit)
        d = mc.measure_audit_findings()
        # Bands: 50(critical=0)+0(high>0)+15(medium=0)+0(sum>0) = 65
        assert d.score == pytest.approx(65.0, abs=0.1)

    def test_partial_agent_coverage_proportional(self, tmp_path, monkeypatch):
        """Only 2/4 agents covered → score halved."""
        audit = tmp_path / "audit"
        audit.mkdir()
        for agent in ["ui", "math"]:
            (audit / f"{agent}_20260501_1200.json").write_text(json.dumps({
                "bugs": [],
            }))
        monkeypatch.setattr(mc, "AUDIT_DIR", audit)
        d = mc.measure_audit_findings()
        # 2/4 coverage × 100 ceiling
        assert d.score == pytest.approx(50.0, abs=0.1)

    def test_unreadable_audit_does_not_crash(self, tmp_path, monkeypatch):
        audit = tmp_path / "audit"
        audit.mkdir()
        (audit / "ui_20260501_1200.json").write_text("{not json")
        for agent in ["math", "universe", "ideas"]:
            (audit / f"{agent}_20260501_1200.json").write_text("{}")
        monkeypatch.setattr(mc, "AUDIT_DIR", audit)
        d = mc.measure_audit_findings()
        assert isinstance(d.score, float)


# ──────────────────────────────────────────────────────────────────────────
# Universe coverage
# ──────────────────────────────────────────────────────────────────────────

class TestUniverseCoverage:
    def test_runs(self):
        d = mc.measure_universe_coverage()
        # Should not crash and return a finite score
        assert 0.0 <= d.score <= 100.0
        assert "n_tickers" in d.details

    def test_below_target_flagged(self):
        d = mc.measure_universe_coverage()
        if d.details.get("n_tickers", 0) < 350:
            assert any("tickers" in g for g in d.gaps)


# ──────────────────────────────────────────────────────────────────────────
# Recommendation quality
# ──────────────────────────────────────────────────────────────────────────

class TestRecommendationQuality:
    def test_runs(self):
        d = mc.measure_recommendation_quality()
        assert 0.0 <= d.score <= 100.0
        assert "present" in d.details

    def test_edge_score_present_today(self):
        """Edge Score module was added today; it must register as present."""
        d = mc.measure_recommendation_quality()
        assert d.details["present"]["edge_score"] is True


# ──────────────────────────────────────────────────────────────────────────
# UX polish
# ──────────────────────────────────────────────────────────────────────────

class TestUxPolish:
    def test_runs(self):
        d = mc.measure_ux_polish()
        assert 0.0 <= d.score <= 100.0


# ──────────────────────────────────────────────────────────────────────────
# Aggregator
# ──────────────────────────────────────────────────────────────────────────

class TestAggregator:
    def test_aggregates_six_dimensions(self):
        r = mc.compute_maturity(skip_tests=True, skip_verify=True)
        assert len(r.dimensions) == 6

    def test_score_in_range(self):
        r = mc.compute_maturity(skip_tests=True, skip_verify=True)
        assert 0.0 <= r.score <= 100.0

    def test_weighted_sum_correct(self):
        r = mc.compute_maturity(skip_tests=True, skip_verify=True)
        manual = sum(d.score * d.weight for d in r.dimensions)
        assert abs(r.score - round(manual, 1)) < 0.2

    def test_iteration_field_optional(self):
        r = mc.compute_maturity(skip_tests=True, skip_verify=True, iteration=42)
        assert r.iteration == 42


# ──────────────────────────────────────────────────────────────────────────
# Persistence
# ──────────────────────────────────────────────────────────────────────────

class TestPersistence:
    def test_jsonl_append(self, tmp_path, monkeypatch):
        history = tmp_path / "h.jsonl"
        latest_json = tmp_path / "latest.json"
        latest_md = tmp_path / "latest.md"
        monkeypatch.setattr(mc, "DATA_DIR", tmp_path)
        monkeypatch.setattr(mc, "HISTORY_JSONL", history)
        monkeypatch.setattr(mc, "LATEST_JSON", latest_json)
        monkeypatch.setattr(mc, "LATEST_MD", latest_md)

        r = mc.compute_maturity(skip_tests=True, skip_verify=True)
        mc.persist(r)
        mc.persist(r)

        lines = history.read_text().strip().split("\n")
        assert len(lines) == 2
        for line in lines:
            json.loads(line)  # each line is valid JSON

    def test_md_renders(self, tmp_path, monkeypatch):
        monkeypatch.setattr(mc, "DATA_DIR", tmp_path)
        monkeypatch.setattr(mc, "HISTORY_JSONL", tmp_path / "h.jsonl")
        monkeypatch.setattr(mc, "LATEST_JSON", tmp_path / "latest.json")
        monkeypatch.setattr(mc, "LATEST_MD", tmp_path / "latest.md")
        r = mc.compute_maturity(skip_tests=True, skip_verify=True)
        mc.persist(r)
        md = (tmp_path / "latest.md").read_text()
        assert "Maturity Report" in md
        assert "Score" in md
        assert "Dimension" in md
