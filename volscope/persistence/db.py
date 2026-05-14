"""
Bot-side DuckDB connection + migration runner — Phase 1 scaffold.

The bot writes to its own logical namespace inside the existing
``volscope.db`` file (table prefix ``bot_``). This keeps the research
dashboard and the bot on a single DB without crossing wires.

Migrations are versioned SQL files in ``migrations/``. The runner
applies them in lexical order and records the applied version in a
``bot_migrations`` table so they're idempotent.
"""
from __future__ import annotations

import re
from pathlib import Path

import duckdb

MIGRATIONS_DIR = Path(__file__).parent / "migrations"


def apply_migrations(conn: duckdb.DuckDBPyConnection) -> list[str]:
    """
    Apply all pending migrations to ``conn`` and return list of names applied.

    Migration filenames follow ``NNN_description.sql`` (e.g. ``001_init.sql``).
    Each is applied exactly once; the bookkeeping table records what's done.
    """
    conn.execute("""
        CREATE TABLE IF NOT EXISTS bot_migrations (
            version    TEXT PRIMARY KEY,
            applied_at TIMESTAMP DEFAULT current_timestamp
        )
    """)
    already = {row[0] for row in conn.execute(
        "SELECT version FROM bot_migrations"
    ).fetchall()}

    applied: list[str] = []
    for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
        version = path.stem
        if version in already:
            continue
        sql = path.read_text()
        # DuckDB executes one statement per call when using the python
        # binding — split on top-level semicolons.
        for stmt in _split_statements(sql):
            if stmt.strip():
                conn.execute(stmt)
        conn.execute("INSERT INTO bot_migrations (version) VALUES (?)", [version])
        applied.append(version)
    return applied


def _split_statements(sql: str) -> list[str]:
    """Split SQL on semicolons that are not inside a string literal."""
    # Strip line comments — keep block comments inside statements alone.
    cleaned = re.sub(r"--[^\n]*", "", sql)
    parts: list[str] = []
    buf: list[str] = []
    in_str: str | None = None
    for ch in cleaned:
        if in_str:
            buf.append(ch)
            if ch == in_str:
                in_str = None
            continue
        if ch in ("'", '"'):
            in_str = ch
            buf.append(ch)
            continue
        if ch == ";":
            parts.append("".join(buf))
            buf = []
            continue
        buf.append(ch)
    tail = "".join(buf).strip()
    if tail:
        parts.append(tail)
    return parts
