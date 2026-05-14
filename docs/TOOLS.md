# VolScope Tool Catalog

VolScope is a **volatility-research workbench** with a **simulation bot**
and **paper-trading** capability layered on top. The dashboard is the
primary product; the bot is one of many users of the same analytics
engine.

This document lists every tool in the platform — what it does, who it's
for, when to use it, and how it connects to the rest.

---

## 1. Research dashboard (Streamlit UI)

The 17 pages a user navigates between. Grouped by purpose in the sidebar.

### ◆ DECISIONS — "what should I do today?"

#### `Command Center`
**What:** Single landing page that surfaces today's most important
signals across every other page — cheapest vol, richest premium,
biggest movers, crowded names, regime status.
**Who:** Anyone opening the app at market open.
**When:** First thing each morning.
**Connects to:** Discover (drill-down), Scope (single-ticker deep-dive),
Signals (actionable trade ideas).

#### `Discover`
**What:** Category-driven opportunity board with four ranked lists —
Cheapest (low IV percentile), Richest (high IV percentile), Movers
(biggest 1-day IV changes), Crowded (high option vs stock activity).
Each card is colour-coded (green = cheap-buy-vol, red = rich-sell-vol).
**Who:** Researcher in idea-generation mode.
**When:** Looking for setups that match the current vol regime.
**Connects to:** Scope (1-click drill-down per ticker), Pre-Trade
(turn a candidate into a sized structure).

#### `Signals`
**What:** Bidirectional IV mean-reversion scanner. Emits ranked
trade signals with direction (LONG_VOL vs SHORT_VOL), confidence
(0–100), strategy template, and a one-line reason. Shows the historical
edge ("71% hit · +28% avg · Sharpe +0.85 · n=14") next to each card.
**Who:** Anyone with a trade thesis to validate.
**When:** Daily, after EOD scrape.
**Connects to:** Options Lab (one-click "→ Options Lab" prefills
ticker / template / strike / DTE), Bot Dashboard (signals_log).
**Powered by:** `volscope/signals/{factors,composite,filters,ranking}.py`
+ `volscope/analytics/regime.py` (HMM) + `volscope/analytics/garch.py`.

#### `Bot` (Bot Dashboard)
**What:** Operator view of the autonomous paper engine — NLV, BPR%,
cash reserve, portfolio Greeks, HMM regime probability, live
signals queue, open paper trades, equity curve, and a closed-trade
performance report (win rate, Sharpe, profit factor, expectancy,
max-DD).
**Who:** The operator running the bot.
**When:** Twice a day max (per OPERATOR_GUIDE — over-monitoring is
the #1 emotional failure mode).
**Connects to:** Everything bot-side — `bot_trades`, `bot_pnl_daily`,
`bot_signals_log`, `bot_chain_snapshots`.

#### `Alerts`
**What:** Configurable alert engine — set rules ("notify me when
PYPL IV drops below 25") and the daily scraper triggers them. Email
delivery via `VOLSCOPE_SMTP_PASS`.
**Who:** Operator who doesn't want to babysit the dashboard.
**When:** Set once, forget. Inspect weekly.

#### `Earnings Hub`
**What:** Weekly earnings calendar grid. Each cell shows implied
move (from straddle pricing), skew, IV crush history, and a
"crowded-pre-earnings" flag.
**Who:** Earnings traders.
**When:** Weekly review (Sunday) to plan the week's earnings setups.
**Hard rule:** SHORT-vol entries blocked inside 14 days of earnings.
LONG-vol setups OK if IV hasn't priced the event in.

#### `Portfolio`
**What:** Manual paper-trade journal. Multi-leg buy/close with cash
account, strategy group linkage, P&L tracking. Distinct from the bot —
this is for hand-driven trade tracking.
**Who:** Discretionary trader who wants a simulation account.

#### `Mega-Scan`
**What:** Aggressive bulk-load + scan over the full universe. Pulls
options data for every ticker the user has loaded.
**Who:** Power-user looking for hidden opportunities.
**When:** Weekly. Expensive (~5 min runtime).

---

### ◇ RESEARCH — "what does the data actually say?"

#### `Scope`
**What:** Single-ticker deep-dive. IV / HV chart with shaded
cheap/rich bands, 25-delta skew historical line, 52-week IV range bar,
earnings annotation, IV regime label, term-structure peek, company name
+ sector pill.
**Who:** Anyone investigating a specific ticker.
**When:** After Discover or Signals surfaces an interesting name.
**Inputs:** `daily_vol` rows; HV computed from OHLCV via
Close-Close / Parkinson / Garman-Klass / Yang-Zhang.

#### `Scanner`
**What:** Full universe table — sortable / filterable by IV
percentile, IV rank, IV/HV ratio, sector, market cap, etc.
ProgressColumn inline bars instead of raw numbers.
**Who:** Quant doing factor analysis.
**When:** After a hypothesis is formed ("show me all tech names with
IV percentile < 20").

#### `Heatmap`
**What:** Universe-wide IV percentile heatmap. One cell per ticker,
colour-graded green→amber→red, packed into a dense grid. Click cell →
jump to Scope. Sector medians shown when >100 tickers.
**Who:** The "where's vol cheap right now?" gut-check.
**When:** Anytime — 1-second answer.

#### `Rotation`
**What:** Sector vol regime over time — heatmap of sector × date with
median IV percentile per cell. Forward-fill densified (no sparse holes
from single missing scrapes).
**Who:** Sector-rotation analyst.
**When:** Weekly market-context review.

#### `Flow`
**What:** Capital flow indicators — put/call ratio, total call vs
put volume, open-interest trends.
**Who:** Anyone tracking dealer positioning + sentiment.

---

### ▷ EXECUTION — "turn the idea into a trade"

#### `Pre-Trade`
**What:** Single-leg sizing tool. Slider for strikes / DTE; live
greeks; risk-of-ruin calc; capital-at-risk indicator.
**Who:** Anyone about to enter a trade.
**When:** Right before paper-buying.

#### `Builder` (Strategy Builder)
**What:** Scenario-driven strategy recommender. Pick a market view
("vol cheap + bullish") → it suggests structures (Long Call, Bull Call
Spread, etc.) with strikes / DTE / sizing pre-filled. Each suggestion
includes a one-line reason.
**Who:** Trader who knows the view but needs the structure.

#### `Options Lab`
**What:** OptionStrat-grade workbench. Payoff diagrams (at-expiry +
at-time-t), greeks surface (3D delta/gamma/vega over spot×IV),
scenario matrix (P&L grid over spot-shift × IV-shift), time-decay
chart, probability cone, 11 strategy templates with one-click
materialisation. IV slider + preset loader.
**Who:** Anyone modelling a multi-leg trade.
**When:** Pre-flight check before any non-trivial structure.
**Connects to:** Signals (prefill via session_state), Portfolio
(save-to-portfolio).

#### `LEAPS Lab`
**What:** Specialised deep-OTM LEAPS scanner. Three-signal
convergence — Mispricing × Neglect × Reversal (MIS/NEG/REV) — produces
concrete deep-OTM call suggestions. Stock-replacement at 0.70-0.85 delta.
**Who:** Long-dated bullish thesis player.

#### `Dossier`
**What:** Single-LEAPS-trade renderer. Produces a PDF deck with the
full thesis, sizing (RuleOfThumb + Vince + Kelly), greeks at-open and
at-close, scenarios, exit triggers. The reference output mirrors the
operator's anchor deck.
**Who:** Anyone preparing a LEAPS thesis to share or revisit.
**Connects to:** LEAPS Lab (select ticker → click "Build Dossier").

#### `Earnings Trades`
**What:** Pre/post-earnings position tracker. Logs entries with IV
expectations, marks them after the print, computes IV crush realised
vs implied. Builds a per-ticker historical crush distribution over
time.

#### `Backtest`
**What:** Historical strategy P&L replay. Pick a strategy + ticker +
date range → see Sharpe, win rate, max-DD, profit factor. Live
progress streaming.
**Who:** Anyone validating a strategy idea before paper-trading it.

---

### ? REFERENCE

#### `Help`
**What:** Glossary + keyboard shortcuts + page-by-page user guide.

---

## 2. Analytics engine (`volscope/analytics/`)

The pure-math layer every UI page sits on top of.

| Module | What it does | Inputs | Outputs |
|---|---|---|---|
| `black_scholes.py` | Price + Δ + Γ + Θ + Vega + ρ for European options. Q-aware. Validated against `py_vollib` to 1e-15. | spot, strike, rate, div, sigma, T, type | float price + greeks dict |
| `bsm_iv.py` | Newton-Raphson IV solver. Bisection fallback. Validated round-trip to 1e-4. | price, spot, strike, rate, div, T, type | sigma (or None on no-arb violation) |
| `hv_*.py` | Four HV estimators — Close-Close, Parkinson, Garman-Klass, Yang-Zhang. YZ is the min-variance unbiased estimator. | OHLCV DataFrame | annualised σ series |
| `metrics.py` | IV rank, IV percentile, IV/HV ratio, vol regime label. | iv30 series | scalar per metric |
| `regime.py` | 2-state Gaussian HMM. Features `[VIX Δ, SPY 20d RV]`. `predict_proba_calm()` returns p_calm ∈ [0,1]. | VIX Δ, SPY RV20d | RegimeDetector |
| `garch.py` | GARCH(1,1)-t volatility forecaster. Persistence check (α+β<1). | log-returns | 30-day annualised σ forecast |
| `leaps_*.py` | LEAPS convergence scoring, watchlist, scenarios, sizing, pretrade checks, PDF rendering. | ticker + IV history | LeapsRecommendation |
| `crowded_*.py` | Crowded-trade scoring + pre-earnings crowding. | option vol / stock vol | Composite score 0-100 |
| `signals.py` | Legacy bidirectional signal engine (LONG_VOL / SHORT_VOL with TRIPLE_CHEAP / TRIPLE_RICH types). | daily_vol latest | List[Signal] |
| `signal_backtest.py` | Historical replay of any signal trigger; produces hit rate + Sharpe + n. | signal trigger + history | BacktestResult |
| `paper_backtest.py` | NEW (v0.3.0): closed-trade P&L summary for the paper engine. | `bot_trades` closed rows | BacktestReport |

All analytics functions follow the contract:
- Inputs validated at the boundary; invalid → returns `None`, never raises.
- Pure functions — no DB writes, no network.
- 1e-15 numerical agreement with reference implementations on goldens.

---

## 3. Signal engine (`volscope/signals/`)

The bot's brain. Six atomic factors → composite score → 8 hard gates →
ranked output.

| Module | What it does |
|---|---|
| `factors.py` | IVR, IVP, IV/HV ratio, term slope (iv30/iv90-1), 25Δ risk reversal, HV momentum (hv5/hv30). Pure scalars from a pandas Series. |
| `composite.py` | Weighted 0-100 score (weights: IVR 0.15 / IVP 0.20 / VRP 0.20 / term 0.15 / skew 0.05 / mom 0.10 / regime 0.15). Direction-aware. NaN-tolerant — missing factors get their weight redistributed. |
| `filters.py` | 8 hard gates: persistence (≥2d), volume, OI, BAS, earnings (14d / 21d on low source confidence), macro calendar (Fed / CPI / NFP ±3d), HMM regime (p_calm > 0.6 for short vol), consensus rule (IVR & IVP must agree; |IVR-IVP|>30 = single-spike contamination). |
| `ranking.py` | Sort by composite → apply portfolio caps (max_concurrent / max_per_underlying / max_per_sector / max_index_vs_single_name). Blocked candidates retain `blocked_reason`. |

---

## 4. Paper engine (`volscope/execution/`, `volscope/lifecycle/`)

The simulation layer. Takes a ranked signal → executes against real
chain data → tracks lifecycle → MTM daily.

| Module | What it does |
|---|---|
| `execution/ibkr_stub.py` | Connectivity scaffold. Never raises on connect failure. Phase 2.5 swaps in the live `ibkr_client.py`. |
| `execution/paper_engine.py` | NEW (v0.3.0): take a `RankedSignal` → look up real strikes from `bot_chain_snapshots` → apply slippage model → write `bot_trades` + `bot_legs`. Transactional — no partial fills. |
| `lifecycle/machine.py` | 11-state trade lifecycle via `transitions` library. SIGNALED → SIZED → SUBMITTED → FILLED → MANAGED → CLOSING → CLOSED + terminal paths (ABANDONED, REJECTED, EXPIRED, ASSIGNED, ROLLED). Audit callback fires on every transition. |
| `lifecycle/daily_mtm.py` | NEW (v0.3.0): for each open trade, look up current chain quote → compute MTM → apply exit rules (50% PT / 2× stop / 21-DTE) → trigger CLOSING transition → roll up `bot_pnl_daily`. |

---

## 5. Risk + scheduling (`volscope/risk/`, `volscope/scheduler/`)

| Module | What it does |
|---|---|
| `risk/kill_switch.py` | Three manual trip paths (file flag, env var, DB row) + five auto-checks (drawdown, VIX, daily loss, IBKR disconnect, term-structure inversion). Reset requires literal date-stamped token. |
| `scheduler/jobs.py` | APScheduler 3.11 AsyncIOScheduler. `America/New_York` timezone. 8 daily jobs (premarket / connect / signals / execute / midday / EOD / reconcile + weekly report) + heartbeat to Healthchecks.io if URL set. SQLite jobstore persists across restarts. |

---

## 6. Data layer (`volscope/data/`)

| Module | What it does |
|---|---|
| `database.py` | DuckDB connection wrapper. Path defaults to `~/Library/Application Support/VolScope/volscope.db` on macOS (outside iCloud File Provider scope). Read-only mode for UI; bot is sole writer. |
| `scraper.py` | Daily yfinance scrape — OHLCV + chain summary (IV30, IV90) per ticker. Validates IV bounds; rejects suspect rows. |
| `chain_scraper.py` | NEW (v0.3.0): full-chain scrape per ticker (every strike × every expiry). Writes `bot_chain_snapshots`. Nightly. |
| `chain_quote.py` | NEW (v0.3.0): quote lookup with closest-strike fallback. `apply_slippage()` haircut from `config/risk.yaml::slippage_model`. |
| `ticker_resolver.py` | On-demand ticker addition. Yahoo symbol validates → 2y OHLCV backfill → HV computed → ticker becomes first-class. International fallback (HK, TW, SS, T, KS for digits; L, DE, PA, AS, AX, TO for alpha). |
| `universe_loader.py` | Bulk-load entire ticker universe with progress streaming. |
| `earnings_meta.py` | Earnings-date metadata: BMO/AMC flag, source confidence (Finnhub primary, Alpha Vantage cross-check). |

---

## 7. Persistence (`volscope/persistence/`)

| Component | What it does |
|---|---|
| `migrations/001_init.sql` | 5 `bot_*` tables: trades, legs, pnl_daily, signals_log, orders_log + bookkeeping `bot_migrations`. |
| `migrations/002_killswitch.sql` | `bot_killswitch` — single-row table with active state. |
| `migrations/003_chain_snapshots.sql` | NEW (v0.3.0): `bot_chain_snapshots` (per ticker × snapshot × strike × expiry × right) + `bot_chain_latest` view. |
| `db.py::apply_migrations()` | Idempotent migration runner. Lexical-order application; bookkeeping prevents re-runs. |

---

## 8. Scripts (`scripts/`)

Organised by purpose:

| Group | Purpose |
|---|---|
| `scrape/` | Data ingestion — daily, earnings, chains, signals capture. |
| `verify/` | End-to-end smoke regression. `verify_all.py` is the canonical 7-stage check. |
| `audit/` | Code + design-drift detection. Used by autonomous Maturity Loop. |
| `compute/` | Periodic recomputation — convergence, sector rotation, aggregates. |
| `backtest/` | Strategy backtest drivers. |
| `ops/` | Setup + lock management + autonomous loop + pre-flight + reconcile. |
| `autonomous/` | Launchd-driven prompt files (5 daily loops + 3 weekly: audit / backtest / renewal). |
| `_dev/` | Dev-only / ad-hoc — gitignored. |

---

## 9. Configuration (`config/`)

Plain YAML. Operator-readable. Edits land only in the Sunday 18:00 ET
review window with a 90-day cooldown (enforced by social contract, not
code — yet).

| File | Governs |
|---|---|
| `strategies.yaml` | Per-strategy params (DTE, deltas, PT, stop, blackouts). |
| `risk.yaml` | Kelly fraction, max BPR, sector caps, kill-switch thresholds, slippage model, go-live gate. |
| `tickers.yaml` | Universe by tier (indices / megacap-tech / sector-ETFs / monitor-only / blocked) + liquidity minima. |
| `calendar.yaml` | FOMC / CPI / NFP / OPEX dates + blackout window. |

---

## 10. Synergies — how tools chain together

The platform is designed so a single insight flows through multiple
tools without re-typing:

1. **Discover** surfaces "PYPL IV is cheap" → click → **Scope** shows
   the full IV/HV history.
2. From **Scope** the user clicks "Pre-Trade" → **Pre-Trade** opens
   with PYPL preloaded + a sized long-call structure suggested.
3. The user tweaks → clicks "Save to Portfolio" → the multi-leg trade
   lands in **Portfolio** with an open paper position.
4. Simultaneously, **Signals** has already flagged PYPL as TRIPLE_CHEAP
   → its card shows the historical edge ("65% hit · n=18") → clicking
   "→ Options Lab" prefills the same idea there for modeling.
5. The **Bot Dashboard** shows whether the bot has independently
   executed the same setup paper-engine-side, and what its current MTM is.
6. After earnings, the **Earnings Trades** page logs the IV crush and
   feeds the crush-distribution back into next quarter's Earnings Hub
   model.

The point: every page is a different lens on the same underlying
`daily_vol` + `bot_*` truth. The bot is a USER of the same engine, not
a separate product.

---

## Audience summary

| You are... | Start here |
|---|---|
| Discretionary trader, manual workflow | Command Center → Discover → Scope → Pre-Trade / Options Lab → Portfolio |
| Researcher, no live trades | Scanner → Heatmap → Rotation → Flow |
| Earnings specialist | Earnings Hub → Earnings Trades |
| LEAPS thesis player | LEAPS Lab → Dossier → Portfolio |
| Bot operator | Bot Dashboard → check kill switch → review signals_log + closed-trade backtest |
| Quant validating an idea | Backtest → Options Lab scenario matrix → Signal back-edge string on Signals page |
| New session agent | `WELCOME-AGENT.md` → `memory/INDEX.md` → `docs/ARCHITECTURE.md` → this doc |
