# VolScope Progress

## Last Session: 2026-05-14 (v0.5.0 SHIPPED — production-hardening complete)

Today's wave (commits a8e05a7 + 3c81a40 + earlier):

- **9 of 13 deferred items shipped** in v0.5.0 (per operator's research prompt):
  hash-chained audit log, order_intents idempotency, asyncio.Lock on risk
  paths, risk-thresholds split + immutability, DuckDB backup + restore drill,
  `.claude/` fully populated (7 agents + 10 skills + 5 commands + 5 rules),
  anti-stop block, Hull goldens + Hypothesis property suite, CLAUDE.md trim.
- **CLAUDE.md trimmed 289 → 184 lines** (under research cap).
- **`docs/roadmap/MASTERPIECE_BACKLOG.md`** banked — 70-item inventory of
  everything between us and v1.0, sourced from two parallel research streams.
- **6 commits live** at https://github.com/SchoenTom/volscope (private).
- CI green; repo ready for collaboration.

## Current Phase: v0.5.0 done → v0.6.0 (math validation + chain backfill + 5-agent panel)

## Test Status

138 tests across 14 modules; all green locally. Coverage on new modules ~87%.
CI green on Ubuntu Python 3.11 + 3.12.

## Bot Status: paper_dev (scaffolds + hardening shipped; awaiting Phase 2.5 wiring)

- ✅ Audit chain WORM-enforced (SHA-256 prev_hash + orjson canonical)
- ✅ Order intents idempotent (Stripe Idempotency-Key semantics)
- ✅ Kill switch hardened (3 manual + 5 auto paths + literal reset)
- ✅ Risk thresholds immutability gate (OPERATOR_APPROVED=yes trailer)
- ✅ Backup + restore drill scripts (DuckDB 1.4 native AES-256-GCM optional)
- ⏳ Live scheduler wiring (Phase 2.5)
- ⏳ HMM training on real history (v0.6.0 D10)
- ⏳ `bot_chain_snapshots` / `sector_daily` data backfill (v0.6.0 D6/D7 — BLOCKER)

## Active Branch: main

## Open Bugs

- `bot_chain_snapshots` empty (v0.6.0 D6 — backfill blocks Phase 3 backtest)
- `sector_daily` table 0 rows; `compute_sector_rotation.py` failing silently
  (v0.6.0 D7)

## Next 3 Steps (priority order — see MASTERPIECE_BACKLOG.md)

1. **v0.6.0 D6 + D7** — populate chain snapshots + fix sector rotation.
   Unblocks every downstream backtest + dashboard panel.
2. **v0.6.0 A3 + A4** — `py_vollib_vectorized` round-trip + QuantLib goldens.
   The math validation gate.
3. **v0.6.0 B2 + B3** — wire scheduler handlers + reconciler.
   Makes the bot actually run autonomously.

## Open Questions for Operator

- Free vs paid product split — when does the bot tier become paid?
- License flip to MIT — when do GOING_PUBLIC_CHECKLIST.md gates clear?
- Co-maintainer on CODEOWNERS — anyone besides @SchoenTom?
- Branch protection on main — set today after CI green confirms?
