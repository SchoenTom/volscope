---
paths:
  - volscope/analytics/**
description: Analytics-layer invariants — applies on every edit under volscope/analytics/.
---

# Rules for `volscope/analytics/`

These rules apply automatically when editing any file under
`volscope/analytics/`.

## Pure functions

- No I/O inside analytics functions (no DuckDB writes, no network).
- No global mutable state.
- All inputs validated; bad input returns `None`, never raises.

## Yahoo IV is forbidden

- `yfinance.Ticker(...).option_chain(...).impliedVolatility` MUST NOT
  be used as a price input. Always recompute IV from the bid/ask mid
  via VolScope's own Newton-Raphson solver.
- Reason: Yahoo's IV is opaque, stale, rate-limited, and off by 1-3%
  in stress.

## Plotly: `go` only

- `import plotly.graph_objects as go` is the ONLY allowed Plotly path.
- `plotly.express` is REJECTED on any review.

## Black-Scholes conventions

- Continuous-dividend (q-continuous) throughout. See
  `.claude/skills/black-scholes-pricing/SKILL.md`.
- Year fraction = `days / 365` for time-to-expiry (not 252; that's
  the annualisation factor for volatility).
- Put-call parity must hold to 1e-6 for any (S, K, T, r, σ, q). The
  Hypothesis property test at `tests/properties/test_put_call_parity.py`
  enforces this.

## HV estimators

- Default = Yang-Zhang. Fall back to Close-Close only if OHLC
  missing.
- Never subtract sample mean from log returns when computing for use
  in BSM (BSM uses variance with mean 0).

## Citations required

Every new factor / metric must include a citation in its docstring
(Hull chapter, Bali 2008, Yang-Zhang 2000, etc.). No anonymous
constants.
