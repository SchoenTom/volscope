"""
VolScope Maturity Check — quantitative Definition-of-Done.

Computes a 0-100 maturity score across 6 weighted dimensions, appends a
JSONL history record, and writes a human-readable Markdown report.

The score exists to keep the autonomous improvement loop *honest*: without
an external quantitative oracle, an LLM iterating on its own work drifts
into plausibility-confidence (see auto-dreaming-blueprint memory).

Run: ``python scripts/maturity_check.py``
Output:
    - stdout: pretty score table
    - data/maturity_history.jsonl  (append-only)
    - data/maturity_latest.json    (latest snapshot, machine-readable)
    - data/maturity_latest.md      (human-readable report)
Exit code: 0 = computed, 1 = error
"""
from __future__ import annotations

import argparse
import json
import logging
import re
import subprocess
import sys
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parent.parent.parent  # v0.2.0 reorg: repo root is 3 levels up
sys.path.insert(0, str(ROOT))

DATA_DIR    = ROOT / "data"
AUDIT_DIR   = DATA_DIR / "audit"
HISTORY_JSONL = DATA_DIR / "maturity_history.jsonl"
LATEST_JSON   = DATA_DIR / "maturity_latest.json"
LATEST_MD     = DATA_DIR / "maturity_latest.md"

log = logging.getLogger(__name__)


# ── Dimension weights (must sum to 1.0) ──────────────────────────────────
WEIGHTS = {
    "D1_test_coverage":      0.15,
    "D2_audit_findings":     0.25,
    "D3_universe_coverage":  0.10,
    "D4_math_correctness":   0.20,
    "D5_recommendation_qty": 0.15,
    "D6_ux_polish":          0.15,
}
assert abs(sum(WEIGHTS.values()) - 1.0) < 1e-6


@dataclass
class DimensionScore:
    """One dimension contribution to the overall maturity score."""
    name:     str
    score:    float           # 0..100
    weight:   float           # 0..1
    details:  dict            = field(default_factory=dict)
    gaps:     list[str]       = field(default_factory=list)


@dataclass
class MaturityReport:
    timestamp:   str
    score:       float                 # 0..100, weighted
    dimensions:  list[DimensionScore]
    gaps:        list[str]             # flat union of all dimension gaps
    iteration:   Optional[int] = None  # external iteration counter

    def as_dict(self) -> dict:
        return {
            "timestamp":  self.timestamp,
            "score":      round(self.score, 1),
            "iteration":  self.iteration,
            "dimensions": [asdict(d) for d in self.dimensions],
            "gaps":       self.gaps,
        }


# ─────────────────────────────────────────────────────────────────────────
# Dimension 1: Test Coverage
# ─────────────────────────────────────────────────────────────────────────

def measure_test_coverage(skip_tests: bool = False) -> DimensionScore:
    """
    D1 — Test coverage. Runs pytest with collect-only and counts test items.
    No coverage.py dependency required: we use test count as a proxy
    for coverage maturity. Threshold: ≥ 800 tests = 100, scaled below.
    """
    if skip_tests:
        return DimensionScore(
            name="D1_test_coverage",
            score=0.0,
            weight=WEIGHTS["D1_test_coverage"],
            details={"skipped": True},
            gaps=["test count not measured (--skip-tests)"],
        )

    try:
        out = subprocess.run(
            ["python", "-m", "pytest", "--collect-only", "-q"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=180,
        )
        text = out.stdout + out.stderr
        # Match like "867 tests collected" or "867/867 tests collected"
        m = re.search(r"(\d+)\s+tests?\s+collected", text)
        n_tests = int(m.group(1)) if m else 0
    except Exception as exc:
        log.warning("pytest collect failed: %s", exc)
        return DimensionScore(
            name="D1_test_coverage",
            score=0.0,
            weight=WEIGHTS["D1_test_coverage"],
            details={"error": str(exc)},
            gaps=["pytest collection failed"],
        )

    # Linear ramp: 0 → 0pts, 800 → 100pts, capped.
    score = min(100.0, n_tests / 800.0 * 100.0)
    gaps: list[str] = []
    if n_tests < 800:
        gaps.append(f"only {n_tests} tests (target 800+)")

    return DimensionScore(
        name="D1_test_coverage",
        score=score,
        weight=WEIGHTS["D1_test_coverage"],
        details={"n_tests": n_tests, "target": 800},
        gaps=gaps,
    )


# ─────────────────────────────────────────────────────────────────────────
# Dimension 2: Audit Findings (counts of issues from the 4 audit agents)
# ─────────────────────────────────────────────────────────────────────────

def measure_audit_findings() -> DimensionScore:
    """
    D2 — Audit findings. Reads the most recent JSON for each of the 4
    audit agents (ui, math, universe, ideas) and tallies issues by severity.

    Score:
      0 critical   → +50 pts
      0 high       → +30 pts
      ≤ 3 medium   → +15 pts
      bonus       → +5 pts if 0 issues anywhere
    """
    counts = {"critical": 0, "high": 0, "medium": 0, "low": 0}
    files_used: list[str] = []
    gaps: list[str] = []
    n_agents_with_data = 0

    for agent in ["ui", "math", "universe", "ideas"]:
        latest = _latest_audit(agent)
        if latest is None:
            gaps.append(f"no {agent} audit yet — run make audit")
            continue
        files_used.append(latest.name)
        n_agents_with_data += 1
        try:
            data = json.loads(latest.read_text())
        except Exception as exc:
            gaps.append(f"{agent} audit unreadable: {exc}")
            continue
        # Count issues across known list keys, regardless of which keys
        # the agent used (bugs / math_bugs / universe_gaps / bold_ideas …)
        for key, items in data.items():
            if not isinstance(items, list):
                continue
            for item in items:
                if not isinstance(item, dict):
                    continue
                sev = str(item.get("severity", "medium")).lower()
                if sev in counts:
                    counts[sev] += 1
                else:
                    counts["medium"] += 1

    # If we have no audits at all, we cannot claim anything is fixed.
    # Be honest: zero data = zero credit. The loop's job is to fix this.
    if n_agents_with_data == 0:
        return DimensionScore(
            name="D2_audit_findings",
            score=0.0,
            weight=WEIGHTS["D2_audit_findings"],
            details={"counts": counts, "files": files_used, "no_audits": True},
            gaps=gaps + ["no audit data yet — run make audit before scoring D2"],
        )

    # Each missing agent withholds a quarter of the credit ceiling.
    coverage_factor = n_agents_with_data / 4.0

    score = 0.0
    if counts["critical"] == 0: score += 50.0
    else: gaps.append(f"{counts['critical']} CRITICAL findings open")
    if counts["high"] == 0:     score += 30.0
    else: gaps.append(f"{counts['high']} HIGH findings open")
    if counts["medium"] <= 3:   score += 15.0
    else: gaps.append(f"{counts['medium']} MEDIUM findings open (target ≤ 3)")
    if sum(counts.values()) == 0: score += 5.0

    score *= coverage_factor

    return DimensionScore(
        name="D2_audit_findings",
        score=min(100.0, score),
        weight=WEIGHTS["D2_audit_findings"],
        details={
            "counts": counts,
            "files": files_used,
            "agents_covered": n_agents_with_data,
        },
        gaps=gaps,
    )


def _latest_audit(agent: str) -> Optional[Path]:
    """Return the newest audit JSON for the given agent, or None."""
    if not AUDIT_DIR.exists():
        return None
    candidates = sorted(AUDIT_DIR.glob(f"{agent}_*.json"))
    return candidates[-1] if candidates else None


# ─────────────────────────────────────────────────────────────────────────
# Dimension 3: Universe Coverage
# ─────────────────────────────────────────────────────────────────────────

def measure_universe_coverage() -> DimensionScore:
    """
    D3 — Universe coverage. Inspects the curated ticker list and DB.
    Targets: ≥ 350 tickers · ≥ 6 vol indices · ≥ 4 asset classes.
    """
    gaps: list[str] = []
    n_tickers = 0
    n_vol_indices = 0
    n_asset_classes = 0

    # Count from the curated module
    try:
        from volscope.data.ticker_universe import TICKER_UNIVERSE  # type: ignore[attr-defined]
        all_syms: list[str] = []
        if isinstance(TICKER_UNIVERSE, dict):
            for v in TICKER_UNIVERSE.values():
                if isinstance(v, (list, tuple, set)):
                    all_syms.extend(list(v))
            n_asset_classes = sum(
                1 for v in TICKER_UNIVERSE.values()
                if isinstance(v, (list, tuple, set)) and len(v) > 0
            )
        elif isinstance(TICKER_UNIVERSE, (list, tuple, set)):
            all_syms = list(TICKER_UNIVERSE)
            n_asset_classes = 1
        n_tickers = len(set(all_syms))
        # Vol indices commonly start with ^V, ^X, or are known symbols.
        vol_set = {"^VIX", "^VDAX", "VDAX-NEW.DE", "^VXN", "^RVX", "^VXFXI",
                   "^V2X", "^VSTOXX", "^OVX", "^GVZ", "^VXEEM", "BVOL"}
        n_vol_indices = sum(1 for s in all_syms if s.upper() in vol_set)
    except Exception as exc:
        gaps.append(f"ticker_universe import failed: {exc}")

    # Subscores
    s_count   = min(100.0, n_tickers / 350.0 * 100.0)
    s_indices = min(100.0, n_vol_indices / 6.0 * 100.0)
    s_classes = min(100.0, n_asset_classes / 4.0 * 100.0)
    score = (s_count + s_indices + s_classes) / 3.0

    if n_tickers < 350:
        gaps.append(f"only {n_tickers} tickers (target 350+)")
    if n_vol_indices < 6:
        gaps.append(f"only {n_vol_indices} vol indices (target 6+: VIX, VDAX, VXN, RVX, V2X, GVZ)")
    if n_asset_classes < 4:
        gaps.append(f"only {n_asset_classes} asset classes (target 4+: equity, FX, commodity, crypto)")

    return DimensionScore(
        name="D3_universe_coverage",
        score=score,
        weight=WEIGHTS["D3_universe_coverage"],
        details={
            "n_tickers": n_tickers,
            "n_vol_indices": n_vol_indices,
            "n_asset_classes": n_asset_classes,
        },
        gaps=gaps,
    )


# ─────────────────────────────────────────────────────────────────────────
# Dimension 4: Math Correctness — gated on `make verify` PASS + gold tests
# ─────────────────────────────────────────────────────────────────────────

def measure_math_correctness(skip_verify: bool = False, assume_verified: bool = False) -> DimensionScore:
    """
    D4 — Math correctness. Runs `make verify` (the external oracle).
    PASS ⇒ 100. FAIL ⇒ 0. No partial credit because numerics are binary.

    If ``assume_verified`` is True, returns 100 without running verify.
    Used by the loop orchestrator after it has just run verify itself
    (avoids running it twice in one iteration).
    """
    if assume_verified:
        return DimensionScore(
            name="D4_math_correctness",
            score=100.0,
            weight=WEIGHTS["D4_math_correctness"],
            details={"verify_passed": True, "assumed_by_caller": True},
            gaps=[],
        )
    if skip_verify:
        return DimensionScore(
            name="D4_math_correctness",
            score=0.0,
            weight=WEIGHTS["D4_math_correctness"],
            details={"skipped": True},
            gaps=["math correctness not measured (--skip-verify)"],
        )

    try:
        out = subprocess.run(
            ["make", "verify"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=600,
        )
        text = out.stdout + out.stderr
        passed = "OVERALL: PASS" in text
    except Exception as exc:
        log.warning("make verify failed to run: %s", exc)
        return DimensionScore(
            name="D4_math_correctness",
            score=0.0,
            weight=WEIGHTS["D4_math_correctness"],
            details={"error": str(exc)},
            gaps=["make verify did not run"],
        )

    return DimensionScore(
        name="D4_math_correctness",
        score=100.0 if passed else 0.0,
        weight=WEIGHTS["D4_math_correctness"],
        details={"verify_passed": passed},
        gaps=[] if passed else ["make verify FAILED — fix before next iteration"],
    )


# ─────────────────────────────────────────────────────────────────────────
# Dimension 5: Recommendation Quality
# ─────────────────────────────────────────────────────────────────────────

def measure_recommendation_quality() -> DimensionScore:
    """
    D5 — Recommendation quality. We can't run a full backtest cheaply on
    every loop iteration, so we use feature-presence as a proxy:

      - Edge Score module exists                  → +25
      - Strategy Recommender module exists        → +25
      - Pre-Trade Card module exists              → +20
      - Kelly position-sizing exists              → +15
      - Cross-asset hedge engine exists           → +15
    """
    checks = {
        "edge_score":          ROOT / "volscope" / "analytics" / "edge_score.py",
        "strategy_recommender":ROOT / "volscope" / "analytics" / "strategy_recommender.py",
        "pretrade_card":       ROOT / "volscope" / "ui" / "views" / "pretrade_page.py",
        "kelly_sizing":        ROOT / "volscope" / "analytics" / "kelly_sizing.py",
        "cross_asset_hedge":   ROOT / "volscope" / "analytics" / "cross_asset_hedge.py",
    }
    weights = {
        "edge_score":          25.0,
        "strategy_recommender":25.0,
        "pretrade_card":       20.0,
        "kelly_sizing":        15.0,
        "cross_asset_hedge":   15.0,
    }
    score = 0.0
    present: dict[str, bool] = {}
    gaps: list[str] = []
    for name, path in checks.items():
        ok = path.exists()
        present[name] = ok
        if ok:
            score += weights[name]
        else:
            gaps.append(f"{name} module missing ({path.relative_to(ROOT)})")

    return DimensionScore(
        name="D5_recommendation_qty",
        score=score,
        weight=WEIGHTS["D5_recommendation_qty"],
        details={"present": present},
        gaps=gaps,
    )


# ─────────────────────────────────────────────────────────────────────────
# Dimension 6: UX Polish
# ─────────────────────────────────────────────────────────────────────────

UX_CHECKLIST: list[tuple[str, str, str]] = [
    # (key, search file, search needle that, when present, indicates feature exists)
    ("csv_export",      "volscope/ui",        "download_button"),
    ("empty_state",     "volscope/ui/views/", "No data — run"),
    ("mobile_layout",   "volscope/ui/styles", "@media"),
    ("onboarding_tour", "volscope/ui/views/", "onboarding"),
    ("keyboard_shortcuts", "volscope/ui/components", "keydown"),
    ("theme_toggle",    "volscope/ui",        "theme_toggle"),
]


def measure_ux_polish() -> DimensionScore:
    """
    D6 — UX polish checklist. Each item present in the codebase = +16.7 pts.
    Detection is grep-based: a feature counts as present when its needle
    appears at least once in the target subtree. This is intentionally
    coarse — the audit agents catch the nuanced bugs.
    """
    score = 0.0
    present: dict[str, bool] = {}
    gaps: list[str] = []
    for key, subpath, needle in UX_CHECKLIST:
        target = ROOT / subpath
        found = _grep_exists(target, needle)
        present[key] = found
        if found:
            score += 100.0 / len(UX_CHECKLIST)
        else:
            gaps.append(f"{key} not detected (needle '{needle}' missing under {subpath})")
    score = min(100.0, score)  # guard against 6 × 16.67 = 100.00…01 drift
    return DimensionScore(
        name="D6_ux_polish",
        score=score,
        weight=WEIGHTS["D6_ux_polish"],
        details={"present": present},
        gaps=gaps,
    )


def _grep_exists(target: Path, needle: str) -> bool:
    if not target.exists():
        return False
    try:
        out = subprocess.run(
            ["grep", "-r", "-l", "--include=*.py", "--include=*.css", needle, str(target)],
            capture_output=True,
            text=True,
            timeout=10,
        )
        return out.returncode == 0 and bool(out.stdout.strip())
    except Exception:
        return False


# ─────────────────────────────────────────────────────────────────────────
# Aggregator
# ─────────────────────────────────────────────────────────────────────────

def compute_maturity(
    *,
    skip_tests:      bool = False,
    skip_verify:     bool = False,
    assume_verified: bool = False,
    iteration:       Optional[int] = None,
) -> MaturityReport:
    dims = [
        measure_test_coverage(skip_tests=skip_tests),
        measure_audit_findings(),
        measure_universe_coverage(),
        measure_math_correctness(skip_verify=skip_verify, assume_verified=assume_verified),
        measure_recommendation_quality(),
        measure_ux_polish(),
    ]
    score = sum(d.score * d.weight for d in dims)
    gaps  = [g for d in dims for g in d.gaps]
    return MaturityReport(
        timestamp=datetime.now().isoformat(timespec="seconds"),
        score=round(score, 1),
        dimensions=dims,
        gaps=gaps,
        iteration=iteration,
    )


# ─────────────────────────────────────────────────────────────────────────
# Persistence
# ─────────────────────────────────────────────────────────────────────────

def persist(report: MaturityReport) -> None:
    DATA_DIR.mkdir(exist_ok=True)
    HISTORY_JSONL.touch(exist_ok=True)
    with HISTORY_JSONL.open("a") as f:
        f.write(json.dumps(report.as_dict()) + "\n")
    LATEST_JSON.write_text(json.dumps(report.as_dict(), indent=2))
    LATEST_MD.write_text(_render_md(report))


def _render_md(r: MaturityReport) -> str:
    lines = [
        f"# VolScope Maturity Report",
        "",
        f"**Score:** **{r.score:.1f} / 100**",
        f"**Timestamp:** {r.timestamp}",
        f"**Iteration:** {r.iteration if r.iteration is not None else '—'}",
        "",
        "## Dimensions",
        "",
        "| Dimension | Weight | Score | Weighted |",
        "|-----------|-------:|------:|---------:|",
    ]
    for d in r.dimensions:
        lines.append(
            f"| {d.name} | {d.weight*100:.0f}% | {d.score:.1f} | {d.score*d.weight:.1f} |"
        )
    lines.append("")
    if r.gaps:
        lines.append("## Open Gaps")
        lines.append("")
        for g in r.gaps:
            lines.append(f"- {g}")
        lines.append("")
    return "\n".join(lines)


def _render_table(r: MaturityReport) -> str:
    rows = [
        f"  {d.name:25s}  weight={d.weight*100:>4.0f}%  score={d.score:>5.1f}  → {d.score*d.weight:>5.1f}"
        for d in r.dimensions
    ]
    return (
        f"\nMATURITY: {r.score:.1f} / 100  ({r.timestamp})\n"
        + "\n".join(rows)
        + (f"\n\nGaps ({len(r.gaps)}):\n  - " + "\n  - ".join(r.gaps) if r.gaps else "\n\nNo open gaps.")
    )


# ─────────────────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────────────────

def main() -> int:
    p = argparse.ArgumentParser(description="VolScope maturity check")
    p.add_argument("--skip-tests",     action="store_true", help="skip pytest collect (D1)")
    p.add_argument("--skip-verify",    action="store_true", help="skip make verify (D4) — D4 will be 0")
    p.add_argument("--assume-verified", action="store_true",
                   help="assume make verify already passed in this loop iteration — D4 = 100")
    p.add_argument("--iteration",      type=int, default=None, help="loop iteration counter")
    p.add_argument("--quiet",          action="store_true", help="json output only")
    args = p.parse_args()

    t0 = time.time()
    report = compute_maturity(
        skip_tests=args.skip_tests,
        skip_verify=args.skip_verify,
        assume_verified=args.assume_verified,
        iteration=args.iteration,
    )
    persist(report)

    if args.quiet:
        print(json.dumps(report.as_dict()))
    else:
        print(_render_table(report))
        print(f"\nWritten:")
        print(f"  {HISTORY_JSONL.relative_to(ROOT)}")
        print(f"  {LATEST_JSON.relative_to(ROOT)}")
        print(f"  {LATEST_MD.relative_to(ROOT)}")
        print(f"\nElapsed: {time.time()-t0:.1f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
