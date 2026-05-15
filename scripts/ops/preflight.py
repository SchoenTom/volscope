"""
Pre-flight check — Phase 2 core scaffold.

Run BEFORE the scheduler starts. Exit code 0 = good to go; non-zero =
abort. Prints a Rich table with each check ✓/✗ + reason. Wired into
``make start`` (Phase 2.5).

Checks (in order):

1. DuckDB connectable + bot_* tables present.
2. IBKR Gateway/TWS reachable on configured port (3-sec TCP test).
3. Kill switch NOT tripped (all 3 manual paths checked).
4. No open positions with earnings inside 14 days.
5. No `bot_trades` rows stuck in mid-state (SUBMITTED, PARTIAL_FILL,
   CLOSING) from a prior dirty shutdown — needs human review before
   resume.
"""
from __future__ import annotations

import socket
import sys
from datetime import date, timedelta
from pathlib import Path

from rich.console import Console
from rich.table import Table

# Defer volscope imports until called — keeps the CLI snappy even
# without the venv warmed.


def _check_db() -> tuple[bool, str]:
    try:
        from volscope.data.database import VolScopeDB
        db = VolScopeDB()
        try:
            rows = db.con.execute(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_name LIKE 'bot_%'"
            ).fetchall()
            expected = {"bot_trades", "bot_legs", "bot_pnl_daily",
                        "bot_signals_log", "bot_orders_log", "bot_migrations"}
            found = {r[0] for r in rows}
            missing = expected - found
            if missing:
                return (False, f"missing tables: {sorted(missing)}")
            return (True, f"{len(found)} bot_* tables present")
        finally:
            db.close()
    except Exception as exc:                 # noqa: BLE001
        return (False, f"DB connect failed: {exc}")


def _check_ibkr_port(host: str = "127.0.0.1", port: int = 7497,
                     timeout: float = 3.0) -> tuple[bool, str]:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return (True, f"{host}:{port} reachable")
    except OSError as exc:
        return (False, f"{host}:{port} unreachable: {exc}")


def _check_killswitch() -> tuple[bool, str]:
    try:
        from volscope.risk.kill_switch import KillSwitch
        ks = KillSwitch(sticky_path=Path("/var/run/volscope/KILL"))
        tripped, reason = ks.is_tripped()
        if tripped:
            return (False, f"TRIPPED: {reason}")
        return (True, "clear")
    except Exception as exc:                 # noqa: BLE001
        return (False, f"check failed: {exc}")


def _check_no_earnings_in_open_positions() -> tuple[bool, str]:
    try:
        from volscope.data.database import VolScopeDB
        db = VolScopeDB()
        try:
            cutoff = date.today() + timedelta(days=14)
            # Parameterised — even though `cutoff` is internally computed
            # (not user input), .claude/rules/secrets.md auto-rejects any
            # f-string SQL on review. Stay clean.
            rows = db.con.execute(
                """
                SELECT bt.underlying, ec.earnings_date
                FROM bot_trades bt
                LEFT JOIN earnings_calendar ec USING (ticker)
                WHERE bt.status NOT IN ('CLOSED','EXPIRED','ABANDONED','ASSIGNED','REJECTED','ROLLED')
                  AND ec.earnings_date <= ?
                  AND ec.earnings_date >= CURRENT_DATE
                """,
                [cutoff],
            ).fetchall()
            if rows:
                return (False, f"open positions with earnings ≤14d: "
                        f"{[r[0] for r in rows]}")
            return (True, "none")
        finally:
            db.close()
    except Exception as exc:                 # noqa: BLE001
        # Earnings table may not exist yet — non-blocking
        return (True, f"(skipped: {exc})")


def _check_no_stuck_trades() -> tuple[bool, str]:
    try:
        from volscope.data.database import VolScopeDB
        db = VolScopeDB()
        try:
            rows = db.con.execute("""
                SELECT trade_id, status FROM bot_trades
                WHERE status IN ('SUBMITTED', 'PARTIAL_FILL', 'CLOSING')
            """).fetchall()
            if rows:
                return (False, f"{len(rows)} trades stuck in transient state — "
                        "need reconciliation before resume")
            return (True, "none")
        finally:
            db.close()
    except Exception as exc:                 # noqa: BLE001
        return (False, f"check failed: {exc}")


def main() -> int:
    console = Console()
    table = Table(title="VolScope Pre-Flight", show_lines=False)
    table.add_column("#", style="dim", width=3)
    table.add_column("Check")
    table.add_column("Status", width=6)
    table.add_column("Detail")

    checks = [
        ("DuckDB + bot_* tables",        _check_db),
        ("IBKR Gateway/TWS reachable",   _check_ibkr_port),
        ("Kill switch not tripped",      _check_killswitch),
        ("No earnings ≤14d on open positions", _check_no_earnings_in_open_positions),
        ("No trades stuck in transient state",  _check_no_stuck_trades),
    ]
    exit_code = 0
    for i, (label, fn) in enumerate(checks, 1):
        ok, detail = fn()
        status = "[green]✓[/green]" if ok else "[red]✗[/red]"
        table.add_row(str(i), label, status, detail)
        if not ok:
            exit_code = 1

    console.print(table)
    if exit_code != 0:
        console.print("[red]Pre-flight FAILED. Aborting.[/red]")
    else:
        console.print("[green]Pre-flight OK.[/green]")
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
