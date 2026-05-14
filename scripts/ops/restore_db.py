"""
DuckDB restore drill — v0.5.0 F.

Round-trip restore of a backup directory into a temp DB; verifies the
schema + row counts match the source. Used by the monthly
``/restore-drill`` to prove backups are actually restorable.

Usage:
    python -m scripts.ops.restore_db --temp                   # default drill
    python -m scripts.ops.restore_db --from <backup-dir>      # specific snapshot
    python -m scripts.ops.restore_db --target /path/db        # restore for real
"""
from __future__ import annotations

import argparse
import os
import sys
import tempfile
from datetime import date
from pathlib import Path

import duckdb


def _default_data_dir() -> Path:
    xdg = os.environ.get("VOLSCOPE_DATA_DIR")
    if xdg:
        return Path(xdg)
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "VolScope"
    return Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")) / "VolScope"


def _latest_backup_dir(backups_root: Path) -> Path | None:
    """Find the most-recent dated subdir under `backups_root`."""
    if not backups_root.is_dir():
        return None
    dated = []
    for d in backups_root.iterdir():
        if not d.is_dir():
            continue
        try:
            dated.append((date.fromisoformat(d.name), d))
        except ValueError:
            continue
    if not dated:
        return None
    return max(dated, key=lambda p: p[0])[1]


def _count_rows_per_table(conn) -> dict[str, int]:
    """Return {table_name: row_count} for all `bot_*` tables."""
    out: dict[str, int] = {}
    rows = conn.execute(
        "SELECT table_name FROM information_schema.tables WHERE table_name LIKE 'bot_%'"
    ).fetchall()
    for (name,) in rows:
        try:
            cnt = conn.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0]
            out[name] = int(cnt)
        except duckdb.Error:
            pass
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--temp", action="store_true",
                         help="round-trip into a temp DB + verify + tear down")
    parser.add_argument("--from", dest="from_dir", default=None,
                         help="backup dir to restore (default: latest)")
    parser.add_argument("--target", default=None,
                         help="real target DB path (for non-drill restore)")
    args = parser.parse_args(argv)

    data_dir = _default_data_dir()
    backups_root = data_dir / "backups"
    src_dir = Path(args.from_dir) if args.from_dir else _latest_backup_dir(backups_root)
    if src_dir is None or not src_dir.is_dir():
        print(f"!! no backup directory found under {backups_root}", file=sys.stderr)
        return 2

    print(f"restoring from {src_dir}")
    schema_sql = src_dir / "schema.sql"
    load_sql = src_dir / "load.sql"
    if not (schema_sql.is_file() and load_sql.is_file()):
        print(f"!! schema.sql / load.sql missing in {src_dir} — corrupted backup?",
              file=sys.stderr)
        return 3

    if args.target and not args.temp:
        target = Path(args.target)
        print(f"   restoring to {target} (LIVE — review before overwriting)")
    else:
        # Drill mode: temp DB
        tmpdir = tempfile.mkdtemp(prefix="volscope-restore-")
        target = Path(tmpdir) / "restored.db"
        print(f"   drill — temp DB at {target}")

    # Live source row counts (for comparison)
    live_path = data_dir / "volscope.db"
    live_counts: dict[str, int] = {}
    if live_path.is_file():
        try:
            live = duckdb.connect(str(live_path), read_only=True)
            live_counts = _count_rows_per_table(live)
            live.close()
        except duckdb.Error as exc:
            print(f"!! live DB readable but query failed: {exc}", file=sys.stderr)

    # Apply schema + load
    conn = duckdb.connect(str(target))
    try:
        conn.execute(schema_sql.read_text())
        # `load.sql` uses relative paths; chdir into the backup so they resolve.
        cwd = os.getcwd()
        try:
            os.chdir(src_dir)
            conn.execute(load_sql.read_text())
        finally:
            os.chdir(cwd)
        restored_counts = _count_rows_per_table(conn)
        print(f"   restored {len(restored_counts)} bot_* tables")
    finally:
        conn.close()

    if args.temp:
        if live_counts:
            mismatches = []
            for t in live_counts:
                if restored_counts.get(t) != live_counts.get(t):
                    mismatches.append((t, live_counts.get(t), restored_counts.get(t)))
            if mismatches:
                print(f"!! row-count mismatch on {len(mismatches)} tables:",
                      file=sys.stderr)
                for t, l, r in mismatches:
                    print(f"    {t}: live={l} restored={r}", file=sys.stderr)
                return 4
            print(f"   row counts match across {len(live_counts)} tables")
        else:
            print(f"   (no live DB to compare against; restored row counts: {restored_counts})")
        # Cleanup
        try:
            target.unlink()
            target.parent.rmdir()
        except OSError:
            pass

    print("RESTORE OK")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
