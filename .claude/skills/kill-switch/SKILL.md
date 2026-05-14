---
name: kill-switch
description: This skill should be used when working with the kill switch — adding a trip path, modifying reset logic, or interpreting a sticky-file state.
---

# Kill switch — 3 manual + 5 auto

The single most important risk surface. Tripping halts ALL new entries
and (per policy) liquidates undefined-risk positions.

## Three manual trip paths

1. **File flag.** `touch /var/run/volscope/KILL` (path configurable).
   No DB required; survives bot restart.
2. **Env var.** `export BOT_KILL=1`. Next process inherits.
3. **DB row.** `bot_killswitch.active = TRUE`. Set via SQL or
   `KillSwitch.trip()`.

Any of the three trips the bot. `is_tripped()` checks all three in
order; first hit wins.

## Five auto-check functions

Located in `volscope/risk/kill_switch.py`. Each returns
`(should_trip: bool, reason: str)`. Caller (the scheduler loop) calls
them every cycle and invokes `KillSwitch.trip(reason)` on first True.

| Check | Trip when |
|---|---|
| `check_drawdown(nlv_today, nlv_30d_peak)` | DD ≥ 20% from 30-day peak |
| `check_vix(vix_level)` | VIX > 40 |
| `check_daily_loss(today_pnl_pct)` | today PnL ≤ -3% NLV |
| `check_disconnect(seconds_disconnected)` | IBKR off > 60s |
| `check_term_inversion(vix9d, vix)` | VIX9D/VIX > 1.0 (backwardation) |

Thresholds live in `config/risk-thresholds.yaml` (operator-only).

## On trip

`KillSwitch.trip(reason)` does:

1. Writes sticky file at `sticky_path` with `{reason, tripped_at}` JSON.
2. If `db_write` callback is set: UPDATE `bot_killswitch SET active=TRUE`.
3. Caller is responsible for:
   - `ib.reqGlobalCancel()` — cancel all open orders.
   - Selective close of undefined-risk positions per policy.
   - Telegram alert via `volscope/alerts/telegram.py`.
   - `audit_chain.append(kind="kill_trip", payload={"reason": ...})`.

## Reset — literal token gate

`KillSwitch.reset(human_confirmation=token)` REFUSES anything other than:

```
I-RESET-VOLSCOPE-YYYYMMDD     # today's date in UTC
```

Anything else raises ValueError. The literal date enforces "yes, today,
I am resuming live trading." Operators copy-paste this; agents must NOT.

On reset:
1. Deletes sticky file.
2. `os.environ.pop("BOT_KILL")`.
3. If `db_write` set: UPDATE `bot_killswitch SET active=FALSE, reset_at=NOW()`.
4. Appends `audit_chain.append(kind="kill_reset", payload={...})`.

## Hard rules

- **Agents never reset.** The literal token is operator-only.
- **Never modify `reset()`'s token format** without an operator-approved
  ADR.
- **Never bypass `is_tripped()`** in any new code path. Any function
  that could place an order, modify a position, or change risk state
  must check first.

## File location

- `volscope/risk/kill_switch.py`
- Tests: `tests/test_risk_killswitch.py` (15+ tests cover all 8 paths
  + reset literal + idempotency).
- Migration: `volscope/persistence/migrations/002_killswitch.sql`.

## Operator response when tripped

1. Read sticky file for `reason`.
2. Read `bot_audit_chain` recent rows for the trigger event.
3. Decide: was this a real risk event or a false alarm?
4. If real:
   - Hand-flatten positions if scheduler can't.
   - Post-mortem in `docs/post-mortems/`.
   - Wait at least one trading day before reset.
5. If false alarm:
   - Identify the broken check.
   - Add a regression test.
   - Reset with the literal token.

## When NOT to use the kill switch

- Single-trade adjustments — that's `bot_lifecycle.machine.abandon()`.
- Strategy retirement — that's `config/strategies.yaml` edit on Sunday.
- Operator going on vacation — pause via launchd, not kill switch.
