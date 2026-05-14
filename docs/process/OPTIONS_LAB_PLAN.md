> Status: ARCHIVED
> This document captures a past planning session. It is preserved
> for historical context — current state lives in /memory/roadmaps/ + /ROADMAP.md.

# OPTIONS_LAB_PLAN.md

VolScope · Options Lab + Pro Chart + Strategy Presets — implementation contract.
Owner: claude-opus-4-7. Created 2026-05-11.

## Scope

Three new modules grafted onto the existing VolScope stack:

1. **Options Lab** — single-page OptionStrat-class workbench (payoff curves,
   Greeks surface, scenario matrix, probability cone) for 10 named strategies.
2. **Pro Chart** — reusable Plotly building block, TradingView-/IBKR-grade
   candles + volume + IV overlay + range-selector + crosshair.
3. **Strategy Presets** — DuckDB-persisted, idempotent seeds; UI hook in
   the Options Lab sidebar; three seeded trades (PYPL, EWZ, JD).

Conventions: existing project paths (`volscope/ui/views/*_page.py` +
`_PAGE_REGISTRY`), existing theme tokens (`COLORS`), existing BSM module
(`volscope/analytics/black_scholes.py`).

---

## Pre-Build Audit

### Block 1: q-Yield Coverage in `volscope/analytics/black_scholes.py`

| Function       | Signature accepts `q` | Applies `q` correctly | Patch needed |
|----------------|-----------------------|-----------------------|--------------|
| `bs_price`     | YES (`q=0.0`)         | YES — `d1` carries `(r-q)`, both `exp(-qT)` and `exp(-rT)` discounts | no |
| `bs_delta`     | YES (`q=0.0`)         | YES — multiplied by `exp(-qT)` for call; `exp(-qT) * (N(d1)-1)` for put | no |
| `bs_gamma`     | YES (`q=0.0`)         | YES — `exp(-qT) * φ(d1) / (S σ √T)` | no |
| `bs_vega`      | YES (`q=0.0`)         | YES — `S * exp(-qT) * φ(d1) * √T` | no |
| `bs_theta`     | YES (`q=0.0`)         | YES — full call+put forms including `± qS exp(-qT) N(±d1)` | no |
| `bs_rho`       | — (function absent)   | —                     | **YES — add new function** |
| `implied_vol`  | YES (`q=0.0`)         | YES — pipes `q` into both `bs_price` and `bs_vega`; round-trip `err = 2.78e-17` | no |

**Verification:** `scripts/_audit_q.py` (deleted post-audit). Diff test
`Greek(q=0)` vs `Greek(q=0.03)` showed non-zero deltas for every Greek
listed above (e.g. call price drops $1.74, call delta drops 0.063, put
theta drops $1.07/yr). IV round-trip with `q=0.03` recovered the input
σ to machine precision.

**Phase 1 patch list:**

1. **Add `bs_rho(S, K, T, r, sigma, q=0.0, option_type='call')`** —
   analytical formula: `K*T*exp(-r*T)*N(d2)` for call,
   `-K*T*exp(-r*T)*N(-d2)` for put. Divide by 100 in the caller when
   displaying "per 1 % rate change" semantics.
2. Add `bs_rho` test to `tests/test_black_scholes.py` covering
   put-call parity for rho (`rho_call - rho_put = K T exp(-rT)`),
   finite-difference vs analytical (tol 1e-3), `q>0` sensitivity.

No edits to existing functions. The BSM core is already correct.

---

### Block 2: Strategy Template Interface

**Existing templates (9, in `volscope/analytics/strategy_templates.py`):**

| Name | Direction | Legs |
|---|---|---|
| Long Call | long_vol | 1 |
| Long Put | long_vol | 1 |
| Long Straddle | long_vol | 2 |
| Long Strangle | long_vol | 2 |
| Short Iron Condor | short_vol | 4 |
| Bull Call Spread | long_vol | 2 |
| Bear Put Spread | long_vol | 2 |
| Long Calendar | neutral_vol | 2 |
| Risk Reversal | long_vol | 2 |

**`StrategyTemplate.materialize(ticker, spot, iv_pct, dte, contracts)` returns `MaterializedStrategy`** with frozen fields:

| Field | Type | Notes |
|---|---|---|
| `template_name` | `str` | analog to Protocol's `name` |
| `ticker` | `str` | — |
| `legs` | `tuple[LegSpec, ...]` | each Leg: option_type, action, strike, expiry, contracts, entry_premium, delta |
| `net_debit` | `float` | + paid, − collected — single config |
| `max_loss` | `Optional[float]` | static, single config |
| `max_gain` | `Optional[float]` | static, single config |
| `breakevens` | `tuple[float, ...]` | static, single config |
| `summary_line` | `str` | — |
| `direction` | `str` | — |

**Protocol gap analysis (against Master Prompt):**

- `name` — covered (`template_name`)
- `legs: list[Leg]` — covered (tuple, list-castable)
- `payoff_at_expiry(S)` — **missing**
- `payoff_at_t(S, t, iv, r, q)` — **missing**
- `net_premium(S0, iv, r, q, T)` — **missing as function** (the field
  `net_debit` is a snapshot; Protocol wants a recomputable hook)
- `breakevens(S0, iv, r, q, T)` — **partial** (exists as static tuple;
  Protocol wants method recomputed against new (S0,iv,r,q,T))
- `max_profit()` — **partial** (field `max_gain`; Protocol wants method)
- `max_loss()` — **partial** (field `max_loss`; Protocol wants method)
- `greeks(S, iv, r, q, T)` — **missing**

**Existing callers of `strategy_templates`:**

- `volscope/ui/views/strategy_builder_page.py` → uses `resolve_template`
- `volscope/ui/views/pretrade_page.py` → uses `resolve_template`
- `volscope/data/paper_trader.py` → uses `LegSpec`, `MaterializedStrategy`
- `tests/test_paper_trader.py` → uses `TEMPLATES`
- `tests/test_strategy_templates.py` → uses `TEMPLATES`, `LegSpec`, `MaterializedStrategy`, `resolve_template`

All callers read fields of `MaterializedStrategy`; none expect the Protocol methods today. Adding methods is **purely additive**.

**Decision: Option B-modified — extend `MaterializedStrategy` itself with operational methods.**

Rationale: `MaterializedStrategy` already carries concrete legs with concrete strikes, which is exactly what payoff math needs. Adding `payoff_at_expiry(S) → np.ndarray`, `payoff_at_t(S, t, iv, r, q) → np.ndarray`, `greeks(S, iv, r, q, T) → dict` as methods of the dataclass keeps a single canonical strategy object, avoids a parallel adapter hierarchy, and leaves every existing caller untouched (the snapshot fields stay). The `breakevens` / `max_profit` / `max_loss` field-vs-method ambiguity is resolved by keeping the fields and exposing the methods as pass-throughs that *also* accept a recompute-from-scratch path when `(S0, iv, r, q, T)` differs from materialization params.

**Iron Butterfly + Covered Call** added as new templates in the same module (non-negotiable per spec).

---

### Block 3: Theme COLORS

**Theme location:** `volscope/ui/styles/theme.py` (export: `COLORS: dict[str, str]`).

**Existing relevant keys:**

| Key | Hex | Used for |
|---|---|---|
| `bg` | `#0a0b0f` | page background |
| `surface` | `#12131a` | sidebar / elevated panels |
| `card` | `#151620` | cards |
| `hover` | `#181924` | hover state |
| `border` | `#1e2038` | dividers |
| `text` | `#e0e4ef` | primary text |
| `muted` | `#8a8f9e` | secondary text |
| `label` | `#424666` | tiny uppercase labels |
| `accent` | `#00d4aa` | green/long-vol/cheap |
| `accent2` | `#5b8cff` | blue/HV/calm |
| `warn` | `#ff4466` | red/danger/rich |
| `amber` | `#ff9f43` | warning |
| `gold` | `#ffd700` | earnings markers |
| `panel`, `grid` | legacy aliases | — |

**Spec-required values vs project palette:**

| Spec key | Spec hex | Project equivalent | Decision |
|---|---|---|---|
| candle_up | `#26A69A` | `accent` `#00d4aa` | Project wins — visual consistency with KPI cells, verdict hero, all existing chart traces. Add explicit alias key `candle_up` = `#00d4aa`. |
| candle_down | `#EF5350` | `warn` `#ff4466` | Project wins — same rationale. Add explicit alias `candle_down` = `#ff4466`. |
| paper_bg / plot_bg | `#131722` | transparent (`rgba(0,0,0,0)`) in `chart_builders._base_layout` | Project wins — charts inherit `page.bg` via transparency. Pro Chart follows the same convention; no key needed. |
| grid | `#1E222D` | `rgba(255,255,255,0.03)` (chart_builders convention) | Project wins — match existing chart-grid hairlines. |
| font | `#D1D4DC` | `text` `#e0e4ef` (hover), `muted` `#8a8f9e` (axis), `label` `#424666` (titles) | Project wins — three-tier hierarchy is established. |
| iv_overlay | `#FFA726` | `amber` `#ff9f43` | Visually indistinguishable. Add alias key `iv_overlay` = `#ff9f43` so Pro Chart references a named role-key, not a generic semantic key. |
| spike | `#787B86` | not present | **Add new key** `spike` = `#787B86` (project picks the spec value because no project equivalent exists). |

**Theme additions (Phase 4 patch):**

```python
"candle_up":   "#00d4aa",   # alias of accent — explicit role for chart traces
"candle_down": "#ff4466",   # alias of warn   — explicit role
"iv_overlay":  "#ff9f43",   # alias of amber  — IV overlay line
"spike":       "#787B86",   # crosshair / spike-line color (new)
```

**Pro Chart consumed keys (final list):**

- `bg`, `card`, `surface` — containers
- `text`, `muted`, `label` — three-tier text hierarchy
- `border` — dividers
- `candle_up`, `candle_down` — candle traces
- `iv_overlay` — IV line
- `spike` — crosshair
- `accent`, `warn` — secondary overlays (median lines, percentile bands)
- `"rgba(0,0,0,0)"` — paper/plot bg (inline literal, matches existing convention)
- `"rgba(255,255,255,0.03)"` — chart grid (inline literal, matches existing convention)

---

### Block 4: Migrations

**Migration system:** none. Schema is ad-hoc via `CREATE TABLE IF NOT EXISTS` inside `VolScopeDB._create_tables()` (file `volscope/data/database.py`, called from `__init__`). Schema additions on existing tables use `ALTER TABLE … ADD COLUMN IF NOT EXISTS` in the same method (see e.g. the `positions` backfill for `strategy_group_id`).

**Schema init location:** `volscope/data/database.py:_create_tables` (lines 31-237). All tables (daily_vol, earnings, options_snapshots, positions, sector_daily, alert_rules, alert_log, validation_log, user_settings, paper_trades) are declared here. Runs idempotently on every `VolScopeDB()` instantiation.

**Decision for `strategy_presets`:** follow the existing ad-hoc pattern. Append a `CREATE TABLE IF NOT EXISTS strategy_presets (…)` block at the end of `_create_tables()` (after `paper_trades`, before the indexes). Schema:

```sql
CREATE TABLE IF NOT EXISTS strategy_presets (
    id              VARCHAR PRIMARY KEY,
    ticker          VARCHAR NOT NULL,
    strategy_name   VARCHAR NOT NULL,
    legs_spec_json  VARCHAR NOT NULL,
    thesis          VARCHAR,
    scaling_plan_json VARCHAR,
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    notes           VARCHAR
)
```

**Seed mechanism:** standalone CLI module `volscope/data/presets_seed.py`, invoked via `python -m volscope.data.presets_seed`. Idempotent on the primary key (UPSERT semantics via `INSERT … ON CONFLICT(id) DO NOTHING`). Documented in `OPTIONS_LAB_PLAN.md` and the README footer. **No auto-run on bootstrap** — explicit user gesture only. Rationale: presets are personal trade ideas, not chrome; the user should consciously decide to seed them, especially because future runs of the seed must remain idempotent and silent.

**Naming deviation from spec:** spec asked for `volscope/presets.py` + `volscope/presets_seed.py` at the package root. Project layout puts persistence helpers under `volscope/data/` (e.g. `database.py`, `paper_trader.py`, `ticker_resolver.py`). To stay consistent we use `volscope/data/presets.py` and `volscope/data/presets_seed.py`. The CLI command becomes `python -m volscope.data.presets_seed`.

---

## Phase Roadmap (post-audit)

| # | Phase | Deliverable | Acceptance |
|---|---|---|---|
| 0 | Pre-Build Audit | This doc | committed before Phase 1 |
| 1 | Black-Scholes Rho | `bs_rho` + tests | put-call parity & finite-diff pass to 1e-3 |
| 2 | Strategy operational methods | `MaterializedStrategy.payoff_at_expiry/payoff_at_t/greeks/net_premium` + Iron Butterfly + Covered Call templates | tests cover all 11 templates with payoff snapshot + Iron Condor breakevens exact |
| 3 | Probability Engine | `volscope/analytics/probability.py` — closed-form for vanillas + 10 k-path Monte Carlo for complex payoffs | Long Call ATM @ 30 % IV ⇒ PoP ∈ [0.35, 0.50] |
| 4 | Pro Chart | `volscope/ui/components/pro_chart.py` + theme additions | renders Apple-grade dark candles + IV overlay; range-selector works |
| 5 | Options Lab Page | `volscope/ui/views/options_lab_page.py` + `_PAGE_REGISTRY` entry | (thesis position — outside bot scope) renders end-to-end < 300 ms |
| 6 | Strategy Presets | `volscope/data/presets.py` + `presets_seed.py` + DB schema + sidebar UI | three initial presets seeded; "Load preset" pre-fills lab |
| 7 | Polish & Integration | sidebar nav entry, README, manual end-to-end | verify-all 7/7 green; AppTest covers Options Lab |

## Coding standards (re-stated, project-specific)

- Python 3.11+, type hints everywhere
- Variable names per quant convention: `S, K, T, r, q, sigma`
- Constants in UPPER_SNAKE_CASE at module top
- English comments, docstrings on every public function
- No external options libraries
- No `st.write` debug statements
- New tests required for each phase before committing
- Each phase ends with: `pytest -q` green + `verify-all` 7/7 + atomic commit
