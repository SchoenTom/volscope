# Operator Guide

For the human running VolScope. Not for agents — agents read `WELCOME-AGENT.md`
and `memory/INDEX.md`.

VolScope is an IV-research workbench. It scrapes option chains and
underlying history, computes volatility analytics, and surfaces them in
a Streamlit dashboard. It does **not** place orders — you read the
signals here and trade in your own broker.

## Starting the app

```bash
# Refresh today's data only if missing, then launch the dashboard
make start
# Or launch directly against whatever is already in the DB
make run
```

`make start` checks DB freshness and runs the scrape only if today's
data is absent. `make run` is hardened against the Streamlit stdin
email prompt (runs headless with usage stats off).

## Refreshing data manually

```bash
# Pull EOD underlying + chain snapshots into DuckDB
.venv/bin/python -m volscope.data.scrape
```

Yahoo `impliedVolatility` is never trusted — VolScope recomputes IV
from the bid/ask mid via its own Newton-Raphson solver. Yahoo IV is
rate-limited (~360 req/hour/IP) so refreshes are EOD-oriented.

## Reading the dashboard

Pages, by nav group:

| Page | What it answers |
|---|---|
| Discover | Which names have the richest / cheapest vol right now. |
| Scope | Deep single-ticker view: IV/HV term structure, skew, history. |
| Heatmap | Cross-sectional IV richness across the universe. |
| Earnings Hub | Upcoming prints + implied move vs historical move. |
| Vol Insights | Regime + GARCH forecast context for the forward 30 days. |
| Scanner | Filterable cross-sectional screen on vol metrics. |
| Alerts / Watchlist | Custom ticker groups + threshold alarms (Telegram + macOS). |
| Options Lab | Per-name chain inspection and what-if pricing. |

Deep-link views (Rotation / Flow / Research / Mega-Scan) hang off the
same pages.

## Releasing a stuck DB lock

DuckDB allows one writer at a time. If a scrape died mid-write and the
UI cannot open the DB:

```bash
make unlock
```

## Backups

DuckDB has no point-in-time recovery — back up via `EXPORT DATABASE`:

```bash
make backup
make restore-drill   # rehearse a restore into a scratch dir
```

See `docs/BACKUPS.md` for the encryption-key handling.

## Things you must NEVER do

1. **Force-push to main.** Branch protection forbids it; `CONTRIBUTING.md`
   documents the recovery procedure.
2. **Trust Yahoo's `impliedVolatility`.** Always recompute from the
   bid/ask mid via the BSM solver.
3. **Run two writers at once.** The UI is read-only; only the scraper
   writes. `make unlock` if a lock is stuck.
