# ADR-0006: TradingView Lightweight Charts for price, Plotly for analytics

## Status

Accepted — 2026-05-14.

## Context

The v0.6.x line shipped a research workbench whose price charts —
rendered as `go.Scatter` with `shape="spline"` + `fill="tozeroy"` —
looked like a notebook plot, not a trader's chart. The operator
benchmarked them against TradingView, IBKR TWS, and Hyperliquid and
found them visibly inferior on six axes:

- no candlesticks (OHLC wicks hidden by spline smoothing),
- no native range-selector (1D / 5D / 1M / 3M / 6M / 1J / YTD / ALL),
- no vertical-crosshair on hover,
- no volume sub-pane,
- no drag-to-zoom,
- no built-in series toggles.

Three realistic options:

1. **Embed the TradingView Advanced Chart widget** (iframe / JS bridge).
2. **`streamlit-lightweight-charts`** — Streamlit wrapper around
   TradingView's own MIT-licensed Lightweight Charts library.
3. **Aggressively upgrade Plotly** with `go.Candlestick`, `xaxis.rangeselector`,
   `xaxis.showspikes`, etc.

The dashboard's *unique value* is the overlay layer the operator
ships on top of price: IV %-rank historical line, HMM regime-shading
bands, 52-week IV-band horizontals, scanner-signal markers, earnings
markers from `bot_earnings_calendar`. These overlays must remain
plottable. They are what differentiates VolScope from a generic
charting tool.

## Decision

Adopt **`streamlit-lightweight-charts`** for the *price* surface on
Scope, Pre-Trade, and Options Lab. Keep **Plotly** for the
*volatility / analytics* surface (IV/HV multi-line, skew, term
structure, sector rotation, heatmaps).

A second helper module — `volscope/ui/components/lwc_chart.py` —
exposes `price_chart_lwc(history, *, with_volume, with_iv_overlay,
with_regime_shading, with_earnings_markers)` and returns the spec
the wrapper consumes.

## Consequences

- **Positive — visual parity with TradingView.** Lightweight Charts
  *is* the library TradingView ships for embedded charts; the visual
  feel matches without an iframe.
- **Positive — own-data, own-overlays.** Unlike option 1, we feed
  our DuckDB rows, and we can stack as many additional series as we
  like (IV %-rank line, HMM-stress band, earnings markers).
- **Positive — no external service call.** All rendering is local
  JS bundled with the wrapper; no GDPR-painful iframe, no third-party
  data fetch, no tracking cookies.
- **Positive — Plotly remains for what it is good at.** Multi-line
  IV/HV overlays, skew curves, heatmaps, sector rotation: Plotly's
  layout / annotation / shape primitives are still best-in-class
  for analytical charts.
- **Negative — new dependency.** `streamlit-lightweight-charts` is
  a small pure-Python wrapper, but it bundles a JS payload (~80 KB
  gzipped). Pinned in `requirements.txt`.
- **Negative — split rendering knowledge.** Maintainers must know
  *both* libraries. Mitigated by isolating the LWC path to
  `lwc_chart.py` so most calling code is unaware of the underlying
  engine.

## Rejected: TradingView widget embed

Tested in v0.7.0 exploration and rejected. It loses the overlay
layer — TV widget renders TV's data, not ours, and refuses external
series — which removes the entire reason VolScope exists.

## Rejected: pure-Plotly upgrade

`go.Candlestick` + `xaxis.rangeselector` + `xaxis.showspikes` gets
us 70% of the visual parity but still feels like a *plot of trading
data*, not a *trading chart*. The operator A/B'd a hand-built
Plotly candlestick against `streamlit-lightweight-charts` and chose
the latter.

## Migration plan

- v0.7.0 — Scope price section, Pre-Trade underlying chart,
  Options-Lab pro chart.
- v0.8.0 — Bot Dashboard equity curve (if `st.line_chart` proves
  too generic).
- Never — IV/HV section, skew curves, sector rotation heatmap,
  earnings hub grid (Plotly stays).
