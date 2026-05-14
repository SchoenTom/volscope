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
