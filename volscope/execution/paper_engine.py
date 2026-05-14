"""
Paper engine — v0.3.0.

Takes a `RankedSignal` (from `signals/ranking.py`), looks up the real
strikes in `bot_chain_snapshots`, applies the slippage model, and
writes a complete trade into `bot_trades` + `bot_legs`.

NO IBKR. NO network. Pure DB writes. Designed so:

1. Backtest replay can call this against historical chain snapshots
   to produce a realistic P&L curve.
2. Daily paper-engine driver can call it against the latest snapshot
   to "live paper-trade" today's signals.
3. The state machine fires correctly (SIGNALED → SIZED → SUBMITTED →
   FILLED → MANAGED in one synchronous step, since paper has no
   broker round-trip).
"""
from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Literal

from volscope.data.chain_quote import (
    Quote, SlippageModel, apply_slippage, get_quote,
)
from volscope.signals.ranking import RankedSignal

log = logging.getLogger(__name__)

Direction = Literal["short_vol", "long_vol"]


@dataclass(frozen=True)
class LegSpec:
    """Spec for one leg of a multi-leg trade."""
    side: Literal["buy", "sell"]
    right: Literal["C", "P"]
    target_strike: float
    expiry: date
    contracts: int


@dataclass(frozen=True)
class TradeBlueprint:
    """A multi-leg structure ready to be filled at chain quotes."""
    strategy: str                    # e.g. "Iron Condor"
    underlying: str
    direction: Direction
    legs: list[LegSpec]
    target_dte: int


@dataclass(frozen=True)
class FilledLeg:
    """A leg after chain lookup + slippage applied."""
    side: Literal["buy", "sell"]
    right: Literal["C", "P"]
    actual_strike: float
    expiry: date
    contracts: int
    fill_price: float                # per contract, post-slippage
    quote: Quote


@dataclass(frozen=True)
class FilledTrade:
    """Output of `paper_execute()`. Written to bot_trades + bot_legs."""
    trade_id: str
    strategy: str
    underlying: str
    direction: Direction
    legs: list[FilledLeg]
    net_credit_or_debit: float       # + = credit; - = debit
    opened_at: datetime


def execute_blueprint(
    db, *,
    blueprint: TradeBlueprint,
    slippage: SlippageModel,
    is_index: bool = False,
) -> FilledTrade | None:
    """
    Fill every leg of ``blueprint`` from the chain, write the trade
    to DuckDB, and return a ``FilledTrade``.

    Returns ``None`` if any required leg can't be quoted — the entire
    trade is rejected rather than half-filled (paper-engine
    no-leg-risk invariant).
    """
    filled: list[FilledLeg] = []
    today = date.today()
    for spec in blueprint.legs:
        dte = max(0, (spec.expiry - today).days)
        quote = get_quote(
            db,
            ticker=blueprint.underlying,
            strike=spec.target_strike,
            expiry=spec.expiry,
            right=spec.right,
        )
        if quote is None or quote.mid is None:
            log.warning(
                "paper-engine: cannot quote %s %s %s @ %s exp %s — REJECT trade",
                blueprint.underlying, spec.right, spec.side,
                spec.target_strike, spec.expiry,
            )
            return None
        price = apply_slippage(
            quote, side=spec.side, model=slippage,
            dte=dte, is_index=is_index,
        )
        filled.append(FilledLeg(
            side=spec.side, right=spec.right,
            actual_strike=quote.strike, expiry=quote.expiry,
            contracts=spec.contracts, fill_price=price,
            quote=quote,
        ))

    # Net credit/debit (multiplier 100 for equity options):
    # SELL → receive premium (+), BUY → pay premium (-).
    net = sum(
        (1.0 if leg.side == "sell" else -1.0)
        * leg.fill_price * leg.contracts * 100.0
        for leg in filled
    )
    trade_id = str(uuid.uuid4())
    opened_at = datetime.now(tz=timezone.utc)

    # Persist
    _persist(db, trade_id=trade_id, blueprint=blueprint, filled=filled,
              net=net, opened_at=opened_at)

    return FilledTrade(
        trade_id=trade_id, strategy=blueprint.strategy,
        underlying=blueprint.underlying, direction=blueprint.direction,
        legs=filled, net_credit_or_debit=net, opened_at=opened_at,
    )


def execute_signal(
    db, *,
    signal: RankedSignal,
    blueprint_factory,
    slippage: SlippageModel,
    is_index: bool = False,
) -> FilledTrade | None:
    """
    High-level wrapper: take a ranked signal → ask the strategy factory
    to produce a TradeBlueprint → execute it.

    ``blueprint_factory`` is a callable that takes the signal + DB and
    returns a TradeBlueprint. Decoupled so different strategies can
    plug in without paper_engine knowing them.
    """
    if signal.blocked_reason is not None:
        log.info("skip blocked signal %s: %s", signal.ticker, signal.blocked_reason)
        return None
    blueprint = blueprint_factory(signal, db)
    if blueprint is None:
        return None
    return execute_blueprint(
        db, blueprint=blueprint, slippage=slippage, is_index=is_index,
    )


# ── DB write helpers ──────────────────────────────────────────────


def _persist(db, *, trade_id: str, blueprint: TradeBlueprint,
             filled: list[FilledLeg], net: float,
             opened_at: datetime) -> None:
    """Single transaction: insert bot_trades + bot_legs."""
    db.con.begin()
    try:
        db.con.execute("""
            INSERT INTO bot_trades
            (trade_id, strategy, underlying, direction, status,
             composite_score, size_fraction, contracts,
             capital_at_risk, credit_or_debit, opened_at,
             closed_at, realized_pnl, legs_snapshot, reason_block, notes)
            VALUES (?, ?, ?, ?, 'FILLED',
                    NULL, NULL, ?,
                    ?, ?, ?,
                    NULL, NULL, ?, NULL, NULL)
        """, [
            trade_id, blueprint.strategy, blueprint.underlying,
            blueprint.direction,
            sum(l.contracts for l in filled),
            _capital_at_risk(filled), net, opened_at,
            _legs_json(filled),
        ])
        for leg in filled:
            db.con.execute("""
                INSERT INTO bot_legs
                (leg_id, trade_id, side, option_type, strike, expiry,
                 contracts, open_premium, close_premium,
                 delta_at_open, iv_at_open, assigned)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL, ?, FALSE)
            """, [
                str(uuid.uuid4()), trade_id, leg.side,
                "call" if leg.right == "C" else "put",
                leg.actual_strike, leg.expiry, leg.contracts,
                leg.fill_price, leg.quote.iv,
            ])
        db.con.commit()
    except Exception:
        db.con.rollback()
        raise


def _capital_at_risk(legs: list[FilledLeg]) -> float:
    """Rough $-at-risk estimate. Phase 3+ will replace with formal max-loss."""
    # For credit spreads / iron condors, max loss = wing width × 100 × contracts
    # minus net credit. For undefined-risk (naked), this is conservative.
    # For now we estimate as the absolute net premium — sufficient for
    # paper-engine accounting; replace in Phase 3 backtest harness.
    return abs(sum(leg.fill_price * leg.contracts * 100.0 for leg in legs))


def _legs_json(legs: list[FilledLeg]) -> str:
    import json
    return json.dumps([{
        "side": leg.side, "right": leg.right,
        "strike": leg.actual_strike, "expiry": leg.expiry.isoformat(),
        "contracts": leg.contracts, "fill_price": leg.fill_price,
    } for leg in legs])
