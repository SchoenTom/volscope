# Welcome, Agent

You are a Claude Code session that has just opened this repo. Read this
file first. It takes 2 minutes and saves you from re-deriving project
context.

## Reading order

1. **`WELCOME-AGENT.md`** — this file. Hard rules + orientation.
2. **`CLAUDE.md`** — developer guide, common commands, non-obvious
   architecture notes.
3. **`memory/INDEX.md`** — curated reading order for the agent canon.
4. **`ROADMAP.md`** — phase status table.
5. **`docs/ARCHITECTURE.md`** — module diagram + data flow + WORM
   audit-log invariant.

Stop when you have enough to begin. You do not have to read everything.

## Where things live

| Path | Purpose |
|---|---|
| `volscope/` | Python source. Streamlit UI + analytics + signals + bot loop. |
| `tests/` | pytest. Run with `make test`. |
| `scripts/` | Batch jobs grouped by purpose (`scrape/`, `verify/`, `audit/`, `compute/`, `backtest/`, `ops/`). |
| `config/` | YAML — strategies, risk, tickers, calendar. **Operator-visible.** |
| `memory/` | Persistent agent knowledge (read on every new session). |
| `docs/` | Reference docs + ADRs + roadmap. |
| `.github/` | CI, dependabot, issue / PR templates. |

## Hard rules (do not violate)

1. **No live IBKR orders without explicit human approval.** The Phase 2
   scaffolds run paper-only. Live wiring is Phase 2.5+ and requires the
   operator's written go-ahead.
2. **No intraday parameter changes.** `config/*.yaml` edits land in the
   Sunday 18:00 ET review window with a 90-day cooldown.
3. **`memory/` files are sanitised.** No real names, emails, university
   details, position sizes, or tax IDs. Preserve this on every edit.
4. **Don't trade the operator's existing thesis positions.** They appear
   in `config/tickers.yaml` as `monitor_only`.
5. **Don't force-push.** Branch protection rejects it. Recovery
   procedure documented in `CONTRIBUTING.md`.
6. **Don't skip `pre-commit`.** Gitleaks runs as a hook — bypassing it
   risks leaking the personal info we just sanitised.

## Common commands

```bash
make run            # start Streamlit UI
make test           # full test suite
make verify-all     # 7-stage end-to-end smoke
make start          # daily startup ritual (DB freshness + scrape if stale)
make unlock         # release stale DuckDB lock
```

## What you can do without asking

- Read any file.
- Run tests, ruff, mypy, gitleaks.
- Edit code on a feature branch.
- Add ADRs for any architecturally significant decision you make.
- Create issues + draft PRs.

## What you must ask before doing

- Pushing to GitHub.
- Force operations (`git reset --hard`, `git push --force`).
- Changes to `config/risk.yaml` or `config/strategies.yaml`.
- Anything that touches `volscope/risk/`, `volscope/execution/`, or
  `volscope/lifecycle/` once Phase 2.5 is live.
- Bringing new external dependencies into `pyproject.toml`.

## If you're stuck

- Check `memory/INDEX.md` for prior decisions and context.
- Check `docs/adr/` for the "why" of load-bearing choices.
- Check `docs/process/` for archived planning artefacts (useful for
  long-running questions like "why does the Pre-Trade page do X").

Welcome aboard.
