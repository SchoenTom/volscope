"""
VolScope Audit Spawner — emits the 4 audit-agent prompts.

This is Phase-1 of the maturity loop. Four parallel Explore subagents
read the codebase and produce structured JSON findings under
``data/audit/<agent>_<timestamp>.json``.

Modes
-----
- ``python scripts/run_audits.py --emit``
    Writes the 4 prompt files (data/audit/agents/{ui,math,universe,ideas}.md)
    and prints a copy-paste invocation block for the orchestrator.
- ``python scripts/run_audits.py --schema``
    Prints the expected JSON output schema. The orchestrator validates
    each agent's output against this schema before accepting it into
    the queue.
- ``python scripts/run_audits.py --list``
    Lists all audit JSON files currently on disk, newest first.

This script does NOT itself spawn agents — agent dispatch is the
responsibility of the orchestrator running inside Claude Code (which
has access to the Agent tool). This script just produces and validates
the prompt + schema artifacts so a human or an LLM can copy-paste them.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

ROOT       = Path(__file__).resolve().parent.parent
AUDIT_DIR  = ROOT / "data" / "audit"
AGENTS_DIR = AUDIT_DIR / "agents"


# ─────────────────────────────────────────────────────────────────────────
# Agent prompt templates
# ─────────────────────────────────────────────────────────────────────────

UI_AUDIT_PROMPT = """\
You are auditing VolScope's UI/UX layer at /Users/tomschoen/Desktop/VolScope.
Simulate a hedge-fund trader who opens the app for the first time.
Read every file under volscope/ui/ — pages, components, styles. Be brutal
and concrete; the owner has signed off on this honesty.

For every defect, capture:
  - file (relative path)
  - line (best estimate)
  - severity (critical | high | medium | low)
  - description (one sentence)
  - fix_sketch (one sentence)
  - estimate_minutes (rough effort)

Look specifically for:
  1. Tables / column-config bugs (overflow, wrong format, wrong color semantics)
  2. Empty-states (every page when DB is empty)
  3. Layout breakage at 1, 5, 10 tickers; mobile (< 800px width)
  4. Missing onboarding / Cmd+K / keyboard shortcuts / CSV export / theme toggle
  5. Pages with 1-word captions instead of explanations
  6. Discover-page recommendation cards: do they explain WHY a ticker is on top?
  7. Scope page: what's missing for a serious trader (Greeks? Surface? Earnings timeline?)

Output JSON (and only JSON) matching this schema:
{
  "agent": "ui",
  "timestamp": "<ISO8601>",
  "bugs":         [{file, line, severity, description, fix_sketch, estimate_minutes}, ...],
  "feature_gaps": [{file, line, severity, description, fix_sketch, estimate_minutes}, ...],
  "ux_friction":  [{file, line, severity, description, fix_sketch, estimate_minutes}, ...],
  "quick_wins":   [{file, line, severity, description, fix_sketch, estimate_minutes}, ...]
}

Each list ≥ 5 entries. Reject empty findings — if you find none, search harder.
Write the JSON to data/audit/ui_<YYYYMMDD_HHMM>.json. Print only the path.
"""

MATH_AUDIT_PROMPT = """\
You are auditing VolScope's quantitative layer at /Users/tomschoen/Desktop/VolScope.
Read every file under volscope/analytics/ and volscope/data/options_scraper.py
and volscope/data/risk_free.py.

Cross-check formulas against:
  - Hull, "Options, Futures, and Other Derivatives", 11th ed.
  - Yang & Zhang (2000) for the YZ historical-vol estimator
  - Tastytrade's IV-Rank/Percentile definitions
  - Sinclair, "Volatility Trading", 2nd ed., for VRP convention

For each finding capture:
  - file, line
  - severity (critical | high | medium | low)
  - formula_check (what was the textbook expectation?)
  - actual (what does the code do?)
  - fix_sketch (one sentence)
  - estimate_minutes

Specifically check:
  1. Unit consistency (IV in % vs decimal — same throughout?)
  2. Edge cases: σ → 0, T → 0, S=0, K=0, NaN/inf, hv=0
  3. Lookahead: does training cleanly exclude future data?
  4. Annualisation: √252 vs √365 used consistently?
  5. IV-percentile tie-handling (current==history values)
  6. Newton-Raphson convergence at deep OTM/ITM and short t
  7. Yang-Zhang k-parameter sensitivity to window size
  8. Capital-flow z-score robustness when n_tickers < 10
  9. Sector-regime z-score with < 5 history points
 10. Edge-Score VRP linear-mapping universality (DAX, MSTR, crypto)
 11. ML-signal direction asymmetry vs long-vol-buyer perspective

Output JSON:
{
  "agent": "math",
  "timestamp": "<ISO8601>",
  "math_bugs":         [{...}, ...],
  "edge_case_gaps":    [{...}, ...],
  "conceptual_problems": [{...}, ...],
  "quick_fixes":       [{...}, ...]
}

Write to data/audit/math_<YYYYMMDD_HHMM>.json. Print only the path.
"""

UNIVERSE_AUDIT_PROMPT = """\
You are auditing VolScope's asset universe and recommendation engine at
/Users/tomschoen/Desktop/VolScope. The owner trades DAX puts (Sep 2027),
Nasdaq puts (Dec 2026), and knock-out certificates on MSTR / SNOW / 1810.HK.
He has explicitly said: "I'm dissatisfied with the pre-loaded asset count
and with the low-vol-area recommendations."

Read:
  - volscope/data/ticker_universe.py
  - volscope/analytics/opportunity.py
  - volscope/analytics/edge_score.py
  - volscope/ui/views/discover_page.py
  - volscope/ui/views/scan_page.py

For each finding capture:
  - file, line, severity
  - problem (one sentence)
  - business_impact (why this hurts a hedge-fund trader)
  - fix_sketch
  - estimate_minutes

Specifically check:
  1. Asset coverage: how many tickers, which classes, which markets?
  2. EU single-names (SAP, Siemens, Allianz, ASML, NVO) — present?
  3. HK listings (0700.HK Tencent, 9988.HK Alibaba) — present?
  4. Vol indices (VXN, RVX, VSTOXX, V2X, GVZ, OVX, VXEEM) — present?
  5. Absolute IV-floor filter: does "cheap percentile" account for the
     fact that the IV may already be at its annual floor?
  6. Reversion-upside-magnitude: do recommendations include expected
     vega payoff, or just rank by percentile?
  7. Liquidity floor: are tickers with OI < 1000 still recommended?
  8. Sector-concentration: are top-5 cheaps all in one sector?
  9. Pre-trade workflow: when user clicks BUY, what happens? Is there
     a strike/maturity recommendation, P&L curve, max-loss?
 10. Strategy-recommender: is there one (long put / strangle / calendar
     / risk-reversal selection)?

Output JSON:
{
  "agent": "universe",
  "timestamp": "<ISO8601>",
  "universe_gaps":         [{...}, ...],
  "recommendation_flaws":  [{...}, ...],
  "missing_modes":         [{...}, ...],
  "ticker_suggestions":    [{symbol, asset_class, market, rationale}, ...]
}

Write to data/audit/universe_<YYYYMMDD_HHMM>.json. Print only the path.
"""

IDEAS_AUDIT_PROMPT = """\
You are the Innovation Agent for VolScope at /Users/tomschoen/Desktop/VolScope.
Your job is to brainstorm bold ideas that take VolScope from "good vol tool"
to "best-in-class hedge-fund Vol Intelligence Platform."

You may research best-in-class peers (Bloomberg Vol Suite, OptionMetrics,
ORATS, Volcube, predictive analytics tooling) — but every idea must be
implementable on the existing stack: Python + Streamlit + DuckDB + yfinance
+ FRED. No paid data feeds, no GPU clusters.

Read first:
  - .claude/projects/-Users-tomschoen/memory/volscope-vision.md
  - .claude/projects/-Users-tomschoen/memory/volscope-giga-plan.md
  - .claude/plans/volscope-roadmap.md

Then propose, for each idea:
  - name
  - description (3-4 sentences)
  - hedgefund_impact (why a serious trader would care)
  - implementation_sketch (1 paragraph — files, modules, math)
  - novelty_score (1-10, vs what VolScope has today)
  - feasibility_score (1-10, given the stack)
  - estimate_hours

Seed ideas (extend, don't repeat verbatim):
  - SVI vol-surface fit (single 5-param object per ticker, smooth interpolation)
  - PCA-based sector-regime classification (level + slope PCs)
  - Realized skew from intraday spot path (compare against IV skew → mismatch signal)
  - Strategy-recommender (vol-state → multi-leg structure)
  - Calendar-spread edge detector
  - Risk-reversal anomaly scanner
  - Cross-asset convergence (VIX vs VXFXI vs VSTOXX divergence trades)
  - Pair-trade engine (correlated underlying, vol divergence)
  - Kelly-criterion position sizing with backtest hit-rate prior
  - Monte-Carlo VaR with vol-of-vol
  - Plain-English Vol Regime Summary (LLM-synthesised one-paragraph)
  - Pre-trade card with strike/maturity selection + P&L curve
  - Vol-of-vol indicator (VVIX-equivalent for any ticker)
  - Greeks aggregation across tracked positions (portfolio vega/theta)

Mandate: ≥ 12 distinct ideas, scored. Quality > quantity. No platitudes.
The orchestrator will pick the highest novelty×feasibility item to schedule.

Output JSON:
{
  "agent": "ideas",
  "timestamp": "<ISO8601>",
  "bold_ideas":           [{name, description, hedgefund_impact, implementation_sketch, novelty_score, feasibility_score, estimate_hours, severity}, ...],
  "concept_redesigns":    [{...}, ...],
  "experimental_features":[{...}, ...]
}

`severity` should be set by you to "high" if novelty ≥ 7 AND feasibility ≥ 7,
else "medium". This makes findings show up in the maturity-check D2 dimension.

Write to data/audit/ideas_<YYYYMMDD_HHMM>.json. Print only the path.
"""

PROMPTS = {
    "ui":       UI_AUDIT_PROMPT,
    "math":     MATH_AUDIT_PROMPT,
    "universe": UNIVERSE_AUDIT_PROMPT,
    "ideas":    IDEAS_AUDIT_PROMPT,
}


# ─────────────────────────────────────────────────────────────────────────
# Output schema (for validation)
# ─────────────────────────────────────────────────────────────────────────

SCHEMA = {
    "ui": {
        "required_keys": ["agent", "bugs", "feature_gaps", "ux_friction", "quick_wins"],
        "list_keys":     ["bugs", "feature_gaps", "ux_friction", "quick_wins"],
        "item_required": ["severity", "description"],
    },
    "math": {
        "required_keys": ["agent", "math_bugs", "edge_case_gaps", "conceptual_problems"],
        "list_keys":     ["math_bugs", "edge_case_gaps", "conceptual_problems", "quick_fixes"],
        "item_required": ["severity", "description"],
    },
    "universe": {
        "required_keys": ["agent", "universe_gaps", "recommendation_flaws", "missing_modes"],
        "list_keys":     ["universe_gaps", "recommendation_flaws", "missing_modes", "ticker_suggestions"],
        "item_required": ["severity"],   # ticker_suggestions don't need severity
    },
    "ideas": {
        "required_keys": ["agent", "bold_ideas"],
        "list_keys":     ["bold_ideas", "concept_redesigns", "experimental_features"],
        "item_required": ["name", "description"],
    },
}


def validate_audit(agent: str, payload: dict) -> tuple[bool, list[str]]:
    """Validate an audit JSON payload against the agent's schema.
    Returns (ok, list_of_errors)."""
    errors: list[str] = []
    spec = SCHEMA.get(agent)
    if spec is None:
        return False, [f"unknown agent: {agent}"]
    for k in spec["required_keys"]:
        if k not in payload:
            errors.append(f"missing key: {k}")
    for k in spec["list_keys"]:
        v = payload.get(k)
        if v is not None and not isinstance(v, list):
            errors.append(f"key {k} must be a list, got {type(v).__name__}")
    return (len(errors) == 0), errors


# ─────────────────────────────────────────────────────────────────────────
# CLI helpers
# ─────────────────────────────────────────────────────────────────────────

def emit_prompts() -> None:
    """Write each prompt to data/audit/agents/<agent>.md."""
    AGENTS_DIR.mkdir(parents=True, exist_ok=True)
    for agent, prompt in PROMPTS.items():
        target = AGENTS_DIR / f"{agent}.md"
        target.write_text(prompt)
    print(f"Wrote {len(PROMPTS)} prompt files to {AGENTS_DIR.relative_to(ROOT)}/")
    print()
    print("To run the audits, the orchestrator (or a human) launches 4 Explore")
    print("subagents in parallel — one per prompt. Each agent writes its JSON")
    print("output back to data/audit/<agent>_<YYYYMMDD_HHMM>.json.")
    print()
    print("Suggested timestamp tag for this batch:")
    print(f"  {datetime.now().strftime('%Y%m%d_%H%M')}")


def list_audits() -> None:
    """Print existing audit files newest-first, grouped by agent."""
    if not AUDIT_DIR.exists():
        print("(no audit dir yet)")
        return
    by_agent: dict[str, list[Path]] = {}
    for p in AUDIT_DIR.glob("*_*.json"):
        agent = p.stem.split("_")[0]
        by_agent.setdefault(agent, []).append(p)
    for agent in ["ui", "math", "universe", "ideas"]:
        files = sorted(by_agent.get(agent, []), reverse=True)
        if not files:
            print(f"  {agent:<10} —  no audits yet")
            continue
        print(f"  {agent:<10} {len(files)} files, latest: {files[0].name}")


def print_schema() -> None:
    print(json.dumps(SCHEMA, indent=2))


def main() -> int:
    p = argparse.ArgumentParser(description="VolScope audit prompt spawner")
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--emit",   action="store_true", help="write prompt files")
    g.add_argument("--list",   action="store_true", help="list existing audits")
    g.add_argument("--schema", action="store_true", help="print JSON schema")
    args = p.parse_args()

    if args.emit:
        emit_prompts()
    elif args.list:
        list_audits()
    elif args.schema:
        print_schema()
    return 0


if __name__ == "__main__":
    sys.exit(main())
