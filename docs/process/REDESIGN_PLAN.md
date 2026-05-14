> Status: ARCHIVED
> This document captures a past planning session. It is preserved
> for historical context — current state lives in /memory/roadmaps/ + /ROADMAP.md.

# VolScope · Redesign Plan v3 — "Pro-Quant Cockpit"

Date: 2026-05-12 · Author: claude-opus-4-7
Status: **Draft — pending perf audit results + first-phase implementation**

> *"Mehr Farbe, mehr Fokus auf Kennzahlen, strukturiert aussehen.*
> *Recherchiere wie man so ein mathematisches und kennzahlen-lastiges Tool designed."*

This document captures the third iteration of VolScope's visual system.
The two previous passes (IBKR-density · Apple-Hero) corrected layout
crushing and emphasised single statements. They did **not** deliver
the structured, color-saturated, KPI-dense feel of a real trading
cockpit. This plan does.

---

## Part 1 — Reference Tools & Design Principles

### What IBKR TWS / OptionTrader actually look like

- **Six visual zones** at any time: workspace tabs, symbol bar, time-and-sales,
  option chain grid, position blotter, risk navigator. Every zone visible
  at once — no tabs hiding state.
- **The option chain** is the centerpiece: strike rows, call columns on the
  left, put columns on the right, ATM strike highlighted with a vertical
  band. Each cell is dense: bid/ask/last/IV/Δ/Γ/Θ stacked.
- **Color encodes magnitude** not just sign. ITM cells get an intensity
  gradient (deeper green = deeper ITM). Bid/Ask tightness is hinted by
  width of the spread column relative to mid.
- **Microtypography**: 11 px monospace tabular nums. Every column right-aligned
  on the decimal. Headers 9 px uppercase. No prose anywhere in the grid.
- **Status bar** at top with one-line summary: ticker, last, change, IV30,
  HV20, IV-Rank, Earnings-DTE, account NLV.

### What Bloomberg Terminal (OMON / SKEW / VOLR) does

- **Pure data wall** — no chrome, no padding. Every pixel is information.
- **Field codes shown beside values** (e.g. `IVOL_30D 23.4`) so the trader
  knows the source.
- **Heatmaps for surfaces** — option vol surface as a strike × expiry grid
  with cells colored by IV (green low / red high) and labels in the cell.
- **Three columns of monitors** running in parallel: real-time prices,
  charts, news. Eye doesn't scroll, the data scrolls.

### What OptionStrat does well

- **Payoff diagram as the page hero** — large, top, with curve fill colored
  by profit/loss. Strike markers + spot marker labeled in-place.
- **Greeks beside the payoff**, not below — landscape layout.
- **Position table inside the same view** with current P&L per leg,
  click-to-edit strikes.
- **Probability cone overlay** on the payoff diagram itself, not a separate tab.

### What Tradier / Tastytrade do for retail

- **Bigger numbers, fewer columns** — sacrifices density for clarity.
- **Color is semantic only**, never decorative. Green = open/buy/profit,
  red = close/sell/loss, amber = adjust/warn, blue = info.
- **Inline sparklines** in scanner rows (50 px wide, 12 px tall) showing
  30-day IV trajectory at a glance.

### Synthesis — design principles for VolScope v3

1. **Density wins** — every screen shows 5-10 KPIs minimum, never just 1-2.
   Stop wasting 30 % of vertical on whitespace.
2. **Color encodes intensity, not just direction**. A 2× IV/HV ratio is more
   alarming than 1.2× and the visual weight must reflect that.
3. **Option chain pattern** — adopt strike-rows with ATM-band for any view
   that shows option grids (Pre-Trade, LEAPS Lab leg breakdown, Paper-Trader
   leg table).
4. **Microtypography** — 11 px monospace tabular nums, right-aligned, headers
   9 px uppercase grey. We already have JetBrains Mono — use it harder.
5. **Inline sparklines** — every scanner row gets a 50×14 px IV-30d sparkline.
   `volscope/ui/components/sparkline.py` (new helper).
6. **Status bar** — pin a one-line ticker-summary at the top of every
   ticker-specific page (Scope, Options Lab, LEAPS Dossier).
7. **Risk Navigator-style position row** — for Portfolio, show each leg with
   per-greek heatmap cells (color depth = magnitude).
8. **Surface heatmaps** — replace the current sector heatmap with a
   strike × expiry IV surface for any picked ticker.

---

## Part 2 — Color System v3 (Pro-Quant)

The current 4-accent palette (accent · accent2 · warn · amber) is fine for
HTML cards but **flat for data**. A pro-quant tool needs a *graduated*
palette so cells can encode magnitude.

### Diverging scale — P&L, IV/HV ratio, Z-score

```
HEAT[10] (deepest red)   #b71c1c    extreme negative
HEAT[20]                  #d32f2f
HEAT[30]                  #e53935
HEAT[40]                  #f06292    fading red
HEAT[50] (neutral)        #757575    no signal
HEAT[60]                  #66bb6a    fading green
HEAT[70]                  #43a047
HEAT[80]                  #2e7d32
HEAT[90] (deepest green)  #1b5e20    extreme positive
```

### Sequential scale — IV percentile, Rank, density

```
SEQ[0]    #1a237e    deep blue (cheap end)
SEQ[25]   #5b8cff    mid blue
SEQ[50]   #5bc8b0    teal (neutral)
SEQ[75]   #ff9f43    amber (warm)
SEQ[100]  #ff4466    red (rich end)
```

### Categorical (sectors, tickers in multi-ticker charts) — 10 hues

Keep the current `CHART_PALETTE` — it already works.

### Direction-only (existing accents, kept)

- accent     `#00d4aa` — green / long-vol / cheap / profit
- accent2    `#5b8cff` — blue / HV / calm
- warn       `#ff4466` — red / short-vol / rich / loss
- amber      `#ff9f43` — caution
- gold       `#ffd700` — earnings / event

### Surfaces (background layering — 5 levels)

```
LAYER[0]  bg              #0a0b0f    page
LAYER[1]  surface         #12131a    sidebar
LAYER[2]  card            #151620    panels
LAYER[3]  card-elevated   #1a1b27    sub-panels / row-hover (NEW)
LAYER[4]  cell            #1d1e2b    grid cells (NEW)
```

The two new keys (`card_elevated`, `cell`) let us stack a Risk-Navigator-style
table inside a card without losing visual hierarchy.

---

## Part 3 — Layout Grid System

### Six standard layouts the app must support

| Code | Use | Spec |
|---|---|---|
| **HERO-DUAL** | Options Lab payoff + greeks | 60/40 split, payoff left full-height, greeks right side stacked |
| **CHAIN-ROW** | Option chain or leg table | strikes as rows, mono columns: bid/ask/last/Δ/Γ/Θ/ν/IV |
| **STATUS-BAR** | Above any ticker-page | 1-row dense: symbol · price · change · IV30 · HV20 · IV-rank · IV-perc · DTE-ER |
| **METRIC-WALL** | Discover/Command at-a-glance | 4-row × 6-cell grid of mini-KPI cards with sparkline |
| **HEATMAP-GRID** | Sector vol, IV surface | strike × expiry or sector × time matrix, fixed cell size |
| **POSITION-BLOTTER** | Portfolio | one row per leg, columns colored by greek magnitude |

### KPI Cell v2

Replace the current `volscope-ibkr-cell` with a richer block:

```
┌──────────────────────────────┐
│ LABEL   3-LETTER-CODE        │  <- 9 px uppercase + monospace code
│                              │
│ ▌█▆▄▄▆█▆▌  HUGE-NUM          │  <- 12 px sparkline + 18 px hero
│                              │
│ Δ from yesterday: -2.1pt     │  <- 10 px context line
└──────────────────────────────┘
```

Three sub-grades depending on importance:
- **HERO** (18px num, sparkline) — Spot, IV-30d, Convergence
- **MAIN** (15px num) — Greeks, sub-scores
- **MINOR** (12px num) — supporting context

---

## Part 4 — Component Catalogue

Modules to introduce in this redesign:

| Component | File | What it owns |
|---|---|---|
| `Status bar` | `ui/components/status_bar.py` | 1-row ticker summary, used on Scope/Options Lab/Dossier |
| `Mini sparkline` | `ui/components/sparkline.py` | 50×14 px SVG inline trace |
| `KPI cell v2` | extend `metric_components.py` | three sub-grades, optional sparkline + delta |
| `Option chain grid` | `ui/components/option_chain.py` | strike-row layout for any leg-list |
| `IV surface heatmap` | `ui/components/iv_surface.py` | strike × expiry grid |
| `Heat-cell P&L` | extend `metric_components.py` | numeric cell with diverging-scale background |

---

## Part 5 — Per-Page Concrete Redesigns

### Scope page

**Today**: ticker header, verdict hero, 6 KPI cells, three tabs.
**v3**:
- **Status bar** above header (Bloomberg-style)
- **Hero verdict** keeps current shape (works)
- **Status row 2** — Earnings DTE · IV-Rank · IV-Percentile · IV/HV-Ratio · Skew · Term-Slope (6 mini-KPIs with sparklines)
- **Vol tab**: replace IV-Hero ticker-card with IV surface heatmap (strike × expiry) — the most useful single chart for a vol trader
- **Backtest tab**: keep, polish the verdict pill

### Options Lab

**Today**: builder strip top, payoff middle, metrics row, tabs below.
**v3**:
- **HERO-DUAL layout** — payoff diagram LEFT 60 %, greeks + metrics RIGHT 40 %, stacked
- **CHAIN-ROW** of legs below the builder strip — one row per leg with bid/ask/Δ/Γ/Θ
- **Scenario Matrix** stays as tab but uses HEAT[10..90] diverging scale instead of RdYlGn
- **Probability Cone** overlaid on the Payoff itself, not a separate tab

### Portfolio

**Today**: cash strip, strategy groups, per-position cards, performance section.
**v3**:
- **POSITION-BLOTTER** — one row per leg with all greeks visible inline + cell-heatmap colored by greek magnitude
- **Cash strip** stays but adds a daily-Δ-equity sparkline
- **Performance section** stays, but adds a per-greek-history mini-chart (delta over time, vega over time)

### Discover

**Today**: best-setup hero, tabs for 5 categories.
**v3**:
- **METRIC-WALL** — top-25 ticker grid (5×5) with: ticker · IV30 sparkline · convergence-pill · sector tint
- Tabs remain for deep dives
- Add a **regime ring** — circular 12-segment indicator showing today's vol regime (calm/normal/elevated/crowded)

### Scanner

**Today**: dense table.
**v3**:
- Add **inline sparkline column** (30-day IV trend) — 50px wide per row
- Add **earnings-countdown column** colored by proximity
- Column headers get **sort arrows** (currently click-only, no visual cue)

---

## Part 6a — PERFORMANCE FINDINGS (audit 2026-05-12)

### Finding #1 — **iCloud File Provider is the bottleneck (CRITICAL)**

**Evidence**: a fresh `import numpy` subprocess, run after a 10-minute
idle window on this Mac, fails with:

```
TimeoutError: [Errno 60] Operation timed out
File "<frozen importlib._bootstrap_external>", line 1218, in get_data
```

CPU sampling shows 99 % of time in `read()` syscalls under
`_io_FileIO_readall_impl`. The numpy / streamlit / volscope `.py`
files live under `~/Desktop/VolScope`, which iCloud File Provider
evicts to cloud storage after a quiet period. Every cold subprocess
pays a 25-90 s cloud-fetch tax — and occasionally times out.

**This is the real reason the app feels slow.** No amount of
`@st.cache_data` or vectorisation will fix it until the project
sits on local-only disk.

### Fixes (ordered by impact)

| # | Action | Impact | Effort |
|---|---|---|---|
| **F1** | **Move VolScope off Desktop** — `~/dev/VolScope` instead of `~/Desktop/VolScope`. Update Makefile + memory files. | 25-90 s → < 2 s cold start | 10 min, requires `mv` + symlink update |
| **F2** | Mark Desktop/VolScope as "Keep on this Mac" in iCloud settings | same as F1 but reversible | 1 min |
| **F3** | Cron job that touches every `.py` file every 30 min to keep the cache warm | partial mitigation | 5 min, brittle |

**F2 is the cheapest correct fix.** macOS: Settings → Apple Account →
iCloud → Drive → Files in iCloud Drive → uncheck Desktop & Documents
OR right-click VolScope folder → "Keep Downloaded" / "Always Keep
on This Mac" (varies by macOS version).

### Finding #2 — DB lock on parallel subprocess

When tests + audit + streamlit boot overlap, DuckDB throws
``IOException: Could not set lock``. ``scripts/release_db_lock.py
--force`` already mitigates but the cycle is fragile. Recommendation:
make DB-open path retry with a `ValueError` instead of raising on
first-attempt fail (already does — verified in `app.get_db`).

### Finding #3 — Streamlit-WebSocket first render

After HTTP 200, the WebSocket-driven first script run takes additional
30-60 s when imports are cold. This is the visible "white page" the
user sees before the sidebar materialises. Same root cause as F1.

### Finding #4 — Hot-function microbenchmarks (warm cache)

Best numbers we have from earlier targeted measurements:
- `bs_price` scalar: ~0.18 ms
- `payoff_at_t` vectorised (200pts × 4 legs): ~0.2 ms ← already optimised
- `pop_monte_carlo` (10k paths): ~3 ms
- `net_premium` scalar: ~0.18 ms
- scenario matrix (45 cells): ~8 ms ← cached after Phase R7
- AppTest per-page render: 0.3-1.2 s (varies by data freshness)

These are **fast enough** post-vectorisation. The user-perceived slowness
is entirely Finding #1.


## Part 6 — Performance Targets

| Symptom (user observation) | Target |
|---|---|
| "App feels slow to load" | Cold streamlit boot < 8 s on warm cache, < 25 s on iCloud cold |
| Page-switch latency | < 300 ms per switch |
| Options Lab IV-slider drag | < 80 ms per redraw (currently ~250 ms estimated) |
| Discover initial render | < 1.5 s (currently ~3-4 s) |
| AppTest per-page wallclock | < 1 s median |

Phase A (perf audit) below feeds concrete numbers into this table.

---

## Part 7 — Implementation Phases

| Phase | Deliverable | LOC budget | Risk |
|---|---|---|---|
| **R1** | Color system v3 — add HEAT/SEQ scales + 2 surface layers to `theme.py` | ~50 LOC | low |
| **R2** | Status bar + sparkline + KPI cell v2 (component layer) | ~200 LOC | low |
| **R3** | Scope page redesign (status bar + 6-mini-KPI row + IV surface) | ~250 LOC | medium |
| **R4** | Options Lab HERO-DUAL layout + chain-row legs | ~300 LOC | medium |
| **R5** | Portfolio position-blotter + cell-heatmap greeks | ~250 LOC | medium |
| **R6** | Discover metric-wall + regime ring + scanner sparkline column | ~200 LOC | low |
| **R7** | Performance — lazy-load heavy imports, st.cache_data on hot paths | varies | medium |
| **R8** | Visual audit (kaleido per chart, playwright per page) + regression | n/a | low |

Per phase: pytest grün + AppTest grün + visual screenshot + commit.

---

## Part 8 — Open Questions (to confirm before Phase R1)

1. **Sparkline data source** — IV-30d trailing 30 days. Already in `daily_vol`. ✓
2. **IV surface** — need option chain data (`options_snapshots` is empty). Mock with BSM smile until real chain ingest lands.
3. **HERO-DUAL on narrow viewports** — collapse to stacked at < 1100 px?
4. **Tab abolition** — keep Vol/Price/Backtest tabs on Scope, or merge into one
   scrollable panel? Master-Spec earlier said "no tab-switching" for trader-first.

---

## Closing

The previous two rounds (Apple-marketing + IBKR-density) optimised for
*readability* and *non-truncation*. This round optimises for **information
density per square inch** — the move from "polished" to "professional".

The audit below tells us what's actually slow. The plan above tells us what
shape the redesign takes. The two intersect in Phase R7 (performance).
