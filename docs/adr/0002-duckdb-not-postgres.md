# ADR-0002: DuckDB over Postgres for the bot DB

## Status

Accepted — 2026-05-14.

## Context

VolScope needs a transactional database for trade lifecycle, audit logs,
P&L history, and chain snapshots. The realistic options:

1. **DuckDB** (embedded, columnar, single-tenant).
2. **Postgres** (server, row-oriented, multi-tenant by default).
3. **SQLite** (embedded, row-oriented).

Constraints:

- Single operator. No multi-tenant requirement.
- Read-heavy workload (analytics queries scan millions of option-chain
  rows for percentile / aggregate computations).
- Writes are low-frequency (a dozen trades / day + EOD scrapes).
- Operator-friendliness: must be backupable with `cp` and inspectable
  with a one-liner.

## Decision

Use DuckDB as the single storage engine.

## Consequences

- **Positive — analytics speed**: columnar storage + vectorised execution
  makes the 252-day rolling-window queries that drive IV rank/percentile
  10-50× faster than Postgres for our access pattern.
- **Positive — operability**: one file. `cp volscope.db backup-$(date).db`
  is a complete snapshot. No server to admin.
- **Positive — Python ergonomics**: `duckdb.connect(path)` + zero
  network latency.
- **Negative — single writer**: DuckDB takes an exclusive lock on the
  file. Concurrent writers (UI + scheduler + scraper) collide. Mitigated
  by `scripts/ops/release_db_lock.py` and the `make unlock` target;
  long-term the scheduler is the sole writer with the UI in read-only
  mode.
- **Negative — no native UUID type**: TEXT primary keys for trade_id /
  signal_id. Accepted.
- **Negative — partial indexes not supported**: noticed during Phase 1
  migration 001 (had to drop the partial WHERE clause on
  `idx_bot_trades_status_open`). Workaround: full index + WHERE in queries.

## When to revisit

- If we ever go multi-operator (unlikely for a personal bot).
- If chain-snapshot volume exceeds 100 GB and DuckDB's single-file
  approach becomes a backup pain.
- If we need streaming-write semantics that DuckDB's locking can't
  accommodate.

Until then, the embedded-DB choice is correct and we should not
over-engineer.
