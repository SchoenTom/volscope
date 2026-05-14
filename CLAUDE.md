# VolScope — Operating Manual for Claude

> Read at session start. Update when you learn. Hard cap: 250 lines
> (Anthropic empirical guidance + arXiv 2507.11538 instruction-following
> degradation). Conditional / path-scoped detail lives in
> `.claude/rules/*.md` and `.claude/skills/*/SKILL.md`.

## Project Identity

VolScope is a **volatility-research workbench** with a **simulation
bot** + **paper-trading capability** for retail options traders.

- Tech: Python 3.11+, Streamlit, DuckDB 1.4+, Plotly, yfinance (research),
  `ib_async` 2.1+ (paper/live, paper-only this quarter).
- Operator: SchoenTom (private repo, plan to flip MIT later).
- Stage: paper-development. **No live IBKR orders** until Phase 4 with
  explicit opt-in + ≥100 closed paper trades.
- Vision: research dashboard primary; bot is one user of the engine;
  paper trader is a manual workflow on the same DB.

## Session Boot Sequence

1. Read **this file** (`CLAUDE.md`) — 60s orientation.
2. Read **`progress.md`** — last-session state, queued work.
3. Read **`docs/decisions.md`** last 5 entries — recent non-trivial choices.
4. `git status` + `git log --oneline -10`.
5. Check active `TaskList`.

Then report to operator in ≤5 lines: where we are, what's open, ready
for direction.

## Hard rules (NEVER VIOLATE)

1. **Tests green before commit.** `pytest -x` exit 0.
2. **Never use yfinance `impliedVolatility`** — recompute via own BSM
   Newton-Raphson. See `.claude/skills/iv-solver/SKILL.md`.
3. **Analytics returns None on bad input** — no raised exceptions from
   `volscope/analytics/*.py`. UI must keep rendering.
4. **Plotly = `go` only.** Never `plotly.express`. Never 8-char hex
   `fillcolor` — use `rgba()` helper at `volscope/ui/styles/theme.py:15`.
5. **`st.metric` is forbidden** — truncates. Use `kpi_grid_html()`.
6. **Live IBKR orders are FORBIDDEN** until Phase 4 with operator
   opt-in. v0.3.0+ paper engine writes to `bot_trades` only.
7. **No `--force` on main** — branch protection enforces; recovery via
   `chore/initial-fixup` branch per `CONTRIBUTING.md`.
8. **No `--no-verify`** on commits — pre-commit hooks are sacrosanct.
9. **Config changes are weekend-only** — `config/risk-thresholds.yaml`
   is operator-only with `OPERATOR_APPROVED=yes` trailer; reviews in
   the Sunday 18:00 ET window with 90-day cooldown.
10. **No mutations to `bot_audit_chain`** — append-only, hash-chained.

Path-scoped detail in `.claude/rules/{analytics,ui,persistence,live-trading,secrets}.md`.

## Hard commands

| Action | Command |
|---|---|
| Install deps | `.venv/bin/pip install -r requirements.txt` |
| Install bot extras | `.venv/bin/pip install transitions arch hmmlearn apscheduler ib_async orjson hypothesis` |
| Run app | `make run` |
| Fast tests | `make pre-merge-check` |
| New-modules sweep | `.venv/bin/python -m pytest tests/test_audit_chain.py tests/test_intent_manager.py tests/test_risk_locks.py tests/golden/ tests/properties/ -q` |
| E2E smoke | `make verify-all` |
| Release DB lock | `make unlock` |
| Backup | `make backup` |
| Restore drill | `make restore-drill` |
| Audit-chain verify | `make audit-verify` |

## Tool Workflow Standards

Every action follows a chain. See `.claude/skills/` for domain-specific
detail; the standard chains are:

**Bug fix**: TaskCreate → Read + Grep → Edit → pytest -x → ruff → mypy
→ streamlit start → TaskUpdate → progress.md.

**Feature**: TaskCreate → Read → Grep → (WebSearch only if state-of-art
unclear) → Write tests → Write code → test-lint-type-app-boot chain
→ docs/decisions.md → TaskUpdate → progress.md.

**Research**: WebSearch → WebFetch → synthesize → if new insight,
append to CLAUDE.md Gotchas + docs/decisions.md.

## Decision protocol — reversibility-tagged

Every non-trivial autonomous decision appends to `docs/decisions.md`
with the 6-line format. Hard rule:

- `Reversibility=irreversible` AND `Confidence<high` → STOP and
  surface to operator.
- Otherwise → execute and continue. Log. Move on.

## Sichtbarkeit — operator sees what you think

After any tool-sequence > 3 tools: one sentence status. Not more, not
less. Example:

> "Bug 1 fixed + tests green. Moving to Bug 2 (keyboard ghost)."

Opus 4.7 is literal: when the instruction is "short status updates,"
stick to it.

## Persistence — don't stop early

Verbatim from Anthropic's prompting guide (also in `WELCOME-AGENT.md`):

> Context window auto-compacts. Save state to `progress.md` /
> `docs/decisions.md` before refresh. **Never artificially stop any
> task early** regardless of context remaining. By default, implement
> changes rather than only suggesting them.

## Phase Status

| Phase | State | What it is |
|---|---|---|
| 0 | ✅ DONE | Dashboard bug fixes |
| 1 | ✅ DONE | Signal engine: factors / composite / filters / ranker / HMM scaffold / GARCH |
| 2 | 🔧 SCAFFOLD (v0.3.0+) | Paper engine with real chain data + state machine + scheduler + kill switch |
| 2.5 | ⏳ next | Live IBKR wiring (Watchdog, BAG combos, walk-price, reconciler) |
| 3 | ⏳ planned | Backtest validation: vectorbt + optopsy + CPCV + Bootstrap CI |
| 4 | ⏳ planned | Go-live ramp (10% → 25% → 50% → 100% over 12 weeks) |
| 5+ | ⏳ future | SVI/SSVI, per-name GEX, dispersion, calendar spreads |

Anchor doc: `docs/roadmap/MASTER_PLAN.md` + `docs/roadmap/MASTERPIECE_BACKLOG.md`.

## Gotchas (extend when you learn)

Non-obvious "the codebase looks like X but actually behaves like Y":

- **Plotly fillcolor** rejects 8-char hex. Use `rgba()` at
  `volscope/ui/styles/theme.py:15`.
- **`st.metric`** truncates. Use `kpi_grid_html()`.
- **DuckDB exclusive lock** — one writer at a time. UI is read-only;
  bot is sole writer. `make unlock` if stuck.
- **DuckDB reserved words** — `RIGHT` is one. Use `option_right` in
  chain tables (see ADR-0002 + decision-log 2026-05-14).
- **DuckDB no partial indexes** — use full index + WHERE in queries.
- **ib_async clientId=0** — master ID, sees manual GUI orders. Bot
  uses ≥1 to stay isolated.
- **HMM regime fit** needs ≥252 days; the model raises on shorter.
- **IBKR rate limit** — 50 msgs/sec hard cap. Wrap in
  `asyncio.Semaphore(40)`.
- **DuckDB no PITR** — `EXPORT DATABASE` after market close + hourly
  during. See `docs/BACKUPS.md`.
- **iCloud File Provider stall** — project at `~/Desktop/VolScope`,
  not the iCloud mirror. First-import of large deps can stall 25-90s
  on fresh shells. `scripts/ops/keep_warm.sh` warms the cache.
- **scripts/ paths moved in v0.2.0** to `scripts/<group>/`. Old direct
  references will break — grep before reorganising.
- **Yahoo `impliedVolatility`** rate-limited since Nov 2024
  (~360 req/hour/IP). EOD only.
- **`right` as a Python attribute** keeps working on dataclasses;
  only the SQL column was renamed to `option_right`.
- **orjson canonical JSON** — audit chain uses `OPT_SORT_KEYS` for
  deterministic hashing. Don't substitute a different serializer.

## Where things live

| Path | Purpose |
|---|---|
| `volscope/analytics/` | Pure math: BSM, IV solver, HV estimators, regime, GARCH |
| `volscope/signals/` | Bot brain: factors, composite, filters, ranking |
| `volscope/risk/` | Kill switch, locks, thresholds — operator-only |
| `volscope/execution/` | Paper engine + intent manager + IBKR stub |
| `volscope/lifecycle/` | 11-state trade machine + daily MTM |
| `volscope/scheduler/` | APScheduler 3.11, America/New_York |
| `volscope/persistence/` | DuckDB migrations + audit chain |
| `volscope/data/` | Yahoo scraper, chain scraper, ticker resolver |
| `volscope/ui/` | Streamlit pages + components |
| `tests/` | pytest (golden / properties / unit / integration / perf) |
| `scripts/` | Batch jobs grouped by purpose |
| `config/` | YAML — strategies, risk, tickers, calendar; `risk-thresholds.yaml` is operator-only |
| `memory/` | Persistent agent canon (project notes, roadmaps, decisions) |
| `docs/` | Reference (ARCHITECTURE, ADRs, roadmap, TOOLS, decisions) |
| `.claude/` | Local Claude Code config (agents, skills, commands, rules) |

## Reading order for a new session

1. `WELCOME-AGENT.md` — entry point + anti-stop block.
2. `CLAUDE.md` (this file).
3. `progress.md` — last session.
4. `docs/decisions.md` — last 5.
5. `docs/roadmap/MASTERPIECE_BACKLOG.md` — what's between us and v1.0.
6. `memory/INDEX.md` — curated agent canon.
