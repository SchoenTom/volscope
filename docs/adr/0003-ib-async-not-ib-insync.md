# ADR-0003: `ib_async` (not `ib_insync`) as the IBKR client library

## Status

Accepted — 2026-05-14.

## Context

The two community Python clients for Interactive Brokers:

1. **`ib_insync`** — the long-standing standard. Original maintainer
   Ewald de Wit passed away in March 2024. Final release 0.9.86. The
   repo is archived on GitHub. Does not track TWS 10.30+ protocol
   changes.
2. **`ib_async` 2.1.0** (released 2025-12-08, conda-forge 2025-12-18) —
   community fork of `ib_insync` under the `ib-api-reloaded` org,
   maintained by Matt Stancliff. **Drop-in API compatible**
   (`from ib_async import *`). BSD-2 licensed. Python 3.10+ including
   3.13/3.14. Actively tracks TWS protocol updates.
3. **Official `ibapi`** — verbose EClient/EWrapper callbacks; useful as
   a fallback if `ib_async` lacks a brand-new feature.

## Decision

Use `ib_async==2.1.0` for all new code. Pin the major version in
`pyproject.toml`.

## Consequences

- **Positive — maintenance**: a maintained library matters for a system
  that risks real money. Bugs in IBKR-client code can mean unfilled
  closes / mis-routed orders.
- **Positive — drop-in**: any code patterns from `ib_insync` tutorials /
  docs translate directly. The import path change is `ib_insync` →
  `ib_async`; everything else is identical.
- **Positive — protocol parity**: `ib_async` tracks TWS 10.30+, where
  `ib_insync` does not. Future IBKR feature releases will land.
- **Negative — ecosystem maturity**: documentation thinner than
  `ib_insync`. We compensate by reading the source + writing
  integration tests against the paper account before live use.
- **Negative — version churn risk**: a newer fork can have surprise
  regressions. We pin to `==2.1.0` and only bump after a paper-trading
  regression test.

## Implementation note

All IBKR access is mediated by `volscope/execution/ibkr_stub.py` (Phase
1 scaffold) → `volscope/execution/ibkr_client.py` (Phase 2.5). The
import of `ib_async` is **deferred** so that running the rest of the
codebase without the bot extras installed (`uv sync --no-extras`) still
works.

## When to revisit

- If `ib_async` development stalls again for > 6 months.
- If we hit a TWS feature that requires direct `ibapi` access.
