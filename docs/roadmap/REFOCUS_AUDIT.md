# VolScope Refocus — Master Audit

> Companion to `REFOCUS_PLAN.md`. This is the honest record of what was
> executed, what the multi-agent bug hunt found, what got fixed, and what
> is deliberately deferred. Branch: `refactor/refocus-core`. Generated
> across one autonomous session (2026-06-05/06).

---

## 1. What VolScope is now

A focused **implied-volatility research workbench**. One question:
*"Is this ticker's IV cheap or expensive, and by how much?"* — answered by
IV rank/percentile, the vol cone, the term structure, 25Δ skew, and
expected move. No trading bot, no paper engine, no IBKR, no backtest
product. A solo dev can maintain it.

**Scale of the cut:** 27 → 16 pages, **~12,600 lines removed**, 6 bot
packages + paper-trade/IBKR/audit infra deleted, heavy deps dropped.

---

## 2. Process (how this was done)

1. **Audit swarm** (7 agents) → `REFOCUS_PLAN.md` (demolition map, adversarially reviewed).
2. **Demolition** executed leaf-first, collection-gated after each step.
3. **Bug hunt** — 8 finders across distinct dimensions → adversarial
   verification of every finding → completeness critic. **61 agents,
   2.2M tokens, ~48 verified bugs.**
4. **Creative swarm** — 5 directors → 2 judges → CTO synthesis. **34 ideas,
   7 build-now.**
5. **Fixes + builds**, each repro-verified.

Multi-agent verification was the point: every bug was independently
reproduced before it counted; every creative idea's API was checked
against real code before building.

---

## 3. Bug hunt — disposition of all findings

### Fixed — analytics correctness (CLAUDE.md rule #3: return None, never raise)
- `black_scholes` bs_price/bs_delta/bs_theta/bs_rho: invalid `option_type`
  → `None` (was `ValueError`); `T<=0` intrinsic returns `float`.
- `historical_vol.hv_yang_zhang`: `window<2` guard (was `ZeroDivisionError`).
- `iv_robustness.detect_contamination` + `assess_iv_quality`: non-finite
  IVR/IVP treated as insufficient (NaN had produced a bogus EXTREME verdict
  with NaN divergence → orjson `null`; quality now BLOCK not CAUTION).
- `front_back_iv`: reject non-positive IV.

### Fixed — data layer
- **CRITICAL** `database.upsert_daily`: `vol_regime` + 6 `p_vol_*` posteriors
  added to the `_DAILY_FIELDS` whitelist — they were silently dropped, so
  the Vol Regime feature persisted NULL forever.
- `database._LockedResult.__getattr__`: release exec lock before delegating
  (latent deadlock).
- `vol_index_fetcher`: stop dividing `get_rate()` (already a fraction) by
  100 (rate was 100× too small).

### Fixed — navigation integrity (dead targets → removed pages)
- `scope_page`, `command_center`, `discover` Pre-Trade buttons → Options
  Lab / Scope via the registry-validated nav helper.
- `scope_context_cards` Portfolio button removed.
- `state/store._KNOWN_PAGE_PREFIXES` synced to the live registry.
- `next_step.NEXT_STEPS` + `phase_header.PHASES`/`PAGE_TO_PHASE` rewritten
  to reference only kept pages (also fixed 6 full-suite test failures).

### Fixed — UI render
- `earnings_hub._enrich`: cache-hit path now computes recommendation +
  interestingness (was `None` for every cached tile).
- `earnings_hub`: 4 forbidden `st.metric` → `kpi_grid_html`; stale docstring.
- `scope_page`: skew chart now shows a fallback message when `iv_skew_25d`
  is NULL (was a silent blank).
- `options_lab`: dropped Vanna/Charm/Volga 3-D surfaces (rendered silently
  all-zero — `greeks()` only computes 1st-order); added Rho.
- `command_center`: Trade Journal writes guarded (read-only DB safety).
- `pretrade_skew_em`: shows a diagnostic instead of failing invisibly when
  the live chain lacks per-strike IV.

### Fixed — docs / CI / config (parallel cleanup pass)
- `.github/workflows/ci.yml`: removed 8 deleted test files, 5 deleted mypy
  dirs, bot pip extras.
- `CLAUDE.md`: rewritten to the research identity; dead commands/rows/table
  rows removed.
- `docs/OPERATOR_GUIDE.md`: rewritten (removed deleted-module code blocks).
- `.claude/`: deleted dead commands/skills (paper-engine, audit-chain,
  kill-switch, ibkr-adapter, …); fixed pre-merge-check/restore-drill.
- `garch.py`: error message `[bot]` → `[forecasting]`.
- `help_page`: removed bot/kill-switch/audit-chain glossary blocks.
- Deps: dropped 7 zero-import-site packages; pyproject version 0.2.0 → 0.9.2.

### Deferred — deliberately, with rationale
- **`ivr()`/`ivp()` return NaN not None** (LOW): the downstream harm is
  already neutralised at `detect_contamination`/`assess_iv_quality`; the
  existing tests assert NaN behaviour. Changing the contract ripples for
  no functional gain. Tracked for a future contract-alignment pass.
- **`vol_metrics.iv_rank`/`iv_percentile` return 50.0 sentinel** (MEDIUM):
  "no data" vs "exactly median" ambiguity. Changing to `None` ripples
  through DB writes + UI comparators and needs its own verified pass.
- **Full per-strike IV Smile view** (the 5th core view, partial): blocked
  on data — `options_snapshots` is empty (no snapshot-writing pipeline) and
  `build_smile` reads an `iv` column it doesn't solve. The 25Δ skew chart
  (wired, with the new NULL fallback) covers the skew need at today's data
  level. A true HIVG smile needs a per-strike snapshot pipeline that
  computes IV with our own BSM solver — see §5.
- **`chain_scraper` Yahoo-IV + delta=None** (the live-chain path): the
  proper fix (own-solver per-strike IV + delta in the scraper) is a
  sub-project; the invisible-failure symptom is fixed (diagnostic shown).
- **scope_page expected-move card** (LOW): Vol Insights has EM; Scope does
  not. Enhancement, not a defect.

---

## 4. Brilliancies shipped

The creative swarm's two highest-leverage picks were *wiring the orphaned
core analytics* — both bug fix and feature:

1. **Vol Cone tab** — `create_vol_cone_chart` wires `vol_cones.py` (5/25/50/
   75/95 realized-vol bands across 10d…252d, current RV dots coloured by
   band position) into Scope's Vol View.
2. **Term-structure time-travel ghost overlay** (signature) — faint −7d /
   −30d curves behind today's, so a parallel-shift / twist / flatten is
   one static glance. Zero new controls or queries.
3. **Regime-encoded IV/HV background** — contiguous `vol_regime` runs become
   faint `vrect` bands (now that the column persists). Silent no-op if null.
4. **Daily auto-narrative banner** (`analytics/narrate.py`, 10 tests) — one
   plain-English sentence above the fold: verdict + IV-HV premium + cone
   stretch + earnings proximity, with a spike-contamination caveat. No LLM.

Deferred brilliancies (build-later): full per-strike smile (data, §5),
dedicated spike-contamination KPI badge (the narrative already surfaces
it), skew-percentile badge, IV/RV z-score strip, Cmd-K palette, dual-ticker
compare. All catalogued by the swarm.

---

## 5. The one real gap: per-strike option snapshots

The single most valuable next build is a **snapshot pipeline**:
`scrape` persists per-strike rows into `options_snapshots` with IV computed
by VolScope's **own BSM Newton-Raphson solver** (never Yahoo's IV) and
delta populated. That unlocks (a) the true HIVG smile view, (b) the live
skew-EM card, (c) per-name skew history. It is the prerequisite for the
"5th core view" to be real rather than empty. Everything needed (own
solver, `options_snapshots` schema, `build_smile`/`compare_smiles`) already
exists — only the write path is missing.

---

## 6. Test status

- Touched-area no-network subset: **green** (analytics, nav, properties,
  golden, narrate, charts, cones — ~206 tests).
- Full fast suite (`-m "not slow and not integration and not perf and not
  ibkr"`): the pre-fix run was 1765 passed / 6 nav failures (all fixed); a
  fresh full run was launched after the fixes — see the branch CI / latest
  run for the final count.
- `make verify-all` stages were pruned (the broken `leaps_render` gate and
  the backtest stage removed).
- Environment note: this session's sandbox could not reach FRED, so every
  scrape-touching test paid 4×10s timeouts — slow here, fast in CI.

---

## 7. Honest verdict

The **core is materially better and materially smaller**: the bot/backtest
surface is gone, ~48 verified bugs are fixed (including a CRITICAL silent
data-loss and a self-introduced 100×-rate regression), the two orphaned
core-view modules are wired, and the hero page now speaks in plain
English. It is a genuinely cleaner, more trustworthy IV-research tool than
it was.

It is **not "everything done forever"**: the per-strike smile pipeline
(§5) and two deferred contract fixes (§3) remain. Those are scoped,
documented, and non-blocking — they need their own verified passes, not a
rushed one. That honesty is the point: shipping an empty smile tab would
have re-created exactly the "untüftelte Tools" this refocus removed.
