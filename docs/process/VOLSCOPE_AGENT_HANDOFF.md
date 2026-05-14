> Status: ARCHIVED
> This document captures a past planning session. It is preserved
> for historical context — current state lives in /memory/roadmaps/ + /ROADMAP.md.

# VolScope — Agent Handoff & Full-State Documentation

**Stand:** 2026-05-10 (Apple-Pass + verify-all-Framework shipped)
**Zweck:** Ein anderer Opus-Agent (oder du selbst nach einer Pause) kann dieses Dokument lesen und ohne Informationsverlust weiterarbeiten. Hier steht alles: Architektur, Datenbestand, gebaute Features, Konventionen, Quirks, Plan, offene Ideen.

> **Quick-Check für neue Agents:** `make verify-all` — einziger Command der jede Korrektheitsgarantie in unter 5 min prüft. JSON-Report in `data/verify/latest.json`. Exit 0 ⇔ VolScope ist mathematisch + visuell + datentechnisch korrekt.

---

## 0. TL;DR (15 Sekunden)

VolScope ist eine **Volatility-Intelligence-Plattform für Retail-Optionen-Trader**. Python-only, Streamlit-Frontend, DuckDB-Backend.

Das Herzstück ist heute das **LEAPS Lab**: ein Konvergenz-Scanner, der Aktien findet bei denen drei unabhängige Signale gleichzeitig auf eine Anomalie zeigen — Vol-Mispricing × Vernachlässigung × Reversal-Setup — und für jede aktionable Aktie einen konkreten deep-OTM-LEAPS-Trade vorschlägt: Strike, Expiry, Greeks, Payoff-Ladder, Sizing-Kalkulator, Risk-Plan, PDF-Export.

Das kanonische Beispiel ist die **(thesis position — outside bot scope)-Strategie** ((reference deck — see operator's archive)). Das ganze Tool ist gebaut, um genau diese Art von Trade systematisch zu finden und ausführungsreif aufzubereiten.

---

## 1. Mental-Modell

### Die EINE Frage

> *"Wo sind Optionen heute gleichzeitig billig vs. realisierter Vol, billig vs. eigener Historie, in einem vergessenen Namen mit reversierender Chartstruktur — und wie sähe der konkrete LEAPS-Trade aus?"*

### Die drei Signale (LEAPS Lab)

| Signal | Gewicht | Was es misst |
|---|---:|---|
| **Mispricing** | 50 % | IV/HV-Ratio + IV-Rank + IV-Percentile — Optionen unter realisierter Vol *und* nahe annualem Tief |
| **Neglect** | 30 % | TTM-Relative-Strength-Lücke vs. SPY — wenn niemand zuschaut, bleibt Premium zu lange billig |
| **Reversal** | 20 % | Drawdown vom 52w-Hoch + HV-20d/60d Cooling — die "Wave-II-Base"-Pattern |

Composite ≥ 65 = aktionable Konvergenz. Die Kombination ist selten (1-2× pro Jahr pro Ticker). Genau das macht sie handelbar.

### Die vier Signale (alte VolScope-Vision, bleibt gültig)

Aus `~/.claude/projects/-Users-tomschoen/memory/volscope-vision.md`:
1. IV vs HV (real vs erwartet)
2. IV vs eigene Historie (Percentile, Rank)
3. Sektor-Regime (relative Vol-Position der Branche)
4. Capital-Flow (Smart-Money-Flow, Crowded-Trades)

Die LEAPS-Lab-Konvergenz ist eine *spezifische Komposition* dieser Signale plus Neglect (relative Performance vs Index, was vorher gefehlt hat) und Reversal (Drawdown + HV-Cooling, was implizit in der Discover-Seite war).

### Working Philosophy

Aus `~/.claude/projects/-Users-tomschoen/memory/auto-dreaming-blueprint.md`: *"collision-with-reality over plausibility"*. Jede Hypothese muss gegen reale Daten kollidieren bevor sie als Signal akzeptiert wird. Backtests, IV-vs-realised-Tests, Greeks-vs-deck-Vergleiche sind Pflicht.

---

## 2. Projekt-Topologie

```
~/Desktop/VolScope/                       # einzig gültiger Pfad. NIEMALS iCloud-Mirror.
├── volscope/
│   ├── analytics/                        # alle Finanzmathematik, pure Funktionen
│   │   ├── black_scholes.py              # BSM mit Newton-Raphson IV-Solver + Bisection-Fallback
│   │   ├── historical_vol.py             # Yang-Zhang, Close-to-Close, Parkinson, Garman-Klass
│   │   ├── vol_metrics.py                # IV-Rank, IV-Percentile, IV/HV-Spread
│   │   ├── opportunity.py                # find_cheapest_vol, find_richest_premium, find_daily_outliers
│   │   ├── crowded_trades.py             # 4-Komponenten-Score (PCR-z, OI-z, Vol-z, Spread-z)
│   │   ├── data_quality.py               # composite quality (plausibility + freshness + completeness)
│   │   ├── data_validator.py             # 5 schema/value checks für daily_vol
│   │   ├── earnings_calendar.py          # ER-Window-Erkennung
│   │   ├── earnings_crush.py             # Pre/Post-Earnings IV-Drop-Verteilung
│   │   ├── earnings_watch.py             # 30-Tage-Forward-ER-Lookup
│   │   ├── edge_score.py                 # composite long-vol entry score (6 Komponenten)
│   │   ├── expected_move.py              # 1σ Move, percentile-basiert
│   │   ├── iv_smile.py                   # 25Δ-Skew, Term-Slope
│   │   ├── kelly_sizing.py               # Kelly-fraction Position Sizing
│   │   ├── megascan.py                   # Universe-Heatmap-Datenaggregation
│   │   ├── ml_signal.py                  # XGBoost-Buy-Probability (für Long-Vol invertiert)
│   │   ├── optionsschein_lookup.py       # WKN-basierte Suche (Trade Republic)
│   │   ├── portfolio_assistant.py        # Position-Empfehlungen
│   │   ├── portfolio_risk.py             # Portfolio-Greeks-Aggregation
│   │   ├── position_sizing.py            # generic
│   │   ├── scenario_analyzer.py          # alte Scenario-Engine (Pre-LEAPS-Lab)
│   │   ├── sector_rotation.py            # Sektor-Median-Vol + Z-Score
│   │   ├── signal.py                     # Top-Level-Signal-Komposition
│   │   ├── spread_analysis.py            # Bid/Ask-Spread-Quality
│   │   ├── strategy_backtest.py          # generic backtest framework
│   │   ├── strategy_calibration.py       # walk-forward calibration
│   │   ├── strategy_recommender.py       # Vol-State → Multi-Leg-Struktur-Mapping
│   │   ├── vol_cones.py                  # IV-Cones (percentile-bands über Term)
│   │   ├── cross_asset_hedge.py          # cross-asset basis trades
│   │   ├── daily_delta.py                # Day-over-Day Veränderungen
│   │   │
│   │   │   # ── LEAPS Lab v2 (2026-05-10) ─────────────────────────────
│   │   ├── leaps_convergence.py          # Scorer + suggest_leaps + auto_thesis
│   │   ├── leaps_sizing.py               # Budget→Kontrakte→$ Payoff-Ladder
│   │   ├── leaps_scenarios.py            # Spot×Time, Vega-Gain, Theta-Runway, Risk-Table
│   │   ├── leaps_pretrade.py             # Liquidity / ER / Quality + Order-Templates
│   │   ├── leaps_backtest.py             # Walk-Forward der Konvergenz-Regel
│   │   ├── leaps_pdf.py                  # reportlab dossier export
│   │   └── leaps_watchlist.py            # pin/unpin via user_settings
│   │
│   ├── data/
│   │   ├── database.py                   # VolScopeDB — DuckDB wrapper, Schema-Migrationen
│   │   ├── price_fetcher.py              # yfinance OHLCV ingest
│   │   ├── scraper.py                    # daily Yahoo options chain → daily_vol
│   │   ├── ticker_resolver.py            # On-demand-Ticker-Add (yahoo symbol → DB)
│   │   ├── ticker_universe.py            # 283 kuratierte Tickers + Sektor-Tagging
│   │   ├── earnings_fetcher.py           # earnings calendar ingest
│   │   ├── data_freshness.py             # AGE/STALE-Detection
│   │   └── seed_database.py              # initial bulk-load
│   │
│   ├── ui/
│   │   ├── app.py                        # Streamlit entry, _PAGE_REGISTRY mit lazy imports + error isolation
│   │   ├── components/
│   │   │   ├── sidebar.py                # NAV_GROUPS (Decisions/Research/Execution/Reference)
│   │   │   ├── chart_builders.py         # Plotly-Charts, dark theme
│   │   │   ├── error_boundary.py         # per-page Exception-Cards statt Crash
│   │   │   ├── auto_refresh.py           # st.cache_data wrappers
│   │   │   ├── cached_data.py            # bulk-history caching
│   │   │   ├── html_utils.py             # render_html helper (st.markdown unsafe_allow_html)
│   │   │   ├── keyboard_shortcuts.py     # j/k/Enter (rudimentär)
│   │   │   ├── metric_components.py      # _kpi_card etc.
│   │   │   └── navigation.py             # programmatic page switch
│   │   ├── styles/
│   │   │   └── theme.py                  # COLORS dict, JetBrains Mono / DM Sans, Plotly palette
│   │   └── views/
│   │       ├── onboarding_page.py        # First-run wizard
│   │       ├── command_center_page.py    # Tagesdashboard
│   │       ├── portfolio_page.py         # Positionen + Mark-to-Market
│   │       ├── megascan_page.py          # 280er-Heatmap
│   │       ├── discover_page.py          # 2×2 Cards: Cheapest/Richest/Movers/Crowded
│   │       ├── scope_page.py             # Single-Ticker IV-Chart (klassisch)
│   │       ├── scan_page.py              # Sortable screener
│   │       ├── heatmap_page.py           # Sektor-Heatmap
│   │       ├── rotation_page.py          # Sektor-Rotation (sector_daily-basiert, derzeit broken)
│   │       ├── flow_page.py              # Capital-Flow-View
│   │       ├── pretrade_page.py          # alte Pre-Trade-Page
│   │       ├── backtest_page.py          # generic backtest UI
│   │       ├── help_page.py              # Glossar
│   │       ├── leaps_page.py             # LEAPS Lab Index (cards + watchlist-strip)
│   │       └── leaps_dossier_page.py     # ★ NEU: Single-Ticker auto-PYPL-deck
│   │
│   ├── alerts/
│   │   └── alert_engine.py               # Rule-Eval, jetzt mit metric="convergence_score"
│   ├── config.py                         # DB_PATH, DEFAULT_TICKER, env overrides
│   └── utils/
│       ├── timing.py                     # @instrument decorator für perf-tracking
│       └── safe.py                       # safe_num, safe_str
│
├── scripts/
│   ├── seed_database.py                  # bulk-load
│   ├── daily_scrape.py                   # cron-fähig, 1.5s rate-limit
│   ├── compute_sector_rotation.py        # sector_daily-Aggregator (heute broken)
│   ├── compute_convergence_daily.py      # ★ NEU: Convergence-Scores in daily_vol schreiben
│   ├── run_leaps_backtest.py             # ★ NEU: Walk-forward CLI
│   ├── run_alerts.py                     # alert evaluation cron
│   ├── run_validation.py                 # data quality cron
│   ├── run_strategy_simulation.py        # backtest cron
│   ├── verify.py                         # runtime smoke (process-group teardown)
│   ├── audit_design_drift.py             # design-doc consistency check
│   ├── load_universe.py                  # 280-ticker bulk-load
│   ├── maturity_check.py                 # codebase maturity score
│   ├── loop_iteration.py                 # ralph-loop pick/finalize
│   ├── run_audits.py                     # 4-agent audit emitter
│   ├── fix_seed_spread.py                # one-off legacy fix
│   ├── sector_aggregate.py               # sector-level aggregator
│   └── autonomous/                       # launchd job definitions (5 daily + 3 weekly)
│
├── tests/                                # 79 test files, 1300+ tests
│   ├── test_leaps_convergence.py         # 15 tests
│   ├── test_leaps_sizing.py              # 10 tests   ★ NEU
│   ├── test_leaps_scenarios.py           # 10 tests   ★ NEU
│   ├── test_leaps_pretrade.py            # 10 tests   ★ NEU
│   ├── test_leaps_backtest.py            # 5 tests    ★ NEU
│   ├── test_leaps_pdf.py                 # 3 tests    ★ NEU
│   ├── test_leaps_watchlist.py           # 8 tests    ★ NEU
│   ├── test_leaps_dossier_smoke.py       # 5 tests    ★ NEU
│   └── … (übrige 71 Test-Dateien)
│
├── data/
│   ├── volscope.db                       # ALT — von April, eingefroren, NICHT verwenden
│   ├── audit/                            # 4-agent audit outputs
│   ├── backtest/                         # backtest results
│   ├── perf/                             # perf-instrumentation logs
│   ├── maturity_history.jsonl            # codebase maturity score over time
│   ├── maturity_latest.json
│   └── maturity_latest.md
│
├── Makefile                              # ~30 Targets — siehe §6
├── README.md
├── CLAUDE.md                             # Developer guide (read first)
├── PROMPT.md                             # original product spec (Bloomberg-meets-Apple)
├── progress.json                         # 35 P0-P5 task status, T36+ ralph-loop iteration
├── requirements.txt                      # +reportlab>=4.0.0
├── Dockerfile                            # rarely used
├── LEAPS_LAB_HANDOFF.md                  # ★ NEU: Phasen-Mapping
├── VOLSCOPE_AGENT_HANDOFF.md             # ★ DIESES Dokument
└── .venv/                                # Python 3.13 venv

# Außerhalb des Projektordners aber projekt-relevant:
~/Library/Application Support/VolScope/volscope.db    # ★ ECHTE DB (283 tickers, 125 991 rows)
~/.claude/plans/                                       # Mehrere produkt-pläne
~/.claude/projects/-Users-tomschoen/memory/            # Persistente Memory (über Sessions)
```

---

## 3. Daten-Layer

### Wo die DB liegt
**Echte Production-DB:** `~/Library/Application Support/VolScope/volscope.db`
**NICHT** `~/Desktop/VolScope/data/volscope.db` (alte Datei vom April, eingefroren).

Grund: macOS File Provider hält Schreibhandles auf Dateien unter Desktop und kollidiert mit DuckDBs Exclusive-Lock. `volscope/config.py` setzt `DB_PATH` auf den Application-Support-Pfad. Override via `VOLSCOPE_DATA_DIR`.

### Schema (Stand 2026-05-10)

| Tabelle | Zeilen | Stand |
|---|---:|---|
| `daily_vol` | 125 991 | frisch (heute), 283 Ticker |
| `earnings` | 242 | aktuell, treibt ER-Blackout-Chip |
| `options_snapshots` | **0** | **LEER** — kritische Daten-Lücke |
| `sector_daily` | **0** | **LEER** — Aggregator-Bug, fixierbar |
| `positions` | live | reiches Schema (option_type, strike, expiry, instrument_type, contracts, entry_premium, wkn, issuer) |
| `alert_rules` | live | generic (ticker, metric, operator, threshold, channel, label, enabled) |
| `alert_log` | live | fired alerts, audit-trail |
| `validation_log` | live | Datenqualitäts-Reports |
| `user_settings` | live | KV-store, jetzt auch `leaps.watchlist` |

### `daily_vol` Schema (24 Spalten nach 2026-05-10-Migration)

```
ticker VARCHAR PRIMARY KEY
date DATE PRIMARY KEY
spot_price DOUBLE
iv_30d, iv_60d, iv_90d, iv_180d DOUBLE
iv_skew_25d DOUBLE
hv_20d, hv_60d, hv_yz_20d DOUBLE
iv_rank, iv_percentile DOUBLE
iv_hv_spread DOUBLE
put_call_ratio DOUBLE
total_call_volume, total_put_volume, total_open_interest BIGINT
sector, company_name VARCHAR
convergence_score, convergence_mispricing,
convergence_neglect, convergence_reversal DOUBLE         ← NEU
```

### Daten-Lücken die ein neuer Agent angehen sollte

1. **`options_snapshots` leer.** Heute werden alle LEAPS-Premiums als BSM-Modellpreis gerendert. Mit `EST · BSM`-Chip explizit markiert. Live-Bid/Ask via `yfinance.option_chain` mit Retry+Cache+Sentinel ist Phase 0.1 des LEAPS-Lab-Plans.

2. **`sector_daily` leer.** `scripts/compute_sector_rotation.py` existiert aber failt silent. Rotation-Page läuft auf Leerlauf. Phase-0.2-Fix: E2E-Test der nicht-leere Rows nach fresh-aggregate behauptet.

3. **`earnings` decken nicht alle 283 Ticker.** 242 Rows sind eher 60-80 unique Ticker × mehrere Quartale.

---

## 4. Das LEAPS Lab — Produkt-Hero

### User-Journey (90-Sekunden-Test)

```
T+0s   Lab geöffnet → ranked cards visible
T+10s  "◈ NKE Konvergenz 69 [MIS 67 NEG 95 REV 34]" gelesen
T+15s  "Open dossier →" geklickt
T+30s  Auto-These überflogen
T+45s  Sizing-Slider: $300 → 1 Kontrakt, max loss $300
T+60s  Vega-Reversion-Tabelle gecheckt
T+75s  "🔔 Add convergence alert" geklickt
T+90s  "Generate PDF" → druckbares Dossier
```

### Dossier-IA (Trader-First, NICHT Analyst-First)

Reihenfolge:
1. **Header** (Score-Dial, Coverage-Chip wenn <3 Signale, ehrliche Auto-These)
2. **Sizing** ("ist das meine Größe?")
3. **Risk** ("was verliere ich maximal, wo bricht die These?")
4. **Instrument** (Strike/Expiry/Greeks)
5. *Collapsed by default:* Anomaly read · Scenarios · Execution checklist
6. **Export-Sektion** (PDF-Button)

Dieser Plan-Agent-Driven Switch (Sizing vor Anomaly) ist der wichtigste UX-Insight der Session: Trader scannen nicht wie Analysten. Erste Frage: "ist das überhaupt mein Trade?"

### Neue Analytics-Module (LEAPS Lab v2)

#### `volscope/analytics/leaps_convergence.py`
- `compute_mispricing_score(row)` — IV/HV + IV-Rank + IV-Percentile, equal weight
- `compute_neglect_score(hist, benchmark, lookback=252)` — TTM-Relative-Strength-Gap vs SPY
- `compute_reversal_score(hist)` — Drawdown vom 52w-Hoch + HV-20d/60d-Cooling
- `compute_convergence(row, hist, benchmark)` → `ConvergenceResult(score, components, drivers, coverage, one_liner)`
- **`coverage`-Feld + `all_signals_aligned()`-Methode** — Prosa darf NUR "alle drei aligned" claimen wenn alle drei Komponenten ≥ 60.
- **`auto_thesis(result, row, ticker_history, benchmark_history)`** — generiert die 1-Satz-These ehrlich aus `drivers` + den raw IV/HV/Drawdown-Werten, nicht aus statischer Vorlage. Hängt eine Coverage-Tail an wenn <3 Komponenten.
- `suggest_leaps(ticker, spot, iv, target_dte_days=730, strike_uplift=0.75, ...)` → `LeapsSuggestion` mit Strike (round whole-dollar bei +75 % Uplift), Expiry, BSM-Premium, Greeks (Δ Γ Θ ν), Payoff-Ladder anchored on Wave-III Milestones, Rationale-String.
- `rank_universe(latest, histories, benchmark, n)` — top-N convergence-DataFrame mit Sub-Components.

#### `volscope/analytics/leaps_sizing.py`
- `SizingPlan` (Dataclass mit budget, contracts, capital_deployed, capital_residual, max_loss, breakeven_spot, payoff: list[DollarPayoff], rationale)
- `SIZING_RULES`: 6 vordefinierte (`Fixed $300/$1k/$3k`, `2/5/10 % of book`)
- `size_position(suggestion, budget, contract_size=100)` — IMMER abrunden, residual ausweisen
- `lift_to_next_contract_cost(plan, suggestion)` — UI-Hint "$42 short of 4 contracts"

#### `volscope/analytics/leaps_scenarios.py`
- `build_scenario_matrix(suggestion, iv_assumed=None, spot_multipliers=(.7, 1.0, 1.3, 1.7, 2.0, 2.5, 3.3), month_horizons=(1, 6, 12, 24))` — P&L pro Kontrakt für jede Spot×Time-Kombi unter konstantem σ (oder reverted σ)
- `build_vega_gain_table(suggestion, targets=(.20, .30, .40, .50, .60, .80))` — wenn IV heute reverted, Spot unverändert: $-Gewinn pro Kontrakt
- `build_theta_runway(suggestion)` — monatliches Theta von Entry bis Expiry, **Cliff-Detection** (erstes Monat wo |theta| ≥ 2× entry-rate)
- `build_risk_table(suggestion, capital_deployed, invalidation_pct_below_spot=0.20)` — Max-Loss + Invalidation-Spot + 3-stufige Scaling-In-Rungs (-15 %, -25 %, -35 %)

#### `volscope/analytics/leaps_pretrade.py`
- `evaluate_liquidity(suggestion, chain_row, underlying_row)` — Spread/OI/Volume-Read; **Sektor-Fallback** wenn `chain_row` None ist (heute: immer der Fall) basierend auf `total_open_interest`-Proxy
- `evaluate_earnings_blackout(suggestion, next_earnings_date, blackout_days=7)` — Post-ER ist INFO ("IV-crush window open"), Pre-ER innerhalb 7d ist AMBER, >120d ist GREEN
- `evaluate_data_quality(underlying_row, history)` — wraps `data_quality.composite_quality`
- `build_order_templates(suggestion, contracts)` — Strings für IBKR / Tastyworks / Trade Republic (WKN-Suchhinweis)
- `run_pretrade_checks(...)` → `PretradeChecklist(rows, order_templates, blocked: bool)`

#### `volscope/analytics/leaps_backtest.py`
- `run_backtest(panel, benchmark_panel, horizon_days=365, threshold=65, sample_every_n_days=21, ...)` — walk-forward: jeder N-te Tag scoren, bei score≥threshold deep-OTM-Call zum BSM-Modellpreis kaufen, halten bis horizon, repricen mit echter realisierter spot+exit-iv
- **Survivorship-Bias-Guard:** Wenn der Panel vor dem Horizon endet, wird `forced_exit=True` markiert — delisted Names werden nicht silent zum Win
- `Trade` Dataclass + `BacktestResult` mit win_rate, percentiles, by_year-Aggregation
- `summarise(result)` — 1-Zeile-String

#### `volscope/analytics/leaps_pdf.py`
- `render_dossier_pdf(...)` → bytes (für `st.download_button`)
- Strukturmirror des PYPL-Decks: Title, Anomaly-Tabelle, Instrument-Greeks, Sizing+Payoff, Risk+Scaling, Vega-Gain, Pre-Trade-Checklist, Order-Templates, Glossar, Footer (mit Score+Datum für Re-Run-Vergleich)
- `filename_for(suggestion)` → `LEAPS_PYPL_79_2028-05-09.pdf`
- reportlab-basiert (kein System-Dep)

#### `volscope/analytics/leaps_watchlist.py`
- JSON-Blob-Persistenz im `user_settings`-KV-Store unter Key `leaps.watchlist`
- `pin_to_watchlist(db, ticker)` / `unpin_from_watchlist(db, ticker)` / `load_watchlist(db)` / `is_pinned(db, ticker)`
- Re-pinning eines existierenden Tickers refreshed `pinned_at` (float-to-top)
- Korruptions-resilient (invalid JSON → empty list, malformed entries skipped)

### UI-Pages

#### `volscope/ui/views/leaps_page.py` (LEAPS Lab Index)
- Hero-Header + Watchlist-Strip (Top-6 pinned tickers als Buttons, NULL wenn keine)
- "Actionable Convergence" Section: Cards mit Score-Border, Sub-Score-Pills, Sektor-Chip, "CONVERGENCE"-Badge
- Pro Card: **"Open dossier →"-Button** (sets session_state, switches active_page, reruns) + collapsed Payoff-Ladder
- "Watchlist" Section (für Names unter Threshold)
- Erklärungs-Expander am Footer

#### `volscope/ui/views/leaps_dossier_page.py` (NEU)
- Top-Picker (Selectbox aus latest tickers + Custom-Input-Fallback) + Book-Value-Input für %-of-book Sizing
- Quick-Actions-Row: ☆ Pin / ★ Unpin · 🔔 Add convergence alert
- Sektionen wie oben (Header → Sizing → Risk → Instrument → expanders → PDF-Export)
- Jeder BSM-Preis hat den `EST · BSM`-Chip
- `_est_chip()` zentral definiert

### Wiring

`volscope/ui/app.py`:
```python
_PAGE_REGISTRY = {
    ...
    "Pre-Trade":  ("volscope.ui.views.pretrade_page",       "render_pretrade_page"),
    "LEAPS Lab":  ("volscope.ui.views.leaps_page",          "render_leaps_page"),
    "Dossier":    ("volscope.ui.views.leaps_dossier_page",  "render_leaps_dossier_page"),  ★
    "Backtest":   ("volscope.ui.views.backtest_page",       "render_backtest_page"),
    ...
}
```

`volscope/ui/components/sidebar.py`:
```python
("▷ EXECUTION", ["Pre-Trade", "LEAPS Lab", "Dossier", "Backtest"]),
```

### Alert-Engine-Erweiterung

`volscope/alerts/alert_engine.py:compute_metric_value()` versteht jetzt `metric="convergence_score"` — liest die vorberechnete Spalte aus `daily_vol`. Damit funktionieren Convergence-Alerts ohne weitere Engine-Änderung; das bestehende `scripts/run_alerts.py` Cron evaluiert sie gegen den nightly score-update.

---

## 5. Andere Pages und ältere Module

| Page | Was sie macht |
|---|---|
| **Onboarding** | First-run wizard wenn DB leer / Flag fehlt |
| **Command Center** | Tagesdashboard mit Top-KPIs (Edge Score, Mover, Crowded) |
| **Portfolio** | Eigene Positionen, MtM, Greeks-Aggregation |
| **Mega-Scan** | 280-Ticker-Heatmap mit IV-Percentile-Coloring |
| **Discover** | 2×2 Cards: Cheapest-Vol / Richest-Premium / Movers / Crowded — der "PayPal-Moment-Catcher" |
| **Scope** | Single-Ticker-IV-Chart (klassische Discover-Tiefe) |
| **Scanner** | Sortable Screener mit ProgressColumn-Bars |
| **Heatmap** | Sektor-Heatmap |
| **Rotation** | Sektor-Rotation mit Regime-Klassifikation (broken bis sector_daily Aggregator fixiert ist) |
| **Flow** | Capital-Flow-View, Smart-Money-Flow |
| **Pre-Trade** | ältere Pre-Trade-Page (vor LEAPS Lab) |
| **LEAPS Lab** | Konvergenz-Index (NEU, oben dokumentiert) |
| **Dossier** | Single-Ticker auto-PYPL-deck (NEU) |
| **Backtest** | generic backtest UI |
| **Help** | Glossar |

### Wichtige ältere Analytics

- `edge_score.py` — composite long-vol entry score mit 6 Komponenten (iv_perc 30, vrp 20, rank 15, ml 15, regime 10, flow 10). Long-vol convention (high score = good entry to BUY vol).
- `ml_signal.py` — XGBoost predicting P(IV falls in 10d). **Direction-asymmetry critical**: für long-vol entries muss `ml_buy_prob` invertiert werden, sonst zeigt die Heatmap genau die falschen Names. Siehe Memory `volscope-ml-direction.md`.
- `crowded_trades.py` — 4-Komponenten-Score 0-100 mit Bands (calm <25, normal 25-59, elevated 60-79, crowded ≥80). Symmetrisch um 50 = neutral.
- `data_quality.py` — `composite_quality(row, history)` → CompositeQuality mit overall_level (OK/WARN/SUSPECT/STALE/PARTIAL) + `one_liner`. Wird in fast allen Pages für STALE/SUSPECT-Chips verwendet.
- `strategy_recommender.py` — Vol-State → Multi-Leg-Struktur-Mapping. Pure rules, keine ML.

---

## 6. Workflows

### Makefile-Targets (~30, hier die wichtigsten)

```bash
# ── Tägliches ─────────────────────────────────────────────
make start            # check DB-Frische → ggf. scrape → run
make scrape           # daily_scrape.py + automatisch make convergence
make convergence      # NEU: compute_convergence_daily.py, idempotent
make run              # gehärtet: --headless, --browser.gatherUsageStats false, </dev/null
make verify           # runtime smoke (process-group teardown)

# ── Tests ────────────────────────────────────────────────
make test             # pytest tests/ -v --tb=short
pytest tests/test_leaps_*.py -q     # nur LEAPS-Suites (~1 sek)

# ── Backtest ─────────────────────────────────────────────
make backtest-leaps   # NEU: walk-forward CLI
python scripts/run_leaps_backtest.py --horizon-days 180 --threshold 70 --json /tmp/bt.json

# ── Audit Loop (ralph-loop / 4-agent) ───────────────────
make audit            # 4 prompt templates emittieren
make synth            # re-rank queue
make maturity         # codebase score
make loop-forever     # outer while-loop, stops at score ≥ 95 oder pause-marker
make pause / make unpause

# ── Universe ─────────────────────────────────────────────
make seed-starter     # 8 Tickers (SPY QQQ AAPL NVDA TSLA META GLD TLT)
make seed-full        # 280+ kuratierte Tickers
make load-universe    # bulk-load mit resume support

# ── Validation / Simulation ─────────────────────────────
make simulate         # run_strategy_simulation.py
make validate         # run_validation.py (data quality)

# ── Autonomy (cron) ─────────────────────────────────────
make autonomy-status / pause / unpause / test / logs
```

### Streamlit-Start-Ritual

**Niemals** `streamlit run` ohne diese Flags:
```bash
streamlit run volscope/ui/app.py \
    --server.headless true \
    --browser.gatherUsageStats false \
    </dev/null
```

`make run` setzt das automatisch. Wenn man's manuell startet ohne `</dev/null`, blockiert Streamlit auf stdin (E-Mail-Prompt) — der "stille Hang" der frühen Sessions.

### Cron-Jobs (launchd, macOS)

5 daily + 3 weekly autonomous improvement loops aus `scripts/autonomous/`. Memory-File `volscope-cron-roster.md` listet sie. Sie laufen cross-session, brauchen keinen aktiven Claude Code. Reaktivierbar pro Session via Memory-File.

### Maturity-Loop

Selbsterhaltender audit + improve cycle (siehe `volscope-loop.md`). 4 audit-agents emittieren JSON-Reports, `loop_iteration.py` synthesisiert eine Priority-Queue, der Implementer (Claude) edited Code, Verify+Maturity-Score-Gate, Iteration. Stoppt bei Score ≥ 95.

---

## 7. Konventionen

### Code-Style (aus CLAUDE.md)
- Type hints überall
- Docstrings auf jeder public function
- Tests vor Implementation (TDD)
- Alle Finanz-Berechnungen gegen analytisch korrekte Werte validiert
- Edge cases: `return None`, nie crashen
- Keine Comments wenn der Code selbsterklärend ist; WHY only, nicht WHAT

### Schema-Migrationen
DuckDB unterstützt `ALTER TABLE ... ADD COLUMN IF NOT EXISTS`. `VolScopeDB._create_tables()` ist die zentrale Schema-Definition + Backfill-Liste. Neue Spalten werden dort hinzugefügt; existierende DBs bekommen sie beim nächsten `VolScopeDB()`-Init via try/except-ALTER.

**Wichtig:** Scripts die DuckDB direkt via `duckdb.connect(path)` öffnen (statt via `VolScopeDB`) **triggern keine Migration**. Daher: scripts für daily-jobs sollten `VolScopeDB()` oder zumindest einmal `VolScopeDB(path).close()` aufrufen vor dem Eigentlichen.

### Test-Strategie
- pytest, kein Pytest-Plugin außer pytest-cov
- Pure-Analytics: 100 % branch coverage angestrebt
- DB/Repos: temp-DuckDB pro Test (siehe `test_leaps_watchlist.py` für Pattern)
- UI: Streamlit headless smoke (curl 200, no error cards) + module-level import smokes
- Property tests wo sinnvoll (nicht überall — meist deterministische References)

### Frontend-Konventionen
- **Theme** in `volscope/ui/styles/theme.py` — niemals inline-color
- **JetBrains Mono** für Zahlen (tabular-nums), **DM Sans** für Prose
- **Plotly graph_objects** (NICHT plotly.express)
- **Cards** mit left-border-Accent (4px, semantisch farbig)
- **Tables** mit JetBrains Mono + tabular-nums + RIGHT-align für Numerics
- **Hover** lifts mit shadow im accent-color
- **Render** ausschließlich via `render_html(st, html_string)` Helper, der `st.markdown(..., unsafe_allow_html=True)` macht — niemals direkt

---

## 8. Known Issues / Quirks / Caveats

### 1. DuckDB 1.5.2 SELECT *-Bug
**Symptom:** `SELECT * FROM daily_vol WHERE date = '2026-05-10'` → 0 Rows. Aber `SELECT COUNT(*) FROM daily_vol WHERE date = '2026-05-10'` → 101.

**Workaround:** `BETWEEN`. Reproduziert mit `c.execute("SELECT * FROM daily_vol WHERE date BETWEEN '2026-05-10' AND '2026-05-10'")` → 101 Rows.

Dokumentiert in `scripts/compute_convergence_daily.py`. Wer SQL kopiert, denkt dran.

### 2. options_snapshots leer
**Konsequenz:** alle LEAPS-Premiums sind BSM-Modellpreise. Live-Bid/Ask kann ±20-50 % abweichen. Jede UI-Zahl hat den `EST · BSM`-Chip.

**Fix:** Phase 0.1 — `daily_scrape.py --with-chains` mit yfinance `option_chain` für Expiries (60d, 1100d), Retry+Cache+Sentinel.

### 3. sector_daily leer
**Konsequenz:** Rotation-Page rendert leer. Sektor-Median-Vol-Read funktioniert nicht.

**Fix:** Phase 0.2 — `compute_sector_rotation.py` debuggen (failt silent), E2E-Test schreiben der nicht-leere Rows nach fresh-aggregate behauptet.

### 4. iCloud File Provider auf Desktop
**Symptom:** Slow filesystem reads (5-min full pytest cold start), occasional DuckDB lock collisions.

**Workaround:** DB ist in `~/Library/Application Support/VolScope/` (außerhalb Desktop). Tests laufen halt langsam beim ersten Import — ist nicht zu fixen ohne den Projekt-Pfad zu verschieben.

### 5. Streamlit-stdin-Block
**Symptom:** `streamlit run volscope/ui/app.py` ohne Flags hängt silent (E-Mail-Prompt).

**Workaround:** `make run` setzt `--server.headless true --browser.gatherUsageStats false </dev/null`.

### 6. ML-Signal Direction-Asymmetry
**Symptom:** ML-Buy-Probability-Heatmap zeigt scheinbar "richtige" Names oben — aber für Long-Vol-Entries braucht man die *invertierte* Probability.

**Doku:** `volscope-ml-direction.md` Memory-File. `edge_score.py` hat den Inversion bereits eingebaut.

### 7. Synthetic-Backtest oversized
**Symptom:** Backtest auf der Live-DB findet nur 2 Trades auf 30-Ticker × 6-Monate, weil Universum erst kürzlich gewachsen + Threshold 65 absichtlich hoch.

**Note:** Synthetisches Test-Universum in `tests/test_leaps_backtest.py` (`_build_synthetic_universe`) baut explizite plateau→crash→base→rally Pfade um Pipeline-Mechanik zu prüfen. Bei production-DB: niedrigerer Threshold (50?) oder mehr Sample-Days nehmen.

---

## 9. Der Plan (8 Phasen) — Status

Vollständiger Plan in `~/.claude/plans/volscope-leaps-lab-product-plan.md`.

| Phase | Goal | Status |
|---|---|---|
| 0 | Data foundations (chain ingest, sector_daily) | **partial** — chain ingest deferred (rate-limit-Risk in autonomous-run); sector_daily noch broken |
| 1 | Single-ticker Dossier | ✅ **shipped** |
| 2 | Sizing + Scenarios | ✅ **shipped** |
| 3 | Pre-trade Checklist | ✅ **shipped** (sector-rule liquidity fallback aktiv) |
| 4 | Convergence alerts + tracker | ✅ **shipped (alerts)**; Position-tracker mit Score-Trajektorie offen |
| 5 | Walk-forward backtest | ✅ **shipped** |
| 6 | Watchlist + onboarding | ✅ **shipped (watchlist)**; Onboarding-Tour offen |
| 7 | PDF export | ✅ **shipped** |
| 8 | Polish | **partial** — EST·BSM-chips, error boundaries, expander UX, A11y noch offen |

**6 von 8 Phasen vollständig shipped. 2 partial mit klarer Continuation-Pfad.**

### Nicht-Ziele (bewusst ausgelassen)
- Live-Broker-Integration (out of scope; user klickt selbst durch zu IBKR)
- Multi-Leg-Strukturen (Spreads, Butterflies) — Lab v2 Konversation
- Day-Trading / 0DTE — LEAPS-Lab-Horizont ist 12-32 Monate

---

## 10. Offene Ideen / Brainstorm

Hier roh, ohne Priorisierung — der nächste Agent wählt was Sinn macht.

### Daten-Foundation
1. **Live-Chain-Ingest** für Top-50-by-Score: yfinance.option_chain mit Retry+Cache+Sentinel. Phase 0.1.
2. **Survivorship-bias-freies Backtest-Universum** — delisted Names (Bed Bath, SVB) inklusive. Phase 5.4.
3. **`data_freshness` View** — pro-Ticker latest-scrape-ts, surfaces STALE-Chip in Dossier-Header.
4. **Sektor-Aggregator-Fix** — `compute_sector_rotation.py` debuggen.
5. **Earnings-Calendar-Erweiterung** — alle 283 Ticker, nicht nur die Top-Liquid.

### Konvergenz-Schärfung
6. **Score-Trajektorie pro Ticker** — letzte 90 Tage Score-Verlauf, anchored to entry-date wenn user owns it.
7. **Cross-Ticker-Korrelation** — wenn 5 Names gleichzeitig konvergieren, sind sie wahrscheinlich nicht orthogonal (z.B. alle Cyber-Aktien). Add Diversifikations-Penalty.
8. **Sektor-Konvergenz-Map** — welche Sektoren häufen Konvergenz? Wenn Healthcare-Sektor 12 von 25 Names mit Score≥65 hat, ist das ein Sektor-Trade, nicht 12 Single-Names.
9. **Regime-Cluster** — k-means auf (rank, percentile, drawdown, RS-gap) — welche Cluster historisch best performed?
10. **Adaptive Threshold** — statt fixer 65, percentile-based (top 5 % der 30-Day-Composite-Verteilung).

### UI / UX
11. **Score-Trajektorie-Chart in Dossier** (Phase 4 partial finishen)
12. **Onboarding-Tour** — 4-Step-Modal mit PYPL-Deck als kanonischem Beispiel + "schau dir heute NKE/UNH an"-Callout
13. **Keyboard-Shortcuts** auf Dossier: j/k zwischen actionable, Enter zum öffnen, s = sizing-slider focus, a = arm-alert
14. **Glossary-Side-Drawer** — ausziehbare Helper-Drawer von jedem Greek-Tooltip
15. **Convergence-Heatmap** — 280-Ticker-Grid coloriert nach Score, sortable nach Sub-Komponente
16. **Animated Convergence-Dial** — 300ms fill-in beim ersten Render
17. **Empty-State-Polish** — jede Sektion mit Fallback-Copy ("no chain data → estimate shown · run `make scrape-chains`")
18. **A11y** — keyboard-only walk passes axe-core, color-contrast WCAG AA

### Operationelles
19. **Alert-Templates pro Dossier** — "convergence opens", "convergence breaks", "vega tailwind", "spot target", "invalidation"
20. **Position-Tracker mit MTM** — `positions` mit live chain (oder BSM fallback) bewerten, Score-Trajektorie seit Entry
21. **Watchlist-Nightly-Rescan** — cron-Job der pro pinned ticker delta_score_7d + delta_score_30d aufzeichnet
22. **PDF-Auto-Generation** für Top-3-Daily ins `data/dossiers/`-Verzeichnis (gut für Tagesjournal)
23. **Slack/Discord-Webhook** für Alerts (channel-Erweiterung des AlertEngine)
24. **Hold-Period-Optimization** — Backtest verschiedene Holds, finde sweet-spot per Score-Bucket

### Methodisch / Forschung
25. **Goyal-Saretto-Replication** — der Long-Options-Position-Effekt von 2009. Macht das Konvergenz-Signal robuster.
26. **VRP-Term-Structure** — IV-30d/HV-20d vs IV-180d/HV-60d — flatte Term-Structure ist anders zu spielen als steile.
27. **Earnings-IV-Crush-Estimator** — pro Ticker pre-/post-earnings IV-Drop-Verteilung, in `earnings_crush.py` halb da
28. **Volatility-Surface-Reconstruction** — wenn `options_snapshots` voll ist, ganze Smile rekonstruieren (Term × Skew)
29. **Cross-Asset-Hedge-Engine** — `cross_asset_hedge.py` halb da, könnte Konvergenz-Trades absichern

### Multi-Agent / Workflow
30. **Worktree-Parallel-Builds** für unabhängige Features (siehe `OPTIMALER-WORKFLOW.rtf`). Z.B. Phase 0 (Data) + Phase 4 (Position-Tracker) parallel weil disjunkte Files.
31. **Code-Reviewer-Subagent** der nach jedem ralph-loop iteration das Diff reviewt
32. **PRD-Agent** der vor jeder neuen Phase ein Mini-PRD schreibt mit "what we won't build"

---

## 11. Erste Schritte für einen neuen Agent

Wenn du gerade in dieses Projekt einsteigst, hier dein 30-Minuten-Onboarding:

```bash
# 1. Position bestätigen
cd ~/Desktop/VolScope
ls

# 2. Pflicht-Lektüre (in dieser Reihenfolge)
cat CLAUDE.md                       # 5 min — Architektur + Konventionen
cat VOLSCOPE_AGENT_HANDOFF.md       # dieses Dokument
cat LEAPS_LAB_HANDOFF.md            # 3 min — was die letzte Session shipped hat
cat ~/.claude/plans/volscope-leaps-lab-product-plan.md   # 10 min — der 8-Phasen-Plan

# 3. Memory durchschauen
ls ~/.claude/projects/-Users-tomschoen/memory/
# Wichtige: volscope-project.md, volscope-leaps-lab.md, volscope-ml-direction.md,
#           volscope-vision.md, auto-dreaming-blueprint.md

# 4. State verifizieren
source .venv/bin/activate
python -c "from volscope.config import DB_PATH; import duckdb; \
  c = duckdb.connect(str(DB_PATH)); \
  print('latest:', c.execute('SELECT MAX(date), COUNT(*) FROM daily_vol').fetchone())"

# 5. Tests grün
python -m pytest tests/test_leaps_*.py -q

# 6. App bootbar
make run    # Browser → localhost:8501 → check LEAPS Lab + Dossier
# Strg-C wenn fertig

# 7. Status-Check
make verify
```

### Was als nächstes Sinn macht (priorisiert)

**P1 — Hochwertig & feasibel in <2h:**
- Live-Chain-Ingest (Phase 0.1) — schaltet die Liquidity-Gate von AMBER auf hart, höchster UX-Lift
- sector_daily-Aggregator-Fix (Phase 0.2) — entriegelt Rotation-Page

**P2 — Hochwertig, mehr Aufwand:**
- Survivorship-bias-freies Backtest-Universum (Phase 5.4) — macht Backtest-Claims belastbar
- Position-Tracker mit Score-Trajektorie (Phase 4 finishen)

**P3 — Nice-to-have:**
- Onboarding-Tour, Keyboard-Shortcuts, A11y (Phase 8 Polish)
- Score-Trajektorie-Chart in Dossier
- Multi-Leg-Lab v2 (eigenes Konversations-Thema)

### Was du NICHT machen sollst ohne expliziten User-Auftrag

- Live-Broker-Integration (out of scope per Plan)
- Multi-Leg-Strukturen (out of scope per Plan v1)
- Schema-Refactors die existierende daily_vol-Spalten umbenennen/löschen (würde 100k+ Rows brechen)
- Den iCloud-mirror-Pfad benutzen
- yfinance ohne rate-limiting hammern (1.5s Delay zwischen Tickers ist Convention)
- Yahoo's `impliedVolatility` Spalte statt eigenem BSM-Solver verwenden — Memory `volscope-project.md` ist explizit
- Tests unter dem Vorwand "ist eh schwer testbar" auslassen

---

## 12. Reference: File Inventory (was-ist-wo-Quick-Lookup)

### Volscope-spezifische Dokumente
| Datei | Zweck |
|---|---|
| `CLAUDE.md` | Developer guide — first read |
| `README.md` | Public-facing intro |
| `PROMPT.md` | Original Bloomberg-meets-Apple Spec |
| `LEAPS_LAB_HANDOFF.md` | Letzte Session: was shipped, Phasen-Map |
| `VOLSCOPE_AGENT_HANDOFF.md` | **Dieses Dokument** |
| `progress.json` | T01-T35 + ralph-loop-Iterationen Status |

### Plans (außerhalb Repo)
| Datei | Zweck |
|---|---|
| `~/.claude/plans/volscope-roadmap.md` | High-level roadmap |
| `~/.claude/plans/volscope-giga-master-plan.md` | 5-Pillar-Build-Plan (executed 2026-05-03) |
| `~/.claude/plans/volscope-design-plan.md` | Design-System-Plan |
| `~/.claude/plans/volscope-leaps-lab-product-plan.md` | **8-Phasen-Plan für LEAPS Lab v2** |
| `~/.claude/plans/volscope-loop-protocol.md` | Maturity-Loop-Protokoll |
| `~/.claude/plans/beginne-nun-mit-dem-cheeky-noodle.md` | Maturity-Loop-Setup-Doc |

### Memory (außerhalb Repo, persistent über Sessions)
| Datei | Zweck |
|---|---|
| `volscope-project.md` | Pfad, Crons, do/dont's |
| `volscope-vision.md` | Die ONE Frage + 4 Signale |
| `volscope-giga-plan.md` | Sector-Rotation + Capital-Flow + ML + Backtest |
| `auto-dreaming-blueprint.md` | "collision-with-reality"-Philosophie |
| `volscope-ml-direction.md` | ML-Signal-Direction-Asymmetry |
| `volscope-loop.md` | Maturity-Loop-Design |
| `volscope-cron-roster.md` | 5 daily + 3 weekly launchd jobs |
| `volscope-leaps-lab.md` | LEAPS-Lab-Kanon + PYPL-Deck-Anchor |
| `MEMORY.md` | Index aller obigen |

---

## Closing thoughts

VolScope ist heute kein "Scanner mit ein paar UI-Goodies" mehr. Mit dem LEAPS Lab v2 ist es ein durchgängiger Workflow von **anomaly-detection** bis **printable trade dossier** — das einzige Stück das fehlt um vor einer Trade-Entscheidung den Browser zu verlassen ist der Klick zum Broker.

Die wichtigste Stilrichtung die ich beibehalten würde:
- **Ehrliche Prosa.** Coverage-Felder, EST-Chips, "based on 2 of 3"-Tails. Trader-Tools die overclaim verlieren Vertrauen schneller als sie es aufbauen.
- **Trader-IA, nicht Analyst-IA.** Sizing vor Anomaly. "Was verliere ich?" vor "Wie funktioniert es?"
- **Konvergenz, nicht Single-Signal.** Die 1-2-mal-pro-Jahr-Frequenz ist das Feature, nicht der Bug. Ein Tool das täglich 50 "Opportunitäten" wirft trainiert seine User zur Numbness.
- **Pure Analytics + dünner UI.** Jedes neue Feature *erst* als pure Funktion mit Tests, *dann* als UI. Macht Backtests, Cron-Jobs und PDF-Export trivial.

Die wichtigste mentale Vorsicht für den nächsten Agent: **`options_snapshots` ist leer**. Solange das so ist, sind alle Premiums Modellpreise. Wenn jemand das übersieht und einen Algorithmus auf den Live-Werten trainiert, baut er auf Sand. Phase 0.1 — Chain-Ingest — ist deshalb die höchste Priorität nach diesem Doc.

Viel Erfolg.
