# VolScope Progress

## Last Session: 2026-05-14 (v0.2.0 + v0.3.0 shipped, OS framework next)

- Bootstrapped the repo: 4 commits pushed to github.com/SchoenTom/volscope (private)
- Shipped Phase 0 bug fixes + Phase 1 signal engine + Phase 1 finishing (garch/ibkr_stub/ranking)
- Shipped Phase 2 core scaffolds (state machine + scheduler + kill switch)
- Shipped v0.3.0 paper engine: chain scraper + chain_quote + paper_engine + daily_mtm + paper_backtest + Bot Dashboard wiring
- Wrote `docs/TOOLS.md` (10-section tool catalog) + `docs/roadmap/MASTER_PLAN.md` (unified scope)
- Repositioned README: research workbench primary, sim bot + paper trader as layered modes
- Now building the Operating System framework (MEGA-1)

## Current Phase: Phase 2 scaffolds shipped → MEGA-1 OS framework

## Test Status

Last full run: 90 passed / 1 skipped / 0 failed on the 11 new modules; 87% coverage on new code.
Legacy test suite not re-run after script reorg — pending CI green confirmation.

## Bot Status: paper_dev (scaffold stage)

- ✅ Chain snapshots schema + scraper
- ✅ paper_engine.execute_blueprint writes bot_trades + bot_legs
- ✅ daily_mtm computes MTM + applies 50% PT / 2× stop / 21-DTE close
- ⏳ Scheduler wiring (handlers stubbed; real handlers Phase 2.5)
- ⏳ Telegram alerts (raw httpx; not connected)
- ⏳ Live IBKR (Phase 2.5+; not in scope this quarter)

## Active Branch: main

## Open Bugs

(none P0 currently — see MASTER_PLAN.md for backlog)

## Next 3 Steps (priority order)

1. MEGA-1: finish Operating System framework (CLAUDE.md extensions + decisions.md +
   .claude/ structure)
2. Watch CI to green + set branch protection on `main`
3. MEGA-3 partial: per-page banners for top-5 pages (Command, Discover, Signals,
   Scope, Bot Dashboard)

## Open Questions for Operator

- Free vs paid product split — when does the bot become paid-tier?
- License flip to MIT — what timeline?
- Co-maintainers on CODEOWNERS — anyone besides @SchoenTom?
