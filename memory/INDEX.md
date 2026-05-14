# memory/INDEX.md — Reading order for a new agent

If you just opened this repo, read these in order. Stop when you have
enough to begin the requested task — you do not need to read everything.

## 1. Entry point (≤5 min)

1. [`/WELCOME-AGENT.md`](../WELCOME-AGENT.md) — quick orientation, hard rules.
2. [`/CLAUDE.md`](../CLAUDE.md) — developer guide, command reference,
   non-obvious architecture notes, **VolScope Operating System** section
   (Session Boot Sequence, Tool Workflow Standards, Gotchas).
3. [`/progress.md`](../progress.md) — last-session state, what's queued.
4. [`/docs/decisions.md`](../docs/decisions.md) — recent non-trivial
   decisions (last 5 are usually enough).
5. [`/docs/roadmap/MASTER_PLAN.md`](../docs/roadmap/MASTER_PLAN.md) —
   single source of truth for "what's next".
6. [`/docs/TOOLS.md`](../docs/TOOLS.md) — tool catalog (every page,
   every analytics module, synergies).
7. [`/ROADMAP.md`](../ROADMAP.md) — high-level phase status table.

## 2. Project context (≤15 min)

4. [`project.md`](project.md) — what VolScope is, the operator's hard rules.
5. [`roadmaps/bot-masterplan.md`](roadmaps/bot-masterplan.md) — the
   canonical 5-phase north star. **Most important single file** for
   understanding "what are we building and why."
6. [`leaps-lab.md`](leaps-lab.md) — LEAPS Lab subsystem context (the
   convergence scanner + dossier renderer).

## 3. Operational protocols (read if your task touches the bot loop)

7. [`ops/cron-roster.md`](ops/cron-roster.md) — the 8 launchd jobs that
   run autonomous improvement cycles across sessions.
8. [`ops/loop-protocol.md`](ops/loop-protocol.md) — `/loop` discipline
   for cross-session work.
9. [`philosophy/auto-dreaming.md`](philosophy/auto-dreaming.md) —
   "collision with reality over plausibility" — the working philosophy
   for autonomous iteration.

## 4. Signal direction (read if your task touches signals or ML)

10. [`signals/ml-direction.md`](signals/ml-direction.md) — why long-vol
    entries need inverted ML buy_prob (asymmetry note).

## 5. Historical roadmaps (read only if you need the long view)

11. [`roadmaps/giga-master.md`](roadmaps/giga-master.md) — the original
    giga-plan that pre-dates the bot masterplan.
12. [`roadmaps/early-roadmap.md`](roadmaps/early-roadmap.md) — first
    formal roadmap, before the bot direction was set.
13. [`roadmaps/leaps-lab-product.md`](roadmaps/leaps-lab-product.md) —
    LEAPS Lab product plan (now shipped through v3).

## 6. Raw archives (only if specifically needed)

14. [`chat-archive/`](chat-archive/) — raw session transcripts.
    Skip unless investigating a specific past decision.
15. [`research/iv-anomalie-strategie.rtf`](research/iv-anomalie-strategie.rtf)
    — IV anomaly + strategy notes.

## What is NOT in this folder

- Code → see [`/volscope/`](../volscope/)
- Tests → see [`/tests/`](../tests/)
- Live state (DB, logs) → outside the repo (see CLAUDE.md)
- Personal identifiers → removed by sanitisation policy (see README.md)
