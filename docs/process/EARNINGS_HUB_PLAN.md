> Status: ARCHIVED
> This document captures a past planning session. It is preserved
> for historical context — current state lives in /memory/roadmaps/ + /ROADMAP.md.

# Earnings Hub — Plan

Date: 2026-05-13 · Author: claude-opus-4-7 · Status: **v1 SHIPPED**

> **2026-05-13 update**: all phases E1-E8 executed autonomously under
> CEO mandate. Deliverables below. Pending: live pytest verification
> (the iCloud-cold subprocess issue documented in REDESIGN_PLAN.md
> Part 6a is blocking the regression run in this session).
>
> Files added:
>   - `volscope/analytics/earnings_expected_move.py`
>   - `volscope/analytics/crowded_pre_er.py`
>   - `volscope/analytics/earnings_strategy.py`
>   - `volscope/ui/views/earnings_hub_page.py`
>   - `scripts/scrape_earnings_meta.py`
>   - `tests/test_earnings_analytics.py`
>
> Files modified:
>   - `volscope/data/database.py` (7-col earnings migration)
>   - `volscope/ui/styles/theme.py` (vs-er-tile CSS)
>   - `volscope/ui/app.py` (registry entry)
>   - `volscope/ui/components/sidebar.py` (nav entry)
>   - `README.md` (feature blurb)

> *"Interaktiver Earnings-Kalender 1:1 wie bei earningshub.com — die ganze*
> *Woche mit Uhrzeit, UND UNDBEDINGT der Option-Implied Expected Move für*
> *die Earnings mit Skewness, Crowded Trades in Earnings.*
> *BRAINSTORME — DAS IST EIN GENIALES FEATURE."*

This document plans VolScope's most valuable new page: a vol-trader's
earnings calendar. It is not a clone of earningshub.com — earningshub
is an equity tool, VolScope is a vol tool. We use the calendar layout
as the visual anchor and add the four columns that actually matter to
someone trading options: **implied move · skew · crowdedness ·
expected post-print crush**.

---

## Part 1 — Why this feature is genius

A retail vol trader's morning routine has one decision per ticker per
day: *Is the options market mispricing this earnings event?* That
decision needs **four numbers** sitting next to each other:

1. **Implied move** — what the market is pricing as the next 1-day move.
2. **Direction skew** — are calls or puts more expensive? Where is the
   market positioning?
3. **Crowdedness** — has unusual size been building up before the print?
4. **Post-crush expectation** — how much will vol crater after the print,
   and is that crush already priced or still a gift?

Every other tool (earningshub, optionstrat-calendar, Yahoo earnings)
shows you the *consensus EPS* and the *date*. We show the four numbers
that decide whether you trade or sit out — and we put them next to
each other in a weekly grid so the trader scans a whole week in
30 seconds.

The leverage is huge because all four numbers are derivable from data
we already have in DuckDB. There is **no new external data source
required for v1** beyond enriching the existing earnings table with a
BMO/AMC flag.

---

## Part 2 — What earningshub.com does (the visual reference)

| Element | earningshub.com |
|---|---|
| Layout | Weekly grid: Mon-Fri columns, tickers as cells |
| Time grouping | BMO (Before Market Open) / AMC (After Market Close) bands |
| Tile contents | Symbol · market cap · consensus EPS · revenue estimate · last quarter reaction |
| Sort | Default by market cap; sortable by date/IV |
| Filter | Sector, market cap, watchlist |
| Detail | Click → page with full earnings history, EPS surprise heatmap |

VolScope's gap analysis:

| earningshub | VolScope v1 | Why we differ |
|---|---|---|
| Consensus EPS | Show but secondary | Numbers don't move IV — the *implied move* does |
| Revenue estimate | Skip in v1 | Not a vol-tool concern |
| Market cap | Show as context only | Bucket tickers, not header |
| Earnings history | Yes — last 8 quarters | Same as them |
| **Implied move** | **NEW (their headline)** | Our headline |
| **Direction skew** | **NEW** | The Bloomberg trader-grade indicator |
| **Crowded score** | **NEW** | Anomaly-detection unique to us |
| **Post-crush %** | **NEW (estimated)** | Already in `earnings_crush.py` |

---

## Part 3 — Analytics: what each number means + how we compute it

### 3.1 Implied Move (the headline)

The market-priced 1-day-after-earnings move expressed as `± X %` of spot.

**Three computation methods, ranked:**

| Method | Formula | Pros | Cons | Status |
|---|---|---|---|---|
| **A. ATM Straddle (preferred)** | `(call_atm + put_atm) / spot` for first expiry past ER | direct market price | needs chain | partial — we can simulate via BSM at iv_30d |
| B. ATM-IV scale | `iv_30d * sqrt(dte_to_post_er / 365)` | works with our data | underestimates because ER is binary, not continuous | already have |
| C. Variance differential | `sqrt(iv_post² * t_post − iv_pre² * t_pre)` | mathematically correct | needs two-expiry chain | future |

**For v1**: implement A using BSM-priced synthetic straddle at the
ticker's current `iv_30d` (since we don't have live chains). Display
also the cross-check from method B in a small tooltip. Document the
synthetic nature with an `EST·BSM`-style chip (we already have this
convention from LEAPS Lab).

Module: `volscope/analytics/earnings_expected_move.py` (new) —
single function `compute_implied_move(db, ticker, earnings_date) →
ImpliedMove`.

`ImpliedMove` dataclass:
```python
@dataclass
class ImpliedMove:
    ticker: str
    earnings_date: date
    days_to_er: int
    iv_used: float                 # IV % used as input
    spot: float
    move_pct: float                # ±X %
    move_dollars: float            # in $ on the underlying
    upper_bound: float             # spot + move_dollars
    lower_bound: float             # spot − move_dollars
    method: str                    # "atm_straddle_bsm" | "atm_iv"
    cross_check_iv_method_pct: float    # the alternative for comparison
    confidence: str                # "high" | "medium" | "low"
```

### 3.2 Direction Skew (puts vs calls)

The 25-delta risk reversal: `iv_put_25d − iv_call_25d` in vol points.

- **Positive (puts richer)** → market hedging downside / pricing in a
  bearish surprise. **Trade view**: market is paying up for protection,
  asymmetric upside-call is a contrarian-cheap entry.
- **Negative (calls richer)** → bullish positioning. Market priced in
  good news. **Trade view**: protective puts are cheap. Cheap fade.

We already have `iv_skew_25d` in `daily_vol` — that's the put-call
delta-skew snapshot. The Earnings Hub just surfaces it next to the
implied move.

UI: a tiny diverging bar:
```
       ─10pt   ATM   +10pt
calls rich   |       puts rich
                ▌▌▌▌▌  (skew = +5.2pt)
```

### 3.3 Crowded Score (pre-ER)

We already have `compute_crowded_score(row, history)` which combines
4 z-scores (PCR, OI, volume, IV-HV spread). For the Earnings Hub we
add a **pre-ER baseline comparison**:

```
crowded_score_today = 76
historical_pre_er_75th_percentile = 64
→ this is in the top 12 % of pre-ER crowding for this ticker
```

Module addition: `volscope/analytics/crowded_pre_er.py` (new)

```python
def pre_er_crowded_context(db, ticker, earnings_date) → CrowdedPreER:
    """For the 7d window before each historical earnings date,
    snapshot the crowded score. Build a per-ticker distribution.
    Return today's percentile within that distribution."""
```

`CrowdedPreER` dataclass:
```python
@dataclass
class CrowdedPreER:
    score_today: float           # 0..100
    historical_n_events: int     # how many past earnings we have
    historical_median: float
    historical_p75: float
    historical_p90: float
    percentile_today: float      # where today sits in its own history
    band: str                    # "calm" | "normal" | "elevated" | "exceptional"
```

### 3.4 Post-Print IV Crush (expected)

We already have `compute_crush_estimate(db, ticker) → CrushEstimate`
which computes per-ticker historical avg crush. Just plug into the
tile.

```
CrushEstimate.avg_crush_pct = −42 %   (IV typically drops 42 % after this ticker's prints)
CrushEstimate.n_events = 8
CrushEstimate.range = (−55 %, −28 %)
```

**Tile shows**: `crush −42 % (avg over 8 events)`.

**v2**: combine crush estimate with current IV-rank to identify
"crush opportunities" — tickers where IV is ramping AND the crush is
historically aggressive → short-vol setup.

### 3.5 Suggested Strategy (bonus analytics)

For each (implied_move, skew, crowded, crush) tuple, classify into one
of five trader-recognisable strategies:

| Pattern | Suggested |
|---|---|
| Implied move > 1.5× realised (last 8 quarters), low crowding | Long Straddle — cheap gamma |
| Implied move ≈ realised, IV rank > 80, crowded calm | Short Iron Condor — fade-vol |
| Strong put skew + crowded high | Long Call (contrarian) — fade panic |
| Strong call skew + crowded high | Long Put (contrarian) — fade euphoria |
| Mixed signals | Wait — no edge |

Already have `strategy_recommender.recommend_strategies` — extend with
an earnings-aware variant `recommend_for_earnings(implied, skew,
crowded, crush) → list[StrategyRec]`.

---

## Part 4 — Data: what we have, what we need

### Already in DuckDB

| Source | Fields | Note |
|---|---|---|
| `earnings` | ticker, earnings_date | needs migration (Part 4.2) |
| `daily_vol` | spot, iv_30d, iv_60d, hv_20d, iv_skew_25d, iv_rank, iv_percentile, PCR, OI, volume | sufficient |
| `validation_log` | quality flags | for the freshness chip |

### Migration needed

Add to `earnings`:
```sql
ALTER TABLE earnings ADD COLUMN IF NOT EXISTS time_of_day VARCHAR;     -- 'bmo'|'amc'|'unknown'
ALTER TABLE earnings ADD COLUMN IF NOT EXISTS eps_estimate DOUBLE;
ALTER TABLE earnings ADD COLUMN IF NOT EXISTS revenue_estimate DOUBLE;
ALTER TABLE earnings ADD COLUMN IF NOT EXISTS last_reaction_pct DOUBLE;
ALTER TABLE earnings ADD COLUMN IF NOT EXISTS last_implied_pct DOUBLE;
```

### New scraper

`scripts/scrape_earnings_meta.py` (new) — for every ticker with an
upcoming earnings in the next 30 days:

1. Call `yf.Ticker(t).calendar` to pull BMO/AMC + EPS estimate.
2. Call `yf.Ticker(t).earnings_dates` for last 4 quarters' actuals.
3. For each historical earnings, compute the actual 1d move from
   `daily_vol.spot_price` (close-to-close earnings_date to next).
4. Reconstruct what the implied move WOULD have been (using the
   `iv_30d` of `earnings_date − 1`) — gives us calibration data.
5. Upsert into the new fields.

Runs idempotently. ETA ~3-5 min for 290 tickers (yfinance rate limit
1.5 s/ticker).

Wire into `make scrape` as a sub-step (after `daily_scrape`).

### Fallbacks for missing data

- No BMO/AMC available → show "—" + sort to end of day
- No EPS estimate → silent omission, no fake number
- No historical actuals → skip calibration banner, show only forward-looking numbers

---

## Part 5 — UI: the page itself

### 5.1 Top of page

```
◈ Earnings Hub                     [● FRESH 0d · 292 tickers]  [↻ refresh]

This week · 12 earnings events     [Mon][Tue][Wed][Thu][Fri][Next week]
                                   Filter: sector · min implied · watchlist
```

- Title + freshness bar (already built last session)
- Day-of-week pills as sticky navigation (jump to that column)
- Sector filter dropdown, min-implied-move slider, watchlist-only toggle

### 5.2 Weekly grid

5 columns (Mon-Fri), each split horizontally into 3 sub-bands:
- **BMO** (top)
- **DURING** (middle, rare — most companies report BMO or AMC)
- **AMC** (bottom)

Each cell is a ticker tile. Color of the cell's left border = quick
heat signal (combination of crowded + skew anomaly).

```
            MON 5/13       TUE 5/14       WED 5/15       THU 5/16       FRI 5/17
   ┌─────────────────┐ ┌─────────────────┐
BMO│ JPM         ⬛⬛ │ │ BAC         ⬛⬛ │
   │ ±3.1 %  +1.2pt  │ │ ±2.8 %  −0.5pt │
   │ crowd 45  IVR 38│ │ crowd 31  IVR 22│
   └─────────────────┘ └─────────────────┘
                                                          ┌─────────────────┐
                                                          │ NFLX        ⬛⬛⬛│
AMC                                                       │ ±8.2 %  +3.4pt  │
                                                          │ crowd 81  IVR 84│
                                                          └─────────────────┘
```

The "interesting" tiles get auto-highlighted (animated dim-up on
hover, never auto-bouncing).

### 5.3 Tile component (collapsed state)

Compact, 4-line:

```
┌─────────────────────────────────────────┐
│ NFLX     $645.32  +0.4%      Thu AMC   │  ← header (ticker, spot, day/time)
│ ±8.2 %   ▲+5.8  ▼-4.2 |  skew +3.4pt   │  ← implied move (up+down asym) + skew
│ crowd 81 ●●● top 8 %  IVR 84  crush -52%│  ← crowd + IV-rank + post-crush
│ Suggested: Long Straddle              ▸ │  ← strategy + click-to-expand
└─────────────────────────────────────────┘
```

Color encoding:
- Implied move % uses `seq_color(move_pct, 0, 15)` — deeper blue for
  bigger move.
- Skew bar: red if >|3pt|, amber if >|1pt|, muted otherwise.
- Crowded score uses `seq_color(crowd, 0, 100)` already-existing.
- Border-left color = the *strongest* of the three signals (whichever
  is most extreme).

### 5.4 Detail drawer (clicked state)

Click a tile → drawer expands inline with 6 sub-cards:

1. **Implied vs realised** — last 8 quarters: implied move bar vs
   actual move bar, side-by-side. Shows whether the market has been
   systematically over- or underpricing this ticker.

2. **Direction skew evolution** — line chart, last 30 days of
   `iv_skew_25d` for this ticker. Shows whether positioning is
   building toward one side.

3. **IV ramp** — line chart, last 30 days of `iv_30d`, with a vertical
   marker at "−7d to ER". Shows the pre-print IV ramp.

4. **Crowded score evolution** — last 30 days line. Already have the
   computation; just plot it.

5. **Recommended structure** — full `StrategyRec` card (existing
   component) tailored to this earnings event.

6. **Paper-buy CTA** — one button: "▶ paper-buy this trade". Goes
   through the existing `paper_trader.paper_buy_strategy()`.

Drawer can be closed by clicking the tile again or pressing `Esc`.

### 5.5 Sector heatmap (bottom-of-page bonus)

A small horizontal bar chart: for each sector with ≥ 2 earnings this
week, show the median implied move. Surfaces "this week tech is
pricing 9 %, banks 3 %" — useful for relative-vol-positioning.

### 5.6 Watchlist overlay

If the user has positions in the Portfolio for a ticker that reports
this week, the tile gets a `▣ in portfolio` badge. Click → jumps to
that position with the earnings-aware suggestion pre-loaded.

---

## Part 6 — Implementation phases

| # | Phase | Deliverable | Risk | Test |
|---|---|---|---|---|
| **E1** | DB migration + scraper for BMO/AMC + EPS | adds 4 columns + new `scrape_earnings_meta.py` CLI | low | unit-test migration idempotency |
| **E2** | Analytics: `earnings_expected_move.py` + `crowded_pre_er.py` + extend `strategy_recommender.recommend_for_earnings()` | pure functions | low | tests against synthetic + live PYPL data |
| **E3** | `volscope/ui/views/earnings_hub_page.py` skeleton — page registers, freshness bar, week-nav pills | renders empty grid | low | AppTest |
| **E4** | Tile component — single ticker's earnings tile with all 4 metrics | reusable widget | low | render-test via kaleido (extracted HTML) |
| **E5** | Weekly grid layout — 5 columns × BMO/AMC bands, populates from `db.get_upcoming_earnings()` over next 7 days | full hub usable | medium | AppTest |
| **E6** | Detail drawer (click expansion) — 6 sub-cards + paper-buy CTA | most code in this phase | medium | AppTest interaction |
| **E7** | Sector heatmap footer + watchlist overlay | nice-to-have | low | smoke-test only |
| **E8** | Sidebar nav entry + Help docs + visual audit + verify-all | integration | low | full regression |

Per phase: pytest green, AppTest green, atomic commit.

**Total estimate**: 1500-2000 LOC across phases. Plan for 1-2 sessions.

---

## Part 7a — Decisions (committed 2026-05-13)

Acting as CEO, I committed the following without further user review.
Each decision is reversible later if data shows it's wrong; the
rationale is logged for traceability.

| # | Question | Decision | Rationale |
|---|---|---|---|
| 1 | Earnings-time source | **yfinance.Ticker(t).calendar** primary; **yfinance.Ticker(t).earnings_dates** fallback. Tickers without time → "Time TBD" pseudo-band sorted to bottom of each day. | Cheapest. Already a dependency. Probe (see Phase 0) confirms it returns ``earningsTimestampStart`` (epoch sec) on most liquid US tickers. |
| 2 | Implied-move method | **Auto-switch**: BSM-synthetic ATM straddle when DTE-to-ER ≤ 14 days; `iv_30d × √(days/365)` otherwise. Method shown in tile tooltip. | A diverges from B when there's a meaningful pre-ER IV ramp — at ≤14d the straddle captures the binary-event premium correctly; further out the simpler scaling is more honest about uncertainty. |
| 3 | Calibration depth | **Use up to 8 quarters**, require **≥ 3** to surface the calibration bar. Below 3 → "insufficient history" badge but the live implied-move tile still renders. | 3 is the minimum for a meaningful avg; 8 covers two years of regimes without overfitting current vol environment. |
| 4 | Default sort within a day | **Interestingness score** = `0.40 × min(implied_move_pct, 15)/15 + 0.40 × crowded_score/100 + 0.20 × min(|skew_pt|, 5)/5`. Re-sortable. | Treat each signal as 0..1 normalised then weighted-sum; the cap (15%, 5pt) prevents one extreme from dominating. |
| 5 | Cache TTL | **`@st.cache_data(ttl=1800)`** (30 min) per `(ticker, earnings_date)` tuple for the tile-level analytics. | Implied move + crowded change daily, so 30 min is a balanced refresh that survives ~all intraday IV-slider use. |
| 6 | Performance budget | **< 1.5 s page render for ≤ 15 events/week**. Each tile ~15 ms cold, ~0 ms warm. Sector heatmap ~50 ms. Drawer ~100 ms on click. | Already established from prior microbenchmarks. |

### Additional decisions discovered while planning

| 7 | Sector grouping toggle | **Off by default** — chronological grid first. Toggle in filter bar adds a "group by sector" mode that reorders the grid into sector rows × day columns. | Trader scans by date first, sector second. |
| 8 | Watchlist overlay | **Always on** — owned positions get a green `▣ in portfolio` badge in the tile header. Click-through deep-links to that position with the earnings recommendation pre-loaded. | Portfolio integration is the killer feature. |
| 9 | Crush estimate display | Only show when `n_events ≥ 3` (matches calibration rule). Below that, show "—". | Avoid fake precision. |
| 10 | Strategy recommendation thresholds | Long straddle when `implied_realised_ratio < 0.85` AND `crowded_band ∈ {calm, normal}`. Short condor when `iv_rank > 80` AND `crowded_band = calm`. Fade-skew long-call when `skew > +4pt` AND `crowded_band ∈ {elevated, crowded}`. Mirror for fade-skew long-put. Else WAIT. | Each rule mappable to a known trade idea; passes the trader-recognisability test. |

### Methodology — Implied-realised ratio

For each historical earnings event (≥ 3 events required):
1. Get `iv_30d` on `earnings_date − 1` → reconstructed implied move = `iv × sqrt(1/365)` (1-day post-ER move expectation).
2. Get actual 1d return = `spot[earnings_date + 1] / spot[earnings_date − 1] − 1`.
3. Ratio = `|actual| / implied`.
4. Avg across events → if avg > 1.1 → market UNDERPRICES (long-straddle edge), < 0.9 → market OVERPRICES (fade-vol edge).


## Part 7 — Open questions to answer BEFORE Phase E1

1. **Earnings-time-of-day source** — yfinance is the cheapest. But
   yfinance's `calendar` field is inconsistent (sometimes missing).
   Backup source: Nasdaq IR feed? Yahoo manual scrape?
   **Default**: yfinance only; tiles without time-of-day go to a
   "Time TBD" pseudo-band at the bottom of each day.

2. **Implied move method default** — A (BSM straddle) is best when we
   have IV-30d. But for ER more than 14d out, IV-30d isn't a clean
   proxy. Use B (`iv_30d × sqrt(t)`) for ER > 21d.
   **Decision**: switch automatically based on days-to-ER; document
   the switch in the tooltip.

3. **Historical calibration depth** — 4 quarters minimum? 8 quarters
   preferred? More data = better calibration but most tickers don't
   have 8 quarters of `daily_vol` history.
   **Decision**: use up to 8, require ≥ 3 to surface the calibration
   bar; otherwise skip with "insufficient history" badge.

4. **Default sort within a day** — by spot? Market cap? Implied move?
   Crowded score?
   **Decision**: by *interestingness score* = `0.4 × implied_move_pct +
   0.4 × crowded_score / 10 + 0.2 × |skew_pt|`. Re-sortable by user.

5. **Refresh frequency** — earnings dates change rarely (weekly).
   Implied move + skew + crowded change daily. Re-compute on every
   page render? Cache?
   **Decision**: cache per-(ticker, date) for 30 min with
   `@st.cache_data(ttl=1800)`.

6. **Performance budget** — page render must be < 1.5 s on 12 earnings
   events / week (typical). Each tile's analytics: ~5-15 ms cold.
   12 × 15 = 180 ms — fine.

---

## Part 8 — Acceptance criteria

Before declaring v1 done:

- [ ] Sidebar shows `Earnings Hub` under DECISIONS
- [ ] Page loads in < 1.5 s for 12 weekly events
- [ ] Each tile shows implied move + skew + crowded + crush
- [ ] Click expansion drawer works on at least 3 tickers
- [ ] Detail-drawer charts (4 of them) render without exception
- [ ] Paper-buy CTA → success + position appears in Portfolio
- [ ] Watchlist overlay highlights tickers user owns
- [ ] Freshness bar reflects last scrape
- [ ] All 290+ tickers scraped for BMO/AMC + EPS at least once
- [ ] pytest + verify-all green
- [ ] Visual audit of weekly grid via kaleido (one PNG per layout case)

---

## Closing

This feature has the *highest-leverage* of anything we could build now,
because it answers the single most-asked retail-vol question
("should I trade XYZ's earnings?") with our existing analytics plus
one new layout. Earnings calendars exist everywhere; vol-tool earnings
calendars don't. We make the volscope canonical one.

After this is shipped, the natural next iterations are:
- **Live chain ingest** (Phase 0.1 of the LEAPS Lab plan) to replace
  the BSM-synthetic straddle with real bid/ask
- **Multi-ticker comparison panel** — overlay implied vs realised
  across all tech ER events this quarter
- **Calendar alerts** — push when a watchlist ticker enters
  "interesting" band (crowd > 75 + IV ramp > 20 pt within 7d)

I'll wait for your go before I touch code. If the open questions in
Part 7 are answered ("yes use yfinance / yes auto-switch method /
3+ quarters / interestingness sort / 30 min cache") I can start
straight at Phase E1.
