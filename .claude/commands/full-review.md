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

## Implementation

(v0.6.0 scope per `docs/roadmap/MASTERPIECE_BACKLOG.md` G5)
v0.5.0 just defines the command + agents; v0.6.0 wires the
subprocess-based runner that spawns 5 agents in parallel via
`claude --output-format json -p ...` and aggregates the JSON.

Until v0.6.0: invoke each agent manually with the `Agent` tool +
`subagent_type=<name>`; copy-paste their verdicts; eyeball the dedupe.

## Anti-patterns to avoid

- Cross-agent Python imports (use subprocess + JSON stdio only).
- Counting findings without dedupe (over-weights overlapping agents).
- Skipping the cap at 3 iterations (turns into endless polish).
- Letting agents edit each other's verdicts.
