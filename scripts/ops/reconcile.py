"""
Reconciliation stub — Phase 2 core scaffold.

On startup, fetch IBKR open positions + recent executions and compare
against the DuckDB `bot_trades` rows still in non-terminal status.
Print any deltas; Phase 2.5 will RESOLVE them (close orphan positions,
mark missing trades ABANDONED). This stub only diffs and reports.

Exit codes:
    0  no deltas
    1  deltas present (operator review required)
    2  IBKR unreachable / DB unreadable
"""
from __future__ import annotations

import asyncio
import sys

from rich.console import Console
from rich.table import Table


async def _fetch_ibkr_state() -> dict | None:
    try:
        from volscope.execution.ibkr_stub import IBKRClient
        client = IBKRClient()
        ok = await client.connect()
        if not ok:
            return None
        try:
            ib = client._ib                          # noqa: SLF001
            positions = ib.positions()
            execs = ib.executions()
            return {
                "positions": [(p.contract.symbol, p.contract.lastTradeDateOrContractMonth,
                               p.contract.strike, p.contract.right, p.position)
                              for p in positions],
                "executions": [(e.contract.symbol, e.execution.execId,
                                 e.execution.time) for e in execs],
            }
        finally:
            await client.disconnect()
    except Exception as exc:                          # noqa: BLE001
        print(f"IBKR fetch error: {exc}", file=sys.stderr)
        return None


def _fetch_db_state() -> list[tuple] | None:
    try:
        from volscope.data.database import VolScopeDB
        db = VolScopeDB()
        try:
            rows = db.con.execute("""
                SELECT trade_id, underlying, status, opened_at
                FROM bot_trades
                WHERE status NOT IN ('CLOSED', 'EXPIRED', 'ABANDONED',
                                      'ASSIGNED', 'REJECTED', 'ROLLED')
                ORDER BY opened_at
            """).fetchall()
            return list(rows)
        finally:
            db.close()
    except Exception as exc:                          # noqa: BLE001
        print(f"DB fetch error: {exc}", file=sys.stderr)
        return None


def main() -> int:
    console = Console()
    db_state = _fetch_db_state()
    if db_state is None:
        return 2
    ibkr_state = asyncio.run(_fetch_ibkr_state())
    if ibkr_state is None:
        console.print("[yellow]IBKR unreachable — cannot reconcile.[/yellow]")
        console.print(f"DB open trades: {len(db_state)}")
        for row in db_state:
            console.print(f"  {row}")
        return 2

    # Naive diff: trade in DB without a matching position symbol is a candidate
    # "missing fill" — needs human eyes.
    db_symbols = {r[1] for r in db_state}
    ibkr_symbols = {p[0] for p in ibkr_state["positions"]}

    only_db = db_symbols - ibkr_symbols
    only_ib = ibkr_symbols - db_symbols
    both = db_symbols & ibkr_symbols

    table = Table(title="Reconciliation", show_lines=False)
    table.add_column("Where", style="dim")
    table.add_column("Count")
    table.add_column("Symbols")
    table.add_row("DB only (orphan trades)", str(len(only_db)),
                  ", ".join(sorted(only_db)) or "—")
    table.add_row("IBKR only (orphan positions)", str(len(only_ib)),
                  ", ".join(sorted(only_ib)) or "—")
    table.add_row("Both", str(len(both)),
                  ", ".join(sorted(both)) or "—")
    console.print(table)

    if only_db or only_ib:
        console.print("[red]Deltas present — operator review required.[/red]")
        return 1
    console.print("[green]No deltas.[/green]")
    return 0


if __name__ == "__main__":
    sys.exit(main())
