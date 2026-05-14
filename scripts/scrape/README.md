# scripts/scrape/

Data ingestion: fetch raw market data and write it into DuckDB.

- `daily_scrape.py` — main EOD scrape (universe-wide).
- `scrape_earnings_meta.py` — earnings dates + confirmation metadata.
- `post_earnings_capture.py` — after-earnings IV crush snapshot.
- `capture_signals.py` — daily signal log capture for the Bot Dashboard.
