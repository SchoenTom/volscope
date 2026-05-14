# VolScope Autonomous Audit Refresh

You are an autonomous Claude firing weekly to refresh the audit findings that drive the maturity loop. The audit JSONs become stale as code evolves; this routine keeps them honest.

## Pre-flight
- `cd /Users/tomschoen/Desktop/VolScope`
- Stop if `~/.volscope_loop_pause` exists
- Read `~/.claude/projects/-Users-tomschoen/memory/volscope-loop.md`
- Read `data/audit/queue.json` to see what's currently flagged
- Read `data/audit/completed.jsonl` to see what's been resolved
- Read `data/maturity_latest.md` for context on what dimensions are weak

## The 4 agents — spawn ALL IN PARALLEL

Use the Agent tool with `subagent_type=Explore` for each. **All 4 in one message** so they run concurrently. Each writes its result JSON to `data/audit/<agent>_<YYYYMMDD_HHMM>.json`.

### Agent A — UI/UX Auditor
> Read all files under volscope/ui/. Find UI/UX bugs, layout breakage, missing affordances. Skip findings already in completed.jsonl. Output JSON with bugs[] / feature_gaps[] / ux_friction[] / quick_wins[]. Each item: {file, line, severity, description, fix_sketch, estimate_minutes}. Max 6 per list. Write to data/audit/ui_<ts>.json.

### Agent B — Math Auditor
> Read all files under volscope/analytics/ and volscope/data/options_scraper.py. Cross-check formulas against Hull and Yang-Zhang (2000). Output JSON with math_bugs[] / edge_case_gaps[] / conceptual_problems[] / quick_fixes[]. Same item schema. Max 6 per list. Write to data/audit/math_<ts>.json.

### Agent C — Universe + Recommendations Auditor
> Read ticker_universe.py, opportunity.py, edge_score.py, strategy_recommender.py, discover_page.py. Find universe gaps + recommendation flaws. Output JSON with universe_gaps[] / recommendation_flaws[] / missing_modes[] / ticker_suggestions[]. Max 6 per list. Write to data/audit/universe_<ts>.json.

### Agent D — Innovation / Ideation Agent
> Read memory files volscope-vision.md and volscope-loop.md. Brainstorm bold features that would push VolScope from "good vol tool" to "best-in-class hedge-fund Vol Intelligence Platform." Score each idea: novelty (1-10), feasibility (1-10), estimate_hours, severity (high if novelty≥7 AND feasibility≥7 else medium). Output JSON with bold_ideas[] / concept_redesigns[] / experimental_features[]. Min 8 distinct ideas. Write to data/audit/ideas_<ts>.json.

## Post-spawn

After all 4 agents return, run:
```
make synth
```
This re-ranks the queue with the fresh findings. Print the top 10 issues.

Then run:
```
make maturity
```
to recompute the score with the new D2 (audit findings) data.

## End-of-session report

Write `data/audit/.last_audit.md`:
- Counts per severity per agent
- Top 5 newly-discovered issues (not in completed.jsonl)
- Maturity score change vs prior

Notify via osascript.

## Safety
- Don't edit code in this routine. Audits are read-only.
- Don't create commits. Audits live in `data/audit/`.
- The 4 Explore subagents are sandboxed (read-only by definition of Explore).
