---
description: Five-agent virtual review panel — Security / Math+Correctness / Performance / UX / Risk. Parallel review of a PR or a code change set. Outputs PASS / REVISE / REJECT with deduplicated findings.
---

# /full-review

The 5-agent virtual panel. Used before merging a non-trivial PR.

## Invocation

```
/full-review <diff-ref>     # e.g. main..feat/foo, HEAD~3..HEAD
```

If no ref given, defaults to the staged diff (`git diff --cached`).

## Five reviewers run in parallel

| Agent | Focus | Trigger phrase |
|---|---|---|
| `signal-engineer` | Math + correctness of signals / analytics | MUST BE USED on volscope/signals/ + analytics/regime + garch |
| `risk-auditor` | Safety surface: kill switch, sizing, thresholds | PROACTIVELY on volscope/risk/ + config/risk-thresholds.yaml |
| `security-reviewer` | Secrets, injection, audit-chain integrity | PROACTIVELY on .env*, persistence/audit_chain.py, kill_switch.py |
| `code-reviewer` | Style, idiom, bug-spotting | MUST BE USED on any new Python in volscope/ |
| `observability-engineer` | Logs, metrics, dashboard surface | when a module adds new state without exposing it |

Each writes a `ReviewArtifact` JSON to a temp dir:

```json
{
  "schema_version": "1.0",
  "agent": "risk-auditor",
  "verdict": "PASS|REVISE|REJECT",
  "findings": [
    {
      "severity": "critical|high|medium|low",
      "category": "secrets|math|risk|style|observability",
      "file": "volscope/risk/kill_switch.py",
      "line": 42,
      "fix": "one-line suggestion"
    }
  ],
  "confidence": 0.0
}
```

## Aggregator

After all 5 finish:

1. **Dedupe** findings by `(file, line_range, category)` — same file +
   line + category from multiple agents = one finding, agreement_count
   recorded.
2. **Severity-weight** by `severity × agreement_count`. A finding
   raised by 3 agents outranks a singleton.
3. **Verdict resolution:**
   - Any REJECT → REJECT.
   - ≥2 REVISE → REVISE.
   - Otherwise PASS.

## PASS / REVISE / REJECT loop

- PASS → merge eligible.
- REVISE → operator addresses findings; re-run `/full-review` (cap 3
  iterations).
- REJECT → operator stops, opens an ADR or post-mortem before
  proceeding.

## Implementation (v0.6.0 — WIRED)

Orchestration: `volscope/orchestration/full_review.py`.
CLI: `scripts/ops/full_review.py`.

Invoke:

```bash
make full-review                       # diff = HEAD~1..HEAD
make full-review REF=main..feat/foo    # specific range
python -m scripts.ops.full_review --mock    # no API calls (CI default)
```

Mock mode runs when the `claude` CLI is not in PATH (CI). Real mode
spawns 5 parallel `claude --output-format json -p <rubric>` subprocesses
— full process isolation, role-specific rubrics from the agent
frontmatter, JSON-only output. Independence by construction.

Aggregator clusters findings by `(file, line_range±3, category)`,
severity merged as MAX, scored by `severity_weight × agreement_count`.
Markdown report at `docs/reviews/<YYYY-MM-DD-HHMM>-<ref>.md`.

Exit code: PASS=0, REVISE=1, REJECT=2.

Tests: `tests/test_full_review.py` covers dedupe + severity merge +
verdict resolution + iteration cap + JSON round-trip + markdown
rendering. **12 tests, all green.**

## Anti-patterns to avoid

- Cross-agent Python imports (use subprocess + JSON stdio only).
- Counting findings without dedupe (over-weights overlapping agents).
- Skipping the cap at 3 iterations (turns into endless polish).
- Letting agents edit each other's verdicts.
