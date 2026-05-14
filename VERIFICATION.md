# VolScope — Verification Reference

**Was?** Eine technische Referenz wie VolScope sich selbst beweist. Wenn `make verify-all` grün ist, ist alles in diesem Dokument gehalten.

**Stand:** 2026-05-10

---

## Der eine Command

```bash
make verify-all
```

→ Schreibt `data/verify/latest.json`. Exit 0 ⇔ alle Korrektheits-Gates passieren.

Beispiel-Output:

```
VolScope verify-all — 2026-05-10T12:34:56+00:00
================================================================================
  … pytest                   ✓ PASS  ( 4.7s)  133 passed in 4.20s
  … external_bsm             ✓ PASS  ( 0.8s)  64 passed, 1 skipped
  … leaps_render             ✓ PASS  (45.3s)  Summary: ✓ PASS test_lab_index ...
  … numeric_consistency      ✓ PASS  ( 0.5s)  9 invariants checked, 0 violations
  … data_quality             ✓ PASS  ( 1.2s)  3/283 suspect (1.1%) — gate ≤ 5 %
  … sector_aggregator        ✓ PASS  ( 4.6s)  Upserted 14008 sector_daily rows.
  … backtest                 ∼ WARN  (12.4s)  3 trades · 67% with non-negative ...
================================================================================
PASS 7 · FAIL 0 · WARN 0 · TOTAL 7
  → data/verify/latest.json
```

---

## Die 7 Stages

### Stage 1 — Pytest (Korrektheits-Gate)

Suite umfasst:

- 7 LEAPS-Module (convergence, sizing, scenarios, pretrade, backtest, pdf, watchlist)
- LEAPS-Dossier-Smoke-Tests
- BSM-External-Validation gegen py_vollib
- BSM-Reference (analytische Werte)
- Yang-Zhang HV gegen Referenz-Werte
- Vol-Metrics

133 Tests + 1 Skip (mathematisch-korrekt: deep-ITM IV-Recovery undefiniert).

### Stage 2 — External BSM (Korrektheits-Gate)

VolScopes BSM gegen `py_vollib` (Industriestandard) auf 9 parametrierten Cases plus 8 analytischen Invarianten:

- Call-Put-Parität (`C - P = S - K e^(-rT)`)
- Premium ≥ Intrinsic
- Call-Delta ∈ [0, 1]
- Put-Delta ∈ [-1, 0]
- Gamma ≥ 0
- Vega ≥ 0
- Premium monoton ↑ in σ
- Premium monoton ↑ in T

**Toleranz:** `1e-10` für Preise und Greeks; `1e-6` für IV-Solver-Round-Trip. **Beobachtet:** `1e-15` (Maschinen-Epsilon) für Preise und Greeks, exakte 0 für meist Greeks.

### Stage 3 — LEAPS Render (Korrektheits-Gate)

`streamlit.testing.AppTest` rendert Lab Index + Dossier headless und prüft 9 visuelle Anker:

- Convergence-Dial-Markup vorhanden
- Score-Bar-Markup vorhanden
- Section-Rule-Markup vorhanden
- KPI-Grid-Markup vorhanden
- EST-Underline / EST-sup vorhanden
- Ticker-Symbol gerendert
- Strike-$ gerendert
- "CONVERG" Caption gerendert
- Sub-Score-Labels (MIS NEG REV) gerendert

Plus Click-Through-Test: Lab → Dossier setzt `dossier_ticker` korrekt.

### Stage 4 — Numeric Consistency (Korrektheits-Gate)

9 Invarianten auf der live-PYPL-Zeile:

| Invariante | Formel | Toleranz |
|---|---|---|
| `strike` | `round(spot × 1.75)` | 0.01 |
| `BE = K + p` | `breakeven = strike + premium` | 0.01 |
| `deployed` | `contracts × premium × 100` | 0.01 |
| `budget cap` | `deployed ≤ budget` | exact |
| `residual` | `budget - deployed = residual` | 0.01 |
| `invalidation` | `spot × 0.80` | 0.01 |
| `scenario t=0` | `matrix(spot×1, 0m).premium = entry` | 0.05 |
| `vega self` | `vega_gain(target=current_iv) = 0` | 0.05 |
| `max loss` | `max_loss = capital_deployed` | exact |

Bei jedem Backfill / Schema-Change re-checked.

### Stage 5 — Data Quality (Korrektheits-Gate)

`composite_quality()` über jede Zeile im latest snapshot. Failure-Rate (Level = SUSPECT) ≤ 5 %. Aktuell: ~1 % (3 von 283).

WARN/PARTIAL/STALE zählen nicht als failure — sie sind UI-surfacing, nicht Korrektheits-Brüche.

### Stage 6 — Sector Aggregator (Korrektheits-Gate)

`scripts/compute_sector_rotation.py` läuft und produziert non-empty `sector_daily`. Aktuell: 14 008 Zeilen × 31 Sektoren.

### Stage 7 — Backtest (Reliability-Gate, kein Exit-Code-Impact)

Walk-forward Backtest läuft, Bootstrap-CI berechnet, p-value gegen Null-Hypothese „mean return = 0" gegeben.

Reliability statt Korrektheit weil:
- Eine schwache Hit-Rate ist Forschung, kein Bug
- Universum-Größe schwankt mit Scrape-State

---

## BSM-Validation im Detail

```python
# Live verifiziert 2026-05-10:
PRICE   max error: 5.33e-15   (effectively zero)
DELTA   max error: 0.00e+00   (exact)
VEGA    max error: 3.55e-15
GAMMA   max error: 0.00e+00
IV-solver round-trip: ≤ 1.4e-13
```

Reference-Cases:

| S | K | T | r | σ | Type | Notes |
|---|---|---|---|---|---|---|
| 100 | 100 | 1.0 | 0.05 | 0.20 | call | ATM, classical |
| 100 | 100 | 1.0 | 0.05 | 0.20 | put | put-call-parity check |
| 100 | 110 | 0.5 | 0.04 | 0.30 | call | OTM short-dated |
| 45.32 | 80 | 2.0 | 0.04 | 0.302 | call | **PYPL deck** |
| 50 | 50 | 0.1 | 0.03 | 0.40 | call | Near-expiry |
| 200 | 150 | 1.5 | 0.05 | 0.25 | call | ITM long-dated, q=2 % |
| 1 | 100 | 1.0 | 0.05 | 0.50 | call | Deep OTM |
| 100 | 1 | 1.0 | 0.05 | 0.50 | call | Deep ITM (skip IV) |

---

## Wenn ein Stage fehlschlägt

| Stage | Häufige Ursache | Erste Schritte |
|---|---|---|
| pytest | neuer Code regressiert | `pytest tests/test_<area>.py -x --tb=long` |
| external_bsm | floating-point pinning verletzt | check `volscope/analytics/black_scholes.py` |
| leaps_render | UI-Komponente fehlt nach Refactor | `python scripts/verify_leaps_pages.py` allein, schau body |
| numeric_consistency | Schema- / Sizing-Refactor | check `volscope/analytics/leaps_*.py` invariants |
| data_quality | yfinance Outage / 280+ Tickers stale | `make scrape` |
| sector_aggregator | DB-Lock von anderer Streamlit-Instanz | streamlit-Prozesse stoppen, retry |
| backtest | DuckDB-Connection-Bug | check Ticker-Universum + history-Length |

---

## Erweiterungs-Punkte

Wenn du eine neue Korrektheitsgarantie hinzufügen willst:

1. Schreib einen self-contained pytest-File (`tests/test_<area>.py`) der bei Verletzung crasht.
2. Füge ihn als Stage in `scripts/verify_all.py` `STAGES` hinzu.
3. Mark `is_correctness_gate=True` wenn ein Fehlschlag bedeutet "VolScope ist gebrochen", `False` wenn Forschungs-Gate.
4. Deploy.

Verify-all rolling time ist bei 70s nach allen Stages — füg Stages in der "billig zuerst"-Reihenfolge hinzu.

---

## Bewährte Pattern für externe Validation

| Was | Wie | Reference |
|---|---|---|
| BSM-Preise | `py_vollib.black_scholes` | shipped |
| Greeks | `py_vollib.black_scholes.greeks.analytical` | shipped |
| IV-Solver | `py_vollib.black_scholes.implied_volatility` | shipped |
| HV-Yang-Zhang | Garman & Klass 1980 closed-form | manuell, fixe Test-Werte |
| Konvergenz-Komponenten | Goyal-Saretto 2009 paper | TODO Phase R5 |
| Live-Chain-Daten | tastytrade IV-Rank-Definition | TODO Phase 0.1 |

---

## Deine TL;DR

- `make verify-all` muss grün sein
- Sind die 9 numerischen Invarianten gebrochen? Stage 4 zeigt's
- Stimmt BSM noch mit Industriestandard? Stage 2 prüft's
- Rendert die UI? Stage 3 simuliert's headless
- Sind Daten frisch + plausibel? Stage 5 + 6 prüfen's

Wenn alles grün → VolScope ist korrekt. Behauptung auditierbar. Kein Aspirational-Copy.
