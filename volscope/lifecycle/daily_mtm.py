"""
Daily mark-to-market — v0.3.0.

For every non-terminal `bot_trades` row, look up the current chain
quote for each leg, compute current MTM and percent-of-PT, and apply
the three exit rules:

1. **50 % profit-target**: realized + unrealized >= 50% of credit collected
   (short-vol) or >= 50% of debit paid (long-vol).
2. **2× credit stop**: unrealized loss >= 2× credit collected.
3. **21-DTE mechanical close**: earliest leg DTE <= 21 (short-vol only —
   long-vol holds through theta-acceleration zone per its own logic).

When a rule fires, the trade transitions MANAGED → CLOSING → CLOSED in
one synchronous step (paper engine has no broker delay). bot_pnl_daily
is rolled up for the account.

Run via `scripts/ops/run_paper_engine.py mtm` after each chain scrape.
"""
from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass
from datetime import date, datetime, timezone

from volscope.data.chain_quote import (
    SlippageModel, apply_slippage, get_quote,
)

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class MtmRow:
    """Per-trade snapshot of current state."""
    trade_id: str
    underlying: str
    direction: str
    opened_at: datetime
    open_credit_or_debit: float
    current_value: float            # positive = position worth $X now
    unrealized_pnl: float
    pct_of_target: float            # 0 to 1 (1 = at 50% PT for short-vol)
    min_dte: int
    should_close: bool
    close_reason: str | None


def compute_mtm(db, *, slippage: SlippageModel) -> list[MtmRow]:
    """
    Compute MTM for every non-terminal trade. Returns one row per trade.
    Does NOT mutate the DB — for that, call `apply_exits()`.
    """
    today = date.today()
    rows = db.con.execute("""
        SELECT trade_id, underlying, direction, opened_at,
               credit_or_debit, legs_snapshot
        FROM bot_trades
        WHERE status NOT IN ('CLOSED','EXPIRED','ABANDONED','ASSIGNED','REJECTED','ROLLED')
    """).fetchall()

    out: list[MtmRow] = []
    for trade_id, underlying, direction, opened_at, credit_or_debit, legs_json in rows:
        legs = json.loads(legs_json) if legs_json else []
        if not legs:
            continue
        # Cost to close = SELL legs we BOUGHT + BUY legs we SOLD; net is the
        # cash flow to flatten the position.
        cost_to_close = 0.0
        dtes: list[int] = []
        quotable = True
        for leg in legs:
            expiry = date.fromisoformat(leg["expiry"])
            dtes.append(max(0, (expiry - today).days))
            quote = get_quote(
                db, ticker=underlying,
                strike=float(leg["strike"]),
                expiry=expiry, right=leg["right"],
            )
            if quote is None or quote.mid is None:
                quotable = False
                break
            # To close: BUY back what we SOLD, SELL what we BOUGHT.
            close_side = "buy" if leg["side"] == "sell" else "sell"
            dte = max(0, (expiry - today).days)
            close_price = apply_slippage(
                quote, side=close_side, model=slippage, dte=dte,
            )
            sign = -1.0 if close_side == "buy" else 1.0
            cost_to_close += sign * close_price * leg["contracts"] * 100.0

        if not quotable:
            log.warning("trade %s — leg unquotable; skipping MTM", trade_id)
            continue

        # P&L: entered with `credit_or_debit` net (positive credit), now would
        # net `cost_to_close` to flatten. Unrealized = credit_or_debit +
        # cost_to_close (positive = profit).
        unrealized = float(credit_or_debit) + cost_to_close

        # Pct of target — short-vol target is 50% of credit, long-vol target
        # is 100% of debit doubled
        if direction == "short_vol" and credit_or_debit > 0:
            target = 0.50 * float(credit_or_debit)
            pct = unrealized / target if target > 0 else 0.0
            stop = -2.0 * float(credit_or_debit)
        elif direction == "long_vol" and credit_or_debit < 0:
            target = abs(float(credit_or_debit))            # +100% return on debit
            pct = unrealized / target if target > 0 else 0.0
            stop = 0.5 * float(credit_or_debit)              # -50% (i.e. half the debit)
        else:
            target = 1.0
            pct = 0.0
            stop = -1e9

        min_dte = min(dtes) if dtes else 0
        reason: str | None = None
        if direction == "short_vol":
            if pct >= 1.0:
                reason = "50% PT hit"
            elif unrealized <= stop:
                reason = "2x credit stop"
            elif min_dte <= 21:
                reason = "21-DTE mechanical close"
        else:
            if pct >= 1.0:
                reason = "+100% target hit"
            elif unrealized <= stop:
                reason = "-50% stop"

        out.append(MtmRow(
            trade_id=trade_id, underlying=underlying, direction=direction,
            opened_at=opened_at,
            open_credit_or_debit=float(credit_or_debit),
            current_value=cost_to_close, unrealized_pnl=unrealized,
            pct_of_target=pct, min_dte=min_dte,
            should_close=reason is not None, close_reason=reason,
        ))
    return out


def apply_exits(db, mtm_rows: list[MtmRow]) -> int:
    """
    Close every trade where `should_close=True`. Returns count closed.
    Writes a final bot_orders_log row per closure.
    """
    closed_at = datetime.now(tz=timezone.utc)
    n = 0
    for row in mtm_rows:
        if not row.should_close:
            continue
        db.con.execute("""
            UPDATE bot_trades
            SET status = 'CLOSED', closed_at = ?, realized_pnl = ?, notes = ?
            WHERE trade_id = ?
        """, [closed_at, row.unrealized_pnl,
              f"closed: {row.close_reason}", row.trade_id])
        db.con.execute("""
            INSERT INTO bot_orders_log (order_event_id, trade_id, ts, event_type, payload_json)
            VALUES (?, ?, ?, 'CLOSE', ?)
        """, [str(uuid.uuid4()), row.trade_id, closed_at,
              json.dumps({"reason": row.close_reason,
                          "realized_pnl": row.unrealized_pnl})])
        n += 1
    return n


def rollup_daily_pnl(db, *, account_id: str = "paper") -> None:
    """
    Build today's bot_pnl_daily row from current state.

    Realised = sum of realized_pnl for trades closed today.
    Unrealised = sum of unrealized for trades still open (from latest MTM).
    NLV / BPR / Greeks left at 0 — Phase 2.5 will wire portfolio aggregates.
    """
    today = date.today()
    realized = db.con.execute("""
        SELECT COALESCE(SUM(realized_pnl), 0) FROM bot_trades
        WHERE DATE(closed_at) = ?
    """, [today]).fetchone()[0] or 0.0

    open_count = db.con.execute("""
        SELECT COUNT(*) FROM bot_trades
        WHERE status NOT IN ('CLOSED','EXPIRED','ABANDONED','ASSIGNED','REJECTED','ROLLED')
    """).fetchone()[0]

    db.con.execute("""
        INSERT INTO bot_pnl_daily
        (account_id, date, nlv, bpr_used, cash, realized_pnl, unrealized_pnl,
         portfolio_delta, portfolio_vega, portfolio_theta, open_positions)
        VALUES (?, ?, 0, 0, 0, ?, 0, 0, 0, 0, ?)
        ON CONFLICT (account_id, date) DO UPDATE
        SET realized_pnl = excluded.realized_pnl,
            open_positions = excluded.open_positions
    """, [account_id, today, realized, open_count])
