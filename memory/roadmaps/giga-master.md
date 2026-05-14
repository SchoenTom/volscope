# VolScope Giga Master Plan — Path to Production-Grade

**Created:** 2026-05-03
**Owner:** Operator
**Status:** approved scope pending owner sign-off
**Guiding principle:** *Wenige Säulen, sauber durchdacht. Qualität > Quantität.*

---

## Where we are right now

- **27+ iterations completed** across 16 days (started 2026-04-20, accelerated 2026-05-01)
- **15 analytics modules:** Edge Score · Kelly Sizing · Cross-Asset Hedge · Strategy Recommender · Strategy Backtest · Strategy Calibration · Vol Cones · IV Smile · Portfolio Risk (Greeks + MC VaR) · Optionsschein Lookup · Portfolio Assistant · Scenario Analyzer · Earnings Crush · ML Mean-Reversion · Data Validator (new today)
- **10 UI pages:** Command · Discover · Portfolio · Scope · Scanner · Heatmap · Rotation · Flow · Pre-Trade · Backtest
- **1232 tests, 0 warnings, `make verify` PASS, Maturity 98.3 / 100**
- **Autonomous system:** 8 macOS launchd jobs running cross-session loops

The codebase is **mature in breadth** but **shallow in depth**. We've added many features fast; what's left is consolidation.

---

## Per-page audit — concrete friction list

Before designing new pillars, here's a brutal honest audit of what's already there and *exactly* where each existing page leaks user time.

### Command Center
**What it is:** the default landing page; default-tracked positions (QQQ, MSTR, SNOW, 1810.HK).

**What works:**
- Top Edges strip surfaces the composite score above the cards (right call)
- Per-card signal + ML + earnings-crush badges layered cleanly
- Trade Journal expander preserves entry-IV history

**What leaks user time:**
| # | Friction | Concrete fix |
|---|----------|--------------|
| C1 | Vol Pulse (cross-asset VIX/VDAX/VXFXI) sits BELOW the charts. It's the second-most-important info on the page. | Move Vol Pulse strip directly under the header, before YOUR MARKETS. |
| C2 | Position Sizer + Vol Alerts hidden in expanders the user has to discover. | Promote to a single "Risk & Alerts" two-column row, collapsed only when truly empty. |
| C3 | Card grid hard-coded to 5 columns regardless of viewport. With 4 tickers the cards are too narrow; with 7+ they wrap awkwardly. | `n_cols = clamp(2, 4, len(tickers) // 2 + 1)` plus CSS `grid-template-columns: repeat(auto-fit, minmax(220px, 1fr))`. |
| C4 | "Manage tickers" expander hides the add form. New users never find it. | Replace with a single inline "+ Add ticker" button; opens the form in a modal-ish container. |
| C5 | The two charts row (term-structure + VRP bar) duplicates information shown in the cards as numbers. | Replace the VRP bar with a single horizontal "VRP heat-strip" — same info, half the height. |
| C6 | No deep-link to Pre-Trade from any card. To trade an edge the user must manually navigate. | Inline "▷ trade" button on each card → sets `selected_ticker` + page=Pre-Trade. |

### Discover
**What it is:** today's best setup + 4-quadrant ranking grid.

**What works:**
- Today's Best Setup hero is the right top-of-page artifact
- Onboarding banner is dismissable (good)
- Cards now show data-quality badge

**What leaks user time:**
| # | Friction | Concrete fix |
|---|----------|--------------|
| D1 | Hero shows ONE setup. Trader often wants to see top-3. | Hero becomes a 3-card carousel — top 3 ranked by `(edge_score, backtest_sharpe, liquidity)`. |
| D2 | The 4 quadrants (CHEAPEST/RICHEST/MOVERS/CROWDED) are 4 separate sections, each with its own header. Visual budget is wasted. | Replace with a single tabbed view: tabs = ["Cheap", "Rich", "Movers", "Crowded", "Crushed"]. One renderer, one card style. |
| D3 | Onboarding text only renders for new users; experienced users never see it again, but the dismiss state is per-session. | Use a localStorage / persistent dismissal via DB user_settings table. |
| D4 | "Quiet zones" section has no clear thesis line. Users don't know what to do with it. | Add a 1-line "what to do" caption: "Sectors with median IV < 15th pctl — ripe for theta-positive structures (iron condor, calendar spread)". |
| D5 | First-run welcome shows "Load Starter Pack" but the action is heavy (full scrape). No progress indicator while it runs. | Add `st.progress` bar with status text streamed from the seed script. |

### Portfolio
**What it is:** add form + position cards + Greeks/VaR + scenarios.

**What works:**
- Optionsschein-by-characteristics input model (no WKN required)
- Greek trajectory + entry-quality + warnings per position card
- Scenario Analyzer in expander (PREBAKED + custom)

**What leaks user time:**
| # | Friction | Concrete fix |
|---|----------|--------------|
| P1 | Add form has 9+ fields all visible at once. Intimidating for first-time use. | 3-step wizard: (1) Identity (ticker, type, direction), (2) Strike + Expiry, (3) Entry data. |
| P2 | VaR slider triggers full recompute on every drag → 1-2 s lag per drag step. | Debounce: only recompute when slider release detected (`st.session_state["var_horizon"]` + explicit `Apply` button). |
| P3 | Position cards always render full Greek trajectory + warnings + actions. For a 10-position portfolio that's a lot of vertical scroll. | Default-collapsed cards showing only the headline; click to expand details. |
| P4 | Concentration table is a separate expander but uses tiny columns. | Promote to inline below the Greeks strip — single line per ticker, much more scannable. |
| P5 | When user logs a new position, the WKN field default is empty but says "informational only". Not all users grasp this. | Inline help: "Optional. VolScope identifies warrants by underlying/strike/expiry, not WKN — issuers behave nearly identically." |

### Scope
**What it is:** single-ticker deep-dive.

**What works:**
- KPI metric row gives the at-a-glance numbers
- IV/HV historical chart + term-structure are the workhorse charts
- Skew chart + backtest expander are valuable additions

**What leaks user time:**
| # | Friction | Concrete fix |
|---|----------|--------------|
| S1 | Page has SIX charts vertically stacked → 3000+ pixels of scroll. | Tabbed layout: Tab 1 = "Vol view" (IV/HV + term + percentile), Tab 2 = "Price view" (intraday + skew chart), Tab 3 = "Backtest". Default to Vol view. |
| S2 | KPI row uses Streamlit's native `st.metric`. On narrow screens labels wrap and values misalign. | Replace with custom HTML grid: `grid-template-columns: repeat(auto-fit, minmax(120px, 1fr))`. |
| S3 | No deep-link to Pre-Trade. After analysing IV the user has to navigate manually. | Inline "▷ Open Pre-Trade for {ticker}" button below the header. |
| S4 | Crush badge is shown but only when ER ≤ 30 days. The historical crush distribution is invisible. | Compact crush mini-bar: shows last-4-events crush% as small bars next to the badge. |

### Scanner
**What it is:** universe filter + sortable table.

**What works:**
- Filters now persist across reruns
- ProgressColumn for IV percentile + IV rank gives visual scan
- CSV export now in place

**What leaks user time:**
| # | Friction | Concrete fix |
|---|----------|--------------|
| Sc1 | Filters expander is collapsed by default. Most users never see them. | Three preset buttons above the table: "Cheap", "Rich", "Crushed" — each applies a canonical filter set. Custom filters in the expander stay. |
| Sc2 | Help table is at the bottom, rarely scrolled. | Replace with inline tooltips on column headers (Streamlit's column_config supports `help`). |
| Sc3 | Sorting by clicking column header works but the active sort is invisible. | Show "Sorted by: PERC (desc)" label above the table. |

### Heatmap
**What it is:** universe IV percentile grid.

**What works:**
- Sector collapse for >100 tickers
- Click-to-Scope navigation
- Stats summary (N cheap / normal / rich)

**What leaks user time:**
| # | Friction | Concrete fix |
|---|----------|--------------|
| H1 | Jump-to-ticker selectbox lists 280+ items. Even fuzzy-search is slow. | Add a search-as-you-type input: filter the selectbox options by substring before render. |
| H2 | Heatmap text font scales but at >150 tickers it's unreadable. | Auto-collapse to sector view at > 120 tickers (currently > 100); add a toggle to force individual view. |
| H3 | Click-to-Scope works but isn't visually indicated. | Hover state via Plotly's `hovertemplate` — subtitle "click to open in Scope". |

### Rotation
**What it is:** sector regime classification + Markov matrix.

**What works:**
- Heatmap regime visualization with z-scores
- HOT/NEUTRAL/COLD badges with momentum arrows
- Rotation predictions ("if Energy heats, Industrials follow in ~15d 68%")

**What leaks user time:**
| # | Friction | Concrete fix |
|---|----------|--------------|
| R1 | The Markov matrix is shown as a table — academic. | Replace with a Sankey-flow diagram (Plotly): width = transition probability, color = current regime. |
| R2 | "Rotation predictions" cards have probability bars but no time horizon prominently displayed. | Add "expected within {N}d at {pct}%" headline per prediction. |
| R3 | Momentum table uses 5/10/21d windows but doesn't say which is the primary. | Color-code: 5d emphasized, 10d/21d muted. |

### Flow
**What it is:** capital-flow proxy heatmap + ranking + divergence alerts.

**What works:**
- 5-component composite (OI, V/OI, PCR, IV-HV, volume-cluster) is a real signal
- Divergence alerts surface accumulation/distribution patterns

**What leaks user time:**
| # | Friction | Concrete fix |
|---|----------|--------------|
| F1 | Disclaimer is in an expander at the bottom. The user might trade on a flow signal without understanding it's a proxy. | Move disclaimer to a small ⓘ tooltip next to "Flow Score" column header. Keep brief. |
| F2 | Component breakdown is in an expander. For users who want to understand WHY flow score is what it is, the breakdown is gold. | Promote: clicking a sector in the heatmap opens a side panel with the 5 component values for that sector. |
| F3 | "Distribution" alerts and "Accumulation" alerts use different cards but visually identical. | Color-code: green border = accumulation, red border = distribution. |

### Pre-Trade
**What it is:** strategy selector + Greeks + P&L curve + sizing summary.

**What works:**
- Strategy Recommender hooks correctly
- Binary-search-for-strike from target delta
- BSM-priced P&L scenarios

**What leaks user time:**
| # | Friction | Concrete fix |
|---|----------|--------------|
| PT1 | For multi-leg strategies (iron condor, calendar) only the LEAD LEG is priced. The Sizing Summary footer says so but it's easy to miss. | Render ALL legs as a leg-by-leg table: leg # · type · strike · entry-price · delta · vega. The P&L curve aggregates them. |
| PT2 | "Save to Portfolio" button is missing — user has to navigate manually and re-type everything. | Add `▷ Save this to Portfolio` button that pre-fills the Portfolio form via session_state. |
| PT3 | Backtest hit-rate for the chosen strategy is computed elsewhere but not shown here. | Pull `strategy_calibration.get_stats_for(rec.name, ticker)` and show "historical: X% hit · Sharpe Y · n=Z" right below the strategy card. |
| PT4 | DTE slider step is 7 days. For users wanting weekly options the granularity is too coarse. | Step=1, but snap to common values (7/14/21/28/45/60/90) via radio quick-picks. |

### Backtest
**What it is:** strategy simulation results.

**What works:**
- Universe-level KPI strip
- Per-ticker filterable table
- Empty-state has a "▶ Run simulation" button

**What leaks user time:**
| # | Friction | Concrete fix |
|---|----------|--------------|
| B1 | When simulation runs, no progress indicator — user sees a spinner with no detail. | Stream stdout lines from `scripts/run_strategy_simulation.py` to a `st.empty()` block (live-updating). |
| B2 | Per-ticker table is great but doesn't allow drilling into individual trades. | Click a row → side panel showing the actual TradeOutcome list (entry/exit/P&L) for that (strategy, ticker) pair. |
| B3 | "Methodology" expander is at the bottom; many users want to understand how Sharpe is computed before trusting it. | Promote a 1-paragraph methodology summary above the table. Full report stays in expander. |

### Cross-page friction (already addressed in Pillar 3)

- No `nav_to(page, ticker)` helper. Every page implements its own navigation logic.
- Session state keys are not namespaced; collisions between pages possible.
- No breadcrumbs — user loses track of how they arrived.

---

## What "new level" actually means

The user asked for VolScope to become a *Giga Scanner / Giga Screen* with portfolio simulation and self-back-checking. After audit, the missing pillars distill to **four strategic priorities**, no more:

> *Better four pillars built rock-solid than ten features half-built.*

---

## Pillar 1 — Mega-Scan Universe View (the "Giga Screen")

### Why
The user has asked for a single page that answers "what's happening in vol across the entire universe RIGHT NOW?" — a Bloomberg-style at-a-glance dashboard. Today the same information is split across 10 pages.

### Architecture: ONE renderer, six rankings

The biggest mistake we'd make is six similar-but-slightly-different table renderers. Instead, the page is one composition of one canonical renderer:

```python
# volscope/ui/views/megascan_page.py

@dataclass(frozen=True)
class RankingSpec:
    """Defines one of the six top-N rankings on Mega-Scan."""
    title:        str          # display header, e.g. "💎 CHEAPEST VOL"
    accent_color: str          # left-border accent
    sort_key:     str          # column to sort by
    ascending:    bool         # sort direction
    filter_fn:    Callable[[pd.DataFrame], pd.DataFrame]  # pre-filter
    explain_col:  str          # which column to render as inline reason
    n:            int = 10

# The six specs:
RANKINGS: tuple[RankingSpec, ...] = (
    RankingSpec("💎 CHEAPEST VOL",  "#00d4aa", "iv_percentile",   True,  filter_liquid,    "context", 10),
    RankingSpec("🔥 RICHEST PREMIUM", "#ff4466", "iv_percentile",  False, filter_liquid,    "context", 10),
    RankingSpec("⚡ MOVERS UP",      "#ff9f43", "iv_change_1d",   False, filter_with_iv,   "delta_str", 10),
    RankingSpec("⚡ MOVERS DOWN",    "#7db4ff", "iv_change_1d",   True,  filter_with_iv,   "delta_str", 10),
    RankingSpec("🌐 CROWDED",        "#ffd700", "crowded_score",  False, filter_with_iv,   "crowded_explain", 10),
    RankingSpec("🎯 HIGHEST EDGE",   "#00d4aa", "edge_score",     False, filter_liquid,    "edge_one_liner", 10),
)

def _render_ranking(st_module, df: pd.DataFrame, spec: RankingSpec) -> None:
    """Single canonical ranking renderer used by all six tiles."""
    ...
```

**Quality gate:** every ranking is rendered by `_render_ranking`. If a future requirement needs a new column, we add it ONCE to the spec; we do not fork the renderer.

### Layout

```
┌────────────────────────────────────────────────────────────┐
│ HERO STRIP — 5 universe-level KPIs                          │
│ Median IV pctl │ Most-cheap ticker │ Most-rich ticker │     │
│ Biggest mover  │ Highest edge                                │
├────────────────┬─────────────────┬─────────────────────────┤
│ TOP 10 CHEAP   │ TOP 10 RICH     │ TOP 10 MOVERS           │
│ (perc + spread)│ (perc + spread) │ (1-day Δ-IV)            │
├────────────────┼─────────────────┼─────────────────────────┤
│ TOP 10 CROWDED │ TOP 10 EDGE     │ TOP 10 LIQUID/ACTIVE    │
│ (consensus)    │ (composite)     │ (volume × OI)           │
├────────────────┴─────────────────┴─────────────────────────┤
│ UNIVERSE SCATTER — IV percentile (x) × IV-HV spread (y)     │
│                    color = sector, size = OI                │
├────────────────────────────────────────────────────────────┤
│ MASTER EXPORT — single CSV with all 11 columns × N tickers  │
└────────────────────────────────────────────────────────────┘
```

### Hero strip — five universe-level KPIs

```python
@dataclass(frozen=True)
class UniverseKPI:
    label:    str       # uppercase short
    value:    str       # already-formatted display
    sublabel: str       # one-line explanation
    color:    str       # accent color
    target:   Optional[str] = None    # ticker to deep-link to

def universe_kpis(latest: pd.DataFrame) -> list[UniverseKPI]:
    """Compute the 5 hero-strip KPIs. Pure function, no UI imports."""
    return [
        UniverseKPI("MEDIAN PCT",      f"{latest['iv_percentile'].median():.0f}",
                    f"of {len(latest)} tickers", "#7db4ff", None),
        UniverseKPI("TOP CHEAP",       cheapest.ticker,
                    f"perc {cheapest.iv_percentile:.0f}", "#00d4aa", cheapest.ticker),
        UniverseKPI("TOP RICH",        richest.ticker,
                    f"perc {richest.iv_percentile:.0f}", "#ff4466", richest.ticker),
        UniverseKPI("BIG MOVER",       mover.ticker,
                    f"Δ-IV {mover.iv_change_1d:+.1f}", "#ff9f43", mover.ticker),
        UniverseKPI("HIGHEST EDGE",    top_edge.ticker,
                    f"score {top_edge.score:.0f}", "#00d4aa", top_edge.ticker),
    ]
```

KPIs are clickable — clicking sets `selected_ticker` + page=Scope.

### Universe scatter

`go.Scatter` plot with:
- x = `iv_percentile` (0..100)
- y = `iv_30d - hv_20d` (the IV-HV spread)
- color = `sector` (categorical, palette from theme)
- size = `total_open_interest` (square-root scaled, capped 4..20 px)
- hover: `f"{ticker} · {company} · perc {p} · spread {s} · sector {sec}"`

Quadrants are annotated:
- Bottom-left (low perc, negative spread) = "CHEAP × CHEAP" — strongest long-vol setups
- Top-right (high perc, positive spread) = "RICH × RICH" — strongest short-vol setups
- Top-left = "low perc but rich vs realized" — usually a data artifact, surface in Data Validator
- Bottom-right = "high perc but cheap vs realized" — earnings-crush candidate

### Master export

A single `st.download_button("📥 Master CSV")` that produces a wide CSV with these EXACT columns:

```
ticker, sector, company,
iv_30d, iv_60d, iv_90d, iv_180d, iv_skew_25d,
hv_20d, hv_60d,
iv_rank, iv_percentile,
iv_change_1d, iv_change_30d, perc_trend_30d,
put_call_ratio, total_open_interest, total_call_volume, total_put_volume,
crowded_score, flow_score,
edge_score, edge_components_json,
quality_overall, quality_one_liner,
last_scrape_date
```

24 columns. Test asserts the column list is EXACTLY this — additions require a docs change in the same PR.

### Quality gates (NOT just "build it")
- Page render time < 1.5s on 300-ticker universe (instrumented via Pillar 4)
- All 6 ranking tables share ONE common renderer; zero copy-paste
- Click any row → navigates to Scope with that ticker pre-selected (uses `nav_to` from Pillar 3)
- CSV export contains exactly the 24 columns above; field-by-field test
- Every numeric in the UI traces to a single canonical computation; no in-page math
- Universe scatter caps at 500 dots; if more, downsample by stratified-sector sampling
- Empty universe (DB freshly initialized) renders the first-run welcome instead of a blank scatter

### Acceptance tests (concrete, codable)

```python
# tests/test_megascan_page.py
def test_universe_kpis_returns_five():
    df = _make_universe_fixture(n=50)
    kpis = universe_kpis(df)
    assert len(kpis) == 5

def test_universe_kpis_top_cheap_has_min_perc():
    df = _make_universe_fixture(n=50)
    kpis = universe_kpis(df)
    cheap = next(k for k in kpis if k.label == "TOP CHEAP")
    perc_for_cheap = df[df["ticker"] == cheap.target]["iv_percentile"].iloc[0]
    assert perc_for_cheap == df["iv_percentile"].min()

def test_each_ranking_uses_filter_then_sort():
    df = _make_universe_fixture(n=50)
    for spec in RANKINGS:
        ranked = _apply_ranking(df, spec)
        assert len(ranked) <= spec.n
        if spec.ascending:
            assert ranked[spec.sort_key].is_monotonic_increasing
        else:
            assert ranked[spec.sort_key].is_monotonic_decreasing

def test_master_csv_columns_exactly():
    df = _make_universe_fixture(n=50)
    csv = build_master_csv(df)
    cols = pd.read_csv(io.StringIO(csv), nrows=0).columns.tolist()
    assert cols == [
        "ticker", "sector", "company",
        # ... 21 more, full list ...
    ]

def test_megascan_renders_under_1500ms():
    df = _make_universe_fixture(n=300)
    t0 = time.perf_counter()
    _build_full_page_data(df)   # all data prep, no streamlit render
    elapsed_ms = (time.perf_counter() - t0) * 1000
    assert elapsed_ms < 1500
```

### Page layout (final)

```
┌──────────────────────────────────────────────────────────────────────┐
│ HEADER: ◎ MEGA SCAN · last refresh 2026-05-03 14:23 · 283 tickers      │
├──────────────────────────────────────────────────────────────────────┤
│ HERO STRIP (5 KPI tiles, each clickable)                              │
│ ┌────────┐ ┌────────┐ ┌────────┐ ┌────────┐ ┌────────┐                │
│ │ MEDIAN │ │  TOP   │ │  TOP   │ │  BIG   │ │ HIGHEST│                │
│ │  PCT   │ │ CHEAP  │ │  RICH  │ │ MOVER  │ │  EDGE  │                │
│ │   42   │ │  XLE   │ │ NVDA   │ │ MSTR   │ │ 1810.HK│                │
│ │of 283  │ │perc 8  │ │perc 91 │ │+5.2pt  │ │score 87│                │
│ └────────┘ └────────┘ └────────┘ └────────┘ └────────┘                │
├──────────────────────────────────────────────────────────────────────┤
│ ┌──────────────┐ ┌──────────────┐ ┌──────────────┐                   │
│ │💎 CHEAPEST   │ │🔥 RICHEST    │ │⚡ MOVERS UP   │                   │
│ │XLE  perc 8   │ │NVDA  perc 91 │ │MSTR +5.2pt   │                   │
│ │BB   perc 11  │ │AMD   perc 88 │ │TSLA +3.8pt   │                   │
│ │... 8 more    │ │... 8 more    │ │... 8 more    │                   │
│ └──────────────┘ └──────────────┘ └──────────────┘                   │
│ ┌──────────────┐ ┌──────────────┐ ┌──────────────┐                   │
│ │⚡ MOVERS DOWN│ │🌐 CROWDED    │ │🎯 EDGE       │                   │
│ │BAC -2.1pt    │ │MSTR  85      │ │1810.HK 87    │                   │
│ │JPM -1.8pt    │ │NVDA  82      │ │XLE     82    │                   │
│ │... 8 more    │ │... 8 more    │ │... 8 more    │                   │
│ └──────────────┘ └──────────────┘ └──────────────┘                   │
├──────────────────────────────────────────────────────────────────────┤
│ UNIVERSE SCATTER · IV percentile (x) × IV-HV spread (y)               │
│ [annotated quadrant labels, clickable dots, sector colors]            │
├──────────────────────────────────────────────────────────────────────┤
│ [📥 Master CSV (24 cols)] [📋 Copy summary]    quality: ✓ 281  ⚠ 2    │
└──────────────────────────────────────────────────────────────────────┘
```

### Not in scope
- News feed (skip — clutter)
- Multi-timeframe toggle (skip — daily is canonical)
- Custom column builder (skip — RANKINGS is the source of truth)
- Saved views (skip — Streamlit's session_state is enough)
- Live streaming refresh (skip — Yahoo doesn't support it)

**Estimated work:** 6–10 hours · 1–2 iterations.

---

## Pillar 2 — Data Integrity Pipeline (self-back-check live)

### Why
The data_validator module exists (built today) but is not yet wired into the daily flow. Without integration it's a research artifact, not a production gate. The user explicitly said "Daten perfekt, Rechnungen fehlerfrei" — this pillar enforces that mechanically, every day.

### Architecture: validation as a first-class data citizen

Validation results are durable artifacts, not transient log messages. Three layers:

```
┌──────────────────────────────────────────────────────────────────────┐
│ Layer 1: scripts/run_validation.py                                    │
│   - reads latest snapshot from DB                                     │
│   - calls validate_universe()                                         │
│   - persists each ValidationReport to DB.validation_log               │
│   - dispatches notifications on FAIL                                  │
├──────────────────────────────────────────────────────────────────────┤
│ Layer 2: integration into scripts/daily_scrape.py                     │
│   - after scrape completes, automatically invoke run_validation       │
│   - guarantees every fresh scrape is validated, no manual step        │
├──────────────────────────────────────────────────────────────────────┤
│ Layer 3: UI — sidebar badge + admin page                              │
│   - badge in sidebar: GREEN / AMBER / RED                             │
│   - new admin page (?dev=1) showing validation_log latest 100 rows    │
└──────────────────────────────────────────────────────────────────────┘
```

### Scope: three concrete deliverables

#### Deliverable 2.1 — `scripts/run_validation.py`

```python
"""Standalone validation runner. Idempotent. Cron-safe."""

def main():
    db = VolScopeDB()
    latest = db.get_all_latest()
    if latest.empty:
        log.warning("no data — skipping validation")
        return 0

    # Build histories dict for time-series check
    tickers = latest["ticker"].tolist()
    histories = db.get_recent_for_tickers(tickers, lookback_days=30)

    # Build proxy levels for cross-ticker check
    proxy_levels = {
        t: float(latest[latest["ticker"] == t]["iv_30d"].iloc[0])
        for t in ["^VIX", "^VXN", "^RVX", "^VXFXI", "^GVZ", "^OVX"]
        if t in latest["ticker"].values
    }

    reports = validate_universe(latest, histories, proxy_levels)

    # Persist
    today = date.today()
    for r in reports:
        db.upsert_validation_report(
            ticker=r.ticker,
            date=today,
            overall_level=r.overall_level,
            n_flags=r.n_flags,
            n_fails=r.n_fails,
            details_json=json.dumps([asdict(f) for f in r.findings]),
        )

    # Dispatch on FAILs for major tickers
    major = {"SPY", "QQQ", "^VIX", "^GDAXI", "MSTR", "SNOW", "1810.HK"}
    fails_for_major = [r for r in reports if r.ticker in major and r.overall_level == "FAIL"]
    if fails_for_major:
        body = "; ".join(f"{r.ticker}: {r.findings[0].detail[:50]}" for r in fails_for_major[:3])
        subprocess.Popen(
            ["osascript", "-e",
             f'display notification "{body}" with title "VolScope: data validation FAIL"'],
            start_new_session=True,
        )

    summary = summarise_universe(reports)
    log.info("validation complete: %s", summary)
    return 0
```

#### Deliverable 2.2 — DB schema migration

```python
# volscope/data/database.py — add to _create_tables:

self.con.execute("""
    CREATE TABLE IF NOT EXISTS validation_log (
        ticker         VARCHAR NOT NULL,
        date           DATE    NOT NULL,
        overall_level  VARCHAR NOT NULL,
        n_flags        INTEGER NOT NULL,
        n_fails        INTEGER NOT NULL,
        details_json   VARCHAR,
        PRIMARY KEY (ticker, date)
    )
""")

def upsert_validation_report(self, ticker, date, overall_level, n_flags, n_fails, details_json):
    self.con.execute("""
        INSERT OR REPLACE INTO validation_log
        (ticker, date, overall_level, n_flags, n_fails, details_json)
        VALUES (?, ?, ?, ?, ?, ?)
    """, [ticker, date, overall_level, n_flags, n_fails, details_json])

def get_validation_summary(self, target_date=None):
    target_date = target_date or date.today()
    return self.con.execute("""
        SELECT overall_level, COUNT(*) AS n
        FROM validation_log
        WHERE date = ?
        GROUP BY overall_level
    """, [target_date]).fetchdf()
```

#### Deliverable 2.3 — Sidebar badge + admin page

The badge replaces the existing "tickers loaded / last scrape / freshness" block. Three states:

```python
def _render_data_health_badge(st_module, db):
    summary = db.get_validation_summary()
    if summary.empty:
        # never validated → muted "—"
        color, label, detail = "#8a8f9e", "DATA NEVER VALIDATED", "run scripts/run_validation.py"
    else:
        n_fail = int(summary[summary["overall_level"] == "FAIL"]["n"].sum())
        n_flag = int(summary[summary["overall_level"] == "FLAG"]["n"].sum())
        n_ok   = int(summary[summary["overall_level"] == "OK"]["n"].sum())
        if n_fail > 3:
            color, label = "#ff4466", "DATA RED"
        elif n_fail > 0 or n_flag > 20:
            color, label = "#ff9f43", "DATA AMBER"
        else:
            color, label = "#00d4aa", "DATA GREEN"
        detail = f"{n_ok} OK · {n_flag} FLAG · {n_fail} FAIL"
    render_html(st_module, f'<div ...>{label} · {detail}</div>')
```

The admin page (only accessible via `?dev=1`) shows:
- Latest 100 validation rows from DB
- Per-ticker drill-down: click → see all 5 findings + history of past 14 days
- "Re-validate now" button → spawns `run_validation` subprocess

### Quality gates
- Validation runs in < 2 s on 300 tickers (no per-row HTTP calls)
- DB schema migration is idempotent (`CREATE TABLE IF NOT EXISTS` + `ALTER ... IF NOT EXISTS`)
- Notification dispatch is non-blocking (subprocess detached)
- Sidebar badge renders even when `validation_log` is empty (no crash)

### Acceptance test
```python
def test_run_validation_persists_to_db():
    ...
def test_validation_dispatch_notifies_on_fail():
    ...
def test_sidebar_badge_handles_empty_log():
    ...
```

### Not in scope
- Slack / email alerts (skip — macOS only)
- Auto-rollback on validation FAIL (skip — would need a transactional scrape)
- Web-facing health page (skip)

**Estimated work:** 4–6 hours · 1 iteration.

---

## Pillar 3 — Workflow Cohesion (cross-page journey)

### Why
The 10 pages each work in isolation but the trader's journey across them has friction. Operator should be able to: (1) see Edge Score on Discover, (2) click "Pre-Trade", (3) tweak strikes, (4) "Save to Portfolio" with one click. Today every transition requires manual ticker selection + form refill.

### Architecture: ONE navigation helper, ONE state-key naming convention

```python
# volscope/ui/components/navigation.py — new file, single responsibility

@dataclass(frozen=True)
class NavIntent:
    """Intent to navigate to a page, optionally carrying ticker context."""
    page:    str
    ticker:  Optional[str] = None
    source:  Optional[str] = None         # for breadcrumbs ("from Discover")
    payload: Optional[dict] = None        # for prefill (e.g. strike, expiry)


def nav_to(intent: NavIntent) -> None:
    """Single canonical navigation. Sets session_state then triggers rerun.

    Used by EVERY page that initiates a transition. No page implements its
    own session_state mutation for nav — that's a code-review block.
    """
    import streamlit as st
    if intent.ticker is not None:
        st.session_state["selected_ticker"] = intent.ticker
    st.session_state["active_page"] = intent.page
    st.session_state["nav_source"] = intent.source
    if intent.payload is not None:
        # Namespaced prefill key: e.g. "prefill_pretrade", "prefill_portfolio"
        st.session_state[f"prefill_{intent.page.lower().replace('-','_')}"] = intent.payload
    st.rerun()


def consume_prefill(page: str) -> Optional[dict]:
    """Read and clear a prefill payload at page render time.

    Pages call this once at the top of render_*. After the call, the
    payload is gone — preventing stale prefills on subsequent visits.
    """
    import streamlit as st
    key = f"prefill_{page.lower().replace('-','_')}"
    payload = st.session_state.pop(key, None)
    return payload


def render_breadcrumb(st_module, page: str, ticker: Optional[str] = None) -> None:
    """Render a small "◈ {page} · {ticker} ← from {source}" line."""
    import streamlit as st
    source = st.session_state.get("nav_source")
    parts = [f"◈ {page}"]
    if ticker:
        parts.append(ticker)
    if source:
        parts.append(f"← from {source}")
    render_html(st, f'<div ...>{" · ".join(parts)}</div>')
```

### Scope: four surgical changes

#### Change 3.1 — Universal "Open in {page}" buttons

Replace the four ad-hoc deep-link patterns currently scattered across pages with one helper. Touch points:

| Page | Component | Buttons added |
|------|-----------|---------------|
| Discover | each card | `▷ Pre-Trade` + `◈ Scope` |
| Discover | best-setup hero | `▷ Pre-Trade for {ticker}` (already exists; refactor to use `nav_to`) |
| Command | each YOUR MARKETS card | `▷ Pre-Trade` |
| Portfolio | each position card | `◈ Scope` |
| Scope | page header | `▷ Pre-Trade` |
| Mega-Scan | every ranked row | `◈ Scope` |
| Backtest | per-ticker table row | `◈ Scope` |

Total: ~8 inline buttons, each one line:
```python
if st.button(f"▷ Pre-Trade", key=f"nav_pt_{ticker}"):
    nav_to(NavIntent(page="Pre-Trade", ticker=ticker, source=current_page))
```

#### Change 3.2 — Pre-Trade "Save to Portfolio"

After the user has picked a strategy + DTE + reviewed Greeks, the Pre-Trade page gets a single button:

```python
if st.button("▷ Save this to Portfolio"):
    nav_to(NavIntent(
        page="Portfolio",
        ticker=ticker,
        source="Pre-Trade",
        payload={
            "underlying":    ticker,
            "option_type":   option_type,
            "strike":        strike,
            "expiry":        date.today() + timedelta(days=dte),
            "instrument_type": "vanilla",
            "contracts":     1,
            "entry_premium": entry_price,
            "spot_at_entry": spot,
        }
    ))
```

Portfolio page render reads the payload via `consume_prefill("Portfolio")` and pre-fills the form. User reviews, hits Save.

#### Change 3.3 — Breadcrumbs

Each page's `render_*` function calls `render_breadcrumb(st, page_name, ticker)` directly under the page header. Single line. The breadcrumb shows source IF a `nav_source` was set; otherwise just shows page+ticker.

Quality gate: the breadcrumb is rendered by ONE function. No page rolls its own.

#### Change 3.4 — Namespaced session-state keys

Audit all `st.session_state[...]` reads across the codebase. Establish a naming convention:

| Pattern | Used by | Owner |
|---------|---------|-------|
| `selected_ticker` | universal | shared |
| `active_page` | universal | shared (set only by `nav_to`) |
| `nav_source` | universal | shared (set only by `nav_to`) |
| `prefill_<page>` | one-shot prefill payload | sender writes, page reads-and-clears |
| `<page>_<field>` | persistent per-page state | only that page touches |

Examples:
- `pretrade_dte`, `pretrade_strategy`
- `scanner_filters_v1`
- `portfolio_var_horizon`
- `discover_onboarding_dismissed`

Audit + rename:
```bash
# Audit current state-key collisions
grep -r "st.session_state\[" volscope/ui/ | sort | uniq -c | sort -rn
```
Any unprefixed keys outside the universal list above get renamed in this pillar.

### Quality gates
- One canonical `nav_to(page, ticker=None)` helper used by all buttons (single source of truth)
- Round-trip test: Discover click → Pre-Trade renders → back-button preserves Pre-Trade state
- No manual Streamlit state-shenanigans in page code; only the helper

### Acceptance test
```python
def test_nav_to_sets_session_state():
    ...
def test_pretrade_state_survives_page_change():
    ...
def test_save_to_portfolio_prefills_form():
    ...
```

### Not in scope
- Page-load animations (skip)
- Mobile-first redesign (skip — already have @media)
- Dark/light theme switch wiring (skip — currently a stub)

**Estimated work:** 4–6 hours · 1 iteration.

---

## Pillar 4 — Performance + Observability

### Why
We don't currently know if Discover page loads in 0.5 s or 8 s on Operator's machine. Without measurement, performance regressions land silently. A serious tool surfaces performance to the developer.

### Architecture: zero-overhead instrumentation

```python
# volscope/utils/timing.py — single, lightweight, opt-in

import time
import json
from contextlib import contextmanager
from datetime import date
from pathlib import Path
from typing import Optional

_PERF_DIR = Path(__file__).resolve().parents[2] / "data" / "perf"


@contextmanager
def instrument(name: str, extra: Optional[dict] = None):
    """Time a code block and append to data/perf/<date>.jsonl.

    Usage:
        with instrument("render_megascan", {"n_tickers": len(latest)}):
            render_megascan_page(db, settings)

    Overhead: < 1 ms per call (file open + json.dumps + write).
    """
    t0 = time.perf_counter()
    yield
    elapsed_ms = (time.perf_counter() - t0) * 1000.0
    record = {
        "ts":         time.time(),
        "name":       name,
        "elapsed_ms": round(elapsed_ms, 2),
        **(extra or {}),
    }
    _PERF_DIR.mkdir(parents=True, exist_ok=True)
    fpath = _PERF_DIR / f"{date.today().isoformat()}.jsonl"
    # Atomic single-line append; OS guarantees atomicity for < 4kb writes.
    with fpath.open("a") as f:
        f.write(json.dumps(record) + "\n")


def percentiles_for(name: str, days: int = 7) -> dict:
    """Return median and p95 for a given instrument name over the last N days."""
    ...
```

### Wrap points (exhaustive)

Every page's top-level render function:
```python
def render_megascan_page(db, settings):
    with instrument("page.megascan", {"n_tickers": len(db.get_available_tickers() or [])}):
        ...
```

Heavy analytics:
- `compute_edge_table` (called every Command Center render)
- `simulate_universe` (Backtest page; should be slow but bounded)
- `composite_quality` per-ticker (Discover renders this 10 times per page)
- `validate_universe` (run_validation script)
- `monte_carlo_var` (Portfolio page slider)

Total: ~15 wrap points. Single import per file.

### Dev panel

Hidden behind `?dev=1` URL param via `st.query_params`. Sidebar expander shows:

```
┌──────────────────────────────────────────────────┐
│ ⚙ Dev Panel (last 7 days)                        │
├──────────────────────────────────────────────────┤
│ page.command       p50  120ms  p95  340ms  n=87   │
│ page.discover      p50  280ms  p95  610ms  n=72   │
│ page.megascan      p50  450ms  p95  1230ms n=15   │
│ page.portfolio     p50  340ms  p95  890ms  n=43   │
│ analytics.edge_table p50 22ms  p95  60ms   n=159  │
│ analytics.mc_var   p50 380ms  p95 1100ms   n=22   │
└──────────────────────────────────────────────────┘
```

Click a row → see latest 50 records for that name.

### SLA test

```python
# tests/test_perf_sla.py
def test_megascan_render_under_1500ms_p95():
    """Synthetic 300-ticker universe must render data prep in < 1.5s p95.
    Run this test 10 times, take p95."""
    df = _make_universe_fixture(n=300)
    samples = []
    for _ in range(10):
        t0 = time.perf_counter()
        _build_full_page_data(df)
        samples.append((time.perf_counter() - t0) * 1000)
    p95 = sorted(samples)[int(0.95 * len(samples))]
    assert p95 < 1500, f"p95 = {p95:.0f}ms (budget 1500ms)"
```

This test runs in CI; budget regressions break the build.

### Quality gates
- Decorator overhead < 1 ms per call (benchmarked)
- JSONL append is atomic (one file lock per write)
- The `?dev=1` gate is implemented via `st.query_params` (Streamlit native)
- Dashboard renders cleanly when JSONL is empty

### Acceptance test
```python
def test_instrument_decorator_timing_within_overhead_budget():
    ...
def test_jsonl_persistence_concurrent_safe():
    ...
def test_dev_panel_handles_empty_log():
    ...
```

### Not in scope
- Profiling tools (cProfile output in UI) — skip
- Distributed tracing — skip
- Alerting on slow renders — skip

**Estimated work:** 3–4 hours · 1 iteration.

---

## Pillar 5 — Per-Page Refinement Sweep

### Why
The per-page audit above identified ~30 specific friction points across 10 pages. Each is small (5-30 minutes), but together they make the app feel coherent vs. duct-taped. This pillar batches them into a single sweep so we don't half-fix some pages and skip others.

### Scope: one focused PR per page, in priority order

#### 5.1 Command Center refinement (the daily landing page — highest leverage)

```python
# Re-order render_command_center_page:
1. Header strip (current)
2. Top Edges strip (current — already good)
3. Vol Pulse cross-asset       ← MOVED UP from bottom (C1)
4. YOUR MARKETS cards           ← responsive grid (C3)
5. Risk & Alerts two-column row ← Position Sizer + Alerts side by side (C2)
6. Trade Journal expander (kept collapsed by default)
7. Charts row (1 chart, not 2 — replace VRP bar with heat-strip) (C5)
```

Inline action buttons on each card: `▷ Pre-Trade · ◈ Scope · ✕ Remove`. Uses Pillar 3's `nav_to`.

#### 5.2 Discover refinement

```python
# Replace 4-quadrant grid with a tabbed view:
tabs = st.tabs(["💎 Cheap", "🔥 Rich", "⚡ Movers", "🌐 Crowded", "🪓 Crushed"])
with tabs[0]:
    _render_ranking(st, latest, RANKINGS[0])    # canonical renderer from Pillar 1
# ... 4 more
```

The hero (Today's Best Setup) becomes a 3-card carousel via `st.columns(3)`. Each carousel card has its own backtest hit-rate badge.

Persistent dismissal: `db.add_user_setting("onboarding_dismissed", True)` instead of session-scoped state.

#### 5.3 Portfolio refinement

Add-form wizard (3 steps):
```python
step = st.session_state.setdefault("portfolio_form_step", 1)
if step == 1:
    # Identity: ticker, instrument_type, option_type, contracts
elif step == 2:
    # Strike + expiry + barrier (if knockout)
elif step == 3:
    # Entry data: date, premium, notes, WKN
    # → on submit, db.add_position(...) and reset step=1
```

VaR debouncing:
```python
# Replace direct slider→recompute with explicit Apply button
horizon = st.slider("VaR horizon", ...)
st.session_state["portfolio_var_horizon_pending"] = horizon
if st.button("Apply"):
    st.session_state["portfolio_var_horizon"] = st.session_state["portfolio_var_horizon_pending"]
    st.rerun()
```

Position cards default-collapsed showing only headline; expand for full details.

#### 5.4 Scope refinement

Tabbed layout:
```python
tabs = st.tabs(["📈 Vol View", "💲 Price View", "▣ Backtest"])
with tabs[0]:
    _render_kpi_strip(...)         # custom HTML grid (S2)
    _render_iv_hv_chart(...)
    _render_term_structure(...)
    _render_percentile_chart(...)
with tabs[1]:
    _render_intraday_chart(...)
    _render_skew_chart(...)
    _render_crush_minibar(...)     # new (S4)
with tabs[2]:
    _render_backtest_section(...)
```

Add `▷ Pre-Trade for {ticker}` button below header (S3).

#### 5.5 Scanner refinement

Three preset buttons above the table:
```python
col1, col2, col3 = st.columns(3)
if col1.button("💎 Cheap", help="Apply: percentile<25, spread<0"):
    st.session_state["scan_filters_v1"] = CHEAP_PRESET
    st.rerun()
# ... rich, crushed
```

Active sort indicator: `st.caption(f"Sorted by: {sort_col} {order}")` above the dataframe.

Remove the Help table at bottom; inline help on column_config.

#### 5.6 Heatmap refinement

Search-as-you-type for ticker jump:
```python
search = st.text_input("Search", "")
options = [t for t in db.get_available_tickers() if search.lower() in t.lower()]
ticker = st.selectbox("Jump to", options) if options else None
```

Force-individual-view toggle when sector-collapse triggers automatically.

#### 5.7 Rotation refinement

Replace Markov matrix table with Plotly Sankey:
```python
fig = go.Figure(data=[go.Sankey(
    node=dict(label=sectors, color=[COLORS[regime[s]] for s in sectors]),
    link=dict(source=src, target=tgt, value=prob, color=accent_with_alpha)
)])
```

Per-prediction headline format:
```
"Energy → Industrials"
"68% probability within 15-21 days"
```

#### 5.8 Flow refinement

Disclaimer as ⓘ tooltip on column header. Color-code accumulation (green) vs distribution (red) in alert cards.

Sector heatmap clickable → side panel shows the 5 component breakdown for that sector.

#### 5.9 Pre-Trade refinement

All-legs table for multi-leg strategies:
```python
legs_df = pd.DataFrame([
    {"leg": i+1, "type": leg_type, "strike": leg_strike, "delta": leg_delta,
     "vega": leg_vega, "entry_price": leg_price}
    for i, (leg_type, leg_strike, leg_delta, leg_vega, leg_price) in enumerate(_legs_from_rec(rec, ...))
])
st.dataframe(legs_df, ...)
```

Backtest hit-rate inline via `strategy_calibration.get_stats_for(rec.name, ticker)`.

DTE quick-pick radio: `[7, 14, 21, 28, 45, 60, 90, 180]` plus a free-input slider for fine control.

`▷ Save to Portfolio` button (Pillar 3).

#### 5.10 Backtest refinement

Streaming progress for the simulation:
```python
status = st.empty()
proc = subprocess.Popen([...], stdout=subprocess.PIPE)
for line in proc.stdout:
    status.text(line.decode().strip())
```

Click row → side panel with TradeOutcome list for that (strategy, ticker).

Methodology summary above the table; full report stays in expander.

### Quality gates
- Each of the 10 page refactors merges as its own PR
- `make verify` PASS after each
- No NEW FAIL findings in the next audit refresh after the sweep
- Snapshot test for each page (raw HTML output stable across renders)

**Estimated work:** 15–20 hours · 5–10 iterations.

---

## Total scope summary

| Pillar | Files added | Files changed | Tests added | Est. hours |
|--------|------------:|--------------:|------------:|-----------:|
| 1. Mega-Scan | 2 | 1 | ~15 | 6–10 |
| 2. Data Integrity | 2 | 3 | ~10 | 4–6 |
| 3. Workflow Cohesion | 1 (helper) | 4 | ~8 | 4–6 |
| 4. Perf + Observability | 2 | 0 | ~6 | 3–4 |
| 5. Per-Page Refinement | 0 | 10 | ~25 | 15–20 |
| **TOTAL** | **7** | **18** | **~64** | **32–46** |

---

## Sequencing — clear dependency order

The pillars depend on each other in this order:

```
Pillar 4 (timing)  ──┐
                     ├──→ Pillar 2 (validator) ──┐
                     ├──→ Pillar 1 (mega-scan)   ├──→ Pillar 5 (per-page refinement)
                     └──→ Pillar 3 (nav helper)  ┘
```

### Why Pillar 4 first
The `instrument()` decorator is a 60-line module with zero downstream dependencies. Adding it first means the next 4 pillars all get instrumented on the way in — we measure where the wins land. If we add it last, we're retrofitting and likely missing hot paths.

### Why Pillar 2 second
The Data Validator persists results to a new DB table. Pillar 1 (Mega-Scan) uses validation status as a column in the master export. Without Pillar 2 the column is empty.

### Why Pillars 1 and 3 in parallel
Pillar 1 builds the new page; Pillar 3 builds the helper Pillar 1 will use for ranked-row deep-links. They can be done in parallel by a human, sequentially by the autonomous loop.

### Why Pillar 5 last
Per-page refinement *uses* the helpers, the renderer, and the navigation pattern from Pillars 1, 2, 3. Doing it first means double-work.

### Iteration budget per pillar (autonomous-loop calibrated)

| Pillar | Iterations | Why |
|--------|-----------:|------|
| 4 — Perf | 1 | Single small file + 5 wrap points |
| 2 — Validator | 1 | Module exists; integration is mechanical |
| 1 — Mega-Scan | 2 | One iteration for analytics + tests, one for UI |
| 3 — Workflow | 1 | Single helper + 8 button refactors |
| 5 — Refinement | 5 | One per page-pair (Command+Discover, Portfolio+Scope, Scanner+Heatmap, Rotation+Flow, Pre-Trade+Backtest) |

**Total: 10 iterations** = 2 weeks at the current loop cadence (5/day cron + occasional manual).

Each pillar produces a green `make verify` before the next starts. **No pillar gets merged with regressions or new TODOs.** The autonomous loop's verify oracle stays the gate.

---

## What we're NOT building (and why)

The temptation is to bolt on more features. Each was considered and **deliberately deferred**:

| Idea | Why deferred |
|------|--------------|
| News feed (yfinance.news) | Adds external dependency + clutter; pillar 1 covers ranked surfacing |
| Live intraday IV streaming | Requires WebSocket + non-Yahoo source; out of scope for v1 |
| Multi-broker import | Optionsschein form already covers manual entry; CSV import is a pillar-3 candidate next quarter |
| ML retraining loop | Model already trained per call; no demonstrated need for offline pipeline |
| Cross-session collaboration | Single-user tool by design |
| Mobile-native UI | Streamlit responsive layout suffices |
| Vol surface SVI fitting | The vol_cones + iv_smile pair already gives 80% of the insight |
| 3D vol surface chart | Visual sugar; surface_fit gives more practical leverage |

Each of these is a candidate for a *future* plan. Not this one.

---

## Definition of Done

The Giga Master Plan is COMPLETE when:

- [ ] All 4 pillars merged with `make verify` PASS
- [ ] Maturity score ≥ 95 maintained throughout
- [ ] Test count grew by at least 30 tests
- [ ] No new high-severity findings in the next audit refresh
- [ ] At least one full week of autonomous-loop runs without manual intervention
- [ ] Operator can open VolScope, hit Mega-Scan, get the answer in < 5 seconds

When all six are true, VolScope is at the "new level" the user asked for. Anything beyond is a different plan.

---

## Risks & mitigations

| Risk | Likelihood | Mitigation |
|------|-----------:|------------|
| Pillar 1 page becomes a kitchen-sink page (scope creep) | High | Strict 6-table layout; new sections require a new plan |
| Data Validator triggers spurious notifications during normal market events | Medium | Conservative thresholds + escalation rules; user can pause |
| Workflow pillar breaks existing in-progress trader sessions | Medium | Migration shim: detect old session_state keys, port silently |
| Perf instrumentation slows the app | Low | Decorator overhead < 1 ms (gated by test); dev panel hidden |
| Autonomous loops drift in absence of new audits | Medium | Audit refresh cron stays weekly; loop self-pauses if no progress |

---

## Operational note

The autonomous loop crons (`com.tomschoen.volscope.loop*`) will continue executing during this plan. They pick top issues from `data/audit/queue.json`. To prevent them from interfering with the structured pillar work, **set a pause marker before each pillar starts**:

```bash
make autonomy-pause      # before starting pillar work
# ... do the pillar ...
make autonomy-unpause    # after pillar verify PASS
```

This way the autonomous system catches up after each pillar is solid, instead of racing the human.
