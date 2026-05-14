# VolScope Maturity Loop — Operating Protocol

**Single source of truth for how the self-perpetuating improvement cycle runs.**

## TL;DR

```
make loop          # pick top issue from queue, print instructions
# (you implement the fix)
make loop-finalize # verify + score + roadmap-append
make loop-forever  # blocking outer-loop variant
make pause / unpause
make synth         # rebuild queue from latest audit JSONs
make audit         # emit the 4 audit-agent prompt files
make maturity      # standalone score check
```

## Layered architecture

| Layer | What | Lifecycle |
|-------|------|-----------|
| **Scripts** | `scripts/maturity_check.py`, `scripts/run_audits.py`, `scripts/loop_iteration.py` | Persistent code in repo |
| **State** | `data/audit/*.json`, `data/maturity_history.jsonl`, `data/audit/queue.json`, `data/audit/current_task.json`, `data/audit/.done` marker | On disk |
| **Pause** | `~/.volscope_loop_pause` marker file | Manual user control |
| **Make targets** | the verbs above | Stable interface |
| **Claude-driven outer cycle** | ralph-loop plugin OR `/loop` skill OR cron | Per-session |

## The 5 phases of one iteration

```
┌─ AUDIT ──────────────────────────────────────────────┐
│ 4 parallel Explore-subagents (UI / Math / Universe   │
│ / Innovation) read code, write JSON to data/audit/   │
└──────────────────────────────────────────────────────┘
                    ↓
┌─ SYNTHESIZE ─────────────────────────────────────────┐
│ scripts/loop_iteration.py --synthesize-only          │
│ Loads all 4 latest audits, dedupes, ranks by         │
│ (severity desc, effort asc) → data/audit/queue.json  │
└──────────────────────────────────────────────────────┘
                    ↓
┌─ PICK ───────────────────────────────────────────────┐
│ scripts/loop_iteration.py --phase pick               │
│ Top item → data/audit/current_task.json              │
│ Prints implementer instructions                      │
└──────────────────────────────────────────────────────┘
                    ↓
┌─ IMPLEMENT (HUMAN OR CLAUDE) ────────────────────────┐
│ Reads current_task.json, edits code, runs tests      │
│ Touches data/audit/.done when complete               │
└──────────────────────────────────────────────────────┘
                    ↓
┌─ FINALIZE ───────────────────────────────────────────┐
│ scripts/loop_iteration.py --phase finalize           │
│   1. make verify (external oracle)                   │
│   2. maturity_check.py --assume-verified             │
│   3. roadmap append                                  │
│   4. progress.json increment                         │
│   5. macOS notification                              │
└──────────────────────────────────────────────────────┘
                    ↓
              (next iteration)
```

## Maturity Score — what "mature" means

Six weighted dimensions (sum = 1.0):

| ID | Dim | Weight | Targets |
|----|-----|--------|---------|
| D1 | Test coverage | 15% | ≥ 800 tests collected |
| D2 | Audit findings | 25% | 0 critical, 0 high, ≤ 3 medium across all 4 agents |
| D3 | Universe coverage | 10% | ≥ 350 tickers, ≥ 6 vol indices, ≥ 4 asset classes |
| D4 | Math correctness | 20% | `make verify` PASS |
| D5 | Recommendation quality | 15% | edge_score + strategy_recommender + pretrade_card + kelly_sizing + cross_asset_hedge all present |
| D6 | UX polish | 15% | CSV export, empty-states, mobile layout, onboarding tour, keyboard shortcuts, theme toggle |

**Mature gate:** score ≥ 95 → loop terminates with exit 9.

**Current baseline (2026-05-01):** 60.3 / 100.

## Hard stops

The loop self-terminates on any of:

1. `~/.volscope_loop_pause` exists (manual pause via `make pause`)
2. `make verify` returns non-zero (verify FAIL → exit 1)
3. Maturity score ≥ 95 (exit 9 — MATURE)
4. Empty queue and zero audit findings (exit 3 — NO QUEUE)

## How to drive the loop autonomously

### Option A — `make loop-forever` (simplest)

Pure-bash outer loop. Blocks waiting for `data/audit/.done` between iterations.
Useful when a human is sitting in front of the terminal and implementing fixes
in another tab.

### Option B — Claude-driven via ralph-loop plugin

Each iteration = one Claude session. Claude reads `data/audit/queue.json`,
implements the top item, runs `make loop-finalize`, terminates. Outer
ralph-loop daemon spawns next session with same context.

```
# Activation:
/ralph-loop:ralph-loop
# In the prompt: "implement next item from data/audit/queue.json,
# run make loop-finalize when done"
```

### Option C — Cron-driven (5 daily slots)

For unattended overnight progress. Each cron invocation = one iteration in
a fresh Claude session. Robust against context loss.

```
# Recommended slots (CEST):
06:47, 10:17, 13:43, 17:51, 21:23
```

## Audit refresh policy

Audits become stale as the codebase evolves. Re-run them:

- After every 5 iterations (meta-rule, enforced by orchestrator), OR
- After any iteration that touches > 200 lines of code, OR
- Manually via `make audit` + spawning the 4 Explore subagents

The maturity score's D2 dimension naturally penalises stale audits because
fixes don't show up in old JSONs. Re-running keeps D2 honest.

## Implementer rules of engagement

When Claude (or a human) implements a queue item:

1. **Read `data/audit/current_task.json` first** — that is the single source of
   truth for what to do this iteration.
2. **Make minimal, scoped changes** — fix what the task says, no scope creep.
3. **Add or update tests** — every code change must have test coverage.
4. **Run `make verify` locally first** — don't push code that doesn't pass.
5. **Touch `data/audit/.done` when complete** — signals the loop to finalize.
6. **If blocked, `make pause`** — never silently abandon a task.

## Anti-drift mechanisms

The auto-dreaming-blueprint memory warns about LLMs drifting into
plausibility-confidence. The loop counters this with:

- **External verify oracle** — `make verify` cannot be faked by Claude
- **Quantitative maturity** — score is computed from disk state, not from
  Claude's claims
- **Audit refresh** — stale findings get superseded automatically
- **Hard stops** — loop won't run past failures or pause-marker

## Files-of-record

| File | Role |
|------|------|
| `progress.json` (`phases.P6_loop.iterations`) | Authoritative iteration counter |
| `data/maturity_history.jsonl` | Append-only score history |
| `data/maturity_latest.md` | Human-readable latest report |
| `~/.claude/plans/volscope-roadmap.md` | Run log (one line per iteration) |
| `data/audit/<agent>_<ts>.json` | Each agent's findings (immutable) |
| `data/audit/queue.json` | Ranked open issues |
| `data/audit/current_task.json` | The active iteration's task |
| `~/.volscope_loop_pause` | Stop-knob (touch to pause, rm to resume) |

## Success criteria (4-week target)

- [ ] Maturity score ≥ 80 by 2026-06-01
- [ ] Universe ≥ 350 tickers
- [ ] D6 UX polish: 6/6 checklist items present
- [ ] D5 Recommendation: 5/5 modules built (edge, strategy, pretrade, kelly, cross-asset)
- [ ] At least 12 successful loop iterations logged
- [ ] No iteration in history with `verify FAIL`
