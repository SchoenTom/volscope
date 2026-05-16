# Feature-Bloat Audit — 2026-05-16

> Operator feedback: "wir sollten unnötige Features die nicht tun
> ausbauen". Each registered page is rated KEEP / MERGE / REMOVE with
> a one-liner justification. Operator signs off before any deletion.

## Method

Pages found in `_PAGE_REGISTRY` (24 entries). Verdicts based on:
1. How often the page appears in the master plan / roadmap docs
2. Whether it has unique data (vs. reusing what another page shows)
3. Whether the operator referenced it in the last 5 feedback rounds

## Verdicts

| Page | Verdict | Rationale |
|---|---|---|
| **Onboarding** | KEEP | First-launch wizard. Drives the smart-bootstrap path. |
| **Command** | KEEP | The "what should I look at today" landing. |
| **Discover** | KEEP | Universe-level ranking. Heaviest research entry point. |
| **Scope** | KEEP | Single-ticker deep dive. Just got Scope→Watchlist buttons. |
| **Scanner** | KEEP | Filter-driven screener — different mental model from Discover. |
| **Heatmap** | KEEP | Big-picture sector visual the operator references repeatedly. |
| **Rotation** | KEEP | Sector-rotation signals; now has sidebar context panel. |
| **Flow** | KEEP | Capital-flow proxy; just got an inline explainer. |
| **Vol Insights** | KEEP | Skew-EM + front/back IV + max-pain. Differentiating feature. |
| **Alerts** | MERGE → Command | Universe-wide scan; could live as a Command-Center panel. |
| **Earnings Hub** | KEEP | Weekly grid. Operator hits it pre-earnings. |
| **Earnings Trades** | MERGE → Portfolio | Earnings-positioned subset of paper book. Redundant with Portfolio + filter. |
| **Mega-Scan** | REMOVE | Duplicate of Scanner with bigger universe scope. Replace with a "scope" toggle on Scanner. |
| **Bot** | KEEP | Live bot dashboard. Necessary for Phase 2.5+. |
| **Signals** | MERGE → Discover | Factor/HMM tab inside Discover. The standalone page is rarely landed on directly. |
| **Pre-Trade** | KEEP | Checklist before pulling the trigger. Decision-quality gate. |
| **Builder** | MERGE → Options Lab | Strategy Builder is a slimmer Options Lab. Lab is the more powerful surface — fold Builder's templates into Lab's preset library. |
| **Options Lab** | KEEP | Multi-leg analyzer + paper-buy CTA. The "ka-ching" surface. |
| **LEAPS Lab** | KEEP | Long-dated convergence scanner. Distinct strategy lens. |
| **Dossier** | MERGE → LEAPS Lab | Tear-sheet view of a single LEAPS idea. Promote to a Lab tab. |
| **Portfolio** | KEEP | Paper book + risk aggregation. Just got the read-only crash fix. |
| **Backtest** | KEEP | Vectorbt-driven historical performance check. |
| **Research** | KEEP | 4-test statistical gauntlet. Rare but powerful. |
| **Help** | KEEP | Onboarding + glossary anchor. |

## Proposed removals (require operator sign-off)

1. **Mega-Scan** → replaced by Scanner with "Universe: full / curated" toggle.
2. **Builder** → fold templates into Options Lab's preset library.
3. **Earnings Trades** → expose as a "filter by earnings" toggle in Portfolio.
4. **Signals** → integrate as a tab/section in Discover.
5. **Dossier** → become a "details" tab inside LEAPS Lab.
6. **Alerts** → top-of-Command panel.

That collapses 24 sidebar entries to **18** without losing any
analytics. Each removal is an atomic commit; operator can revert
any single one.

## Operator decision

Defer removal until operator confirms each line item. This document
is the proposal; the cuts happen in the next round.

## Not on the chopping block

The hidden-by-design pages (anything reachable only by URL or
next-step footer link) stay reachable — we don't need every page
in the sidebar to render it.
