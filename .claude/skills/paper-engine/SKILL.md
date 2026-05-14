---
name: paper-engine
description: This skill should be used when authoring or reviewing the paper-engine flow — taking a RankedSignal, looking up real chain quotes, applying slippage, and writing transactional trade rows.
---

# Paper engine — RankedSignal → bot_trades

## Flow

```
RankedSignal
  → blueprint_factory(signal, db)        # strategy-specific
  → TradeBlueprint                       # multi-leg specification
  → for each leg:
      get_quote(db, ticker, target_strike, expiry, right)
        → resolves to closest available strike (within 5%)
      apply_slippage(quote, side, slippage_model, dte, is_index)
        → buy = mid + haircut × (spread/2)
        → sell = mid - haircut × (spread/2)
  → FilledTrade (in-memory)
  → _persist(): bot_trades INSERT + bot_legs INSERT (one transaction)
  → audit_chain.append(kind="order_submitted", payload=...)
```

## File locations

- `volscope/execution/paper_engine.py::execute_blueprint`
- `volscope/execution/paper_engine.py::execute_signal` (high-level)
- `volscope/data/chain_quote.py::get_quote` + `apply_slippage`

## Transactional invariants

1. **All legs fill or none fill.** If any leg fails the chain lookup,
   reject the whole trade (return None). No partial writes.
2. **`bot_trades.status = 'FILLED'` on success.** Paper engine has no
   broker round-trip, so SIGNALED → SIZED → SUBMITTED → FILLED happen
   in one synchronous step.
3. **`bot_trades.legs_snapshot` is JSON-frozen at write time.** The
   exact strikes / expiries / fills used. Even if `bot_legs` is later
   re-queried, this snapshot tells you what the engine saw.
4. **`net_credit_or_debit` sign convention:**
   - Positive = credit (we received premium). Short-vol structures.
   - Negative = debit (we paid premium). Long-vol structures.

## Idempotency (v0.5.0)

Paper engine should call `intent_manager.create_intent()` BEFORE the
chain lookup, then `mark_submitted()` after the write succeeds. The
`intent_uuid` becomes the canonical idempotency key — same UUID, same
trade, no duplicates on retry.

```python
from volscope.execution.intent_manager import create_intent, mark_submitted, mark_rejected
intent_uuid = create_intent(db, strategy=..., underlying=..., direction=...,
                              intended_legs=...)
try:
    filled = execute_blueprint(db, blueprint=..., slippage=...)
    if filled:
        mark_submitted(db, intent_uuid, order_ref=filled.trade_id)
        mark_acked(db, intent_uuid)         # paper has no broker delay
    else:
        mark_rejected(db, intent_uuid, reason="chain unquotable")
except Exception as exc:
    mark_rejected(db, intent_uuid, reason=str(exc))
    raise
```

## Slippage model

From `config/risk.yaml::slippage_model`:

| Spread tier | Index tight | Medium | Wide |
|---|---|---|---|
| Base haircut | 0.30 | 0.50 | 0.70 |

Plus:
- Short DTE (≤1 day): +0.10 to base
- Long DTE (>60 days): +0.05 to base

Final per-leg slippage = `haircut_pct × (spread / 2)`.

## Strike fallback rules

`get_quote` falls back to closest available strike within 5%
tolerance + 7-day expiry tolerance. This mirrors what a real broker
does ("fill at the nearest tradable strike"). If both bounds exceeded:
return None, trade rejected.

## What the paper engine does NOT do

- **No live IBKR.** Output goes to `bot_trades`, not the broker.
- **No async.** All operations are synchronous DuckDB writes.
- **No retry on failure.** The intent_manager + reconciler handle
  retries.
- **No order management.** That's `daily_mtm.py` + `lifecycle/machine.py`.

## Testing

- `tests/test_chain_snapshots.py` — quote lookup + slippage
- (v0.6.0) `tests/test_paper_engine.py` — synthetic chain → execute →
  verify bot_trades row.

## When to extend

- New strategy → new `blueprint_factory` in `volscope/strategies/`.
  No paper-engine changes needed.
- New leg type (e.g. crypto) → extend `LegSpec.right` enum + add a
  `multiplier` field (BSM uses 100 for equity, 1 for FX).
