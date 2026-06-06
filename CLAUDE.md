# VolScope — Operating Manual for Claude

> Read at session start. Update when you learn. Hard cap: 250 lines
> (Anthropic empirical guidance + arXiv 2507.11538 instruction-following
> degradation). Conditional / path-scoped detail lives in
> `.claude/rules/*.md` and `.claude/skills/*/SKILL.md`.

## Project Identity

VolScope is a focused **IV-research workbench** for retail options
traders — implied-vol richness/cheapness discovery, term structure,
skew, earnings, and regime forecasting.

- Tech: Python 3.11+, Streamlit, DuckDB 1.4+, Plotly, yfinance (research).
- Operator: SchoenTom (private repo, plan to flip MIT later).
- Stage: research tool. No order execution — VolScope surfaces signals;
  the human decides and trades elsewhere.
- Vision: answer one question — where is vol cheap vs rich? — across
  Discover, Scope, Heatmap, Earnings Hub, Vol Insights, Scanner, and
  the forecasting (GARCH / HMM regime) layer.

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
6. **No `--force` on main** — branch protection enforces; recovery via
   `chore/initial-fixup` branch per `CONTRIBUTING.md`.
7. **No `--no-verify`** on commits — pre-commit hooks are sacrosanct.

Path-scoped detail in `.claude/rules/{analytics,ui,persistence,secrets}.md`.

## Hard commands

| Action | Command |
|---|---|
| Install deps | `.venv/bin/pip install -r requirements.txt` |
| Install forecasting extras | `.venv/bin/pip install -e '.[forecasting]'` |
| Run app | `make run` |
| Fast tests | `make pre-merge-check` |
| Golden + property sweep | `.venv/bin/python -m pytest tests/golden/ tests/properties/ -q` |
| E2E smoke | `make verify-all` |
| Release DB lock | `make unlock` |
| Backup | `make backup` |
| Restore drill | `make restore-drill` |

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
| 1 | ✅ DONE | IV/HV analytics: BSM, IV solver, HV estimators, regime, GARCH |
| 2 | ✅ Core | Research pages: Discover, Scope, Heatmap, Earnings Hub, Vol Insights, Scanner |
| 3 | ⏳ next | Forecasting layer polish: GARCH(1,1)-t + HMM regime surfacing |
| 4+ | ⏳ future | SVI/SSVI surface fit, per-name GEX, dispersion, calendar analytics |

Anchor doc: `docs/roadmap/MASTER_PLAN.md` + `docs/roadmap/MASTERPIECE_BACKLOG.md`.

## Gotchas (extend when you learn)

Non-obvious "the codebase looks like X but actually behaves like Y":

- **Plotly fillcolor** rejects 8-char hex. Use `rgba()` at
  `volscope/ui/styles/theme.py:15`.
- **`st.metric`** truncates. Use `kpi_grid_html()`.
- **DuckDB exclusive lock** — one writer at a time. UI is read-only;
  the scraper is sole writer. `make unlock` if stuck.
- **DuckDB reserved words** — `RIGHT` is one. Use `option_right` in
  chain tables (see ADR-0002 + decision-log 2026-05-14).
- **DuckDB no partial indexes** — use full index + WHERE in queries.
- **HMM regime fit** needs ≥252 days; the model raises on shorter.
- **DuckDB no PITR** — `EXPORT DATABASE` after market close + hourly
  during. See `docs/BACKUPS.md`.
- **Canonical project path is `~/dev/VolScope`** (NOT `~/Desktop/VolScope`).
  The repo was migrated off iCloud-synced Desktop on 2026-05-15 after
  iCloud File Provider timeouts (`Errno 60: Operation timed out` on
  numpy `.so` imports) made Streamlit cold-boot take 8+ minutes and
  caused chain-scrape failures that overwrote iv_30d with NULL across
  52 tickers. Cold-import on `~/dev` is ~10 s (normal Python startup).
  Old `~/Desktop/VolScope` may still exist as a frozen snapshot; do
  not edit it. `scripts/ops/keep_warm.sh` is retained as a no-op
  safety-net but should never be needed again.
- **scripts/ paths moved in v0.2.0** to `scripts/<group>/`. Old direct
  references will break — grep before reorganising.
- **Yahoo `impliedVolatility`** rate-limited since Nov 2024
  (~360 req/hour/IP). EOD only.
- **`right` as a Python attribute** keeps working on dataclasses;
  only the SQL column was renamed to `option_right`.
- **IV Rank single-spike contamination** — `|IVR − IVP| > 30` flags
  the FISV-class bug where one extreme spike inflates the 52-week
  MAX, making standard IVR misleadingly "CHEAP". Always check
  `iv_recommendation` from `daily_vol` before trading on IVR alone.
  See `docs/IV_ROBUSTNESS.md` + `volscope/analytics/iv_robustness.py`.

## Where things live

| Path | Purpose |
|---|---|
| `volscope/analytics/` | Pure math: BSM, IV solver, HV estimators, regime, GARCH |
| `volscope/persistence/` | DuckDB migrations |
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
