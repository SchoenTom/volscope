---
name: ibkr-adapter
description: This skill should be used when authoring or reviewing IBKR connectivity code (ib_async). Covers clientId discipline, rate-limit semaphore, BAG combo orders, walk-price algorithm, and the reconnect-reconcile pattern.
---

# IBKR adapter — ib_async 2.1+

## Library choice — ADR-0003

Use `ib_async` (NOT archived `ib_insync`). Drop-in API compatible:

```python
from ib_async import IB, Stock, Option, Combo, ComboLeg, MarketOrder, LimitOrder
```

## Connection

```python
ib = IB()
await ib.connectAsync(
    host="127.0.0.1",
    port=7497,           # paper; live = 7496
    clientId=1,          # NEVER 0 (master sees manual GUI orders)
    timeout=20,
)
```

`clientId` discipline:

| clientId | Use |
|---|---|
| 0 | RESERVED — master view, sees manual GUI orders. Forbidden for bot. |
| 1 | VolScope paper engine |
| 2 | VolScope live engine (Phase 4+) |
| 100+ | Ad-hoc scripts (chain scrape, reconcile) |

## Rate limit

IBKR: 50 messages/second hard cap per client connection. Always wrap
calls in `asyncio.Semaphore(40)` for headroom:

```python
RATE_LIMIT = asyncio.Semaphore(40)

async def safe_call(coro):
    async with RATE_LIMIT:
        return await coro
```

Historical-data pacing is stricter:
- No identical request within 15s.
- No ≥6 requests per (Contract, Exchange, TickType) per 2s.
- No >60 historical requests per 10 minutes.

Use ib_async's built-in `ib.reqHistoricalDataAsync()` with care; cache
locally in DuckDB.

## BAG (combo) orders

Iron condors, strangles, spreads — always send as a SINGLE bag, never
4 separate orders. This ensures atomic fill, correct spread margin,
zero legging risk.

```python
contract = Contract(symbol="SPY", secType="BAG", currency="USD", exchange="SMART")
contract.comboLegs = [
    ComboLeg(conId=short_call_conid, ratio=1, action="SELL", exchange="SMART"),
    ComboLeg(conId=long_call_conid,  ratio=1, action="BUY",  exchange="SMART"),
    ComboLeg(conId=short_put_conid,  ratio=1, action="SELL", exchange="SMART"),
    ComboLeg(conId=long_put_conid,   ratio=1, action="BUY",  exchange="SMART"),
]
order = LimitOrder("BUY", 1, limitPrice=NET_CREDIT)
```

Routing:
- `SMART` for SPY / QQQ / IWM (penny-pilot equity options).
- `CBOE` for SPX / VIX / RUT (cash-settled index options).
- Never `MKT` for options. Bid-ask spreads are wide.

## Walk-price algorithm

Limit order at combo mid; if not filled in 30 seconds, adjust 1 tick
adverse. Cap at 5 ticks adverse; if still unfilled, cancel.

```python
async def walk_price(ib, contract, side, mid, max_ticks=5, tick_size=0.05,
                     sleep_s=30):
    px = mid
    for tick in range(max_ticks + 1):
        order = LimitOrder(side, 1, limitPrice=px)
        trade = ib.placeOrder(contract, order)
        await asyncio.sleep(sleep_s)
        if trade.isDone():
            return trade
        ib.cancelOrder(order)
        px += tick_size if side == "BUY" else -tick_size
    return None  # failed
```

## Watchdog (recommended pattern)

```python
from ib_async import Watchdog, IBC, IB
ibc = IBC(host="127.0.0.1", port=7497, ...)
ib = IB()
watchdog = Watchdog(ib, ibc, port=7497, clientId=1)
watchdog.start()
```

Auto-reconnect, dismiss daily-restart dialogs.

## Reconnect → reconcile

On every reconnect:

```python
positions = ib.positions()
executions = ib.executions()
# Diff against bot_order_intents WHERE status IN ('PENDING', 'SUBMITTED')
# Resolve via intent_manager.mark_acked() or mark_rejected()
# See scripts/ops/reconcile.py
```

## Greeks via reqMktData

```python
ticker = ib.reqMktData(contract, genericTickList="106")
await asyncio.sleep(0.5)  # let one tick come back
delta = ticker.modelGreeks.delta if ticker.modelGreeks else None
```

`bidGreeks` / `askGreeks` are also available — useful for trade-entry
edge estimation.

## Hard rules

- **NEVER `clientId=0`** for the bot.
- **NEVER `MKT` orders** for options.
- **NEVER skip the reconciler** after reconnect — every PENDING /
  SUBMITTED intent must be resolved before new trades.
- **NEVER place real-money orders** until Phase 4 with operator opt-in.
  v0.3.0+ paper engine routes everything to `bot_chain_snapshots`,
  not IBKR.
