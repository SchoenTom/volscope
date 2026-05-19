# Master Plan — 2026-05-19 Operator Round

> Source: operator session log + frustration message. Eight items
> across four buckets (critical bugs · feature requests · UX clarity
> · documentation). Plan-first per the operator's explicit
> instruction ("MASTER PLAN FIRST").

---

## Inventory of issues (verbatim → categorized)

### Critical bugs (page crashes / wrong numbers)

**B1 — Vol Insights crash (DauerFehler):**
```
TypeError: unsupported format string passed to NoneType.__format__
  File volscope/ui/components/pretrade_skew_em.py:199
  f'· PCR: {result.overall_pcr:.2f}   '
```
When the OI heatmap result returns `overall_pcr=None` (no calls or
no puts in the slice), the format string blows up the whole page.
Root cause: missing `is not None` guard before `:.2f`.

**B2 — Options Builder gibt massiv falsche Werte:**
```
Strategy: Long Call DAX K=$45 premium $2.77
HEBEL          1,610.0×       ← WAY too high
OMEGA          85,018.88      ← WAY too high
LEVERAGE       0.2×           ← inconsistent with HEBEL
CAPITAL @ RISK $27,876        ← 100× too high (should be $277)
NOTIONAL       $4,461
AUFGELD P.A.   +43.2%
```
Inspection:
- Notional 4,461 = 1 × 100 × $44.61 spot → correct
- Capital @ Risk $27,876 = 100 × $278.76 → double-multiplied (the
  premium itself is already per-share, multiplying by 100 once is
  correct, twice gives the bogus number)
- HEBEL 1610× — likely computed against the bogus Capital @ Risk
- LEVERAGE 0.2× = 4461/27876 — uses the same bogus denominator
- AUFGELD P.A. wrong because of bogus underlying scale

Plus: "DAX" being priced at $44.61 is suspicious — DAX index is at
~18,000. Whatever resolved DAX → $44.61 is a wrong ticker mapping
(maybe DAX → some other security on a regional exchange).

**B3 — LEAPS Lab "Open Dossier" button funktioniert nicht:**
Click does nothing. Need to inspect the click handler — likely
either NavIntent path broken or the destination Dossier page can't
find the prefill state.

**B4 — Quickstart braucht ~15min für 842 Ticker:**
`make quickstart` runs `seed-full` which iterates the entire
universe at ~3s/ticker. Operator wants 1-2 min boot. The fast
target already exists (`make quickstart-fast`, single-ticker SPY) —
problem is the default README/CLAUDE.md still points to
`quickstart`. Need to either change the default or make
`make quickstart` itself seed only the watchlist tickers.

### Feature requests

**F1 — Earnings Hub toggle "nur Watchlist-Ticker anzeigen":**
Page already has a "Only tickers in my portfolio" toggle. Add a
parallel "Only tickers in my watchlists" toggle (operator's daily
workflow is watchlist-driven, not portfolio-driven).

**F2 — Alerts page: nur Watchlist-Alerts:**
Today the Alerts page runs a universe-wide scanner (`scan_alerts`
finds anomalies across every ticker in DB → 241+ alerts). Operator
wants this scope-restricted: **only alerts for tickers in his
watchlists** unless he explicitly opts in to universe-wide.

### Documentation / clarity

**D1 — Notification mental model unclear:**
Operator's questions:
1. "Bleibt meine Watchlist immer erhalten?"
   → YES. Persistence in DuckDB `watchlists` + `watchlist_items`
     tables. Survives Streamlit restart, app close, OS reboot. The
     only thing that wipes it is `make backup` + restore from older
     snapshot, or manual DB delete.
2. "Erhalte ich Benachrichtigungen wenn VolScope AUS ist?"
   → YES if the cron job `scripts/ops/check_alarms.py` is
     scheduled (e.g. via launchd). NO if no cron exists. Need a
     one-command setup so this is dead-simple.
3. "Erhalte ich Benachrichtigungen wenn Auto-Refresh nicht aktiviert?"
   → YES. Auto-Refresh is UI-side (page reload cadence); the cron
     alarm path is process-independent and fires regardless of
     whether the UI is open / refreshing / asleep.
4. "Wie erhalte ich die Benachrichtigungen?"
   → Telegram (if `TELEGRAM__BOT_TOKEN` + `TELEGRAM__CHAT_ID` set
     in `.env`) + macOS desktop notification (osascript, no setup).
5. "Steht im Alert auch was passiert (z.B. DAX IV rank < 20)?"
   → YES since `6b47341` — alarm body includes alarm type, current
     value vs threshold, regime, spot, source watchlist, Scope
     deep-link. Operator just hasn't seen one fire yet because the
     legacy default was no alarms enabled.

Need to surface ALL of this on a single "Notifications" help page
(or inline tooltip on the Watchlist alerts panel).

---

## Solution sketches

### B1 — Vol Insights crash
File: `volscope/ui/components/pretrade_skew_em.py:199`
Fix: wrap the format call with a None guard:
```python
pcr_str = (f"{result.overall_pcr:.2f}"
            if result.overall_pcr is not None else "—")
f'· PCR: {pcr_str}   '
```
Apply same guard to every other `f'{x:.2f}'` in that file (defense
in depth). Add a property test: pass a chain with only-calls or
only-puts → rendered string is finite, not raises.

### B2 — Options Builder leverage math
1. Find every spot where `capital @ risk` is computed.
2. Confirm whether the bug is a double 100× multiplication or a
   premium-in-cents-vs-dollars mismatch.
3. Add a leg-level sanity invariant: for a single long call,
   `capital_at_risk == premium_per_share × n_contracts × 100`.
4. Add a UI-side assertion / warning when computed leverage > 200×
   or capital_at_risk diverges by >10× from notional.
5. Separately investigate DAX → $44.61 resolution — looks like the
   ticker resolver is mapping "DAX" to the wrong symbol. Add a
   defensive check: index-symbol tickers (DAX, SPX, NDX, RUT,
   ^VIX) should resolve via Yahoo `^GDAXI`, `^SPX`, etc., not
   bare-stock substitution.

### B3 — LEAPS Open Dossier
1. Find the click handler — probably writes to session_state then
   `st.rerun()`.
2. Check whether the destination Dossier page reads that key on
   render.
3. If the path is via `NavIntent`, make sure the destination is
   registered. If via session_state, make sure both ends use the
   same key name.

### B4 — Quickstart default
Two options:
- **A** Make `make quickstart` alias to `quickstart-fast` (single
  ticker SPY) — operators add what they want via the sidebar.
- **B** Make `make quickstart` seed only watchlist tickers if any
  exist, else fall back to SPY.

Prefer B because it preserves restored-session state. Implement
via the already-existing `seed-watchlist` target — just chain it
into `quickstart`.

Also: update README + CLAUDE.md to point to this faster path. The
operator pasted the old README quickstart command directly, so the
docs are the actual source of frustration.

### F1 — Earnings Hub watchlist filter
File: `volscope/ui/views/earnings_hub_page.py`
Find the existing `Only tickers in my portfolio` toggle. Add a
sibling `Only tickers in my watchlists` toggle. AND-them together
(both filters active → intersection; either alone → that filter).
Read watchlist tickers via `list_watchlists(db)` → flatten.

### F2 — Alerts page watchlist scoping
File: `volscope/ui/views/alerts_page.py`
Add a toggle near the category filter: `Scope: [my watchlists |
full universe]`. Default to **watchlists**. When watchlists, pass a
ticker-allowlist into `scan_alerts(db, allow_tickers=…)`. Need to
add `allow_tickers` parameter to `scan_alerts`.

### D1 — Notifications help
New page or expandable block on the Watchlist page:

```markdown
# How alerts work

**Persistence**
Your watchlists live in the local DuckDB. They survive everything
short of a manual DB delete.

**Channels** (configured via .env)
1. Telegram — TELEGRAM__BOT_TOKEN + TELEGRAM__CHAT_ID
2. macOS desktop notification — no setup, always on
3. Log line at WARNING level — always emitted

**When alerts fire**
- The cron job (scripts/ops/check_alarms.py) runs every 30 min
  during NYSE business hours (09:00–21:00 NY time, weekdays).
- It walks every watchlist's enabled alarm types and pings you
  via the channels above.
- It runs INDEPENDENTLY of the Streamlit UI — you don't need the
  UI open or auto-refresh active.

**Alert content**
Each alarm includes:
  - Title with the ticker + alarm type icon
  - Current value vs. configured threshold
  - Current vol regime + spot price
  - Source watchlist name
  - One-click Scope deep-link

**Setup (one command)**
```bash
make schedule-alerts    # registers a launchd job that runs
                        # check_alarms every 30 min
```
```

Need to actually add the `make schedule-alerts` target + a launchd
plist generator.

---

## Execution order

1. **B1 Vol Insights** (smallest, one-line fix, unblocks page)
2. **B3 LEAPS Open Dossier** (small, important — operator clicked
    and it did nothing)
3. **B4 Quickstart-fast default** (small, big UX win)
4. **B2 Options Builder leverage** (medium — needs math audit)
5. **F1 Earnings Hub watchlist toggle** (medium)
6. **F2 Alerts watchlist scope** (medium)
7. **D1 Notifications help** (docs + new launchd helper)

Each step → atomic commit → push. Live-browser verification after
each. No batching.

---

## Definition of done

- B1: Vol Insights renders for SPY, DAX, ^VIX without exception
- B2: Long Call SPY K=ATM premium $5 shows HEBEL ≈ 1× (not 1000×),
  Capital @ Risk = premium × 100 × contracts
- B3: Click "Open dossier" on LEAPS Lab → Dossier page loads with
  pre-filled ticker
- B4: `make quickstart` finishes under 2 min on a fresh checkout
- F1: Earnings Hub has a Watchlist-filter toggle that actually
  filters the grid
- F2: Alerts page defaults to watchlist scope; counter on the
  sidebar reflects this
- D1: New "How alerts work" expander visible on Watchlist page
  AND new `make schedule-alerts` target works

Live-browser regression run after every commit. Push at the end.
