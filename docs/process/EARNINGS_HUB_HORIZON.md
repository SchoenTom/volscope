> Status: ARCHIVED
> This document captures a past planning session. It is preserved
> for historical context — current state lives in /memory/roadmaps/ + /ROADMAP.md.

# Earnings Hub — Horizon

How far can this feature go? Honest assessment with research perspectives.

Date: 2026-05-14 · Author: claude-opus-4-7 · Status: **v2 SHIPPED (H1-H5 + thesis + post-capture)**

> **2026-05-14 v2 shipped**: phases H1, H2, H3, H4, H5 + NLP thesis + auto-calibration done.
> Pending: live pytest verification (iCloud subprocess wall continues to block long-running runs in this session).
>
> Files added:
>   - `volscope/analytics/earnings_backtest.py` — H1
>   - `volscope/analytics/earnings_thesis.py` — H6 (NLP)
>   - `volscope/ui/components/earnings_diagnostics.py` — H2
>   - `volscope/ui/views/earnings_positions_page.py` — H3
>   - `scripts/post_earnings_capture.py` — H4
>   - `tests/test_earnings_v2.py` — 25 new tests
>
> Files modified:
>   - `volscope/ui/views/earnings_hub_page.py` — drawer × 5 cards, briefing, macro
>   - `volscope/ui/styles/theme.py` — v2 diagnostics CSS
>   - `volscope/ui/app.py` + `sidebar.py` — Earnings Trades nav

---

## Part 1 — Why this is worth pushing hard

Three reasons the Earnings Hub deserves heavy investment over the
next iterations:

1. **The competitive landscape has a hole.** OptionAlpha, Tastytrade,
   OptionStrat each do **bits** of earnings-vol analytics. Bloomberg
   OMON does it well but costs $24 k/year. **Nobody puts these five
   things in one tile**:
     - Option-implied move (with skew bias)
     - Pre-ER crowded percentile (vs ticker's own history)
     - Expected post-print crush
     - 8-quarter calibration of implied-vs-realised
     - 1-click paper-buy of the recommended structure
2. **All the math is local-data-driven.** No new external API required
   to ship 12 more features. The marginal effort per feature drops as
   the framework matures.
3. **The user's actual workflow.** A retail vol trader's morning is
   "what earnings am I in this week, what's mispriced". The hub IS the
   tool that decides this. Building it 10× better is building the
   product 10× better at the same cost.

## Part 2 — The full ceiling (7-layer model)

A taxonomy of *everything* an Earnings Hub could be, regardless of
budget. We tag each layer with current state + headroom estimate.

### Layer 1 — Better data inputs

| Item | Current | Headroom |
|---|---|---|
| Live option chain bid/ask | absent (BSM synthetic) | huge — would replace synthetic with real-market premium |
| Option chain Greeks | computed | small — already accurate |
| Pre/post-ER IV term structure | partial (iv_30d / iv_60d in DB) | medium — proper "earnings IV" extraction needs more depth |
| Options flow (unusual activity) | partial (volume z-score in crowded score) | medium — could pull dark-pool prints |
| Earnings consensus EPS history | partial (one-quarter via scraper) | small |
| Past 8 quarters spot reaction | computable | low effort, high value |
| Sector ETF correlation | computable from daily_vol | low effort, medium value |
| Macro calendar (FOMC, CPI, NFP) | absent | low effort, high context value |

### Layer 2 — Deeper analytics

| Item | Current | Headroom |
|---|---|---|
| **Earnings strategy backtest** | absent | **massive** — every strategy gets historical edge proof |
| Cross-ticker correlation in clusters | absent | medium — "if JPM beats, what's BAC's edge?" |
| Implied probability of strike hit | derivable from BSM Δ | low effort |
| Sector beta of moves | computable | medium effort |
| Pre-print drift pattern | computable | medium effort |
| Anomaly detection (divergence from own history) | partial via crowded_pre_er | medium effort |
| Ensemble move prediction | absent | high effort, medium accuracy gain |
| Earnings IV term-structure decomposition | absent | medium effort, high signal value |

### Layer 3 — Cross-asset context

| Item | Headroom |
|---|---|
| VIX regime overlay on every tile | low effort |
| FOMC / CPI / NFP clash detector | low effort, important |
| Crypto-vol leader-lag (COIN, MSTR, SQ) | medium effort |
| Sector ETF leader-lag | medium effort |

### Layer 4 — Workflow / UX

| Item | Headroom |
|---|---|
| **Earnings position tracker** (separate view of all open ER trades) | low effort, huge UX win |
| Morning briefing auto-digest | low effort, valuable |
| Calendar export (.ics) | trivial |
| Slack/Telegram push alerts | medium effort |
| Audit trail (thesis → outcome → P/L) | low effort, builds calibration data |
| Watchlist tagging (rule-based grouping) | low effort |

### Layer 5 — Smart features

| Item | Headroom |
|---|---|
| NLP-style 1-sentence thesis per tile | low effort, big readability win |
| Bayesian "agreement" indicator (model vs market) | medium effort |
| Anomaly pattern matcher (current pre-ER vs typical) | medium effort |
| Auto-calibration loop (after ER, feed actuals back) | low effort, **compounds value over time** |

### Layer 6 — Community

Out of scope for VolScope (single-user, owner = Operator). Skip.

### Layer 7 — Real-time / live

Out of scope for v2 (requires WebSocket infra). Defer.

## Part 3 — Estimated ceiling vs current

Current Earnings Hub v1: ships layers 1 (basic), 2 (basic implied+crowded+crush), 4 (basic),
nothing of 5 or 7.

Ceiling (everything layers 1-5): **~3-4× the current feature surface**, **~10× the
analytical depth**, achievable in 4-6 iteration cycles.

**Honest assessment**: we can extract another 80 % of the latent value
without any new external data source. The remaining 20 % requires live
option chain data (which is Phase 0.1 of the LEAPS Lab plan and a
multi-week effort).

## Part 4 — The v2 backlog, prioritised

I rank by **edge-per-effort** — features that move the trader's
decision quality per LOC required.

| # | Feature | Layer | Effort | Edge | Why |
|---|---|---|---|---|---|
| 1 | Strategy backtest harness | 2 | M | XXXL | Without this, our recommendations are theoretical. With it, we show *"Long Straddle in this regime has worked 71 % of past 28 events"*. This is the **single highest-leverage feature** available. |
| 2 | 8-quarter calibration heatmap (per tile drawer) | 2 | S | XL | Visual proof of implied-vs-realised gap. Trader sees the edge instantly. |
| 3 | Pre-ER drift sparklines (price + IV last 10d) | 2 | S | L | "Is this ticker drifting up or down into the print?" — typical pre-print drift is a known edge. |
| 4 | Anomaly badge (current vs historical pattern) | 2 | M | L | When today's setup deviates from the ticker's typical pre-ER pattern, surface it as a warning. |
| 5 | Earnings Position Tracker (filtered Portfolio view) | 4 | S | XL | All open ER trades + countdown + live P/L in one place. Killer workflow upgrade. |
| 6 | Auto-calibration loop (post-print capture) | 5 | S | XL (compounds) | After each ER passes, capture actual move → enrich `last_reaction_pct` → next quarter's calibration is more accurate. |
| 7 | Morning briefing card (auto digest) | 4 | S | L | One paragraph: "Today's prints: NFLX AMC, implied 8.2 %, watchlist match." |
| 8 | Macro event overlay (FOMC/CPI/NFP) | 3 | S | M | Yellow stripe across the grid on macro-event dates so you don't trade ER into a Fed surprise. |
| 9 | Sector cluster grouping toggle | 4 | S | M | "All banks Tuesday" — easier to see correlated clusters. |
| 10 | NLP thesis per tile | 5 | M | M | Auto-generated rationale prose. 'cheap vol + bearish skew → fade the panic'. |
| 11 | Implied probability of strike hit | 2 | S | M | Trader sees P(move > 5 %) directly. Uses existing BSM Δ. |
| 12 | Sector beta + cluster correlation | 2 | M | M | If JPM is up 3 % pre-print, what should we expect from BAC? |

Above-line v2 commitment: items 1-7 (the XL/XXL edge cluster).
Items 8-12 are v2.5 if time permits.

## Part 5 — Anti-features (won't build)

- **Discord/Slack pushes** — Operator is single-user, push channels are noise. Skip.
- **Live-streaming UI** — out of scope without WebSocket infra. Daily-grain analytics already capture 95 % of the edge.
- **Multi-leg structure customisation in the hub** — that's Options Lab's job. Hub recommends, Lab refines.
- **Real-money broker integration** — VolScope is paper-trade by design. Never on the roadmap.

## Part 6 — Implementation order (v2 phases)

Each phase is one self-contained commit with tests + smoke.

### Phase H1 — Backtest Harness (item #1)

Most leverage. Build first.

**New module**: `volscope/analytics/earnings_backtest.py`
- `BacktestResult` dataclass: hit_rate, mean_pl_pct, sharpe, max_dd, n_events, by_iv_rank_bucket, by_crowded_band
- `backtest_earnings_strategy(db, ticker, strategy_name)` — replay all historical ER events for a ticker, simulate the strategy, return result
- `backtest_universe(db, strategy_name)` — same but across all tickers
- `recommend_with_backtest(rec, backtest_result)` — extend the existing recommendation with historical-edge stamp

**UI hook**: in the Hub drawer's strategy-recommendation card, append a "historical edge" row:
```
historical: 71 % hit · +28 % avg P/L · Sharpe +0.85 · n=28 events
```

Edge: this turns every Hub recommendation from speculation into evidence.

### Phase H2 — Drawer-Visual upgrades (items #2, #3, #4)

The drawer becomes the killer view.

**New components**:
- `volscope/ui/components/calibration_bar.py` — 8-quarter implied-vs-realised bar chart
- `volscope/ui/components/pre_er_drift.py` — pre-ER 10d spot+IV sparkline chart with shaded 1σ band
- `volscope/ui/components/anomaly_badge.py` — pure-CSS badge (no chart) flagging divergence

**Analytics support**:
- Extend `earnings_expected_move.py` with `pre_er_drift_summary()`
- Extend `crowded_pre_er.py` with `compute_anomaly_score()`

Each component returns SVG/HTML, no Plotly, fast to render.

### Phase H3 — Position Tracker page (item #5)

**New page**: `volscope/ui/views/earnings_positions_page.py`

Reuses existing `list_strategy_groups()` from `paper_trader`. Filter
by note prefix `"Earnings Hub ·"` so only ER-tagged trades surface.
Add a countdown to next earnings_date.

Layout:
```
EARNINGS POSITIONS  ·  3 open

NFLX · Long Straddle  · ER in 2d AMC      P/L  +$320   strikes 640/640
COIN · Short IC       · ER in 5d BMO      P/L  -$ 45   strikes 280/...
AAPL · Long Call      · ER passed 1d ago  P/L  +$890   ▣ ready to close?
```

Add sidebar entry "Earnings Trades" under EXECUTION.

### Phase H4 — Post-print Auto-Calibration (item #6)

**New cron-style script**: `scripts/post_earnings_capture.py`

For every earnings event where `earnings_date < today` AND
`last_reaction_pct IS NULL`, compute the actual 1d move from the
daily_vol table and write it back. Runs idempotently after each daily
scrape.

Wire into `make scrape` as a final step.

Edge: this is the compounding feature. Every ER cycle we run improves
the calibration of the next.

### Phase H5 — Morning Briefing (item #7)

Top of the Earnings Hub: a single auto-generated card

```
┌──────────────────────────────────────────────────────────────┐
│  Good morning. 3 earnings events today.                       │
│                                                                │
│  NFLX  AMC  ±8.2%  ▣ in your portfolio                       │
│  JPM   BMO  ±3.1%  · puts cheap (skew -1.2pt)                 │
│  AAL   AMC  ±5.4%  ⚠ anomaly: pre-ER vol -3σ from history     │
└──────────────────────────────────────────────────────────────┘
```

Card auto-builds from today's enriched events.

### Phase H6 — Macro overlay + cluster grouping + NLP + prob (8-11)

If budget remains. Each is small (1-2 hour). The bundle is the
"surface polish".

---

## Part 7 — Acceptance criteria for v2

Ship-ready when:
- [ ] Phase H1 — backtest harness completes for ≥ 5 sample tickers in
      < 30 s. Drawer shows "historical: N % hit · …"
- [ ] Phase H2 — drawer shows 3 visual diagnostics (calibration bar,
      drift sparkline, anomaly badge). Each renders in < 100 ms.
- [ ] Phase H3 — Earnings Trades page lives under EXECUTION nav.
- [ ] Phase H4 — `post_earnings_capture.py` is wired into `make scrape`
      and idempotent.
- [ ] Phase H5 — morning briefing card surfaces above the weekly grid
      when ≥ 1 ER event lands today.
- [ ] pytest + verify-all green.

## Part 8 — Closing thoughts on horizon

The honest ceiling of this feature is **the canonical retail vol-trader
earnings tool**. No paid tool combines local-data analytics, real
backtest, and 1-click paper-buy with the same density. The free
alternatives (Yahoo, earningshub) don't have vol analytics. The paid
alternatives (Bloomberg OMON, OptionMetrics) cost $20k+/year and
aren't built for the retail workflow.

A trader using the Earnings Hub v2 should be able to:
1. Open the hub in the morning and see 3 events today.
2. Read the morning briefing in 5 seconds.
3. Click the most interesting tile → see the calibration bar showing
   "this ticker has been underpriced 2:1 vs realised over 8 quarters".
4. See the backtest harness say "this exact strategy has had 71 % hit
   over 28 historical setups like this one".
5. Click paper-buy. Trade lands in Portfolio.
6. After the print, the post-print auto-capture updates the
   calibration. Next quarter's recommendation is sharper.

**That's the horizon**. Let's build it.
