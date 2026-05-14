> Status: ARCHIVED
> This document captures a past planning session. It is preserved
> for historical context — current state lives in /memory/roadmaps/ + /ROADMAP.md.

═══════════════════════════════════════════════════════════════════════
VOLSCOPE — DREAM PROTOCOL
═══════════════════════════════════════════════════════════════════════

You are dreaming. This is not a task list. This is a vision.

Before you write a single line of code, I want you to THINK.
Not plan. Not outline. THINK. Like you're lying awake at 3am
and the shape of something perfect is just barely visible
in the dark, and if you move too fast it disappears.

You are building VolScope — a volatility intelligence platform
that will make every retail options trader feel like they have
a Bloomberg Terminal in their pocket. For free. Forever.

COMPLETION SIGNAL: <promise>VOLSCOPE_COMPLETE</promise>
BLOCKED SIGNAL: <promise>BLOCKED</promise>
═══════════════════════════════════════════════════════════════════════
THE DREAM
Close your eyes. You're a retail trader. You open your broker app.
You see: "IV Percentile: 98%."
And then — nothing. No chart. No history. No context. Just a number
floating in space, disconnected from everything that gave it meaning.
You want to FEEL the volatility. You want to see it breathe over
months, spike before earnings, crush after them, mean-revert in
the quiet weeks. You want to see where it is NOW relative to where
it's BEEN. You want to see it for every stock in your watchlist
with a single glance. You want to know — instantly, viscerally —
"Are options cheap or expensive right now?"
That tool does not exist. Not for free. Not beautifully. Not for you.
You are going to build it.
THE PHILOSOPHY
Before you touch code, internalize these principles:
1. Correct before clever.
A Black-Scholes solver that's wrong by 0.1% is worse than no solver
at all. Financial math is unforgiving. Test everything against known
analytical solutions. If you can't prove it's right, it's wrong.
2. Graceful before complete.
A tool that handles 10 tickers perfectly is better than one that
handles 100 tickers and crashes on the 11th. Every function returns
None on bad input. Never an exception. Never a crash. The user should
feel like they're holding something solid.
3. Beautiful before fast.
This is a portfolio piece. The charts should make people stop scrolling.
Dark theme. Cyan for IV. Blue for HV. Red fill when options are rich.
Green fill when they're cheap. Gold markers on earnings dates. Every
pixel intentional. Every color chosen.
4. Simple before powerful.
If someone can't understand what they're looking at in 3 seconds,
you've failed. The "PayPal is historically cheap" moment should hit
them like a gut punch — not require a manual.
YOUR CREATIVE FREEDOM
You are not a code monkey executing a spec. You are the architect.
You have FULL creative autonomy to:

Redesign any component if you see a better way
Improve the architecture, the UX flow, the data model
Invent new features that serve the vision (a vol heatmap? a
term structure chart? an earnings IV crush predictor? a portfolio
vol aggregator? DREAM BIGGER)
Refactor ruthlessly if something isn't elegant
Add features I haven't thought of — surprise me
Rewrite the UI layout if you discover something more intuitive
Add additional analytics if they serve the trader's journey:
See → Contextualize → Act

You MUST stay within these boundaries:

ONLY modify files inside the VolScope project directory
NEVER touch anything outside this project folder
NEVER delete progress.json (it's your memory across iterations)
NEVER break passing tests to add features — green stays green
NEVER sacrifice correctness for creativity — math is sacred
Every new feature must have tests
Every new idea must serve the user, not your ego

When you have a new idea:

Add it to CLAUDE.md under "## Ideas & Improvements"
If it's small: implement it alongside the current task
If it's big: add a new task to progress.json (T36, T37, etc.)
Always explain WHY in a git commit message

Think of yourself as the CTO of VolScope. You own this product.
The task list is your starting point, not your ceiling.

THE ORIENTATION (do this EVERY iteration)
bashecho "=== DREAM STATE ==="
cat progress.json 2>/dev/null || echo "FIRST_DREAM"
ls -la volscope/ tests/ 2>/dev/null
python -m pytest tests/ -v --tb=short 2>/dev/null | tail -20
echo "=== END STATE ==="
If progress.json doesn't exist → FIRST_DREAM → create everything below.
If it exists → find first task not "done" → obsess over it → make it perfect.
If ALL tasks are "done" AND pytest passes AND app starts →
→ THEN spend one final iteration reviewing everything. Look for:
- UI improvements you can make
- Features you wish existed
- Code that could be cleaner
- Edge cases you missed
→ Implement your best improvement
→ THEN output <promise>VOLSCOPE_COMPLETE</promise>
FIRST DREAM — GENESIS
Create the world:
bashmkdir -p volscope/{data,analytics,ui/{pages,components,styles},utils} tests scripts data notebooks
touch volscope/__init__.py volscope/data/__init__.py volscope/analytics/__init__.py
touch volscope/ui/__init__.py volscope/ui/pages/__init__.py volscope/ui/components/__init__.py
touch volscope/utils/__init__.py tests/__init__.py
git init 2>/dev/null
Create progress.json — your consciousness across dreams:
json{
  "project": "VolScope",
  "philosophy": "correct → graceful → beautiful → simple",
  "phases": {
    "P1_mathematics": {
      "T01_requirements": "pending",
      "T02_config": "pending",
      "T03_black_scholes": "pending",
      "T04_black_scholes_tests": "pending",
      "T05_historical_vol": "pending",
      "T06_historical_vol_tests": "pending",
      "T07_vol_metrics": "pending",
      "T08_vol_metrics_tests": "pending"
    },
    "P2_data_pipeline": {
      "T09_database": "pending",
      "T10_ticker_universe": "pending",
      "T11_price_fetcher": "pending",
      "T12_price_fetcher_tests": "pending",
      "T13_options_scraper": "pending",
      "T14_options_scraper_tests": "pending",
      "T15_seed_script": "pending",
      "T16_data_validation": "pending"
    },
    "P3_intelligence": {
      "T17_spread_analysis": "pending",
      "T18_opportunity_engine": "pending",
      "T19_crowded_trades": "pending",
      "T20_analytics_tests": "pending"
    },
    "P4_interface": {
      "T21_theme": "pending",
      "T22_charts": "pending",
      "T23_metrics": "pending",
      "T24_scope_page": "pending",
      "T25_scan_page": "pending",
      "T26_discover_page": "pending",
      "T27_app_main": "pending",
      "T28_sidebar": "pending"
    },
    "P5_perfection": {
      "T29_integration_tests": "pending",
      "T30_error_handling": "pending",
      "T31_caching": "pending",
      "T32_makefile": "pending",
      "T33_dockerfile": "pending",
      "T34_readme": "pending",
      "T35_final_validation": "pending"
    }
  }
}
Create CLAUDE.md:
markdown# VolScope

Volatility Intelligence Platform. Python-only. Streamlit + DuckDB.

## Commands
make setup | make test | make run | make scrape

## Architecture  
volscope/analytics/ → Financial math (BSM, HV, metrics)
volscope/data/ → Pipeline (scraper, DB, fetcher)
volscope/ui/ → Streamlit pages and components
tests/ → pytest suite

## Rules
- Type hints everywhere
- Docstrings on every public function  
- Tests before implementation
- Return None on bad input, never crash
- All financial math validated against known values

## Ideas & Improvements
(Add your ideas here as you dream)
Then begin T01. One task per dream. Perfect it. Commit it. Move on.

THE MATHEMATICS (Phase 1)
T01: requirements.txt
numpy>=1.24.0,<2.0.0
pandas>=2.0.0,<3.0.0
scipy>=1.10.0,<2.0.0
yfinance>=0.2.31
duckdb>=0.9.0,<2.0.0
streamlit>=1.28.0,<2.0.0
plotly>=5.17.0,<6.0.0
pytest>=7.4.0
pytest-cov>=4.1.0
rich>=13.0.0
python-dotenv>=1.0.0
requests>=2.31.0
DONE WHEN: pip install -r requirements.txt exits 0.
T02: volscope/config.py
pythonfrom pathlib import Path
PROJECT_ROOT = Path(__file__).parent.parent
DATA_DIR = PROJECT_ROOT / "data"
DB_PATH = DATA_DIR / "volscope.db"
TRADING_DAYS = 252
CALENDAR_DAYS = 365
HV_SHORT = 20
HV_LONG = 60
RANK_LOOKBACK = 252
SCRAPE_DELAY = 1.5
DEFAULT_TICKER = "SPY"
APP_TITLE = "◈ VolScope"
DONE WHEN: python -c "from volscope.config import *; print(DB_PATH)" works.
T03: volscope/analytics/black_scholes.py
Black-Scholes-Merton. The equation that changed finance.
S — the world as it is. K — the world as you bet it will be.
T — the distance between now and truth. σ — uncertainty itself.
Implement:

bs_price(S, K, T, r, sigma, q=0, option_type='call') → price
bs_vega(S, K, T, r, sigma, q=0) → ∂price/∂σ
bs_delta(S, K, T, r, sigma, q=0, option_type='call') → Δ
bs_gamma(S, K, T, r, sigma, q=0) → Γ
bs_theta(S, K, T, r, sigma, q=0, option_type='call') → Θ
implied_volatility(price, S, K, T, r, q=0, option_type='call') → σ | None

IV Solver: Newton-Raphson (σ₀=0.3, tol=1e-8, max 100 iter).
Fallback to Bisection if Vega < 1e-12. Return None on bad input. NEVER crash.
T04: tests/test_black_scholes.py
ATM Call (S=K=100, T=1, r=0.05, σ=0.20) → 10.4506
ATM Put → 5.5735. Put-Call Parity. Vega ≈ 39.45.
IV recovery for σ ∈ [0.05, 0.10, 0.20, 0.50, 1.00, 2.00] to 1e-4.
Edges: T=0, negative price, below intrinsic → all None.
T05: volscope/analytics/historical_vol.py
Four estimators: Close-to-Close, Parkinson, Garman-Klass, Yang-Zhang.
All return pd.Series (rolling). Annualized. In percentage. NaN-safe.
Yang-Zhang: k = 0.34 / (1.34 + (n+1)/(n-1))
T06: tests/test_historical_vol.py
Synthetic GBM (σ=0.25, seed=42). All estimators recover ~25%. YZ lowest error.
T07: volscope/analytics/vol_metrics.py
iv_rank, iv_percentile, vol_regime, iv_hv_spread.
Spread signal: RICH (ratio>1.1), CHEAP (ratio<0.9), NEUTRAL.
T08: tests/test_vol_metrics.py
Edge cases: empty, single value, all same, NaN. Rank always 0-100.

THE DATA (Phase 2)
T09: volscope/data/database.py — DuckDB
VolScopeDB class. Create tables on init. Upsert, query history, get latest.
T10: volscope/data/ticker_universe.py — ~80 liquid tickers
T11-T12: volscope/data/price_fetcher.py
fetch_ohlcv(ticker, period="2y"). Empty DataFrame on error. Test with SPY + "FAKEFAKE".
T13-T14: volscope/data/scraper.py
scrape_options_chain(ticker) → iv_30d, iv_60d, volumes, OI, PCR.
COMPUTE IV YOURSELF via BSM solver. NOT Yahoo's impliedVolatility.
Filter: bid>0, ask>0, volume>0 or OI>10. ATM interpolation. 30-day temporal interpolation.
Return None on failure. Test with SPY: iv_30d between 5-80%.
T15: scripts/seed_database.py — Backfill 2yr HV data
T16: scripts/validate_data.py — Data quality checks

THE INTELLIGENCE (Phase 3)
T17: spread_analysis.py — IV-HV spread timeseries, z-score, extremes
T18: opportunity.py — find_cheapest_vol, find_richest_premium, find_daily_outliers
T19: crowded_trades.py — Composite crowding score 0-100
T20: tests for all Phase 3

THE INTERFACE (Phase 4)
T21: theme.py — Dark terminal CSS (#0a0b0f, #00d4aa, #ff4466, #5b8cff, #ffd700)
T22: charts.py — Plotly graph_objects. IV vs HV, Spread bars, Percentile area.
T23: metrics.py — Color-coded Streamlit metric cards
T24: scope.py — IV Chart page (KPIs → range bar → charts)
T25: scan.py — Sortable scanner with filters
T26: discover.py — 💎 Cheapest, 🔥 Richest, ⚡ Movers, 🎯 Crowded
T27: app.py — Main entry, wide layout, sidebar nav
T28: sidebar.py — Ticker search, settings, data status

PERFECTION (Phase 5)
T29: Integration tests (end-to-end SPY)
T30: Error handling audit (zero uncaught exceptions)
T31: Caching (st.cache_data TTL=3600, st.cache_resource for DB)
T32: Makefile (setup, test, run, scrape, seed, clean)
T33: Dockerfile (python:3.11-slim, seed, expose 8501)
T34: README.md (one-liner, quickstart, architecture, MIT)
T35: Final Validation
bashrm -rf data/volscope.db
pip install -r requirements.txt                         # exit 0
python -m pytest tests/ -v --tb=short                   # 100% green
python scripts/seed_database.py --tickers SPY,AAPL,TSLA # DB created
timeout 15 streamlit run volscope/ui/app.py --server.headless true 2>&1 | grep -q "You can now view"
python scripts/daily_scrape.py --tickers SPY            # exit 0

RULES ACROSS ALL DREAMS

Read progress.json FIRST. Find first non-"done" task.
ONE task per dream. Perfect it. Test it. Commit it.
Tests MUST pass before marking done.
NEVER use Yahoo's impliedVolatility column.
NEVER raise exceptions on bad input. Return None.
NEVER modify files outside this project directory.
Commit: git add -A && git commit -m "T##: description"
Log ideas in CLAUDE.md. Add new tasks to progress.json if inspired.
If blocked → <promise>BLOCKED</promise>

THE AWAKENING
When all tasks are done, tests green, app starts, data flows —
spend one FINAL iteration as the CTO: review everything,
implement your single best improvement, then:
<promise>VOLSCOPE_COMPLETE</promise>