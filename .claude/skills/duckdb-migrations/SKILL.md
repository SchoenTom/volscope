---
name: duckdb-migrations
description: This skill should be used when authoring a new DuckDB schema migration or troubleshooting an existing one. Covers the apply_migrations runner, reserved-word list, partial-index gotcha, and the seed-row pattern.
---

# DuckDB migrations — `apply_migrations()` runner

## File naming

`volscope/persistence/migrations/NNN_short_name.sql`. Numbers must
increment. `apply_migrations()` glob-sorts lexically, so always use
zero-padded 3-digit prefixes.

Current migrations:

| File | Purpose |
|---|---|
| `001_init.sql` | 5 `bot_*` core tables + bookkeeping |
| `002_killswitch.sql` | single-row state table |
| `003_chain_snapshots.sql` | `bot_chain_snapshots` + `bot_chain_latest` view |
| `004_order_intents.sql` | pre-trade UUID idempotency |
| `005_audit_chain.sql` | SHA-256 hash-chained audit log |

## Runner contract

`volscope/persistence/db.py::apply_migrations(conn)`:

- Reads the `bot_migrations` bookkeeping table (creates it if missing).
- Applies each unapplied `*.sql` in lexical order.
- Splits on top-level semicolons (string-aware — won't break SQL with
  semicolons in string literals).
- Records each application in `bot_migrations`.
- Idempotent — re-running is a no-op.

## Reserved-word landmines

DuckDB rejects these column / object names as bare identifiers:

| Reserved | Use instead |
|---|---|
| `right` (SQL string function) | `option_right` |
| `position` | `pos` or `position_id` |
| `interval` | `time_range` |
| `current_user`, `session_user` | `actor` |
| `default` | `default_value` |
| `desc`, `asc` | `direction` |

Always check the [DuckDB keyword list](https://duckdb.org/docs/sql/keywords)
before naming a column.

## Partial indexes — NOT supported

DuckDB does not implement `CREATE INDEX ... WHERE ...`. If you try:

```sql
CREATE INDEX idx ON tbl(col) WHERE status NOT IN (...)
```

You get `Not implemented Error: Creating partial indexes is not
supported currently`. Workaround: full index + use `WHERE` in queries.

## Seed rows

For single-row state tables (e.g. `bot_killswitch`), seed at migration
time with:

```sql
INSERT INTO bot_killswitch (id, active) VALUES (1, FALSE)
ON CONFLICT (id) DO NOTHING;
```

The `ON CONFLICT (pk) DO NOTHING` makes re-runs safe.

## Sequences for autoincrement

DuckDB doesn't have `SERIAL`. Use:

```sql
CREATE SEQUENCE IF NOT EXISTS bot_audit_seq;
CREATE TABLE bot_audit_chain (
    seq BIGINT PRIMARY KEY DEFAULT nextval('bot_audit_seq'),
    ...
);
```

## Foreign keys

DuckDB enforces FKs only on INSERT (not on cascading DELETE/UPDATE).
That's fine for our append-only audit pattern but matters if you ever
want cascading behaviour.

## Views vs materialised tables

For "latest-per-key" patterns (e.g. `bot_chain_latest`), use a VIEW:

```sql
CREATE OR REPLACE VIEW bot_chain_latest AS
SELECT s.* FROM bot_chain_snapshots s
JOIN (SELECT ticker, MAX(snapshot_ts) AS t FROM bot_chain_snapshots GROUP BY ticker) m
  ON s.ticker = m.ticker AND s.snapshot_ts = m.t;
```

DuckDB queries the view fast enough that materialisation is rarely worth
the staleness.

## Testing a new migration

1. Add migration `NNN_xxx.sql`.
2. Write test in `tests/test_persistence_<table>.py`:
   - `apply_migrations` succeeds.
   - Idempotent on second run.
   - Inserting a synthetic row + reading it back works.
3. `pytest tests/test_persistence_*.py -x` — green required.
4. Bump migration count in any doc that references it.

## When NOT to write a migration

- Adding an index on an existing table to speed up a query — just do
  `CREATE INDEX IF NOT EXISTS` in `apply_migrations()` (it's idempotent).
- Adding a single seed row — use `ON CONFLICT DO NOTHING`.
- For PURE backfills of existing rows — write a one-off Python script
  in `_one_off/` (gitignored), not a migration.
