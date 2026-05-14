---
paths:
  - volscope/execution/**
  - volscope/lifecycle/**
  - volscope/risk/**
description: Live-trading guardrails. Applies on every edit under volscope/execution/, lifecycle/, or risk/.
---

# Rules for `volscope/execution/`, `volscope/lifecycle/`, `volscope/risk/`

## Live IBKR orders are FORBIDDEN

Until Phase 4 with explicit operator opt-in:

- No code path may instantiate an IBKR client with intent to send a
  real order.
- `ibkr_stub.py` is the production engine right now. It RETURNS on
  connect failure; never throws.
- `paper_engine.py` writes to `bot_trades` / `bot_legs`, NOT to a
  broker.

## Read-only IBKR by default

When the live `ibkr_client.py` lands (Phase 2.5+), `read_only=True`
must be the default in `IBKRSettings`. Enabling trading requires:

1. `ENABLE_TRADING=1` env var, OR
2. Explicit `IBKRSettings(read_only=False)` in code with an
   accompanying ADR.

Even with `read_only=False`, an operator-signed flag in `bot_killswitch`
must clear the live-trading gate. (v0.6.0+ enforcement.)

## clientId discipline

- `clientId=0` is RESERVED for the master view (sees manual GUI orders).
  NEVER use it from the bot.
- VolScope bot = clientId 1.
- Scripts (chain scrape, reconcile) = clientId 100+.

## Kill switch is sacred

Every code path that could place an order, modify a position, or
change risk state must check `KillSwitch.is_tripped()` FIRST. There
are no shortcuts.

## Position size = quarter-Kelly default

`config/risk-thresholds.yaml::position_sizing.kelly_fraction = 0.25`.
Changes require:
1. `OPERATOR_APPROVED=yes` in the commit trailer.
2. New ADR.
3. Sunday 18:00 ET review window.
4. 90-day cooldown since last threshold change.

## 21-DTE mechanical close

Every short-vol strategy MUST include `dte_exit: 21`. The validator
in `volscope/strategies/` rejects configs without it (v0.5.1
enforcement target).

## Idempotency for live (Phase 2.5+)

The pattern is documented in `volscope/execution/intent_manager.py`:
`create_intent()` BEFORE any chain lookup or broker call. The
`intent_uuid` is the canonical key — same UUID, same trade.

## Reconciliation on reconnect

Every IBKR reconnect must call `ib.reqAllOpenOrders()` +
`ib.reqExecutions()` and diff against `bot_order_intents`. See
`scripts/ops/reconcile.py` (stub in v0.5.0; full implementation
v0.6.0 B3).
