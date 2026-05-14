---
name: VolScope Maturity Loop System
description: Self-perpetuating audit + improve cycle for VolScope — 4 audit agents, quantitative maturity score, make targets, pause marker
type: project
originSessionId: 716ba485-d808-4974-bcf7-dfef50adc832
---
2026-05-01: built a self-perpetuating improvement loop for VolScope so it can
mature autonomously toward a 95/100 quality gate. Owner asked: "loop dich,
nutze mein limit." Current baseline maturity = 60.3/100.

**Architecture (5-phase cycle):**

1. AUDIT — 4 parallel Explore subagents (UI, Math, Universe, Innovation)
   write JSON to `data/audit/<agent>_<ts>.json`. Prompt templates in
   `data/audit/agents/{ui,math,universe,ideas}.md` (run `make audit` to
   regenerate them).
2. SYNTHESIZE — `scripts/loop_iteration.py --synthesize-only` collapses
   latest audit JSONs into ranked `data/audit/queue.json`.
3. PICK — `make loop` prints top issue and writes `current_task.json`.
4. IMPLEMENT — Claude or human edits code, runs tests, touches
   `data/audit/.done` to signal completion.
5. FINALIZE — `make loop-finalize` runs verify + maturity_check + roadmap
   append + progress.json bump + macOS notification.

**Maturity Score (`scripts/maturity_check.py`):**
6 weighted dimensions sum to 1.0:
- D1 Test coverage (15%) — pytest collect ≥ 800 tests
- D2 Audit findings (25%) — 0 critical/high, ≤ 3 medium
- D3 Universe coverage (10%) — ≥ 350 tickers, ≥ 6 vol indices, ≥ 4 asset classes
- D4 Math correctness (20%) — `make verify` OVERALL PASS
- D5 Recommendation quality (15%) — 5 modules: edge_score, strategy_recommender, pretrade_card, kelly_sizing, cross_asset_hedge
- D6 UX polish (15%) — 6 checklist items: csv_export, empty_state, mobile_layout, onboarding_tour, keyboard_shortcuts, theme_toggle

`--assume-verified` flag exists for the orchestrator path so D4 is set to
100 without re-running verify (already done by finalize phase).

**Hard stops:**
- `~/.volscope_loop_pause` exists → exit 2 (paused)
- `make verify` non-zero → exit 1
- Score ≥ 95 → exit 9 (MATURE)
- Empty queue → exit 3

**Make targets:**
- `make audit` — emit prompt files
- `make synth` — rebuild queue
- `make loop` / `make loop-pick` — pick top, print
- `make loop-finalize` — verify + score + record
- `make loop-forever` — outer bash loop (blocking)
- `make pause` / `make unpause`
- `make maturity` — standalone score (slow, runs verify)

**Files of record:**
- `progress.json` — phases.P6_loop.iterations counter
- `data/maturity_history.jsonl` — append-only history
- `data/maturity_latest.md` — human-readable latest
- `~/.claude/plans/volscope-loop-protocol.md` — operating manual
- `~/.claude/plans/volscope-roadmap.md` — run log

**Initial seed JSONs (2026-05-01):**
84 issues across the 4 agents — UI (23), Math (15), Universe (24), Ideas (16).
Top of queue: Scanner column-width fix (15min, severity=high) — already done
in iter #1, score went 60.3 → recomputed.

**How to apply:** When Operator asks to "continue the loop" or "run another
iteration" or "what's next on VolScope", read `data/audit/queue.json`,
implement the top item, run `make loop-finalize`. The maturity score
trend in `data/maturity_history.jsonl` is the ground truth — never claim
progress without seeing the score rise.

**Owner-approved choices (2026-05-01):**
- Token budget: full freedom, no hard cap
- Branching: direct to master (no feature branches)
- Notifications: macOS notifications via osascript
