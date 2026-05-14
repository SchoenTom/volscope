"""
Five-agent virtual review panel — v0.6.0 G5.

Spawns 5 role-specialised reviewers in parallel subprocesses, each
with its OWN fresh context (no shared system prompt content beyond
the role rubric). Each writes a JSON `ReviewArtifact` to a temp dir.
The Aggregator deduplicates findings by `(file, line_range±3,
category)`, scores by `severity × agreement_count`, and resolves
the verdict.

Designed for paid-product trust: independent rediscovery of the
same issue by N agents is the strongest signal that the issue is
real. Singletons can still drive REVISE but are less weighted.

Reference:
- TradingAgents v0.2.4 (parallel role-specialised agents pattern)
- wshobson/agents 7-agent full-stack-orchestration chain
- Paperclip 6-agent firm postmortem (no direct A→B messaging; JSON
  artifacts only)

This module is pure-Python orchestration. It does NOT call the
Claude API itself — that happens in `scripts/ops/full_review.py`
via `claude --output-format json -p ...` subprocess. Keeping the
orchestration logic separate makes it unit-testable without API
credentials.
"""
from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from typing import Literal

log = logging.getLogger(__name__)


Severity = Literal["critical", "high", "medium", "low"]
Verdict = Literal["PASS", "REVISE", "REJECT"]

_SEVERITY_WEIGHT: dict[Severity, int] = {
    "critical": 100, "high": 30, "medium": 10, "low": 3,
}


@dataclass(frozen=True)
class Finding:
    """One review finding from a single agent."""
    severity: Severity
    category: str                  # 'secrets' | 'math' | 'risk' | 'style' | 'observability'
    file: str
    line_range: tuple[int, int]    # inclusive (start, end)
    fix: str                       # one-line suggestion

    @classmethod
    def from_dict(cls, d: dict) -> "Finding":
        return cls(
            severity=d["severity"],
            category=d["category"],
            file=d["file"],
            line_range=tuple(d["line_range"]),
            fix=d["fix"],
        )


@dataclass(frozen=True)
class ReviewArtifact:
    """One agent's verdict + findings."""
    agent: str
    verdict: Verdict
    findings: list[Finding]
    confidence: float                # 0..1
    schema_version: str = "1.0"

    @classmethod
    def from_dict(cls, d: dict) -> "ReviewArtifact":
        return cls(
            agent=d["agent"],
            verdict=d["verdict"],
            findings=[Finding.from_dict(f) for f in d.get("findings", [])],
            confidence=float(d.get("confidence", 0.5)),
            schema_version=d.get("schema_version", "1.0"),
        )

    @classmethod
    def from_json(cls, raw: str) -> "ReviewArtifact":
        return cls.from_dict(json.loads(raw))


@dataclass(frozen=True)
class ClusteredFinding:
    """A finding that survived dedupe — may aggregate N agents."""
    severity: Severity
    category: str
    file: str
    line_range: tuple[int, int]
    agreement_count: int               # how many agents independently raised this
    agents: list[str]
    fixes: list[str]                    # collected suggestions
    score: float

    @property
    def is_consensus(self) -> bool:
        return self.agreement_count >= 2


@dataclass(frozen=True)
class AggregatedReview:
    """The Aggregator's output. The CEO-grade verdict."""
    verdict: Verdict
    iteration: int
    clusters: list[ClusteredFinding]
    artifacts: list[ReviewArtifact]    # raw inputs preserved for forensics
    summary: str                       # one-paragraph human-readable

    def to_markdown(self) -> str:
        out = [
            f"# Review verdict: **{self.verdict}** (iteration {self.iteration})",
            "",
            self.summary,
            "",
            "## Findings (sorted by score, descending)",
            "",
        ]
        for c in self.clusters:
            consensus_mark = " 🔥" if c.is_consensus else ""
            out.append(
                f"- **[{c.severity.upper()}]** {c.category} — "
                f"{c.file}:{c.line_range[0]}-{c.line_range[1]} "
                f"(score={c.score:.0f}, n={c.agreement_count}){consensus_mark}"
            )
            for f in c.fixes:
                out.append(f"  - {f}")
        out.extend(["", "## Per-agent verdicts", ""])
        for a in self.artifacts:
            out.append(f"- **{a.agent}**: {a.verdict} (confidence={a.confidence:.2f})")
        return "\n".join(out)


# ── Aggregator ────────────────────────────────────────────────────


def aggregate(artifacts: list[ReviewArtifact], *,
              iteration: int = 1,
              line_fuzz: int = 3) -> AggregatedReview:
    """
    Deduplicate findings + score + resolve verdict.

    Dedup key: (file, category, line_range overlapping within ±line_fuzz).
    Two findings cluster if same file + same category + their
    line_ranges overlap by more than line_fuzz lines.

    Score: severity_weight × agreement_count. Highest-score first.

    Verdict resolution:
    - Any agent REJECT → REJECT.
    - ≥2 REVISE → REVISE.
    - All PASS → PASS.
    """
    clusters: list[ClusteredFinding] = []
    for art in artifacts:
        for f in art.findings:
            placed = False
            for i, c in enumerate(clusters):
                if (c.file == f.file and c.category == f.category
                        and _overlap(c.line_range, f.line_range, line_fuzz)):
                    clusters[i] = _merge_into_cluster(c, f, art.agent)
                    placed = True
                    break
            if not placed:
                clusters.append(_new_cluster(f, art.agent))

    # Score + sort
    clusters = [_rescore(c) for c in clusters]
    clusters.sort(key=lambda c: (-c.score, c.file, c.line_range[0]))

    # Verdict resolution
    verdicts = [a.verdict for a in artifacts]
    if "REJECT" in verdicts:
        verdict: Verdict = "REJECT"
    elif sum(1 for v in verdicts if v == "REVISE") >= 2:
        verdict = "REVISE"
    else:
        verdict = "PASS"

    summary = _build_summary(clusters, verdict, len(artifacts))
    return AggregatedReview(
        verdict=verdict, iteration=iteration,
        clusters=clusters, artifacts=artifacts, summary=summary,
    )


def _overlap(a: tuple[int, int], b: tuple[int, int], fuzz: int) -> bool:
    """Do two line-ranges overlap within `fuzz` lines of each other?"""
    a_lo, a_hi = a
    b_lo, b_hi = b
    return (a_lo - fuzz) <= b_hi and (b_lo - fuzz) <= a_hi


def _new_cluster(f: Finding, agent: str) -> ClusteredFinding:
    return ClusteredFinding(
        severity=f.severity, category=f.category,
        file=f.file, line_range=f.line_range,
        agreement_count=1, agents=[agent], fixes=[f.fix],
        score=float(_SEVERITY_WEIGHT[f.severity]),
    )


def _merge_into_cluster(c: ClusteredFinding, f: Finding,
                         agent: str) -> ClusteredFinding:
    """Merge a new finding into an existing cluster.

    Severity = MAX of the two. Line range = bounding span. Agents
    grow; fixes deduplicate.
    """
    new_severity = max(
        (c.severity, f.severity),
        key=lambda s: _SEVERITY_WEIGHT[s],
    )
    new_range = (min(c.line_range[0], f.line_range[0]),
                  max(c.line_range[1], f.line_range[1]))
    new_agents = c.agents + ([agent] if agent not in c.agents else [])
    new_fixes = c.fixes + ([f.fix] if f.fix not in c.fixes else [])
    return ClusteredFinding(
        severity=new_severity, category=c.category,
        file=c.file, line_range=new_range,
        agreement_count=len(new_agents),
        agents=new_agents, fixes=new_fixes,
        score=0.0,           # rescored after all merges
    )


def _rescore(c: ClusteredFinding) -> ClusteredFinding:
    """Final score = severity_weight × agreement_count."""
    score = float(_SEVERITY_WEIGHT[c.severity]) * c.agreement_count
    return ClusteredFinding(
        severity=c.severity, category=c.category,
        file=c.file, line_range=c.line_range,
        agreement_count=c.agreement_count, agents=c.agents,
        fixes=c.fixes, score=score,
    )


def _build_summary(clusters: list[ClusteredFinding], verdict: Verdict,
                    n_artifacts: int) -> str:
    n_consensus = sum(1 for c in clusters if c.is_consensus)
    n_critical = sum(1 for c in clusters if c.severity == "critical")
    n_high = sum(1 for c in clusters if c.severity == "high")
    return (
        f"{n_artifacts} agents reviewed; {len(clusters)} distinct findings "
        f"({n_consensus} consensus, {n_critical} critical, {n_high} high). "
        f"Verdict: {verdict}."
    )


# ── Iteration loop ────────────────────────────────────────────────


@dataclass
class IterationResult:
    iteration: int
    review: AggregatedReview
    operator_revised: bool = False


def run_loop(artifact_loader, *, max_iterations: int = 3) -> IterationResult:
    """
    Drive the PASS/REVISE/REJECT loop.

    `artifact_loader(iteration)` is a callable that returns a list of
    `ReviewArtifact` for the given iteration. Tests inject mocks; the
    CLI invokes real subprocesses.

    Stops when verdict == PASS, REJECT, or iteration == max_iterations.
    """
    last: AggregatedReview | None = None
    for it in range(1, max_iterations + 1):
        artifacts = artifact_loader(it)
        last = aggregate(artifacts, iteration=it)
        log.info("iteration %d verdict=%s clusters=%d",
                  it, last.verdict, len(last.clusters))
        if last.verdict in ("PASS", "REJECT"):
            return IterationResult(iteration=it, review=last)
    # Hit the cap with REVISE still active
    assert last is not None
    return IterationResult(iteration=max_iterations, review=last)
