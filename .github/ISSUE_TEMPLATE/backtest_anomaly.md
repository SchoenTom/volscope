---
name: Backtest / data anomaly
about: Report suspicious IV data or unexpected backtest result
labels: data-quality
---

## Symptom
<!-- "AAPL IV = 1.2 on 2026-03-04" or "Sharpe = 8.5 on 45-DTE IC backtest" -->

## Why is this anomalous
<!-- Vs. published reference data / common sense / prior runs. -->

## Reproduction
- Ticker:
- Date range:
- Strategy / metric:
- Command run:

```
```

## Likely root cause
- [ ] Scraper bug (HTML parse failure / yfinance regression)
- [ ] Look-ahead bias in backtest engine
- [ ] Survivorship bias (delisted ticker)
- [ ] Numerical instability (extreme IV / σ)
- [ ] Real market data anomaly (corporate action / split / spinoff)
- [ ] Unknown

## Action items
- [ ] Reproduce in a test
- [ ] Add a data-quality filter (`valid_iv` boolean?)
- [ ] Document in ADR if it's a methodology shift
