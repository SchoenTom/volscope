---
name: VolScope ML Signal Direction Asymmetry
description: The ML buy_prob predicts IV falling, which is opposite the direction a long-vol buyer wants — important context when interpreting ML badge or building any new score on top of it
type: project
originSessionId: 716ba485-d808-4974-bcf7-dfef50adc832
---
`volscope/analytics/ml_signal.py` defines its target as:

```
y = 1 if iv_30d[t+10] < iv_30d[t]   (IV mean-reverted DOWN)
buy_prob = P(y=1) = P(IV falls in next 10d)
```

The existing `ml_badge_html()` labels high buy_prob as "ML BUY · XX%" in
green. This naming is calibrated for a SHORT-vol seller (theta/vega decay
strategies) — not for Operator.

**Operator's book is LONG vol** (Sep 2027 DAX puts, Dec 2026 Nasdaq puts,
knockouts on MSTR/SNOW/1810.HK). He WANTS IV to rise after entry. So for
his perspective, high `buy_prob` = bad entry, low `buy_prob` = good entry.

**Why:** This subtle inversion is easy to miss when reading the codebase —
"ML BUY" reads as "buy signal" but it's actually "buy a vol-seller setup".

**How to apply:**
- The new `analytics/edge_score.py` (2026-05-01) explicitly inverts:
  `ml_score = 100 * (1 - buy_prob)`. Reuse this convention if you build
  any further long-vol composite signal.
- Don't blindly chain into ml_badge_html for Operator-facing actionable
  recommendations. Either rename the badge ("ML BUY (vol-seller)") or
  invert it. As of 2026-05-01 the badge has not been touched.
- If a future feature uses ML for the BUY-CHEAP-VOL workflow, remember to
  invert. Don't trust the badge label as guidance for a long-vol entry.
