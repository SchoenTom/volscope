---
paths:
  - volscope/persistence/**
  - volscope/data/database.py
description: DuckDB schema + connection conventions. Applies on every edit to persistence + database modules.
---

# Rules for `volscope/persistence/` + `volscope/data/database.py`

## Single writer, multiple readers

DuckDB takes an exclusive lock on the file. The bot scheduler is the
SOLE writer; UI / dashboards open `read_only=True`. If you hit a lock:
`make unlock` (it kills stale `streamlit` / `python` holders).

## Reserved-word landmines

DuckDB rejects these column names without quoting:

| Reserved | Use instead |
|---|---|
| `right` | `option_right` |
| `position` | `pos` |
| `interval` | `time_range` |
| `current_user`, `session_user` | `actor` |
| `default` | `default_value` |

See `.claude/skills/duckdb-migrations/SKILL.md` for full list +
gotchas.

## No partial indexes

`CREATE INDEX ... WHERE ...` is NOT supported. Use full index + WHERE
in queries.

## No native UUID

DuckDB has no UUID type. Use `VARCHAR` PK and `str(uuid.uuid4())` in
application code.

## Audit-chain immutability

`bot_audit_chain` rows are WRITE-ONCE-READ-MANY. NO code path may:
- `UPDATE bot_audit_chain`
- `DELETE FROM bot_audit_chain`
- Modify `prev_hash` or `entry_hash` directly.

Tests must verify this. Pre-commit `gitleaks` is NOT enough — the
security-reviewer agent (`.claude/agents/security-reviewer.md`) does
this manually.

## SQL injection

Always parameter substitution:

```python
db.con.execute("SELECT * FROM t WHERE id = ?", [user_id])   # OK
db.con.execute(f"SELECT * FROM t WHERE id = {user_id}")     # REJECT
```

f-strings on user input → automatic REJECT in security review.

## Migration naming

`migrations/NNN_short_name.sql` with zero-padded 3-digit prefix.
Lexical sort = application order. See
`.claude/skills/duckdb-migrations/SKILL.md`.

## Backup pattern

- Live DB: `~/Library/Application Support/VolScope/volscope.db` (macOS)
  or `$XDG_DATA_HOME` (Linux).
- Daily snapshot: `EXPORT DATABASE` to `<dir>/backups/<YYYY-MM-DD>/`
  with Parquet + zstd.
- Monthly restore drill via `/restore-drill` command.
- See `docs/BACKUPS.md` for restore-drill log.

## Connection lifecycle

```python
db = VolScopeDB()
try:
    ...
finally:
    db.close()
```

Always close in a `finally`. Open connections held past process exit
leave the DB locked.
