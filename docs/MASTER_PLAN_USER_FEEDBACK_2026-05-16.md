# Master Plan — Operator Feedback Round 2026-05-16

> Source: operator screenshot + multi-issue feedback message
> (Options Lab Builder · payoff render, sidebar bug-list, feature
> requests). Captured during the v0.9.8 multi-alarm session.

## The 12 issues (verbatim, then categorized)

1. **Sidebar contextual menu is wrong on Flow / Rotation pages.** The
   page-aware quick-stats block is hard-coded to Discover / Scope /
   Scanner; Flow & Rotation get whatever the previous state left
   behind. → BUG-S1.
2. **Watchlist section is completely missing.** Read-only DB
   connection in `get_db()` makes `ensure_watchlist_tables(db)`
   raise on first access, the silent except falls through to a
   single info card and the user-watchlist UI never renders. → BUG-S2.
3. **Alerts fire even though I never picked those alarm types.**
   Telegram + macOS pings come from cron-runner cycling through every
   watchlist; legacy watchlists carried `regime_alarms_enabled=TRUE`
   by default, so all of them ping. → BUG-A1.
4. **Vol Insights doesn't work at all.** Page references
   `r.option_right` on `ChainRow` — the actual field is `r.right`. The
   try/except in `_cached_chain_fetch` swallows the `AttributeError`,
   returns an empty DataFrame, the page renders an empty-state card.
   → BUG-V1.
5. **Scope is missing "Add to watchlist" + "Configure alarms".** Today
   the only path to add a ticker is the sidebar form, which loses
   context. → FEATURE-W1.
6. **Watchlist must be more elaborate, not less.** Currently it's a
   sidebar mini-widget. Need: rename, reorder, archive, export, plus
   inline alarm summary. → FEATURE-W2.
7. **Cut unnecessary features instead of expanding them.** Operator
   wants a feature-bloat audit. Candidates: Research, Signals, Mega-Scan,
   Earnings Hub vs Earnings Trades duplication, Strategy Builder vs
   Options Lab overlap. → CLEANUP-1.
8. **I don't understand the Flow section.** Need inline explainers,
   `?` tooltips, an "About this page" expander, glossary links. →
   FEATURE-H1.
9. **Vol Insights tut gar nicht** — same as #4. → BUG-V1.
10. **Options Builder shows wrong portfolio.** Today the Builder
    panel shows synthetic demo legs. Operator wants HIS own paper
    positions visible. → FEATURE-P1.
11. **New section under Watchlist: Portfolio.**
    - Manage own positions
    - One-time reset on next open
    - Infinite capital, only active positions shown
    - Unlimited buys
    - IBKR-style equity-curve chart of portfolio value over time
    → FEATURE-P2.
12. **First-launch should load only the watchlist tickers**, not 842.
    Bonus: TradingView Pine export → CSV import path. → FEATURE-B1.

---

## Theoretical solutions

### BUG-S1 · Sidebar contextual menu on Flow/Rotation
`_render_page_context(page, …)` has a 4-page allowlist. Add Flow
+ Rotation branches (Flow: top PCR + IV-rank ranks; Rotation: sector
heat-map mini). Or simpler: render a unified "Universe pulse" card on
any page that doesn't have a custom branch — avoids per-page work.

### BUG-S2 · Watchlist sidebar disappears on read-only DB
Two angles:
- (preferred) `ensure_watchlist_tables` swallows read-only errors
  silently (write-only operation; if tables already exist this is a
  noop). `list_watchlists` then succeeds against the existing schema.
- (defensive) The sidebar widget short-circuits to a friendly "DB is
  read-only; tables will appear after first scrape" only when
  `list_watchlists` itself raises a Catalog error.

### BUG-A1 · Alerts fire without explicit opt-in
The cron-runner `check_alarms.py` already respects `wl.alarm_types`.
Root cause: legacy watchlists default `alarm_types = ["regime_change"]`
when `regime_alarms_enabled=True`. Fix: change the legacy migration
backfill to leave `alarm_types` empty unless the operator explicitly
ticks a box. New watchlists also default to empty list, not regime.

### BUG-V1 · Vol Insights AttributeError
One-line fix: `r.option_right` → `r.right` inside
`_cached_chain_fetch`. Add a property-style test that loops over
ChainRow attributes used by callers.

### FEATURE-W1 · Scope Add-to-Watchlist
Add two buttons in the Scope header area:
- `+ Add to watchlist` — opens a popover with watchlist names + a
  "create new" option. On submit: `add_ticker_to_watchlist(name, t)`
  + toast.
- `🔔 Configure alarms` — deep-links to the sidebar alarm picker
  (or renders an inline expander identical to the sidebar widget).

### FEATURE-W2 · Watchlist feature depth
Defer the rename/archive/export to a dedicated round; this session
ships only what unblocks daily use (alarm summary chip per watchlist
in the expander label).

### CLEANUP-1 · Feature-bloat audit
Write `docs/FEATURE_BLOAT_AUDIT.md` listing every page with a usage
verdict (KEEP / MERGE / REMOVE). Operator approves before any code
is deleted.

### FEATURE-H1 · Flow page explainers
Add an expander at the top: "What this page shows" with a
paragraph + glossary of PCR / volume spike / gamma exposure terms.
Every KPI gets a `help=` tooltip via existing `glossary.py`.

### FEATURE-P1 · Builder shows own portfolio
Wire the Builder's portfolio panel to the paper-portfolio book
(Phase 2 of FEATURE-P2). Until P2 lands, hide the synthetic-demo
panel behind an explicit "Show demo positions" toggle.

### FEATURE-P2 · Personal Portfolio with equity curve
- DB: new `personal_positions(id, ticker, qty, entry_price,
  entry_date, exit_date, exit_price, kind, notes)` table.
- DB: `personal_equity_curve(date PRIMARY KEY, equity)` table —
  rolled forward by a cron or on-render compute.
- UI: new tab on existing `portfolio_page.py` ("Paper Book")
  rendering active positions (no qty-zero rows), an add-position
  form (unlimited capital, no margin), and the equity curve.
- One-time reset: a `reset_personal_book()` helper the operator
  invokes once via a top-of-page button.

### FEATURE-B1 · Watchlist-aware bootstrap + TV CSV import
- `make seed-watchlist` queries watchlist_items, falls back to the
  19-ticker Bot universe if empty.
- `make quickstart` default switched to `seed-watchlist`.
- TV CSV import: add a "Import from CSV" expander to the
  watchlist-create form. Accepts paste or upload; parses
  comma-separated symbols; creates a new watchlist + ingests the
  tickers in the same batch.

---

## Execution order (smallest blast radius first)

| Step | Item | Commit | Risk |
|---|---|---|---|
| 1 | This plan doc | docs only | none |
| 2 | BUG-V1 (Vol Insights field rename) | 1-line analytics | none |
| 3 | BUG-S2 (read-only watchlist) | persistence + sidebar | low |
| 4 | BUG-A1 (alarm opt-in default) | persistence | low |
| 5 | BUG-S1 (Flow/Rotation context) | sidebar component | low |
| 6 | FEATURE-W1 (Scope buttons) | new component + scope_page | low |
| 7 | FEATURE-H1 (Flow explainers) | flow_page | none |
| 8 | FEATURE-P2 (Paper book + equity curve) | persistence + portfolio_page | medium |
| 9 | FEATURE-B1 (Smart bootstrap + CSV import) | Makefile + watchlist form | low |
| 10 | CLEANUP-1 (feature-bloat audit) | docs only | none |
| 11 | FEATURE-P1 (Builder uses own book) | strategy_builder_page | medium |

Each step gets its own atomic commit and a green pytest run before
moving on. Push at the end.

---

## Out of scope for this round (queued for next)

- Full watchlist CRUD (rename, archive, export) — FEATURE-W2 deep
- Removing pages flagged in the bloat audit — needs operator review
- TradingView API integration (Pine export → live sync) — only the
  CSV-import MVP this round
- Portfolio P&L attribution, tax lots, multi-leg display — only
  qty + entry/exit + equity curve this round
