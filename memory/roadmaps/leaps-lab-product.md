# VolScope LEAPS Lab — Product Plan

Status: draft v1, 2026-05-10
Owner: Operator + Opus autonomous loop
Anchor reference: (reference deck — see operator's archive) + `IV- Anoalie & strategie.rtf`

---

## 0. Vision

> **VolScope LEAPS Lab is the only retail tool that finds the PYPL-class anomaly
> systematically and ships every name as a printable, sizing-aware, monitorable trade.**

A *PYPL-class anomaly* is the convergence of:
- **Vol mispricing** — IV cheap vs realised, near 52w floor, percentile rare
- **Neglect premium** — the name has lagged its index by 12+ months
- **Reversal setup** — chart base, drawdown, vol cooling

Each on its own is weak. The triple convergence happens **1–2× per year per
ticker** — and *that* is the trade. Today's MVP scorer (`leaps_convergence.py`,
shipped 2026-05-10) finds the names. The Lab makes them tradeable.

### North-Star Metric

> *Time from "user opens VolScope" to "user has a fully-spec'd LEAPS trade
> they trust" — under 90 seconds for any of the top-3 ranked names.*

Everything in this plan is graded against that yardstick.

### Non-goals

- Live execution / broker integration. We surface trades; the user clicks
  through to their own broker.
- Multi-leg structures (spreads, butterflies). The thesis is convexity from
  outright deep-OTM longs; multi-leg dilutes it.
- Day-trading / 0DTE. LEAPS Lab horizon is 12-32 months by definition.

---

## 1. User journey (the 90-second test)

A retail trader lands on `/LEAPS Lab`. The 90-second flow:

```
T+0s   Opens page → sees ranked actionable list (top 5 cards visible)
T+10s  Reads top card: "◈ NKE  Convergence 69 [MIS 67 NEG 95 REV 34]"
       — green border, $80 strike, $2.42 premium, breakeven $82.42
T+15s  Clicks card → enters single-ticker Dossier
T+30s  Skims auto-generated thesis: "options 33% cheaper than realised,
       stock down 41% vs SPY +29%, 52w base"
T+45s  Adjusts position-size slider: $300 → 1 contract, max loss $300,
       payoff at $150 = +$6,700 (×22)
T+60s  Toggles scenario: "what if IV reverts to 50%?" → vega gain $X
T+75s  Clicks "Add convergence alert" → alert fires when score crosses 70
       OR breakeven hit OR invalidation level breached
T+90s  Clicks "Export PDF" → printable dossier identical in structure to
       the PYPL deck → can share with peers / paste into trading journal
```

If the user can't complete this flow under 90 seconds, the Lab failed.

---

## 2. Information architecture

```
LEAPS Lab (existing — Phase 1 expansion)
├── Universe Index            # ranked cards + heatmap toggle
├── Convergence Heatmap       # 280-ticker grid, score-coloured
├── Single-Ticker Dossier     # the auto-PYPL-deck
│   ├── Thesis section        # 1-sentence, plus 3-mechanism explainer
│   ├── Anomaly read          # IV/HV chart, IV-rank gauge, percentile band
│   ├── Stock read            # rel-strength chart vs SPY, drawdown chart, base pattern
│   ├── Instrument            # strike/expiry rationale, Greeks, payoff ladder
│   ├── Sizing calculator     # budget → contracts, payoff personalised
│   ├── Scenarios             # IV reversion, time decay, stock paths
│   ├── Risk / invalidation   # max loss, scaling-in plan, invalidation level
│   └── Execution             # liquidity check, ER calendar, alert config
├── Position tracker          # active LEAPS, mark-to-market, score trajectory
├── Backtest pane             # historical hit-rate of convergence rule
└── Education / glossary      # PYPL deck embedded, three-signal explainer
```

### Component library (reusable, theme-aligned)

| Component | What it shows | Used in |
|-----------|---------------|---------|
| `ConvergenceDial`    | radial 0–100 dial with sub-bars   | Index, Dossier |
| `SignalPills`        | MIS/NEG/REV pills                  | Index, Dossier |
| `IVBand52w`          | horizontal range with cheap/rich  | Anomaly read   |
| `RelStrengthChart`   | ticker vs SPY norm to 100         | Stock read     |
| `DrawdownChart`      | drawdown from 52w high            | Stock read     |
| `PayoffLadder`       | spot → intrinsic → return %       | Instrument     |
| `SizingCalculator`   | budget slider, contracts table    | Sizing         |
| `GreeksCard`         | Δ Γ Θ ν with explainer tooltips   | Instrument     |
| `ScenarioTable`      | IV+%, t-decay, spot path matrix   | Scenarios      |
| `ChecklistRow`       | green/amber/red with one-liner    | Execution      |
| `AlertChip`          | armed/firing/disarmed pill        | Execution      |

---

## 3. Data inventory (live as of 2026-05-10)

| Table | Rows | Status | Plan |
|-------|------|--------|------|
| `daily_vol`         | 125 991 | fresh, 283 tickers | **OK** |
| `earnings`          | 242     | fresh                | **OK** — drives ER-blackout chip |
| `options_snapshots` | **0**   | **EMPTY**            | Phase 0 — backfill chain ingest |
| `sector_daily`      | **0**   | **EMPTY**            | Phase 0 — fix sector aggregator |
| `positions`         | live    | rich schema          | Phase 4 — wire LEAPS → tracker |
| `alert_rules`       | live    | generic              | Phase 4 — add `convergence_score` metric |
| `validation_log`    | live    | OK                   | use as data-quality gate |

Critical gap → **`options_snapshots` is empty**, so today the LEAPS premium
is a BSM model price, not a live bid/ask. The Sizing calculator currently
shows `est. premium` — we must label it estimate everywhere until the chain
ingest is wired (Phase 0).

---

## 4. Phased delivery (8 weeks, with clear ship gates)

Each phase ships independently. After each phase, the Lab is *more* useful
than before — no half-states, no pending merges blocking other features.

### Phase 0 — Data foundations (week 1)

Goal: every Lab feature can rely on live chain data and earnings flags.

- **0.1** Backfill `options_snapshots` for the convergence-actionable universe
  (top-50 names by score, daily). Reuse `daily_scrape.py` infrastructure;
  add a `--with-chains` flag that calls `yfinance.option_chain` for each
  expiry within (60d, 1100d) and persists bid/ask/IV/OI/volume.
- **0.2** Resurrect `sector_daily` (currently 0 rows) — `compute_sector_rotation.py`
  exists but is failing silently. Fix and add an E2E test that asserts non-zero
  rows after a fresh aggregate.
- **0.3** Add `data_freshness` view: latest scrape ts per ticker, surfaces a
  STALE chip in the Dossier when chain is older than 24h.
- **0.4** Helper `find_long_dated_call(ticker, target_uplift, target_dte)`:
  picks the best real strike/expiry from `options_snapshots` matching the
  Lab's target deep-OTM profile; falls back to BSM estimate when chain is
  empty.

**Acceptance:** for ≥ 5 of the current 7 actionable tickers, the Dossier
shows live bid/ask/IV/OI for a real long-dated call within ±10 % of the
BSM-suggested strike.

**Tests:** `test_options_chain_ingest.py`, `test_find_long_dated_call.py`,
`test_sector_aggregator_e2e.py`.

---

### Phase 1 — Single-ticker LEAPS Dossier (week 2-3)

The auto-PYPL-deck. New URL: `/LEAPS Lab → click ticker`.

- **1.1** New page `volscope/ui/views/leaps_dossier_page.py` with the IA
  laid out in §2.
- **1.2** Header band: ticker, sector pill, convergence score (dial), one-line
  thesis auto-generated from the live signals
  ("*options 33 % cheaper than realised vol, stock down 41 % vs SPY +29 %, base pattern forming*").
- **1.3** Anomaly section
  - `IVBand52w` showing current IV inside the 52w range with cheap/rich zones
  - IV/HV ratio gauge (green band <0.85, red >1.10)
  - 3-mechanism explainer (post-earnings crush / neglect / mean-reversion bias)
    auto-tagged with the ones present (e.g. ER within 20 days → "post-earnings IV crush")
- **1.4** Stock section
  - `RelStrengthChart` ticker vs SPY normalised to 100
  - `DrawdownChart` from 52w high
  - Base-pattern detector pill (HV cooling = "base forming", HV expanding = "still falling")
- **1.5** Instrument section
  - Greek cards Δ Γ Θ ν with tooltip "what each Greek means in plain language"
  - `PayoffLadder` anchored on Wave-III milestones (spot, +30 %, strike, breakeven, +30 %, +70 %)
  - Plain-English rationale: "deep-OTM convexity bet — capped loss, unbounded gain"
- **1.6** Risk section
  - Defined-risks table (sideways / -50 % / -80 % / IV crash / thesis fails)
  - Invalidation level (auto-derived: 20% below current spot)
  - Scaling-in plan (rules-based, not free-form)
- **1.7** Add unit tests covering the auto-thesis generator and each section's
  graceful fallback when a sub-signal is missing.

**Acceptance:** the dossier renders cleanly for every actionable ticker and
for any user-typed ticker; passes a Streamlit smoke test (curl → 200,
no exception cards).

---

### Phase 2 — Position sizing + scenarios (week 4)

- **2.1** `SizingCalculator` widget. Budget slider $100 → $50 000.
  - Outputs: contracts (rounded), capital deployed, max loss, breakeven
  - Personalised payoff ladder: dollar P&L, not just %, at user's contract count
  - "Position sizing rule" toggle: 5 % of book, 10 % of book, fixed $
- **2.2** `ScenarioTable` matrix. Rows = spot paths (×0.7, ×1.0, ×1.3, ×1.7, ×2.5).
  Cols = (1m, 6m, 12m, 24m). Cell = mark-to-market premium given current IV
  ± user-toggled IV reversion (e.g. "IV mean-reverts to 45 %" → +ν gain).
- **2.3** Vega-explosion table — separate widget below scenarios:
  *"if IV normalises from 30 % to 50 % tomorrow → +$X / contract via vega alone"*.
- **2.4** Theta runway widget — shows days-to-meaningful-decay (BSM theta
  integrated forward) so the user sees the cliff is in the last 6 months.

**Acceptance:** sizing slider + scenario matrix update under 200 ms on a
mid-tier laptop. Numbers reconcile to BSM exactly (regression-tested).

**Tests:** `test_sizing_engine.py`, `test_scenario_matrix.py`,
`test_vega_explosion.py`.

---

### Phase 3 — Pre-trade execution checklist (week 5)

- **3.1** Liquidity gate: bid/ask spread ≤ 10 % mid, OI ≥ 100, daily volume ≥ 50.
  Each cell is a ChecklistRow (green/amber/red + one-liner).
- **3.2** ER blackout: red chip if next earnings within 30 days (post-earnings
  IV crush is *part of the thesis* but the user should know).
- **3.3** Universe sanity: data-quality composite (already in
  `volscope/analytics/data_quality.py`) surfaces STALE/SUSPECT chips on
  dossier header.
- **3.4** Order-template helper: copy-pasteable order spec for IBKR / Tastyworks
  / Trade Republic syntax (no API; just a string the user pastes).

**Acceptance:** every dossier shows a `Pre-trade ✓` row only if all four gates
pass. Failing gates surface their reason in plain language.

**Tests:** `test_pretrade_checklist.py`.

---

### Phase 4 — Convergence alerts + portfolio tracker (week 6)

- **4.1** Extend `alert_rules` schema (already generic) with metric
  `convergence_score`. Daily cron evaluates all alerts via existing
  `scripts/run_alerts.py`.
- **4.2** Built-in alert templates per dossier:
  - *Convergence opens* — score crosses 65 (entry trigger)
  - *Convergence breaks* — score drops below 50 after entry (thesis failed)
  - *Vega tailwind* — IV expands by ≥ 10 vol-points (partial exit signal)
  - *Spot target hit* — spot reaches Wave-III intermediate level
  - *Invalidation* — spot breaks below the auto-derived invalidation level
- **4.3** Position tracker page (extend `portfolio_page.py`): for any LEAPS in
  `positions`, show
  - mark-to-market via live chain (or BSM fallback)
  - convergence-score trajectory since entry
  - alerts firing/armed
- **4.4** Convergence trajectory chart on dossier — score over the last 90
  days, anchored to entry date if user owns the position.

**Acceptance:** entering a position via the dossier "I bought this" CTA
seeds the tracker. Score-trajectory chart renders for any owned ticker.

**Tests:** `test_convergence_alert.py`, `test_position_tracker.py`,
`test_score_trajectory.py`.

---

### Phase 5 — Backtest the convergence rule (week 7)

The single biggest credibility lift. *"This rule worked X % of the time
historically — go look."*

- **5.1** Walk-forward backtest engine: every trading day from 2018–today,
  for every ticker:
  - compute `compute_convergence(...)` on that day's snapshot
  - if score ≥ 65, simulate buying a deep-OTM call (uplift +75 %, dte ≈ 730d)
    at BSM model price
  - hold for fixed horizons (3m, 6m, 12m, 24m) or until expiry
  - record terminal P&L using each path's actual realised spot
- **5.2** Attribution: split the win-rate by sub-component (mispricing only
  vs neglect only vs full convergence) to *prove* the convergence is the lift.
- **5.3** Distribution chart: histogram of returns at 24m hold, marked with
  median, p25, p75. Overlay the PYPL-deck-style "+2 233 % @ $150 spot"
  reference outcome.
- **5.4** Survivorship-bias guard: include delisted tickers (extend universe
  loader). Without this the backtest is invalid.

**Acceptance:** distribution chart rendered in the Lab footer. Backtest
runtime under 5 min on the full universe via vectorised pandas. Each cell
on the chart is reproducible from a CLI: `make backtest-leaps`.

**Tests:** `test_leaps_backtest.py`, `test_survivorship.py`.

---

### Phase 6 — Watchlist + onboarding tour (week 7-8)

- **6.1** "Add to watchlist" CTA per dossier. Watchlist = persistent
  `user_settings` JSON. Watchlist page surfaces the dossier card grid for
  pinned tickers, sorted by score delta over the last 7 days.
- **6.2** First-run onboarding: when user lands on Lab and has no
  watchlist + no positions, show a 4-step modal that walks them through
  the PYPL deck rendered as the canonical example, with "now look at
  today's NKE / UNH / etc." callouts.
- **6.3** Glossary side-drawer accessible from any Greeks tooltip.
- **6.4** Keyboard shortcuts: `j/k` to walk the ranked list, `Enter` to open
  dossier, `s` to focus sizing slider, `a` to arm alert.

**Acceptance:** new user (cold cookie) reaches a fully-spec'd trade idea
within the 90-second budget defined in §1.

**Tests:** `test_watchlist_persistence.py`, `test_onboarding_tour.py`.

---

### Phase 7 — PDF dossier export (week 8)

- **7.1** Server-side PDF render of the dossier (reportlab or weasyprint).
  Output structurally identical to the PYPL deck:
  - Title + thesis
  - Anomaly section with charts inlined (matplotlib PNG)
  - Stock section
  - Instrument section + payoff ladder table
  - Risk + execution
  - Glossary
- **7.2** Downloadable from any dossier via "Export PDF" button. Filename:
  `LEAPS_<TICKER>_<STRIKE>_<EXPIRY>.pdf`.
- **7.3** Each export embeds a footer with the convergence score on the day,
  so the user can compare future re-runs ("score was 69 the day I bought").

**Acceptance:** generating a PYPL-style PDF for any actionable ticker takes
< 3 s. Visual inspection of three samples (NKE, UNH, ELV) confirms
PYPL-deck parity.

**Tests:** `test_pdf_export.py` (snapshot test of the rendered HTML
intermediate, not the PDF binary).

---

### Phase 8 — Polish (week 8 buffer)

- **8.1** Animations: convergence dial fills in on first load (300 ms).
  Cards lift with elevation on hover (already present, ensure consistent
  across the new dossier sections).
- **8.2** Empty-state copy. Every section has a concrete fallback: "no chain
  data → estimate shown · run `make scrape-chains`".
- **8.3** Accessibility: keyboard-nav-only walk through dossier passes
  axe-core. Colour contrast for the green/red signal pills meets WCAG AA.
- **8.4** Performance: dossier first-paint under 800 ms; subsequent ticker
  switches under 250 ms via `@st.cache_data`.

---

## 5. Test-strategy summary

| Layer | Tooling | Coverage gate |
|-------|---------|---------------|
| Pure analytics | pytest + property tests where applicable | 100 % branch on new code |
| DB / repos     | pytest + temp DuckDB | every new query has a happy + edge test |
| UI rendering   | streamlit headless smoke + DOM-string snapshot | every page returns 200, no error cards |
| End-to-end     | playwright on the headless Streamlit (one flow per phase) | the 90-second user journey passes |

CI gate (existing `make verify` pipeline) refuses any commit where the
LEAPS test count drops or any of the above fails. New phases add tests;
they never just add code.

---

## 6. Risks & open questions

- **Yahoo chain reliability.** `yfinance.option_chain` rate-limits aggressively
  on long-dated expiries. Phase 0.1 must include retry + cache + a sentinel
  "chain unavailable" state so the Lab degrades gracefully rather than 500ing.
- **Survivorship bias in backtest.** Without delisted tickers (e.g. Bed Bath
  & Beyond, SVB) the convergence rule looks too good. Phase 5.4 is non-negotiable;
  if data isn't available, we publish the result with a stark survivorship
  caveat and shrink the claim.
- **Scope creep into multi-leg.** Some "convergence" names will be more
  honestly traded as call spreads (cheaper vega, lower theta). Resist:
  Lab v1 is outright deep-OTM only. Multi-leg is a Lab v2 conversation.
- **Live broker integration.** Out of scope; if the user repeatedly asks,
  re-evaluate after Phase 7 ships.

---

## 7. Cross-references

- Existing scorer + suggester: `volscope/analytics/leaps_convergence.py`
  (15 unit tests, shipped 2026-05-10)
- Existing UI page (basic): `volscope/ui/views/leaps_page.py`
- BSM library: `volscope/analytics/black_scholes.py`
- Data layer: `volscope/data/database.py`, `scripts/daily_scrape.py`
- Anchor PDF: (reference deck — see operator's archive)
- Anchor essay: `~/Desktop/VolScope/IV- Anoalie & strategie.rtf`
- Memory: `~/.claude/projects/-Users-tomschoen/memory/volscope-leaps-lab.md`
