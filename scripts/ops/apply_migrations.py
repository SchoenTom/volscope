"""
Apply pending DuckDB migrations to the live VolScope DB.

Idempotent: re-running is a no-op. Reads `bot_migrations` bookkeeping
table; applies anything not already applied; reports the list of
applied migrations + current bot_* table count.

Usage:
    python -m scripts.ops.apply_migrations              # live DB
    python -m scripts.ops.apply_migrations --dry-run    # report only
    python -m scripts.ops.apply_migrations --db-path /custom/path
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import duckdb

from volscope.persistence.db import MIGRATIONS_DIR, apply_migrations


def _default_db_path() -> Path:
    """Resolve the live DB path (mirror of volscope/data/database.py)."""
    override = os.environ.get("VOLSCOPE_DATA_DIR")
    if override:
        return Path(override).expanduser() / "volscope.db"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "VolScope" / "volscope.db"
    xdg = os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")
    return Path(xdg) / "VolScope" / "volscope.db"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db-path", default=None,
                         help="override DB path (default: platform-specific live DB)")
    parser.add_argument("--dry-run", action="store_true",
                         help="report what would apply; do not write")
    args = parser.parse_args(argv)

    db_path = Path(args.db_path) if args.db_path else _default_db_path()
    db_path.parent.mkdir(parents=True, exist_ok=True)

    if args.dry_run:
        print(f"DRY RUN — DB at {db_path}")
        sql_files = sorted(MIGRATIONS_DIR.glob("*.sql"))
        print(f"  {len(sql_files)} migration files defined:")
        for p in sql_files:
            print(f"    {p.stem}")
        if db_path.is_file():
            conn = duckdb.connect(str(db_path), read_only=True)
            try:
                rows = conn.execute(
                    "SELECT version FROM bot_migrations ORDER BY version"
                ).fetchall()
                already = [r[0] for r in rows]
                pending = [p.stem for p in sql_files if p.stem not in already]
                print(f"  already applied: {already}")
                print(f"  pending:         {pending}")
            except duckdb.Error:
                print("  bot_migrations table missing — all migrations pending")
            finally:
                conn.close()
        else:
            print(f"  DB doesn't exist yet — all {len(sql_files)} pending")
        return 0

    print(f"applying migrations to {db_path}")
    conn = duckdb.connect(str(db_path))
    try:
        applied = apply_migrations(conn)
        if applied:
            print(f"  applied: {applied}")
        else:
            print(f"  nothing new — already up to date")
        # Report current state
        tables = sorted(r[0] for r in conn.execute(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_name LIKE 'bot_%' ORDER BY table_name"
        ).fetchall())
        views = sorted(r[0] for r in conn.execute(
            "SELECT table_name FROM information_schema.views "
            "WHERE table_name LIKE 'bot_%' ORDER BY table_name"
        ).fetchall())
        print(f"  bot_* tables ({len(tables)}): {', '.join(tables)}")
        if views:
            print(f"  bot_* views  ({len(views)}): {', '.join(views)}")
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
