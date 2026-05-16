# Interactivity Audit — Ist-Stand vor Cross-Tool Weaving Phase

> Snapshot 2026-05-16. Goal: document what state primitives, navigation
> mechanisms, and cross-page links already exist BEFORE we start
> rewiring. Without this, the hardening phase risks duplicating
> infrastructure or breaking the working pieces.

## 1. Was bereits existiert (gut)

### 1.1 `NavIntent` + `nav_to()` — cross-page navigation primitive

`volscope/ui/components/navigation.py` (95 LOC) ist die **single
canonical cross-page transition primitive**. API:

```python
nav_to(NavIntent(page="Scope", ticker="PYPL", source="Discover",
                 payload={"strike": 400}))
```

- 13 files nutzen es bereits
- Mutiert `st.session_state["active_page"]`, `selected_ticker`,
  `prefill_<page>`, `nav_source`
- `consume_prefill(page)` ist read-and-clear (verhindert leaking)
- `render_breadcrumb(...)` rendert "◈ {page} · {ticker} ← from {src}"

**Diese Infrastruktur ist solide.** Wir bauen darauf auf, ersetzen
sie nicht.

### 1.2 `render_next_step_footer` + `NEXT_STEPS` graph

`volscope/ui/components/next_step.py` (M1.B, commit `18e30eb`). Jede
non-terminale Page rendert einen Footer mit 2-3 context-aware
Buttons → nutzt `nav_to` intern.

### 1.3 `render_phase_header` — 4-Phasen-Orientation

`volscope/ui/components/phase_header.py` (M1.A, `abf9f9b`). Jede Page
zeigt aktive Phase + Ticker-Badge oben.

### 1.4 `glossary.py` — single source of truth für Tooltips

`volscope/ui/components/glossary.py` (M1.D, `db3e55c`). 21 KPI-Terms,
Scope KPI-row + Vol Insights cards nutzen es bereits.

### 1.5 5-Stufen Onboarding (M3)

Newbie-Flow: Welcome → Pack → Loading → First-Ticker-Preview →
First-Watchlist (`5d170ce`).

## 2. Was fehlt (Cross-Tool Weaving Gaps)

### 2.1 Kein zentraler State Store (Single Source of Truth)

44 unique `st.session_state` keys über UI verteilt. **selected_ticker**
wird in 16 Pages referenziert — aber als ad-hoc string-key, ohne typed
Schema. Risiko: typo in einem Page bricht Kontext.

Gaps:
- Kein `AppState` Dataclass
- Kein hydrate-from-URL bei Boot
- Kein typed access pattern (autocomplete für ticker, time_range,
  sector_filter)
- Kein page-history-tracking für Back-Navigation

### 2.2 Kein URL Deep-Linking

`st.query_params` wird genau EINMAL benutzt — in
`sidebar.py:880` für `?dev=1` dev-mode toggle. Sonst nichts.

Operator kann KEIN `?ticker=SNOW&page=Scope` URL teilen.

### 2.3 Kein Ticker-Quick-Switch

Sidebar hat einen Ticker-Picker, aber der ist Page-spezifisch
(landet auf der aktiven Page). Keine "tippe SNOW, springe nach
Scope" Universal-Action.

### 2.4 Kein Cross-Tool-Awareness Layer

Beispiele wo Pages "blind" sind:
- Scope zeigt einen Ticker — aber NICHT "du hast eine offene Position"
- Earnings Hub zeigt Events — aber NICHT "du hast 2 Trades zu diesen Tickern"
- Pre-Trade baut einen Trade — aber NICHT "der letzte ähnliche Trade hatte X% return"
- Portfolio zeigt Position — aber NICHT "earnings in 5 Tagen"

### 2.5 Klickbare Datenpunkte selektiv

Heatmap-treemap ist klickbar (M1.A-Era). Discover-Tabelle hat
ranked rows, einige davon klickbar via Buttons. Scanner-Liste:
unklar. Mega-Scan: unklar. Portfolio rows: unklar.

Audit pro Page (siehe §3) zeigt wer was kann.

### 2.6 Visual Affordances inkonsistent

Streamlit `st.button` rendert nativ als pressable, OK. Aber für custom
HTML data points (z.B. KPI-grid cells in Scope) gibt es keinen
hover-state oder pointer-cursor — User weiß nicht was klickbar ist.

### 2.7 Keine Toast-Notifications bei Nav-Events

User klickt "→ Scope", Page wechselt, aber kein "Switched to Scope
for PYPL" Feedback. Streamlit hat `st.toast()` (since 1.27) — nicht
genutzt.

## 3. Per-Page Audit — was sind die Sackgassen

| Page | Selected_ticker source | Cross-links rein | Cross-links raus | Sackgasse? |
|---|---|---|---|---|
| Discover | session_state | M2.A footer + ticker rows | Scope, Mega-Scan, Vol Insights | nein |
| Heatmap | jump-selectbox | nav_to via cell-click | Scope | nein |
| Scope | session_state | nav_to from many | Vol Insights, Options Lab, Pre-Trade | nein |
| Vol Insights | session_state | M2.A footer | Options Lab, Pre-Trade, Scope | nein |
| Pre-Trade | session_state | nav_to from Scope/Command | Options Lab, Portfolio, Alerts | nein |
| Options Lab | session_state + ol_ticker | nav_to from Pre-Trade | Pre-Trade, LEAPS, Portfolio | nein |
| LEAPS Lab | session_state | nav_to from Discover/Mega-Scan | Dossier (embedded), Pre-Trade | nein |
| Portfolio | none (lists all positions) | nav_to to Scope-per-position | Scope, Backtest | **partial** — Position-rows could be richer |
| Earnings Hub | session_state | nav_to from Command | Earnings Trades (embedded), Vol Insights, Pre-Trade | nein |
| Bot | none | nav_to from Backtest | Command, Portfolio | **partial** — Bot signal log lacks clickable rows |
| Rotation | session_state | nav_to from Heatmap | Flow, Scope | nein |
| Flow | session_state | nav_to from Rotation | Rotation, Scope | nein |
| Alerts | none | next-step → Command | Command | **partial** — Alert rows lack ticker-click |
| Command Center | session_state | many | Bot, Alerts, Pre-Trade | nein |
| Backtest | session_state | nav_to from Dossier | Research, Bot | nein |
| Research | session_state | nav_to from Backtest | Scope, Backtest | nein |
| Builder | session_state | nav_to from Scope/Pre-Trade | Options Lab, Pre-Trade | nein |
| Scanner | session_state | next-step → Scope | Scope, Heatmap | **partial** — Scanner result rows could click → Scope |
| Mega-Scan | session_state | nav_to via cards | Scope, LEAPS | nein |
| Signals | none | next-step → Bot | Bot, Pre-Trade | **partial** — Signal log lacks click-through |

**Partials**: Portfolio, Bot, Alerts, Scanner, Signals — ihre data
rows könnten klickbarer sein. Das sind die **§N.C Clickable Affordances**
Targets.

## 4. Wo der Workflow heute bricht

Tom-Beispiele aus der Brief:
- "Discover → SNOW gesehen → muss zu Scope neu tippen"
  → Heute schon via Discover-row-click teilweise gelöst, aber inkonsistent
- "Pre-Trade Idee → kein klick zu Builder"
  → Pre-Trade has nav_to(Builder) — checked but works via NavIntent
- "Earnings Hub → meine offenen Trades nicht sichtbar"
  → Earnings Trades is embedded as expander (M4.B, commit `b6dd96e`) —
    but the AWARENESS (event-line shows "you have N trades on this ticker")
    is missing. **This is §N.D target.**

Konkret bestätigte Sackgassen: keine — jede Page hat raus-Link. Aber
**Awareness und Bidirektionalität** fehlen.

## 5. Was wir nicht haben — und brauchen

| Concept | Status | Where to land |
|---|---|---|
| AppState dataclass | missing | §N.A new `volscope/ui/state/store.py` |
| URL deep-linking | missing (1 use of dev=1) | §N.A hydrate from `st.query_params` on boot, sync on nav |
| Page history / breadcrumbs | NavIntent has `source` but no chain | §N.B extend `render_breadcrumb` |
| Ticker quick-switch (sidebar) | missing | §N.B new component, persistent |
| Bidirectional awareness cards | missing | §N.D Scope shows portfolio+earnings refs |
| Toast on nav | missing | §N.E one-liner in `nav_to` |
| Hover cursor on clickables | partial | §N.E CSS in theme.py |

## 6. What we DON'T touch (out-of-scope this phase)

- analytics/* — math is fine
- data/*  — pipelines work
- persistence/* — schemas stable
- New pages — phase is about WEAVING existing
- Performance — separate phase
- Re-designs of individual pages — only ADD wiring

## 7. Risk Register (this phase)

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| State-store migration breaks 16 pages that use `st.session_state["selected_ticker"]` | High | High | **Don't migrate.** New store wraps session_state, both APIs work in parallel. Old keys remain canonical. |
| URL params override user's in-page selection on rerun | Medium | Medium | Hydrate ONCE on first boot; subsequent reruns use session_state |
| Toast spam on every nav | Low | Low | Only toast on cross-page nav (page change), not in-page rerun |
| Sidebar quick-switch collides with existing ticker-picker | Low | Medium | Place above existing picker, label clearly, use distinct keys |
| Cross-tool awareness cards on Scope add latency | Medium | Low | Cache portfolio + earnings queries via existing `cached_data.py` helpers (60s TTL) |

## 8. Definition of Done (per master plan §13.1)

Each sub-phase ships only when:
- py_compile clean
- 1930+ pytest still green
- Inline assert validates new helper math/contract
- No existing keys changed (only added)
- Memory + master plan updated if scope crossed milestone
