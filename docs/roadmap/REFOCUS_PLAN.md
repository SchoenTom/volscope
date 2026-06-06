# VolScope Refocus Plan — „Zurück zum Kern: IV-Charts + Datenebene"

> Status: **PROPOSED** (2026-06-05). Erarbeitet von einem 7-Agenten-Schwarm
> (5 Audits → Architekt → adversarialer Kritiker), danach von Hand gegen den
> echten Code verifiziert. Kritiker-Korrekturen sind in diesem Dokument bereits
> eingearbeitet. Kanonischer Pfad: `~/dev/VolScope` (NICHT `~/Desktop/VolScope`).

---

## 0. CEO-Entscheid (die eine Frage)

VolScope beantwortet **genau eine Frage**: *„Ist die implizite Volatilität hier
zu teuer oder zu billig — und um wie viel?"*

Alles, was diese Frage nicht direkt beantwortet, verlässt die Default-Navigation
und wird gelöscht oder in „Labs" geparkt. Der Trading-Bot, Paper-Engine, IBKR,
Backtest-Apparat, LEAPS-Lab-Dossier, ML-Signale, Kelly-Sizer, Sektor-Rotation,
Strategy-Builder und Portfolio-Journal sind **kein Kern** und werden entfernt.

**Nicht-Ziele:** kein Order-Routing, keine Live-/Paper-Trades, kein Backtest-
Produkt, keine ML-Vorhersage. VolScope ist ein **Research-Workbench**, kein Bot.

---

## 1. Zielprodukt — 5 Kern-Views + 1 Frage

| View | Beantwortet | Speist sich aus |
|---|---|---|
| **IV-Rank / IV-Percentile** (mit Spike-Contamination-Badge) | Ist IV historisch teuer/billig? | `iv_robustness.py`, `iv_thresholds.py`, `daily_vol` |
| **Vol-Cone** (über Horizonte) | Wo liegt IV vs. realisierte Bandbreite? | `vol_cones.py`, `historical_vol.py` |
| **Term-Structure** (mit Earnings-Flags) | Contango/Backwardation, Event-Buckel? | `front_back_iv.py`, `earnings_fetcher.py` |
| **Skew / Smile** (pro Expiry, Spread-Qualität) | Wie ist die Schiefe bepreist? | `iv_smile.py`, `chain_scraper.py` |
| **Expected-Move-Cards** (IV- vs. HV-implied) | Was preist der Markt an Bewegung ein? | `expected_move.py`, `earnings_expected_move.py` |

Jeder View trägt **sichtbar**: Daten-Frische, Berechnungsqualität (eigener BSM-
Newton-Raphson, niemals Yahoo-IV), und ein Klartext-Label „diese Zahl bedeutet X".

**Ziel-Navigation (10 statt 27 Seiten):**

```
RESEARCH:  Discover · Scope · Heatmap · Earnings Hub · Vol Insights · Scanner · Alerts
MANAGE:    Watchlist · Command (entkernt) · Options Lab (entkernt)
           Help (immer unten)
```

---

## 2. Architektur nach Refocus

```
volscope/
  data/          # IV-Datenebene — KEEP (inkl. chain_scraper); CUT paper_trader, ibkr_scraper
  analytics/     # Reine Mathematik — KEEP BSM/HV/Cones/Smile/Robustness/ExpectedMove/signal.py
                 #                    CUT kelly_sizing, paper_backtest, leaps_backtest, signals*
  alerts/        # KEEP alert_engine (reiner IV-Threshold); CUT regime_alarm_dispatch
  research/      # KEEP walk_forward + statistical_tests (keine Bot-Deps)
  persistence/   # KEEP Migrationen für Kern-Tabellen; CUT audit_chain, db.py, Bot-Migrationen
  ui/views/      # 10 Seiten (s.o.)
  ui/components/ # unverändert außer sidebar.py (2 Gruppen statt 4)
  # GELÖSCHTE Pakete: execution/  lifecycle/  risk/  scheduler/  orchestration/  signals/
```

**Wichtige Erkenntnis (selbst verifiziert):** Kein Kern-Modul importiert Bot-Code.
Der Bot hängt am Kern, nicht umgekehrt → saubere Abtrennung möglich.

---

## 3. KEEP-Liste (Kern — nicht anfassen außer Bugfix)

**Daten:** `options_scraper.py`, `price_fetcher.py`, `yfinance_safe.py`,
`earnings_fetcher.py`, `risk_free.py`, `freshness.py`, `ticker_resolver.py`,
`ticker_universe.py`, `fundamentals.py`, `database.py`, `vol_index_fetcher.py`,
`data_validation.py`, **`chain_scraper.py`** ← Kritiker-Korrektur: reiner yfinance-
Wrapper, speist den Smile in Vol Insights. KEIN Bot-Code.

**Analytics:** `black_scholes.py`, `historical_vol.py`, `vol_cones.py`,
`iv_smile.py`, `iv_robustness.py`, `expected_move.py`, `earnings_expected_move.py`,
`earnings_crush.py`, `earnings_backtest.py`, `backtest.py` (reine Mathe, von
scope_page genutzt), `data_quality.py`, `vol_metrics.py`, `iv_thresholds.py`,
`edge_score.py`, `ml_signal.py`, **`signal.py`** ← Kritiker-Korrektur: Singular!
Wird von `backtest.py`, `metric_components.py`, `position_sizing.py`,
`iv_thresholds.py` importiert. **`position_sizing.py`** (von command_center genutzt).

**Sonstiges:** `alerts/alert_engine.py`, `research/walk_forward.py`,
`research/statistical_tests.py`.

**UI:** `scope_page`, `discover_page`, `heatmap_page`, `vol_insights_page`,
`earnings_hub_page`, `watchlist_page`, `scan_page`, `alerts_page`,
`command_center_page` (nach Positions-Strip), `options_lab_page` (nach Paper-Buy-
Strip), `components/sidebar.py`.

---

## 4. CUT-Liste (entfernen)

**Ganze Pakete (echte Blätter, 0 Reverse-Deps vom Kern):**
`execution/`, `lifecycle/`, `risk/`, `scheduler/`, `orchestration/`, `signals/`
(nach ivr/ivp-Umzug).

**Daten:** `paper_trader.py`, `ibkr_scraper.py`.
~~chain_scraper.py~~ → **bleibt** (Kritiker-Korrektur).

**Persistence:** `audit_chain.py`; `db.py` (erst nach Umstellung von
`make migrate`, s. §6); Bot-Migrationen `002_killswitch`, `004_order_intents`,
`005_audit_chain`, `009_bot_trades_actor`.

**Analytics:** `paper_backtest.py`, `kelly_sizing.py`, `leaps_backtest.py`,
`signals.py` (Plural, nach Signals-Seite weg), `signal_backtest.py`.

**Alerts:** `regime_alarm_dispatch.py`.

**UI-Seiten:** `bot_dashboard_page`, `signals_page`, `earnings_positions_page`,
`strategy_builder_page`, `portfolio_page`, `pretrade_page`, `backtest_page`,
`leaps_page`, `leaps_dossier_page`. `rotation_page` + `flow_page` → aus Sidebar
raus, Dateien als „Labs" behalten (Analytics-Deps am Leben lassen).

**Scripts:** `ops/reconcile.py`, `ops/run_paper_engine.py`, `ops/preflight.py`,
`ops/full_review.py`, `ops/install_alarm_scheduler.py`, `audit/verify_chain.py`,
`backtest/run_leaps_backtest.py`, `scrape/capture_signals.py`. `ops/check_alarms.py`
+ Makefile-Target `check-alarms` (s. §6).

**Tests (mit ihren Targets löschen — Kritiker-Ergänzungen fett):**
`test_execution_ibkr_stub`, `test_intent_manager`, `test_lifecycle_machine`,
`test_scheduler_jobs`, `test_risk_killswitch`, `test_risk_locks`,
`test_persistence_killswitch_migration`, `test_paper_trader`, `test_audit_chain`,
`test_kelly_sizing`, `test_leaps_backtest`, `test_signal_factors`,
`test_signal_composite`, `test_signal_filters`, `test_signal_ranking`,
`test_perf_signal_generation`, `test_full_review`, **`test_signals.py`**,
**`test_chain_snapshots.py`**, **`test_persistence_db.py`**, **`TestIBKRStub`-Klasse
in `test_term_structure.py`**.

**Dependencies (`pyproject.toml`):** `ib_async`, `apscheduler`, `sqlalchemy`,
`transitions`, `orjson` aus `[bot]`-Extras; `xgboost` aus Main-Deps (0 Import-Sites).
`hmmlearn`/`arch` vorerst behalten (Tests dran, keine Reliability-Wirkung).

---

## 5. Refactor-vor-Cut: 7 Tangles (in dieser Reihenfolge)

1. **ivr/ivp** in `signals/factors.py` → nach `analytics/iv_thresholds.py` kopieren
   (reine Mathe, ~20 Zeilen), Import in `test_iv_robustness.py` umbiegen. **Dann**
   `signals/` löschbar.
2. **paper_trader** top-level importiert in `strategy_builder_page.py:24` &
   `earnings_positions_page.py:24` → diese Seiten zuerst löschen. Danach lazy-
   Imports in `earnings_hub_page.py:933`, `options_lab_page.py:381/414` strippen.
3. **backtest.py** top-level in `scope_page.py:9-16` → Importe lazy in den Backtest-
   Tab verschieben (= Reliability-Fix 7). `backtest.py` bleibt.
4. **signals.py + signal_backtest.py** top-level in `signals_page.py:24/27` →
   Seite zuerst raus, dann Module löschen. **Auch `tests/test_signals.py` löschen.**
5. **command_center_page.py** rendert `db.get_positions()` (Z. 655/1214/1225) +
   `_positions_table_html`. Chirurgisch strippen; `ml_signal`/`edge_score`/
   `position_sizing`-Importe bleiben (Kern). Ungenutzte Importe danach via ruff weg.
6. **earnings_hub_page.py** bettet „Earnings Trades"-Tab ein (Z. 162-165) → Embed
   vor Löschen von `earnings_positions_page.py` entfernen.
7. **chain_scraper / vol_insights** (Kritiker): `chain_scraper.py` **bleibt** → kein
   Strip nötig. (Falls je gecuttet: erst `_cached_chain_fetch` in vol_insights stubben.)

---

## 6. Demolition-Sequenz (Blatt-zuerst, nach jedem Schritt `make pre-merge-check`)

> Voraus (Kritiker-Pflicht, sonst brechen die Gates):
> **A.** `scripts/verify/verify_all.py`: `stage_leaps_render` aus `STAGES` entfernen
> oder `is_gate=False` (steht aktuell auf `True` → `make verify-all` ist schon rot).
> `stage_backtest` ebenso prüfen.
> **B.** Makefile `pre-merge-check`: mypy-Pfade `volscope/{signals,risk,lifecycle,execution,scheduler}`
> durch `volscope/{analytics,data,ui}` ersetzen (sonst „No such file"-Rauschen).

1. **Wave-1-Blätter:** `execution/`, `lifecycle/`, `risk/`, `scheduler/`,
   `orchestration/` + Tests löschen. Verifizieren: `grep -rn` auf diese Pakete in
   `volscope/{ui,analytics,data}` = 0 Treffer.
2. **Analytics-Blätter:** `paper_backtest.py`, `kelly_sizing.py`,
   `leaps_backtest.py`, `alerts/regime_alarm_dispatch.py` + Tests.
3. **ivr/ivp-Umzug** (Tangle 1) → `make pre-merge-check`.
4. **Bot-UI-Seiten** aus `_PAGE_REGISTRY` (app.py) + Disk: Bot, Signals, Earnings
   Trades, Builder, Portfolio, Pre-Trade, Backtest, LEAPS Lab, Dossier.
5. **`signals/` löschen** + alle Signal-Tests + `analytics/signals.py` +
   `signal_backtest.py` + **`tests/test_signals.py`**.
6. **paper_trader aus Seiten strippen** (Tangle 2 & 6): earnings_hub + options_lab.
7. **Daten/Persistence löschen:** `paper_trader.py`, `ibkr_scraper.py`,
   `persistence/audit_chain.py`. Für `persistence/db.py`: zuerst `make migrate`
   auf `database.py`-eigenen Runner umstellen **oder** `migrate`-Target entfernen;
   `scripts/audit/verify_chain.py` löschen + Audit-Verify aus pre-merge-check raus;
   **`tests/test_chain_snapshots.py`, `tests/test_persistence_db.py`,
   `TestIBKRStub` in `test_term_structure.py`** löschen.
8. **Bot-DB-Migration 010** `010_drop_bot_tables.sql` (idempotent, `DROP TABLE IF
   EXISTS bot_killswitch/bot_order_intents/bot_audit_chain`). `bot_trades` erst
   droppen, wenn `paper_trader.py` sicher weg. → `make verify-all`.
9. **Sidebar** auf 2 Gruppen (RESEARCH/MANAGE) kürzen; Rotation/Flow aus Nav;
   `_DEEP_LINK_ONLY_PAGES` anpassen.
10. **pyproject/requirements:** Bot-Extras + xgboost raus; `requirements.txt` mit
    pyproject synchronisieren (httpx, pydantic, pydantic-settings, pyyaml,
    structlog, typer ergänzen; pytest/pytest-cov nach dev). `make quickstart` auf
    frischem venv testen. `check-alarms`-Target aus Makefile.
11. **Tests grün:** `test_perf_smoke.py`-Fixture-Pfad fixen; `Watchlist` in
    `phase_header.PAGE_TO_PHASE` + `next_step.NEXT_STEPS`; README „Quick start"→
    „Quick Start"; pytest-Marks `property`/`golden` registrieren. → 0 Failures.

---

## 7. Reliability-Fixes (ZUERST, vor jeder Demolition — Milestone 1)

| # | Fix | Datei | Schwere |
|---|---|---|---|
| 1 | yfinance-Calls über `yfinance_safe`-Timeout (12 s) führen — einzige Stelle im IV-Pfad ohne Hard-Timeout, kann ganzen Scrape 10–20 Min/Ticker hängen | `data/options_scraper.py:176/181/186` | **KRITISCH** |
| 2 | `get_rate()` ohne Argument → TypeError, killt EWG-VDAX-Proxy still → `get_rate(30)` | `data/vol_index_fetcher.py:158` | hoch |
| 3 | `reconnect()` setzt rohen DuckDB-Handle statt `_LockedConnection` → Multi-Tab-Mutex-Crash zurück | `data/database.py:895` | hoch |
| 4 | `daily_scrape` schreibt nie `hv_yz_30d`/`iv_hv_spread_matched` → Spread-Chart auf Seed-Wert eingefroren | `scripts/scrape/daily_scrape.py` | mittel |
| 5 | „Leveraged ETF"/„Crypto ETF" fehlen im IV-Plausibilitäts-Cap | `scripts/scrape/daily_scrape.py` | mittel |
| 6 | `threading.Lock()` um Modul-Cache `_refresh_curve()` (Cold-Boot-Race) | `data/risk_free.py` | mittel |
| 7 | Backtest-Importe in `scope_page` lazy → Import-Fehler killt nicht mehr Hero-Seite | `ui/views/scope_page.py:9-16` | mittel |
| 8 | Default-Landing temporär `Command`→`Discover` bis Command entkernt | `ui/app.py:330` | niedrig |
| 9 | `requirements.txt` ↔ `pyproject.toml` synchron (6 fehlende Kern-Deps) | beide | hoch |
| 10 | Test-Suite auf 0 Failures (s. Schritt 11) | diverse | mittel |

---

## 8. Tooling (für einen Solo-Maintainer, klein gehalten)

- **`/code-review`** (built-in) vor jedem nicht-trivialen Commit; `effort=high` bei
  Änderungen an `options_scraper.py`, `black_scholes.py`, `iv_robustness.py`.
  Checkliste = `.claude/rules/analytics.md`-Invarianten (keine Yahoo-IV, YZ-Default).
- **Pandera-Schemas** auf der `daily_vol`-DataFrame-Grenze vor jedem DB-Write
  (`iv_30d ∈ [0.01, 5.0]`, ticker non-null) → fängt stille NaN vor dem Chart.
- **Streamlit `AppTest`** (schon im Suite) → Daten-Contract-Tests: IV-Cards rendern
  ohne Exception, Expected-Move ∈ [0.5 %, 200 %].
- **launchd-Health-Check** (`scripts/ops/db_health_check.py`, ~20 Zeilen): zählt
  NULL-`iv_30d`, prüft IVR/IVP nicht beide 0, letztes Scrape-Datum = heute.
- **`make pre-merge-check`** als Pflicht-Gate (ruff+mypy+pytest) — keine neuen
  Skip-Marks ohne Eintrag in der Marker-Liste.

---

## 9. Meilensteine

| M | Inhalt | Aufwand | Gate |
|---|---|---|---|
| **M1** Reliability First | Fixes 1–10, **keine** Cuts | 1–2 Tage | `make verify-all` grün, pytest 0 Fail |
| **M2** Wave-1-Demolition | Schritte 1–2 (5 Bot-Pakete weg) | 1 Tag | pre-merge-check nach jedem Schritt |
| **M3** Wave-2-Demolition | Schritte 3–7 (Tangles, Seiten, paper_trader) | 1–2 Tage | pre-merge-check nach jeder Seite |
| **M4** Sidebar + Deps | Schritte 9–10 | ½ Tag | `make quickstart` frisches venv |
| **M5** Tests grün + Health | Schritt 11 + db_health_check in Cron | ½ Tag | pytest 0 Fail/0 Warn |
| **M6** User-Ready v1 | `make scrape`, 5 Kern-Views auf 3 Test-Tickern validieren, Pandera, `/code-review` | laufend | v1.0 deklarieren |

---

## 10. Risiken (vom Kritiker, einzubeziehen)

1. `strategy_calibration.py` lazy in `discover_page.py:661` — vor künftigem Cut prüfen.
2. `backtest.py` bleibt (kein Bot-Dep); erst löschbar, wenn Backtest-Tab in scope weg.
3. `hmmlearn`/`arch` bleiben in `[bot]`-Extras; `vol_regime.py`/`garch.py` von keiner
   UI importiert — späterer Cleanup, jetzt nicht (Tests dran).
4. Rotation/Flow als Dateien behalten → ihre Analytics-Deps am Leben lassen.
5. `reconnect()`-Mutex-Fix unter 2 parallelen Streamlit-Tabs testen (neuer Test).
6. `hv_yz_30d`-Fix braucht OHLCV im selben `process_ticker()`-Call — Reihenfolge prüfen.
7. `010_drop_bot_tables.sql` muss idempotent sein (`IF EXISTS`).
8. Mega-Scan vorerst behalten (Deep-Link), Überlappung mit Scanner/Discover später bewerten.

---

## 11. Arbeitsweise

- **Branch:** Alles auf `refactor/refocus-core` (Hard-Rule: kein Force/Commit auf
  `main`, pre-commit-Hooks sakrosankt, kein `--no-verify`).
- **Reihenfolge:** M1 (Reliability) **vor** Demolition — erst stabilisieren, dann
  schneiden. Nach jedem Schritt grünes `pre-merge-check`.
- **Verifikation:** kein „fertig" ohne laufendes `make run` + 5 Kern-Views auf
  echten Daten gesichtet (Screenshot), nicht nur grüne Tests.
</content>
</invoke>
