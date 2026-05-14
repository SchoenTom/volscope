"""
DuckDB backup — v0.5.0 F.

CHECKPOINT + EXPORT DATABASE to
``~/Library/Application Support/VolScope/backups/<YYYY-MM-DD>/`` with
Parquet + zstd compression. Optional ``--encrypt`` flag uses
``ENCRYPTION_KEY`` from the ``VOLSCOPE_BACKUP_KEY`` env var
(DuckDB 1.4+ native AES-256-GCM).

Usage:
    python -m scripts.ops.backup_db                   # plain
    python -m scripts.ops.backup_db --encrypt         # AES-256-GCM
    python -m scripts.ops.backup_db --retention 30    # prune > N days

Retention: keeps the most recent N days of dated subdirectories;
older ones are removed.
"""
from __future__ import annotations

import argparse
import os
import shutil
import sys
from datetime import date, timedelta
from pathlib import Path

import duckdb


def _default_data_dir() -> Path:
    """Match volscope/data/database.py — macOS preferred, XDG fallback."""
    xdg = os.environ.get("VOLSCOPE_DATA_DIR")
    if xdg:
        return Path(xdg)
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "VolScope"
    return Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")) / "VolScope"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--encrypt", action="store_true",
                         help="encrypt with VOLSCOPE_BACKUP_KEY env var")
    parser.add_argument("--retention", type=int, default=30,
                         help="keep last N days; default 30")
    parser.add_argument("--db-path", default=None,
                         help="override source DB path")
    args = parser.parse_args(argv)

    data_dir = _default_data_dir()
    db_path = Path(args.db_path) if args.db_path else (data_dir / "volscope.db")
    backups_root = data_dir / "backups"
    today_dir = backups_root / date.today().isoformat()

    if not db_path.is_file():
        print(f"!! source DB missing: {db_path}", file=sys.stderr)
        return 2
    today_dir.mkdir(parents=True, exist_ok=True)

    print(f"backing up {db_path} → {today_dir}")
    if args.encrypt:
        key = os.environ.get("VOLSCOPE_BACKUP_KEY")
        if not key:
            print("!! --encrypt requires VOLSCOPE_BACKUP_KEY env var", file=sys.stderr)
            return 3
        # DuckDB 1.4+ ATTACH ... ENCRYPTION_KEY syntax
        conn = duckdb.connect(":memory:")
        conn.execute(f"ATTACH ? AS src", [str(db_path)])
        conn.execute(f"ATTACH ? AS dst (ENCRYPTION_KEY ?)",
                     [str(today_dir / "volscope-encrypted.db"), key])
        conn.execute("COPY FROM DATABASE src TO dst")
        conn.close()
        print(f"   encrypted backup: {today_dir / 'volscope-encrypted.db'}")
    else:
        # Plain EXPORT DATABASE with Parquet + zstd
        conn = duckdb.connect(str(db_path), read_only=True)
        conn.execute("CHECKPOINT")
        conn.execute(
            f"EXPORT DATABASE '{today_dir}' "
            "(FORMAT PARQUET, COMPRESSION ZSTD)"
        )
        conn.close()
        # List what we got
        files = sorted(today_dir.glob("**/*"))
        print(f"   wrote {len(files)} files")

    # Retention
    cutoff = date.today() - timedelta(days=args.retention)
    pruned = 0
    if backups_root.is_dir():
        for d in sorted(backups_root.iterdir()):
            if not d.is_dir():
                continue
            try:
                d_date = date.fromisoformat(d.name)
            except ValueError:
                continue
            if d_date < cutoff:
                shutil.rmtree(d)
                pruned += 1
    if pruned:
        print(f"   pruned {pruned} backups older than {cutoff.isoformat()}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
