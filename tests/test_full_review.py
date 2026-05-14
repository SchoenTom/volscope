"""Tests for the /full-review orchestration layer."""
from __future__ import annotations

import pytest

from volscope.orchestration.full_review import (
    AggregatedReview, ClusteredFinding, Finding, ReviewArtifact,
    aggregate, run_loop,
)


def _f(severity, category, file, lo, hi, fix="suggested fix") -> Finding:
    return Finding(severity=severity, category=category, file=file,
                   line_range=(lo, hi), fix=fix)


def _art(agent, verdict, findings=(), confidence=0.8) -> ReviewArtifact:
    return ReviewArtifact(agent=agent, verdict=verdict,
                          findings=list(findings), confidence=confidence)


# ── Dedup ────────────────────────────────────────────────────────


def test_dedupe_clusters_overlapping_findings():
    """Two agents flag the same line range + category → one cluster."""
    artifacts = [
        _art("signal-engineer", "REVISE",
             findings=[_f("high", "math", "volscope/foo.py", 10, 20)]),
        _art("risk-auditor", "REVISE",
             findings=[_f("high", "math", "volscope/foo.py", 15, 25)]),
    ]
    out = aggregate(artifacts)
    assert len(out.clusters) == 1
    c = out.clusters[0]
    assert c.agreement_count == 2
    assert sorted(c.agents) == ["risk-auditor", "signal-engineer"]
    assert c.line_range == (10, 25)
    # Score = severity_weight(high=30) × agreement_count(2) = 60
    assert c.score == 60.0


def test_dedupe_keeps_distinct_categories():
    """Same file + line but different category → separate clusters."""
    artifacts = [
        _art("a", "REVISE", findings=[_f("medium", "style", "x.py", 1, 5)]),
        _art("b", "REVISE", findings=[_f("medium", "math", "x.py", 1, 5)]),
    ]
    out = aggregate(artifacts)
    assert len(out.clusters) == 2


def test_dedupe_keeps_distinct_files():
    artifacts = [
        _art("a", "REVISE", findings=[_f("medium", "style", "x.py", 1, 5)]),
        _art("b", "REVISE", findings=[_f("medium", "style", "y.py", 1, 5)]),
    ]
    out = aggregate(artifacts)
    assert len(out.clusters) == 2


def test_severity_merges_as_max():
    artifacts = [
        _art("a", "REVISE",
             findings=[_f("medium", "math", "x.py", 1, 5)]),
        _art("b", "REVISE",
             findings=[_f("critical", "math", "x.py", 1, 5)]),
    ]
    out = aggregate(artifacts)
    assert out.clusters[0].severity == "critical"
    # critical=100 × 2 agents = 200
    assert out.clusters[0].score == 200.0


# ── Verdict resolution ───────────────────────────────────────────


def test_any_reject_wins():
    artifacts = [
        _art("a", "REJECT"),
        _art("b", "PASS"),
        _art("c", "PASS"),
        _art("d", "PASS"),
        _art("e", "PASS"),
    ]
    assert aggregate(artifacts).verdict == "REJECT"


def test_two_revise_triggers_revise():
    artifacts = [
        _art("a", "REVISE"),
        _art("b", "REVISE"),
        _art("c", "PASS"),
        _art("d", "PASS"),
        _art("e", "PASS"),
    ]
    assert aggregate(artifacts).verdict == "REVISE"


def test_one_revise_does_not_trigger():
    artifacts = [
        _art("a", "REVISE"),
        _art("b", "PASS"),
        _art("c", "PASS"),
        _art("d", "PASS"),
        _art("e", "PASS"),
    ]
    assert aggregate(artifacts).verdict == "PASS"


# ── Iteration loop ───────────────────────────────────────────────


def test_loop_stops_on_pass():
    """Loop stops the moment verdict goes to PASS."""
    def loader(iter_n):
        return [_art("a", "PASS"), _art("b", "PASS"),
                _art("c", "PASS"), _art("d", "PASS"), _art("e", "PASS")]
    result = run_loop(loader, max_iterations=3)
    assert result.iteration == 1
    assert result.review.verdict == "PASS"


def test_loop_stops_on_reject():
    """Loop stops immediately on REJECT."""
    def loader(iter_n):
        if iter_n == 1:
            return [_art("a", "REJECT"), _art("b", "PASS"),
                    _art("c", "PASS"), _art("d", "PASS"), _art("e", "PASS")]
        return []                                     # unreachable
    result = run_loop(loader, max_iterations=3)
    assert result.iteration == 1
    assert result.review.verdict == "REJECT"


def test_loop_caps_at_3_iterations():
    """If REVISE persists, the loop hits the cap and returns."""
    def loader(iter_n):
        return [_art("a", "REVISE"), _art("b", "REVISE"),
                _art("c", "PASS"), _art("d", "PASS"), _art("e", "PASS")]
    result = run_loop(loader, max_iterations=3)
    assert result.iteration == 3
    assert result.review.verdict == "REVISE"


# ── Round-trip ────────────────────────────────────────────────────


def test_json_roundtrip():
    art = _art("signal-engineer", "REVISE",
                findings=[_f("high", "math", "volscope/foo.py", 10, 20,
                              "use np.float64 not int")])
    # Serialize
    raw = {
        "schema_version": art.schema_version,
        "agent": art.agent,
        "verdict": art.verdict,
        "confidence": art.confidence,
        "findings": [
            {"severity": f.severity, "category": f.category,
             "file": f.file, "line_range": list(f.line_range), "fix": f.fix}
            for f in art.findings
        ],
    }
    import json
    rebuilt = ReviewArtifact.from_json(json.dumps(raw))
    assert rebuilt.agent == art.agent
    assert rebuilt.findings[0].line_range == (10, 20)


# ── Markdown output ──────────────────────────────────────────────


def test_to_markdown_includes_verdict_and_consensus_marker():
    artifacts = [
        _art("a", "REVISE",
             findings=[_f("critical", "math", "x.py", 1, 5, "fix A")]),
        _art("b", "REVISE",
             findings=[_f("critical", "math", "x.py", 1, 5, "fix B")]),
    ]
    out = aggregate(artifacts)
    md = out.to_markdown()
    assert "REVISE" in md
    assert "🔥" in md   # consensus marker for n>=2
    assert "fix A" in md and "fix B" in md
