#!/usr/bin/env python
"""
Release the DuckDB lock on the VolScope DB.

Designed for the daily user flow: when ``make start`` finds the DB
locked by a stale scraper or a lingering autonomous-loop process, this
helper identifies the holder, asks one question (or skips it under
``--force``), and kills it cleanly. Returns 0 if the DB is now unlocked.

Why is this its own script?
- ``lsof`` parsing has enough corner cases to keep out of the Makefile.
- Different Python interpreters (anaconda system Python vs the project
  venv) can both hold a lock; we detect by FD-on-the-DB-file, not by
  process name.
- Autonomous launchd jobs run under different identities; this script
  does not need cron access — it just kills the offending PID.

Usage::

    python scripts/release_db_lock.py            # interactive prompt
    python scripts/release_db_lock.py --force    # kill silently
    python scripts/release_db_lock.py --check    # report only, exit 0/1
"""
from __future__ import annotations

import argparse
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent.parent  # v0.2.0 reorg: repo root is 3 levels up
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from volscope.config import DB_PATH                                       # noqa: E402


def _holders(db_path: str) -> list[tuple[int, str]]:
    """Return ``[(pid, command), ...]`` for processes with the DB file open."""
    try:
        proc = subprocess.run(
            ["lsof", "-Fpc", db_path],
            capture_output=True, text=True, timeout=5,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return []
    pid: int | None = None
    out: list[tuple[int, str]] = []
    for line in proc.stdout.splitlines():
        if not line:
            continue
        tag, value = line[0], line[1:]
        if tag == "p":
            try:
                pid = int(value)
            except ValueError:
                pid = None
        elif tag == "c" and pid is not None:
            out.append((pid, value))
            pid = None
    # De-dupe — lsof can repeat the same PID once per FD.
    seen: set[int] = set()
    deduped: list[tuple[int, str]] = []
    for pid, cmd in out:
        if pid in seen:
            continue
        seen.add(pid)
        deduped.append((pid, cmd))
    # Don't list our own pid.
    return [(p, c) for p, c in deduped if p != os.getpid()]


def _full_cmdline(pid: int) -> str:
    """Best-effort full command line for a PID (for UI detection)."""
    try:
        proc = subprocess.run(
            ["ps", "-p", str(pid), "-o", "command="],
            capture_output=True, text=True, timeout=3,
        )
        return proc.stdout.strip()
    except Exception:
        return ""


def _is_streamlit_ui(pid: int) -> bool:
    """True if PID is the running VolScope Streamlit UI (must NOT be killed).

    Killing the live UI is the single worst failure mode: an in-app
    'refresh data' button (or `make scrape`) would terminate the very
    server the user is looking at — Streamlit prints 'Stopping...' and the
    browser shows a connection error. The DB lock-releaser only ever needs
    to clear STALE writers, never the app itself.
    """
    cmd = _full_cmdline(pid).lower()
    return "streamlit" in cmd or "ui/app.py" in cmd or "ui.app" in cmd


def _kill(pid: int, escalate_seconds: float = 2.0) -> bool:
    """SIGTERM, wait, escalate to SIGKILL if still alive."""
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        return True
    deadline = time.time() + escalate_seconds
    while time.time() < deadline:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return True
        time.sleep(0.1)
    try:
        os.kill(pid, signal.SIGKILL)
    except ProcessLookupError:
        return True
    time.sleep(0.3)
    try:
        os.kill(pid, 0)
        return False  # still alive, kill failed
    except ProcessLookupError:
        return True


def main() -> int:
    parser = argparse.ArgumentParser(description="Release the VolScope DB lock")
    parser.add_argument("--force", action="store_true",
                        help="Kill holders without confirmation")
    parser.add_argument("--check", action="store_true",
                        help="Report lock-status only; exit 1 if locked")
    args = parser.parse_args()

    db_path = str(DB_PATH)
    if not os.path.exists(db_path):
        print(f"[lock] DB does not exist yet: {db_path} — nothing to release")
        return 0

    holders = _holders(db_path)
    # NEVER kill the live Streamlit UI — that would terminate the server the
    # user is looking at (the 'Stopping...' / connection-error crash). The
    # lock-releaser only clears stale writers.
    ui_holders = [(p, c) for p, c in holders if _is_streamlit_ui(p)]
    holders = [(p, c) for p, c in holders if not _is_streamlit_ui(p)]
    if ui_holders:
        print(f"[lock] leaving the running VolScope UI untouched "
              f"(PID {', '.join(str(p) for p, _ in ui_holders)}).")
    if not holders:
        print(f"[lock] no stale writer to clear: {db_path}")
        return 0

    print(f"[lock] DB locked by {len(holders)} stale process(es):")
    for pid, cmd in holders:
        print(f"       PID {pid}  {cmd}")

    if args.check:
        return 1

    if not args.force:
        try:
            answer = input("Kill them? [y/N] ").strip().lower()
        except EOFError:
            answer = "n"
        if answer not in ("y", "yes"):
            print("[lock] aborted — DB still locked")
            return 1

    failed: list[int] = []
    for pid, _cmd in holders:
        ok = _kill(pid)
        print(f"[lock] {'killed' if ok else 'FAILED to kill'} PID {pid}")
        if not ok:
            failed.append(pid)

    # Verify
    time.sleep(0.5)
    remaining = _holders(db_path)
    if remaining:
        print(f"[lock] WARN: {len(remaining)} holder(s) still attached:")
        for pid, cmd in remaining:
            print(f"       PID {pid}  {cmd}")
        return 1
    print(f"[lock] DB is now free")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
