# VolScope Autonomous Bot — Master Plan (canonical, 2026-05-14)

> **Status:** Anchor document. All future autonomous iteration must trace
> back to a deliverable in this plan. Approved by user on 2026-05-14 in
> session a5effc7c (Pasted text #6 +817 lines).

---

## North star

Evolve VolScope from a research dashboard into a **production-grade
autonomous IV mean-reversion options bot** executing via Interactive
Brokers (ib_async). The wedge nobody else fills in 2026:

> IBKR-connected + Python-native + naked premium selling +
> portfolio-Greek-aware sizing + GARCH/HMM overlays + open source

Option Alpha owns no-code multi-broker but lacks IBKR + naked structures.
tastytrade has no native autotrade. ORATS/Spintwig are research-only.
**VolScope is the IBKR-connected DIY-quant operational layer that doesn't
exist yet.**

---

## Core insight (reframes every design decision)

**Statistical IV mean-reversion is real but does not equal exploitable
edge.** Castillo & Mira-McWilliams (2026, *FinTech* 5(1):26) confirm 65%
of US large caps mean-revert IV statistically AND show that naive
delta-neutral backtests "did not yield consistent profitability." VRP
is equilibrium compensation for tail risk, not arbitrage.

**Therefore the bot is built to manage the tail, not capture the
average.** Implications:

- ¼-Kelly sizing (not full-Kelly)
- 50% profit target (not 80%)
- Mechanical 21-DTE close trumps "let it work"
- HMM regime conditioning is mandatory, not optional
- Correlation haircuts non-negotiable
- 8 independent kill-switch triggers

---

## Phase roadmap

| Phase | Duration | Scope | Exit gate |
|---|---|---|---|
| **0 — Stabilize** | 1 wk | Fix 5 known dashboard bugs | All pages render clean |
| **1 — Signal engine** | 3-4 wk | Factors, HMM, composite, filters, Bot Dashboard | Daily signal list, regime gauge, alerts deliver |
| **2 — Paper loop** | 4-6 wk | ib_async + state machine + kill switch + scheduler | 30+ days, 30+ trades, state machine never desyncs |
| **3 — Backtest validation** | 3-4 wk | vectorbt + optopsy + in-house engine; CI regression | Match spintwig IC 45-DTE Sharpe within ±0.2 |
| **4 — Go-live ramp** | 8-12 wk | Pass go-live gate; 10% → 25% → 50% → 100% over 12 wk | 8 wk live with +net-of-slippage realized PnL |
| **5+ — Advanced** | ongoing | SVI/SSVI, per-name GEX, dispersion, calendars | Each strategy ≥6 mo paper before live |

---

## Phase 0 — Bug-fix layer (must precede everything)

1. **Pre-Trade fillcolor crash** — replace any Plotly `fillcolor="#xxxxxx"`
   with `rgba(...)` literal. Add a unit test asserting no exception on
   synthetic chain render.
2. **"keyboard" placeholder ghost** — grep entire repo, replace
   `placeholder="keyboard"` with `""` or contextual hint.
3. **`st.metric` truncation** — switch large values to `1.2k`/`3.4M`
   formatting OR use `st.markdown` with HTML.
4. **Sparse heatmap** — widen DTE bucketing OR forward-fill missing
   strikes OR switch to IV-rank percentile surface.
5. **Rotation page empty** — trace missing sector/ticker bridge LEFT JOIN.

---

## Phase 1 — Signal engine

### Project layout (target)

```
volscope/
├── config/
│   ├── strategies.yaml
│   ├── risk.yaml
│   ├── tickers.yaml
│   └── calendar.yaml
├── volscope/
│   ├── config.py                       # pydantic Settings + YAML
│   ├── analytics/
│   │   ├── garch.py                    # arch wrapper
│   │   └── regime.py                   # 2-state HMM
│   ├── signals/
│   │   ├── factors.py                  # IVR, IVP, IV/HV, term, skew, momentum
│   │   ├── composite.py                # weighted score 0-100
│   │   ├── filters.py                  # 8 hard gates
│   │   └── ranking.py
│   ├── strategies/
│   │   ├── base.py
│   │   ├── iron_condor.py
│   │   ├── short_strangle.py
│   │   ├── put_credit_spread.py
│   │   ├── leaps_call.py
│   │   └── registry.py
│   ├── persistence/
│   │   ├── db.py
│   │   ├── migrations/001_init.sql     # 5 tables
│   │   └── repos.py
│   ├── alerts/telegram.py              # raw httpx
│   └── ui/pages/
│       ├── 3_Bot_Dashboard.py
│       ├── 5_Trade_Journal.py
│       └── 6_Config_Editor.py
```

### Composite score (weighted)

```
score = 0.15·s_ivr + 0.20·s_ivp + 0.20·s_vrp + 0.15·s_term
      + 0.05·s_skew + 0.10·s_mom + 0.15·s_regime
```

Maps to size: <50 = no trade · 50-65 = ¼ · 65-80 = ½ · 80-90 = ¾ · >90 = full.

### Hard gates (any fail → block, log reason)

1. persistence ≥2 days
2. volume ≥50% of 20d ADV
3. OI ≥500 at target strikes
4. BAS ≤10% mid (reject); ≤5% preferred
5. earnings ≥14 days away (21 if confidence<1.0)
6. no Fed/CPI/NFP ±3 days
7. HMM `p_calm > 0.6` for short vol
8. Consensus rule: short vol ⇒ BOTH `ivr>50` AND `ivp>70`;
   long vol ⇒ BOTH `ivr<30` AND `ivp<30`;
   if `|ivr-ivp|>30` ⇒ trust IVP (single-spike contamination)

### HMM regime (hmmlearn, 2-state Gaussian)

Features: `[VIX daily Δ, SPY 20d realized vol]`. Label state with
higher mean RV as "stress." Use `predict_proba` (gate by p_calm > 0.7)
not hard predict. Retrain monthly with expanding window.

---

## Phase 2 — Paper engine

### State machine (11 states, `transitions` lib)

```
SIGNALED → SIZED → SUBMITTED → PARTIAL_FILL → FILLED → MANAGED → CLOSING → CLOSED
            ↓         ↓                                    ↓
        ABANDONED  REJECTED                          EXPIRED/ASSIGNED/ROLLED
```

Every transition emits an immutable audit row.

### Kill switch — 3 manual + 5 auto

Manual: `/var/run/volscope/KILL` file, `BOT_KILL=1` env, UI button via
DuckDB flag table.

Auto:
- daily loss ≥3% NLV
- drawdown ≥20% from 30d peak
- VIX >40 (liquidate undefined) / >30 (no new entries)
- IBKR disconnect >60s
- term inversion VIX9D/VIX > 1.0

Behavior: `ib.reqGlobalCancel()` + selective undefined close + Telegram +
sticky `/var/run/volscope/KILLED` file requiring human removal.

### Scheduler (APScheduler 3.11, AsyncIOScheduler, **America/New_York**)

```
08:00 ET   premarket_load
08:30      connect_ibkr
09:45      generate_signals (15 min post-open)
10:00      execute_entries
12:00      midday_check
15:00      eod_management (21 DTE + 50% PT + stops)
16:15      eod_reconcile
Sat 09:00  weekly_report
```

Job defaults: `coalesce=True, max_instances=1, misfire_grace_time=300`.

---

## Pinned tech stack (verified 2026-05, do not substitute)

| Library | Version | Notes |
|---|---|---|
| ib_async | ==2.1.0 | NOT ib_insync (archived) |
| py_vollib + py_vollib_vectorized | latest | Greeks |
| arch | ==8.0.0 | GARCH HV forecasts |
| hmmlearn | ~=0.3 | Regime |
| optopsy | goldspanlabs fork | Strategy P&L |
| polars | ~=1.0 | Hot paths only |
| apscheduler | ~=3.11 | NOT 4.0-alpha |
| pydantic + pydantic-settings | ~=2.0 | Config |
| structlog | ==25.5.0 | Audit logger |
| httpx | ~=0.27 | HTTP + Telegram |
| transitions | latest | State machine |
| ruff | ~=0.7 | Replaces black+isort+flake8 |
| mypy | ~=1.13 | strict=true |
| uv | ~=0.5 | NOT poetry |

---

## Risk parameters (config/risk.yaml — canonical)

```yaml
position_sizing:
  kelly_fraction: 0.25
  max_risk_per_trade_defined: 0.02
  max_risk_per_trade_undefined: 0.01
  max_bpr_regt: 0.35
  max_bpr_pm: 0.50
  cash_reserve_min: 0.40
  max_concurrent_positions: 12
  max_per_underlying_pct: 0.20
  max_per_sector_pct: 0.30

circuit_breakers:
  daily_loss_halt_pct: 0.03
  drawdown_no_new_entries_pct: 0.10
  drawdown_liquidate_undefined_pct: 0.15
  drawdown_full_halt_pct: 0.20
  vix_no_new_entries: 30
  vix_liquidate_undefined: 40
  vix_term_invert_ratio: 1.0
  consecutive_losses_pause: 5

go_live_gate:
  paper_months_min: 3
  paper_trades_min: 100
  paper_sharpe_min: 0.5
  paper_max_dd_max: 0.20
  paper_win_rate_min: 0.65
  ramp_pct: [0.10, 0.25, 0.50, 1.00]
```

---

## Universe (tickers.yaml)

**Tier 1 — always tradable (cash-settled indices):**
SPY, QQQ, IWM, SPX, XSP

**Tier 2 — pause around earnings (14d blackout):**
AAPL, MSFT, AMZN, NVDA, GOOGL, META, AMD, QCOM, MU
(Castillo 2026 final 26-ticker subset)

**Blocked:** TSLA pre-earnings, BNTX, MRNA, all biotech single names
with binary FDA risk, penny stocks <$20, recent IPOs <6mo

**Monitor-only:** Operator's existing PYPL Jan 2029 LEAPS (untouched as
thesis position outside bot scope)

---

## Operator pre-commits (must be accepted in writing before live)

- "I accept that 20-30% drawdown is statistically expected within 3 years."
- "I accept that 40%+ drawdown is non-trivial probability on the next
  2018/2020/2024-style event."
- "I will not change parameters intraday. Parameter changes only in the
  Sunday 6 PM review window with 90-day cooldown."
- "I will not roll a losing undefined-risk position to defer realized
  loss. (Karen Bruton rule.)"
- "I will not exceed 2/day dashboard checks. Push alerts only for
  critical events."

---

## German tax (consult Steuerberater — do not act on this alone)

- Abgeltungsteuer 26.375% effective (+ KiSt if applicable → 27.82–27.99%)
- Sparer-Pauschbetrag €1,000 single / €2,000 joint
- **JStG 2024 (06.12.2024) REPEALED §20 Abs.6 Satz 5/6 EStG retroactively** —
  €20k/yr Termingeschäfte loss-offset cap is GONE. Losses again fully
  offsettable against Kapitalerträge. BFH 28.03.2025 (VIII R 11/24) confirmed.
- IBKR does NOT withhold German tax — self-report via Anlage KAP
  (Termingeschäfte gains Zeile 21, losses Zeile 24)
- Daily ECB FX translation per trade; keep records 10 years

---

## Citation block (use in code docstrings)

- Iron Condor params: tastytrade 4,872 SPY trades 2005-2019 + Project
  Finance 71,417 trades + DTR Trading 96,624 SPX trades
- 21-DTE rule: tastytrade Market Measures (gamma 3-5× higher inside 21 DTE)
- 50% PT: tastytrade study (win rate 64% → 82% with management)
- IVR vs IVP: MenthorQ 10-yr SPY study
- HMM regime: López de Prado, *Advances in Financial Machine Learning*
  (2018), Ch. 11
- Mean-reversion universe: Castillo & Mira-McWilliams (2026), *FinTech*
  5(1), 26
- VRP magnitudes: Barclays VRP white paper (+4.2 vol points avg, positive
  86% of months)
- Slippage calibration: spintwig.com 51,600-trade SPX strangle + IC
  backtests
- SVI (Phase 3+): Gatheral & Jacquier (2014), arXiv:1204.0646
- Backtest validation: López de Prado, *AFML* Ch. 7/11/13-14 (CPCV,
  walk-forward, embargo)

---

## Hard "do not" list (binding rules)

- Do NOT substitute pinned libraries without explicit user approval
- Do NOT use ib_insync (archived; protocol stale)
- Do NOT use APScheduler 4.0-alpha (production-unstable)
- Do NOT place MKT orders for options (always LMT + walk price)
- Do NOT roll a losing undefined-risk position (Karen rule)
- Do NOT make intraday parameter changes (Sunday 18:00 review window only)
- Do NOT skip paper trading (≥100 closed paper trades before any go-live)
- Do NOT trade Operator's PYPL Jan 2029 LEAPS — monitor only
- Do NOT chase Sharpe via parameter tweaks — respect the canonical
  (16Δ / 45 DTE / 50% PT / 21 DTE close) baseline
