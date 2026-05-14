"""
Paper trader — broker-style multi-leg buy / close with cash accounting.

The core function is ``paper_buy_strategy``:

    materialized = template.materialize(ticker=..., spot=..., iv_pct=..., dte=..., contracts=...)
    group_id, cash_after = paper_buy_strategy(db, materialized, scenario_hint="...")

It writes one row per leg into ``positions`` (each leg shares
``strategy_group_id``), debits the paper-cash balance, and journals
the event in ``paper_trades``. Closes work symmetrically: every leg
of the group is marked inactive, current BSM premium is collected
back into cash, and a single close-event is journaled with realised
P&L.

This makes the whole flow:

    Strategy Builder ➜ template.materialize ➜ paper_buy_strategy ➜ DB
                                                           ↓
                          Portfolio renders by strategy_group_id

…1:1 like a broker, with a cash ledger that lets you verify the
arithmetic at any time. No external API, fully deterministic.
"""
from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Optional

import pandas as pd

from volscope.analytics.black_scholes import bs_price
from volscope.analytics.strategy_templates import LegSpec, MaterializedStrategy


# ── Constants ────────────────────────────────────────────────────────

_CASH_KEY      = "paper.cash_balance"
_CASH_INIT_KEY = "paper.cash_initial"
DEFAULT_CASH   = 10_000.0
_RISK_FREE     = 0.04


# ── Cash accounting ──────────────────────────────────────────────────

def get_cash_balance(db) -> float:
    """Read the current paper-cash balance. Initialises to DEFAULT_CASH
    on first access so the user never sees a 'no balance' state."""
    raw = db.get_user_setting(_CASH_KEY)
    if raw is None:
        db.set_user_setting(_CASH_KEY, str(DEFAULT_CASH))
        db.set_user_setting(_CASH_INIT_KEY, str(DEFAULT_CASH))
        return DEFAULT_CASH
    try:
        return float(raw)
    except (TypeError, ValueError):
        return DEFAULT_CASH


def get_cash_initial(db) -> float:
    """Read the initial deposit — used to compute return-on-cash."""
    raw = db.get_user_setting(_CASH_INIT_KEY)
    if raw is None:
        return DEFAULT_CASH
    try:
        return float(raw)
    except (TypeError, ValueError):
        return DEFAULT_CASH


def set_cash_balance(db, balance: float) -> None:
    db.set_user_setting(_CASH_KEY, str(float(balance)))


def reset_cash(db, *, initial: float = DEFAULT_CASH) -> None:
    """Reset both balance and initial deposit. Doesn't touch positions."""
    db.set_user_setting(_CASH_KEY, str(float(initial)))
    db.set_user_setting(_CASH_INIT_KEY, str(float(initial)))


# ── Trade journal ────────────────────────────────────────────────────

@dataclass(frozen=True)
class TradeEvent:
    """One row of the paper_trades audit log."""
    event_id:          int
    event_ts:          datetime
    event_type:        str           # 'buy' | 'close'
    strategy_group_id: str
    strategy_template: str
    ticker:            str
    legs_json:         str
    net_cash:          float          # + = paid, - = received
    realized_pl:       Optional[float]
    cash_after:        float
    notes:             str


def _log_trade_event(
    db,
    *,
    event_type: str,
    strategy_group_id: str,
    strategy_template: str,
    ticker: str,
    legs: list[dict],
    net_cash: float,
    realized_pl: Optional[float],
    cash_after: float,
    notes: str,
) -> int:
    """Insert one row into paper_trades. Returns the new event_id."""
    next_id = db.con.execute(
        "SELECT COALESCE(MAX(event_id), 0) + 1 FROM paper_trades"
    ).fetchone()[0]
    db.con.execute(
        """
        INSERT INTO paper_trades (
            event_id, event_ts, event_type, strategy_group_id,
            strategy_template, ticker, legs_json, net_cash, realized_pl,
            cash_after, notes
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            next_id, datetime.now(timezone.utc), event_type, strategy_group_id,
            strategy_template, ticker, json.dumps(legs), float(net_cash),
            (float(realized_pl) if realized_pl is not None else None),
            float(cash_after), notes,
        ],
    )
    return next_id


def get_trade_journal(db, limit: int = 50) -> pd.DataFrame:
    """Return the most-recent N paper trades, newest first."""
    return db.con.execute(
        "SELECT * FROM paper_trades ORDER BY event_ts DESC LIMIT ?",
        [int(limit)],
    ).fetchdf()


# ── Position grouping ────────────────────────────────────────────────

@dataclass
class StrategyGroup:
    """All legs that share one strategy_group_id, with derived stats."""
    strategy_group_id:  str
    strategy_template:  str
    ticker:             str
    entry_date:         Optional[date]
    legs:               list[dict]            # raw position rows
    net_entry_debit:    float                 # + = debit at open
    n_legs:             int


def list_strategy_groups(db) -> list[StrategyGroup]:
    """Group active positions by strategy_group_id. Single-leg legacy
    positions (no group id) appear as their own one-leg group so the
    Portfolio render path is uniform."""
    df = db.get_positions(active_only=True)
    if df.empty:
        return []
    groups: dict[str, StrategyGroup] = {}
    for _, row in df.iterrows():
        gid = row.get("strategy_group_id")
        if gid is None or pd.isna(gid):
            gid = f"legacy-{int(row.get('id') or 0)}"
        if gid not in groups:
            groups[gid] = StrategyGroup(
                strategy_group_id=str(gid),
                strategy_template=str(row.get("strategy_template") or "Vanilla"),
                ticker=str(row.get("ticker") or "?"),
                entry_date=_coerce_date(row.get("entry_date")),
                legs=[],
                net_entry_debit=0.0,
                n_legs=0,
            )
        g = groups[gid]
        leg = row.to_dict()
        g.legs.append(leg)
        g.n_legs += 1
        action = (row.get("action") or "buy").lower()
        sign = +1 if action == "buy" else -1
        prem = float(row.get("entry_premium") or 0.0)
        ctrs = int(row.get("contracts") or 1)
        g.net_entry_debit += sign * prem * ctrs * 100
    return sorted(
        groups.values(),
        key=lambda g: g.entry_date or date.min,
        reverse=True,
    )


# ── Buy / close ──────────────────────────────────────────────────────

def paper_buy_strategy(
    db,
    materialized: MaterializedStrategy,
    *,
    entry_iv_pct: Optional[float] = None,
    entry_iv_percentile: Optional[float] = None,
    spot: Optional[float] = None,
    scenario_hint: str = "",
) -> tuple[str, float]:
    """
    Atomically buy all legs of a materialized strategy.

    Each leg becomes one row in ``positions`` sharing a freshly minted
    ``strategy_group_id``. The paper cash balance is debited by
    ``materialized.net_debit`` (negative net_debit ⇒ credit, balance
    rises). A single ``paper_trades`` ledger row is written.

    Returns
    -------
    (strategy_group_id, cash_after)
    """
    group_id = f"sg-{uuid.uuid4().hex[:10]}"
    today = date.today()
    cash_now = get_cash_balance(db)

    inserted_ids: list[int] = []
    legs_journal: list[dict] = []

    for leg in materialized.legs:
        pos_id = db.add_position(
            ticker=materialized.ticker,
            entry_date=today,
            entry_iv_30d=entry_iv_pct,
            entry_iv_percentile=entry_iv_percentile,
            notes=(
                f"{materialized.template_name}"
                + (f" · {scenario_hint}" if scenario_hint else "")
                + f" · group {group_id}"
            ),
            option_type=leg.option_type,
            strike=float(leg.strike),
            expiry=leg.expiry,
            instrument_type="vanilla",
            contracts=int(leg.contracts),
            entry_premium=float(leg.entry_premium),
            spot_at_entry=(float(spot) if spot is not None else None),
            strategy_group_id=group_id,
            strategy_template=materialized.template_name,
            action=leg.action,
        )
        inserted_ids.append(pos_id)
        legs_journal.append({
            "position_id":   pos_id,
            "option_type":   leg.option_type,
            "action":        leg.action,
            "strike":        float(leg.strike),
            "expiry":        leg.expiry.isoformat() if hasattr(leg.expiry, "isoformat") else str(leg.expiry),
            "contracts":     int(leg.contracts),
            "entry_premium": float(leg.entry_premium),
            "delta":         float(leg.delta),
        })

    cash_after = cash_now - materialized.net_debit
    set_cash_balance(db, cash_after)

    _log_trade_event(
        db,
        event_type="buy",
        strategy_group_id=group_id,
        strategy_template=materialized.template_name,
        ticker=materialized.ticker,
        legs=legs_journal,
        net_cash=materialized.net_debit,    # + paid, - collected
        realized_pl=None,
        cash_after=cash_after,
        notes=scenario_hint,
    )
    return group_id, cash_after


def paper_close_strategy(
    db,
    strategy_group_id: str,
    *,
    history_by_ticker: Optional[dict[str, pd.DataFrame]] = None,
) -> tuple[float, float]:
    """
    Close every active leg in the named group at the BSM mark.

    Cash impact: collect short legs' current premium back (sell to
    close = credit), pay long legs' current premium back (buy back to
    close → here mirrored as we *paid* on entry and *receive* on
    close).

    Returns
    -------
    (realized_pl, cash_after)
    """
    # Pull active legs of this group
    legs_df = db.con.execute(
        "SELECT * FROM positions WHERE strategy_group_id = ? AND active = true",
        [strategy_group_id],
    ).fetchdf()
    if legs_df.empty:
        return (0.0, get_cash_balance(db))

    ticker = str(legs_df["ticker"].iloc[0])
    template = str(legs_df["strategy_template"].iloc[0] or "Vanilla")

    # Determine current spot + IV
    history = None
    if history_by_ticker is not None:
        history = history_by_ticker.get(ticker)
    if history is None or history.empty:
        history = db.get_ticker_history(ticker)
    if history is None or history.empty:
        # Without market data we can't mark — treat close as P&L-zero
        # to avoid corrupting the cash balance.
        return (0.0, get_cash_balance(db))

    latest = history.iloc[-1]
    spot = float(latest.get("spot_price") or 0)
    iv_pct = float(latest.get("iv_30d") or 0)
    if spot <= 0 or iv_pct <= 0:
        return (0.0, get_cash_balance(db))

    today = date.today()
    cash_now = get_cash_balance(db)
    net_close_cash = 0.0        # + = received on close, - = paid on close
    realized_pl = 0.0
    legs_journal: list[dict] = []

    for _, leg in legs_df.iterrows():
        action       = str(leg.get("action") or "buy").lower()
        option_type  = str(leg.get("option_type") or "call").lower()
        strike       = float(leg.get("strike") or 0)
        contracts    = int(leg.get("contracts") or 1)
        entry_prem   = float(leg.get("entry_premium") or 0)
        expiry       = _coerce_date(leg.get("expiry"))
        if expiry is None:
            continue
        dte = max(1, (expiry - today).days)
        T = dte / 365.0
        current_prem = bs_price(spot, strike, T, _RISK_FREE,
                                max(0.001, iv_pct / 100.0),
                                option_type=option_type)
        if action == "buy":
            # We paid entry_prem; now sell-to-close at current_prem (credit)
            cash_in = current_prem * contracts * 100
            leg_pl  = (current_prem - entry_prem) * contracts * 100
        else:
            # We collected entry_prem; now buy-to-close at current_prem (debit)
            cash_in = -current_prem * contracts * 100
            leg_pl  = (entry_prem - current_prem) * contracts * 100
        net_close_cash += cash_in
        realized_pl += leg_pl
        legs_journal.append({
            "position_id":   int(leg.get("id")),
            "option_type":   option_type,
            "action_open":   action,
            "strike":        strike,
            "expiry":        expiry.isoformat(),
            "contracts":     contracts,
            "entry_premium": entry_prem,
            "close_premium": current_prem,
            "leg_pl":        leg_pl,
        })

        db.con.execute(
            "UPDATE positions SET active = false WHERE id = ?",
            [int(leg.get("id"))],
        )

    cash_after = cash_now + net_close_cash
    set_cash_balance(db, cash_after)

    _log_trade_event(
        db,
        event_type="close",
        strategy_group_id=strategy_group_id,
        strategy_template=template,
        ticker=ticker,
        legs=legs_journal,
        net_cash=-net_close_cash,           # invert sign to match buy convention
        realized_pl=realized_pl,
        cash_after=cash_after,
        notes="paper-close at BSM mark",
    )
    return (realized_pl, cash_after)


# ── Helpers ──────────────────────────────────────────────────────────

def _coerce_date(v) -> Optional[date]:
    if v is None:
        return None
    try:
        if pd.isna(v):
            return None
    except (TypeError, ValueError):
        pass
    if isinstance(v, date) and not isinstance(v, pd.Timestamp):
        return v
    try:
        return pd.to_datetime(v).date()
    except Exception:
        return None
