# VolScope — Unified Master Plan

Consolidation of every directive the operator has given across this
session, sequenced by leverage. This is the **single source of truth**
for "what's next" — every other roadmap doc defers to this one.

## Status as of 2026-05-14

✅ Repo live at github.com/SchoenTom/volscope (private)
✅ v0.2.0 foundation + v0.3.0 paper engine pushed
✅ TOOLS.md catalog + README repositioning
🔧 CI re-running (uv → pip migration)
⏳ Branch protection pending
⏳ Operating System framework pending
⏳ Math Validation (Prompt 2) pending
⏳ Performance & UX (Prompt 5) pending

---

## The 4 outstanding mega-asks

### MEGA-1 — Operating System framework

**Source:** User's "Meta-Prompt" message demanding TodoWrite-enforced
sessions, self-updating CLAUDE.md, persistent `progress.md`,
`docs/decisions.md` flat log, `.claude/{agents,skills,commands,rules}/`
structure, Tool Workflow Standards.

**Why:** Every future session benefits. Loses ~zero alpha to other
asks. ~1 hour.

**Deliverables:**
- [ ] `progress.md` at repo root (session-state, <50 lines, distinct
      from historical `progress.json`)
- [ ] `docs/decisions.md` (CEO log — lighter than ADRs, one block per
      decision)
- [ ] CLAUDE.md "Tool Workflow Standards" section (Bug fix workflow,
      Feature workflow, Research workflow)
- [ ] CLAUDE.md "Hard Commands" reference table
- [ ] CLAUDE.md "Gotchas" section (extend the existing developer-guide
      notes into an explicit Gotchas list — plotly fillcolor, st.metric,
      DuckDB locking, etc.)
- [ ] CLAUDE.md "Session Boot Sequence" (5-step ritual at session start)
- [ ] `.claude/agents/` (empty — placeholder for future custom subagents)
- [ ] `.claude/skills/` (empty — placeholder for future user-invocable skills)
- [ ] `.claude/commands/` (empty — placeholder for slash commands)
- [ ] `.claude/rules/` (empty — placeholder for project-specific rules)

### MEGA-2 — Math Validation (Prompt 2 in 5-prompt sequence)

**Source:** User's "Mathematical Validation" mega-prompt + the
"all data must be perfect for paying customers" directive.

**Why:** This is the gate that separates hobby from production.
Without it, signals are plausible but not provable. ~3-4 hours.

**Deliverables:**
- [ ] `tests/golden/test_bs_hull.py` — 30+ Hull (10th ed) reference
      values for price + Δ + Γ + Θ + Vega + ρ
- [ ] Property tests via Hypothesis (1000+ examples):
      - Put-call parity: `C - P = S - K·e^{-rT}`
      - Greeks bounds: 0 ≤ |Δ_call| ≤ 1; Γ ≥ 0; Vega ≥ 0
      - Analytical-vs-numerical Δ within 1e-3
      - IV solver round-trip recovery within 1e-4
- [ ] Edge-case tests: T=0, σ=0, deep OTM/ITM, negative rates, very long T
- [ ] HV-estimator validation: generate log-normal returns with known σ,
      recover via CC/Parkinson/Garman-Klass/Yang-Zhang
- [ ] Strike-selection at target delta (interpolation between brackets)
- [ ] IVR vs IVP definitional tests + single-spike contamination
- [ ] Date arithmetic (NYSE business days, 3rd-Friday expiries, weeklies)
- [ ] `notebooks/validation.ipynb` — VolScope-vs-py_vollib plots for
      visual confirmation
- [ ] `docs/MATHEMATICAL_FOUNDATIONS.md` — LaTeX formulas + citations
      + known approximation limits

### MEGA-3 — Per-page UI tooltips + descriptions

**Source:** User's "ausführliche beschreibungen hinzufügen" +
"VolScope soll ein produkt werden, leute sollen dafür zahlen" +
"alle tools funktionieren, synergien genutzt werden, die ganze seite
ergibt richtig viel sinn".

**Why:** Today a new user lands on Discover with no idea what it's for.
Tooltips + a "what is this page" banner per page = product-grade UX.
~2 hours.

**Deliverables:**
- [ ] Each Streamlit page (17 pages) gets a top-banner with:
      - 1-line: what is this
      - 1-line: when do I use it
      - "Learn more →" link to `docs/TOOLS.md` section
- [ ] Sidebar tooltip on each nav item (hover = same 1-liner)
- [ ] First-run onboarding modal (already exists at `volscope/ui/views/onboarding_page.py`
      — extend with a tour of the 5 most-used pages)
- [ ] In-page glossary: hover over IV / IVR / IVP / VRP / Greeks shows
      a one-sentence definition

### MEGA-4 — Performance & UX Turbo (Prompt 5 in 5-prompt sequence)

**Source:** User's "Performance & UX Turbo" mega-prompt + product-grade
expectation.

**Why:** Sub-200ms page renders + power-user features (Cmd+K palette,
keyboard shortcuts, fragment refresh) make the difference between
"this is OK" and "this is delightful". ~3 hours.

**Deliverables:**
- [ ] Polars for hot paths > 100k rows
- [ ] DuckDB pragmas tuned for read-heavy workload
- [ ] Streamlit fragment-based refresh on Bot Dashboard (5s autorefresh
      per section, not whole-page)
- [ ] Plotly WebGL for the large IV-percentile heatmap
- [ ] DiskCache for expensive computations (HMM fit, GARCH fit,
      backtest replay)
- [ ] Loading skeletons + optimistic UI on slow operations
- [ ] Cmd+K command palette (jump to any page, search any ticker)
- [ ] Keyboard shortcuts: j/k navigation; hjkl in tables; / for search
- [ ] Per-page render benchmarks in `tests/test_perf_smoke.py`
- [ ] Footer with commit-SHA stamping (operator always knows which
      code is running)

---

## Quick-wins worth doing alongside

These are short (≤30 min each) but high-impact items found while
re-reading the conversation:

- [ ] **Watch CI → branch protection.** Once green, lock main.
- [ ] **Smoke-test the live Bot Dashboard** with a real DB to confirm
      empty-state rendering looks right (no `null` literals, no
      truncation).
- [ ] **`bot_signals_log` snapshot_date column type** — current INSERT in
      Bot Dashboard query may collide with existing schema. Verify.
- [ ] **`scripts/scrape/scrape_chains.py` smoke run** — pull 1 ticker
      (SPY), persist 1 snapshot, confirm `get_quote()` returns it.
- [ ] **Update `memory/INDEX.md`** to reference TOOLS.md and MASTER_PLAN.md.

---

## Execution sequence (this session + next)

### This session (remaining budget: ~2-3 hours)

1. **MEGA-1 — Operating System framework** (1 hour, highest leverage —
   benefits every subsequent ask).
2. **Branch protection on main** once CI green (10 min).
3. **MEGA-3 partial — per-page banners** for the 5 most-used pages
   (1 hour — Command, Discover, Signals, Scope, Bot).
4. Commit + push.

### Next session

1. **MEGA-2 — Math Validation** (the big confidence-gate).
2. **MEGA-3 finish — remaining 12 pages + onboarding tour**.
3. Smoke-test live + iterate on visible bugs.

### Session after

1. **MEGA-4 — Performance & UX Turbo**.
2. **Wire scheduler to real handlers** (start the paper engine
   running daily).
3. **30-day paper run** generates real `bot_*` data for the dashboard.

---

## Open questions for operator (non-blocking)

- Free vs paid product split — does the bot become paid-tier later?
  ("Leute sollen dafür zahlen" suggests yes.)
- License flip timeline — when do we flip to MIT and announce?
- Co-maintainers — who else gets CODEOWNERS rights?
- Tier hosting — local-only forever, or eventually a hosted version?
