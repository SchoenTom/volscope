# VolScope Master Plan — Product Maturity & Cross-Page Weave

> **Status**: draft 2026-05-16. Author: Tom + Claude Opus 4.7.
> **Scope**: turn VolScope from "powerful but disconnected tool collection"
> into "guided workflow product that walks a newcomer from question to
> trade decision without them needing to know which page does what".
>
> **Hard constraint**: no new bugs. Every change is measured before/after.
> Every step ships independently. The product can be paused at any
> commit and still be more useful than the day before.

---

## 0 — Why this plan exists

VolScope today has **23 pages** with strong individual analytics
(Skew-adjusted EM, Vol Regime, LEAPS Convergence, Bot, etc.). The
gap is not capability — it's **workflow**:

1. A newbie loads the dashboard and faces a 23-entry sidebar with no
   suggested order of operations.
2. Once on a page, the next-step is implicit. From Discover → "click
   ticker → land on Scope" works, but Scope doesn't tell the user
   *"now what?"*.
3. Many pages duplicate concepts under different names (Watchlist on
   Sidebar vs Alerts on Command Center vs Watchlists in Discover).
4. Some powerful features hide deep inside pages with no entry point
   (Skew-adjusted EM on Vol Insights, but a Pre-Trade user never
   sees it).
5. Newbie language gaps: "IV percentile 80" needs to read as "this
   stock's options are pricier than 80 % of the past year" the first
   time the user sees it.

This plan converts those 5 gaps into 5 work streams. Each is
incremental, atomic, testable.

---

## 1 — Vision in one sentence

> **A user opens VolScope, types one ticker, and the product walks
> them — page by page, with breadcrumbs and "next step" prompts —
> from "is this interesting?" to "this is the trade I'd place".**

Three personas the product should serve at v1.0:

| Persona | Journey | Today's gap |
|---|---|---|
| **Newbie** ("Tom's friend Lukas") | Hears about an earnings play, wants to know if it's rich/cheap, sizing | No guided flow; lands on Discover and gets lost |
| **Operator** (Tom) | Daily pre-market scan → watchlist refresh → 1-2 deep dives → 0-1 paper trade | Works but switches sidebar 8+ times for one trade |
| **Bot supervisor** | Sees what the bot wants to do, signs off / blocks | Bot dashboard exists but isn't woven into the operator flow |

---

## 2 — The four-act workflow architecture

The product has **four logical phases** of any vol-research session.
Every page maps to exactly one phase. The sidebar groups them
visually + numerically.

```
   ① SCAN           ② INVESTIGATE         ③ STRUCTURE          ④ EXECUTE
  ─────────         ──────────────         ────────────         ──────────
   What's          What is this           What's the           What do I
  interesting?    actually doing?         right trade?         actually do?

  Discover        Scope                   Pre-Trade            Options Lab
  Heatmap         Vol Insights            Builder              LEAPS Lab
  Rotation        Earnings Hub            Strategy presets     Bot dashboard
  Mega-Scan       Research                Portfolio           Backtest
                  Flow                                         Alerts/Command
```

**Cross-page weave rule**: every page MUST render a "→ next step"
footer that points the operator to the most likely next page given
the page's current selection state.

Examples:
- **Discover** ticker row → footer: *"Selected NVDA? Take it to Scope for the
  deep dive (Vol View + Price View + IV regime)."*
- **Scope** showing PYPL → footer: *"Want to price a trade? → Options Lab
  with PYPL preselected. Or scan the option chain → Vol Insights."*
- **Options Lab** with a long call set up → footer: *"Save as paper trade
  → Portfolio. Or define an alert at break-even → Alerts."*
- **Bot dashboard** with a queued intent → footer: *"Approve / reject —
  goes straight to `bot_audit_chain`."*

Implementation: a new **`render_next_step_footer(page_name, context)`**
helper in `volscope/ui/components/next_step.py`. Every page calls it
exactly once at the bottom. Context is `{ticker, page_state, ...}`.

---

## 3 — Five work streams (each independent, atomic, paus-safe)

### Stream A — "Newbie language" tooltips on every metric (P0)

**Problem**: "IV Rank 82" requires three pieces of context (what's IV,
what's Rank, what's 82 in this context). A newbie clicks past it.

**Solution**: every KPI label has a `help="…"` tooltip with one
plain-language sentence that defines the term *and* says how to read
the current value. Already partially done in some pages — make it
consistent.

**Standard template**:

> "IV Rank (`current_value`/100) — `<plain reading of what current_value means>`.
> Higher = options more expensive than this name's own past year."

**Effort**: ~3 hours. Touches: every page render. Risk: zero (text only).

### Stream B — "Where you are + where you go" header strip (P0)

**Problem**: 23 sidebar pages, no breadcrumb, no orientation.

**Solution**: a single 24px header strip on every page that reads:

```
   ① SCAN  →  ② INVESTIGATE  →  ③ STRUCTURE  →  ④ EXECUTE
                  ▲ you are here (Scope · NVDA)
```

Phase highlighted by current page. Ticker badge if the page is
ticker-scoped. Click any phase → jump to that phase's default page.

**Effort**: ~4 hours. One new component, one wire-in per page (mostly
a one-line addition near each page's `st.markdown("## ...")`).
Risk: low (additive, no logic change).

### Stream C — Unified "Next Step" footer (P1)

**Problem**: User finishes reading a page and has no idea what to do
next. Manual sidebar-hunt.

**Solution**: `render_next_step_footer(page, ctx)` as described in §2.
Each page declares its 2-3 likely next steps via a static config in
`volscope/ui/components/next_step.py`:

```python
NEXT_STEPS = {
    "Discover": [
        ("Scope",       "Deep-dive the highlighted ticker"),
        ("Vol Insights", "Asymmetric move + OI heatmap"),
        ("Pre-Trade",   "Size a trade now"),
    ],
    "Scope": [
        ("Vol Insights", "Skew + OI map for {ticker}"),
        ("Options Lab",  "Price a trade on {ticker}"),
        ("Pre-Trade",    "Build a position spec"),
    ],
    ...
}
```

Footer renders as 2-3 right-aligned buttons that pre-populate the
target page's ticker context (re-uses existing `NavIntent` pattern).

**Effort**: ~6 hours (1 helper + 23 page config entries + tests).
Risk: low (only adds buttons, no existing flow changes).

### Stream D — Consolidate duplicated concepts (P1)

**Problem**: "Watchlist" means three different things across the app:
- **Sidebar alerts watchlist**: live alert-rule status (just shipped)
- **Sidebar user watchlists**: TradingView-style ticker groupings (just shipped)
- **Discover starter pack**: implicit "first 8 tickers" reference

**Solution**: one **canonical concept = Watchlist**, two **roles**:
- **Alarms**: configured per-list, fire via Telegram/desktop
- **Display**: shown on Discover (filter chips), Heatmap (highlighted
  cells), Scope (status pill)

Plus: rename "Watchlist (alerts)" sidebar section → "**Active alerts**"
to remove the name collision.

**Effort**: ~5 hours. Risk: medium (touches Discover/Heatmap filtering
logic — needs tests).

### Stream E — Onboarding wizard rewrite (P2)

**Problem**: current Onboarding page (4 steps) exists but operator
feedback (Tom) says "I forget what the bot mode means". Newbie
abandons before they understand IV regime classification.

**Solution**: 5-step wizard with **live preview** for each concept:

1. **Welcome** — 30-sec video / GIF showing one full workflow
2. **Your first ticker** — input → live IV-Rank + Regime card →
   "good times to trade this name"
3. **What an option does** — interactive payoff diagram, slide the
   strike → see payoff change
4. **Long-vol vs Short-vol** — when each works (with IV regime
   cross-reference)
5. **Your first watchlist** — pick 3-5 tickers, regime alarms on,
   "we'll ping you when one enters CHEAP"

After completion: redirect to **Discover** with the new watchlist
filter applied. The operator's first real action is a guided one.

**Effort**: ~8 hours (mostly content, some interactive components).
Risk: low (isolated to Onboarding page).

---

## 4 — Cross-page weave — concrete navigation graph

This is the explicit list of "from → to" links each page must
expose. Forward links via the new footer; backward via breadcrumb
strip.

| From | Suggested next steps |
|---|---|
| Discover | Scope · Vol Insights · Pre-Trade |
| Heatmap | Scope · Discover (filter) · Rotation |
| Rotation | Flow · Scope (per sector leader) |
| Flow | Rotation · Scope (per ticker) |
| Mega-Scan | Scope · LEAPS Lab |
| Scope | Vol Insights · Options Lab · Pre-Trade · Earnings Hub |
| Vol Insights | Options Lab (price the EM) · Pre-Trade (build short-premium spread) |
| Earnings Hub | Vol Insights (event premium) · Pre-Trade |
| Research | Scope (re-test on different ticker) · Backtest |
| Pre-Trade | Options Lab (refine) · Portfolio (save) · Alerts (notify) |
| Builder | Options Lab · Pre-Trade |
| Options Lab | Pre-Trade · LEAPS Lab · Portfolio |
| LEAPS Lab | Dossier · Pre-Trade |
| Dossier | LEAPS Lab · Backtest |
| Backtest | Research · Bot |
| Bot | Command Center · Portfolio |
| Portfolio | Scope (per position) · Backtest |
| Alerts | Command Center · Watchlists (sidebar) |
| Command Center | Bot · Alerts · Pre-Trade |
| Earnings Trades | Earnings Hub · Portfolio |

Every entry above translates to one row in `NEXT_STEPS`. The footer
helper picks the top 3 by context (e.g. only show "Options Lab" if a
ticker is selected).

---

## 5 — Simplification audit (remove or merge)

Current page count = **23**. Realistic target = **15-17**.

Candidates for merge / removal:

| Pages | Action | Reason |
|---|---|---|
| `Heatmap` + `Discover` (filter) | KEEP both | Different UX (visual treemap vs ranked list) — both add value |
| `Rotation` + `Flow` | KEEP both | Different timeframes (sector regimes vs daily flows) |
| `Scope` + `Vol Insights` | KEEP separate | Scope = single-ticker history; Vol Insights = chain math |
| `Earnings Hub` + `Earnings Trades` | **MERGE** to "Earnings" with tabs | Two pages today, one workflow |
| `Pre-Trade` + `Builder` + `Options Lab` | KEEP separate | Different abstraction levels (idea → spec → pricer) |
| `LEAPS Lab` + `Dossier` | **MERGE** to "LEAPS" with tabs | Dossier is "open trade view" of LEAPS Lab |
| `Mega-Scan` | **DEPRECATE** | Functionality subsumed by Discover + Heatmap |
| `Research` | KEEP | Statistical gauntlet is a power-user tool |
| `Signals` | **EVALUATE** | If it duplicates Bot's signal log, merge |

Net: **23 → 19** with no capability loss.

**Effort per merge**: ~4-6 hours each. Risk: medium (test surface
changes).

---

## 6 — Performance principles (codified)

Profile-driven, never speculative.

1. Any page must render in **< 1.5 s on warm cache** (already met
   by all 23 pages per the 2026-05-15 multi-page probe).
2. Cold boot **< 25 s** end-to-end (currently 23 s on `~/dev/`).
3. Every new DB query MUST go through `cached_data.py` helpers OR
   come with a profile justification.
4. No SQL `LIKE %X%` on `daily_vol` without a sector pre-filter.
5. Plotly charts >800 traces MUST use `scattergl` or a treemap
   reduction.
6. Streamlit `cache_data` TTL is *always* explicit (no defaults).

These are already mostly enforced; codifying them as `.claude/rules/perf.md`
makes them automatic for future contributors.

---

## 7 — Bug-prevention discipline (codified)

Already shipped (v0.9.4-9.6) but worth pinning:

- ON CONFLICT DO UPDATE for every upsert (no DELETE+INSERT).
- `_to_py_scalar` cast on every DB-bound value.
- `safe_history` / `safe_option_chain` wrappers for all yfinance.
- Module-level singletons (executors, caches) not per-call.
- Schema-drift audit on every release (compare migrations/*.sql to
  database.py CREATE TABLE).
- Pytest must be green BEFORE push (1916/1916 today).

Codify in `.claude/rules/perf.md` + `.claude/rules/db-safety.md`.

---

## 8 — Ship plan (8 weeks, 4 milestones)

### Milestone M1 — Orientation (Week 1-2)
- Stream B: phase-header strip on every page
- Stream A: tooltip pass (P0 metrics first: IV Rank, IV Percentile,
  Skew, Expected Move, Vol Regime)
- Stream C: next-step footer helper + Discover/Scope wire-in

Definition of done: a newbie can navigate any of the 4 phases with
≤ 1 click and read the active page's primary KPIs without a
glossary.

### Milestone M2 — Weave (Week 3-4)
- Stream C: next-step footer on remaining 21 pages
- Stream D: Watchlist consolidation
- Watchlist sidebar widget connects to alarm dispatch (done — verify)

Definition of done: every "from → to" entry in §4 works with one
click, ticker context preserved.

### Milestone M3 — Onboarding (Week 5-6)
- Stream E: 5-step wizard rewrite with live previews
- Glossary page (Help expansion) explaining 15 core terms

Definition of done: a tester who has never traded options can finish
the onboarding and place their first paper trade in ≤ 10 minutes.

### Milestone M4 — Consolidate (Week 7-8)
- Earnings Hub + Earnings Trades merge
- LEAPS Lab + Dossier merge
- Mega-Scan deprecation (folded into Discover)
- Signals page evaluation

Definition of done: 19 (or fewer) sidebar entries, no functionality
lost, all tests green.

---

## 9 — Risk register

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Breaking existing operator-saved state (session_state keys) | Medium | High | Preserve all current keys; new keys only |
| Tooltip overload — too many "?" icons clutters UI | Low | Medium | Apply Pareto: tooltip only the 20% of KPIs that confuse 80% of newbies |
| Phase-header strip eats vertical space | Medium | Medium | Strip is 24 px max, collapsible via session-state toggle |
| Cross-page weave creates circular nav (Scope → Pre-Trade → Scope) | Low | Low | Footer hides current-page entries; breadcrumb shows path |
| Page merges break operator muscle memory | High | Medium | Keep old names as aliases for 1 release; deprecate in v1.1 |
| New "wizard" Onboarding skipped by power users | Medium | Low | Persistent "Skip" + `onboarding_complete=True` flag (already exists) |

---

## 10 — Open questions for the operator

Before I start, **three decisions need your input**:

1. **Phase-header strip placement**: top-of-page (after page title) or
   replace the existing sub-tab labels? Recommendation: top-of-page,
   single line, doesn't replace existing structure.

2. **Footer position**: bottom of page (after main content) or sticky
   right rail? Recommendation: bottom (less screen real-estate
   contention with charts).

3. **Page merges in M4**: Earnings Hub + Earnings Trades and LEAPS
   Lab + Dossier — both have separate URL-bookmarkable behaviour
   today. Are you OK breaking bookmarks for v1.0? Recommendation:
   yes, redirect old paths to new tab anchors.

---

## 11 — Definition of v1.0 product maturity

VolScope reaches v1.0 when:

- [ ] All 4 milestones (M1-M4) shipped
- [ ] ≥ 95 % of pages have a next-step footer
- [ ] ≥ 80 % of KPIs have plain-language tooltips
- [ ] Onboarding completion rate (operator self-test): 1 newbie places
      first paper trade within 10 min, alone
- [ ] No regressions in the 1916-test suite + the multi-page probe
- [ ] PRE_LAUNCH_REPORT.md status: GO for paper bot (live IBKR still
      gated by Phase 4 separately)
- [ ] Zero `except Exception: pass` in the data pipeline (currently
      ~5 — all in render fallbacks)
- [ ] Schema-drift audit clean (currently clean as of 2026-05-16)

---

## 13 — Implementation discipline (how we ship bug-free)

This section answers the operator's 2026-05-16 question:
*"Wie schließen wir Bugs aus, implementieren optimal, verknüpfen mit
Vorhandenem und arbeiten sauber?"*

### 13.1 — Per-stream acceptance criteria

A stream is NOT done until ALL of these are true:

| Criterion | How verified |
|---|---|
| `py_compile` clean on every touched file | `find . -name "*.py" -exec python -m py_compile {} +` |
| Pytest 1916 tests still green | `pytest tests/ --ignore=tests/perf -q` |
| No new `except: pass` introduced | `git diff` review + `.claude/agents/security-reviewer.md` |
| Streamlit boot < 25 s | curl-poll until HTTP-ready, measured |
| Playwright multi-page probe — 0 stException | `/tmp/multipage_probe.py` re-run |
| Inline assert proves the new helper's math | `python -c "from X import Y; assert Y(...) == ..."` |
| Memory file updated if scope crossed a stream boundary | edit `~/.claude/.../volscope-v0.9.3-state.md` |

If any one of these fails → revert the commit, never patch-forward.

### 13.2 — Integration map (what we touch, what we DON'T)

The plan touches ONLY these surfaces. Everything else is invariant.

| Stream | Touched | Untouched (do not modify) |
|---|---|---|
| A — Tooltips | `help=` kwarg on existing `st.*` calls; KPI-card `title` HTML | Analytics math, DB schema, render order |
| B — Phase strip | New file `phase_header.py`; one `render_phase_header()` line per page | Page logic, KPI computations, charts |
| C — Next-step footer | New file `next_step.py`; one `render_next_step_footer()` line per page | NavIntent mechanism (already battle-tested) |
| D — Watchlist consolidation | `sidebar.py` section names; `discover_page.py` filter chips | watchlist persistence + dispatch (just shipped) |
| E — Onboarding rewrite | `onboarding_page.py` only | Other pages |
| M4 — Page merges | `app.py` registry + sidebar nav groups | merged pages' render functions (kept verbatim, just exposed as tabs) |

This list is the *operator's contract* — if a diff touches anything
outside its row, the reviewer rejects.

### 13.3 — Test coverage per stream

| Stream | New tests | Existing tests run |
|---|---|---|
| A | None — pure cosmetic | Full 1916 suite |
| B | `tests/test_phase_header.py` — render returns valid HTML for each page, falls back silently on unknown page | Full suite + multi-page probe |
| C | `tests/test_next_step.py` — every page in `NEXT_STEPS` resolves to a real page in `app._PAGE_REGISTRY` | Full suite + multi-page probe |
| D | `tests/test_watchlist_consolidation.py` — Discover filter chip honours user-watchlist membership | Full suite + watchlist persistence tests |
| E | `tests/test_onboarding_wizard.py` — each step renders without exception under AppTest | Full suite + AppTest perf-smoke |
| M4 | Test that old-name page paths still load (redirect via session_state) | Full suite |

### 13.4 — Failure-mode catalog

Per stream, the most likely break, and how we detect / fix:

| Stream | Likely break | Detector | Recovery |
|---|---|---|---|
| A | Tooltip text contains `{ticker}` that wasn't substituted | grep diff for `{` in `help=` | Replace literal or use f-string |
| B | Phase header makes pages too tall on small screens | Playwright viewport probe @ 1366×768 | Reduce strip to 20 px or make collapsible |
| C | Footer click navigates but ticker context lost | Session-state log inspection | NavIntent payload checked at every footer site |
| D | Discover filter shows ZERO tickers when user-watchlist is empty | AppTest with empty watchlist DB | Show "your watchlist is empty — add tickers" hint |
| E | Wizard step 3 (payoff diagram) crashes for users with no DB data | AppTest with empty DB | Fall back to synthetic example chain |
| M4 | Merged-page tab order surprises operator muscle memory | manual test + operator sign-off | Keep tab order matching original page registry order |

### 13.5 — Rollback playbook

Every stream is **one commit per concern**. If a commit ships a bug:

1. `git revert <sha>` on main — never amend a pushed commit.
2. Reopen the corresponding task as `in_progress`.
3. Document what broke in `docs/decisions.md` (post-mortem).
4. Reattempt only after the failure-mode is in §13.4.

This is the same pattern that worked for the iCloud-migration and
seed-FATAL fixes (v0.9.5 → 9.6, no rollbacks needed because of strict
atomic discipline).

### 13.6 — How we link to what's already there

We DO NOT re-implement. The plan re-uses these existing pieces
verbatim:

| Existing | Re-used in | Where |
|---|---|---|
| `volscope.ui.components.navigation.NavIntent` + `nav_to()` | All cross-page links (Stream C) | Footer helper |
| `volscope.ui.components.cached_data` (60s/300s/600s TTL helpers) | All new DB queries | Phase-header `current_phase_from_state()` |
| `volscope.persistence.watchlists` (just shipped) | Stream D | Discover filter chip |
| `volscope.alerts.regime_alarm_dispatch` (just shipped) | Stream D follow-on (cron + auto-fire) | Already wired |
| `.claude/rules/ui.md` (Plotly `go` only, no `st.metric`, `rgba()` helper) | Every new render | Phase strip uses rgba; new tooltips never use `st.metric` |
| `.claude/rules/perf.md` (every new query through cached_data) | All streams | Enforced by reviewer |
| `volscope.ui.styles.theme.COLORS` + `rgba()` | Phase header, footer | Single design-token source |
| `volscope.utils.timing.instrument` decorator | Every new helper > 50 ms expected | Profile-driven; only add when needed |

If a new helper would duplicate ≥ 5 lines of an existing helper,
the reviewer rejects the diff with "use the existing one".

### 13.7 — Definition of "saubere Arbeit"

Operator-facing translation: clean work means

1. **One commit = one logical change** (not "and also ...").
2. **Commit message explains WHY, not WHAT** (the diff already
   shows what).
3. **No dead code** — if a helper is added but not called yet, the
   commit also adds the first caller in the same diff.
4. **No magic numbers** — every literal threshold has a named
   constant + a comment explaining why that value.
5. **No silent fallbacks** — every `except:` either re-raises or
   logs with operator-visible context.
6. **`Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>`**
   trailer on every commit (so the human/AI division is auditable).

If a diff fails any of these → revert, re-do.

---

## 12 — What I will do RIGHT NOW vs ASYNCHRONOUSLY

**Right now (next 30 min)**: deliver this document, get your sign-off
on the three §10 decisions.

**This session (next 2 hours, if you say go)**: ship M1 in full
(phase-header strip + tooltip-pass on top-15 KPIs + next-step footer
on Discover + Scope). Commit per stream. Push.

**Next session**: M2.

**Asynchronous**: I'll keep the `docs/MASTER_PLAN_PRODUCT_MATURITY.md`
under version control. Every milestone checkpoint updates this file
(check boxes, change log) so we always have a single source of truth
for the v1.0 roadmap.
