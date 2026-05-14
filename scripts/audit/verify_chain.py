"""
CLI wrapper for bot_audit_chain verification.

Exit codes:
    0 — chain valid
    1 — chain broken (prints first-break seq)
    2 — DB unreadable

Usage:
    python -m scripts.audit.verify_chain
"""
from __future__ import annotations

import sys


def main() -> int:
    from rich.console import Console
    from volscope.data.database import VolScopeDB
    from volscope.persistence.audit_chain import length, verify_chain

    console = Console()
    try:
        db = VolScopeDB()
    except Exception as exc:                     # noqa: BLE001
        console.print(f"[red]DB unreadable: {exc}[/red]")
        return 2

    try:
        n = length(db)
        ok, broken_seq = verify_chain(db)
        if ok:
            console.print(f"[green]CHAIN VALID[/green] — {n} rows, prev_hash linkage intact")
            return 0
        console.print(f"[red]CHAIN BROKEN[/red] at seq={broken_seq} (of {n} total)")
        return 1
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
