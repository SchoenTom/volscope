# Decision Log

A flat, append-only log of every non-trivial decision. Lighter than
ADRs (those are reserved for architecturally significant choices) —
this catches the day-to-day "why did we do it this way" so future-you
or future-agent doesn't have to spelunk through commits.

**Format per entry:**

```
## [ISO-Date] [Title]
**Choice:** what was chosen
**Alternatives:** what else was on the table
**Why:** 2-3 sentences
**Evidence:** files / tests / sources consulted
**Reversibility:** reversible | hard | irreversible
**Confidence:** low | medium | high
```

---

## 2026-05-14 Wire `/full-review` as a real 5-agent panel

**Choice:** Implement `volscope/orchestration/full_review.py` +
`scripts/ops/full_review.py` to spawn 5 parallel `claude -p`
subprocesses (signal-engineer, risk-auditor, security-reviewer,
code-reviewer, observability-engineer), each with role-specific
rubric + isolated context. Aggregate via dedupe-by-(file, line±3,
category) with severity × agreement scoring.
**Alternatives:** Sequential agent calls inside one Claude session
(loses independence); single super-agent reviewer (less diversification);
keep it as a spec-only command (theatre).
**Why:** Operator's iid-ness question — without subprocess isolation
+ JSON contracts, the 7 subagent specs are decoration, not a review
committee. Real independence rewards rediscovery and surfaces
real disagreement.
**Evidence:** TradingAgents v0.2.4, wshobson/agents, Paperclip
6-agent postmortem (no direct A→B messaging — JSON via shared state).
**Reversibility:** reversible — orchestration layer is pure Python;
removing it leaves agent specs intact.
**Confidence:** high.

## 2026-05-14 Apply DuckDB migrations 001-005 to the live DB

**Choice:** Run `apply_migrations()` against
`~/Library/Application Support/VolScope/volscope.db` — adds 6 `bot_*`
tables + `bot_chain_latest` view that have been defined since v0.3.0
but never instantiated on the operator's actual DB.
**Alternatives:** Wait for live IBKR wiring (Phase 2.5+) to apply
migrations as part of that work.
**Why:** Without the live tables, `bot_chain_snapshots` cannot store
the option-chain data the paper engine needs for daily MTM. The
operator's DB has been running with v0.2.0 schema for 2 weeks while
v0.3.0+ test DBs had the new schema.
**Evidence:** Phase 1 exploration confirmed `bot_chain_snapshots`
returned ParserException ("Table not found") on the live DB.
**Reversibility:** hard — creating tables is non-destructive but
rolling back would require manual `DROP TABLE` + cleanup of any rows
the paper engine writes after migration.
**Confidence:** high.

## 2026-05-14 Fix `.parent.parent` → `.parent.parent.parent` in 17 scripts

**Choice:** Mass-rewrite the `_ROOT = Path(__file__).resolve().parent.parent`
pattern across `scripts/` to use 3 levels (the post-v0.2.0-reorg correct
path to the repo root). Used a Python regex sweep to ensure consistency.
**Alternatives:** Switch every script to use `pip install -e .`
exclusively (no sys.path manipulation needed).
**Why:** The bug was introduced by the v0.2.0 script reorg that moved
files from `scripts/foo.py` (2 levels above root) to
`scripts/<group>/foo.py` (3 levels). 14 of 18 scripts had the broken
2-level path, causing `ModuleNotFoundError: No module named 'volscope'`
when invoked. The operator hit this on a fresh ZIP download from
GitHub — exactly the "must work first-try" expectation.
**Evidence:** Operator's bug report 2026-05-14 (16:32 ET) + my Python
sweep that fixed 14 files.
**Reversibility:** reversible — the pattern is mechanically detectable.
**Confidence:** high.

---

## 2026-05-14 Make memory/ chat-archive a committed folder (31 MB of RTFs)

**Choice:** Commit the 31 MB of chat-dump RTFs as `memory/chat-archive/`.
**Alternatives:** (a) gitignore them, (b) move to a sibling repo via
git submodule, (c) delete entirely.
**Why:** Operator explicitly wants them as agent context — "everything
to know for agents". Git handles 31 MB without LFS; the value of
preserving conversation history for future Claude sessions outweighs
the size cost. Will switch to LFS if archive grows past ~100 MB.
**Evidence:** Operator's directive in session 2026-05-14, +
`memory/README.md` documents the trade-off.
**Reversibility:** reversible (can `git filter-repo` later).
**Confidence:** high.

## 2026-05-14 Rename SQL column `right` → `option_right`

**Choice:** Rename the call/put indicator column in
`bot_chain_snapshots` from `right` to `option_right`.
**Alternatives:** Keep `right`, quote it in every SQL statement
(`"right"`).
**Why:** `RIGHT` is a SQL reserved word (string function); DuckDB's
parser rejected it in DDL. Renaming is cleaner than quoting in every
query and future-proofs against parser updates.
**Evidence:** DuckDB ParserException on first migration apply (see
session log 2026-05-14).
**Reversibility:** reversible (migration would be `ALTER TABLE ...
RENAME COLUMN`); zero data live yet.
**Confidence:** high.

## 2026-05-14 Drop `uv` from CI in favour of stock `pip`

**Choice:** CI workflow uses `actions/setup-python` + `pip install -r
requirements.txt` instead of `astral-sh/setup-uv` + `uv sync`.
**Alternatives:** Generate a `uv.lock` file and commit it; switch CI to
fully `uv`-native.
**Why:** First CI run failed because `setup-uv@v3` requires `uv.lock`
which we don't have. Generating + maintaining a lockfile is friction
that doesn't pay off for a single-operator private repo at this stage.
Local dev still uses uv via `pyproject.toml`.
**Evidence:** CI run #25854641098 failure log; commit `79360b0`.
**Reversibility:** reversible — flip back when we're ready to commit
`uv.lock` and standardise on uv across dev + CI.
**Confidence:** medium (will revisit when team grows or build
reproducibility becomes critical).

## 2026-05-14 Private repo with NOTICE, flip to MIT later

**Choice:** Push as private with a proprietary NOTICE; plan a flip to
MIT once `docs/GOING_PUBLIC_CHECKLIST.md` gates clear.
**Alternatives:** Public + MIT from day 1; private forever.
**Why:** Private gives breathing room to iterate without external
scrutiny; MIT later opens the project to community contributors once
the bot logic is paper-validated and the audit log is clean.
**Evidence:** Operator's `AskUserQuestion` answer + checklist doc.
**Reversibility:** hard once public — git history would need a
filter-repo pass before flip.
**Confidence:** high.

## 2026-05-14 21-DTE mechanical close as a hard invariant

**Choice:** Every short-vol strategy config block must include
`dte_exit: 21`. Validator rejects any short-vol config that omits it.
**Alternatives:** Per-strategy override; soft default with operator
discretion.
**Why:** Gamma is 3-5× higher inside 21 DTE (tastytrade Market
Measures). Empirically (tastytrade 4,872 SPY trades + DTR 96k SPX
trades) the rule lifts realised win rate from 64% → 82% on the same
underlying logic. This is non-negotiable for the bot.
**Evidence:** `docs/adr/0005-21-dte-mechanical-close.md`.
**Reversibility:** reversible only after Phase 3 backtest validation
shows a different cut produces strictly better risk-adjusted returns.
**Confidence:** high.

## 2026-05-14 Quarter-Kelly position sizing as production-safe start

**Choice:** `kelly_fraction: 0.25` in `config/risk.yaml`.
**Alternatives:** Half-Kelly (0.5), Full Kelly (1.0), fractional based
on rolling volatility.
**Why:** Options returns are leptokurtic + negatively skewed; full
Kelly breaks down at Student-t v=4 (Turlakov 2016). Half-Kelly captures
~75% of expected growth at ~50% of drawdown. Quarter-Kelly is the
conservative-by-design starting point; promotion to 0.5 requires
6 months live + Sharpe ±0.3 of paper.
**Evidence:** `docs/adr/0004-quarter-kelly-position-sizing.md`.
**Reversibility:** reversible via Sunday review window + 90-day
cooldown.
**Confidence:** high.

---

(append new decisions here, newest at the top)
