# Mathematical Foundations

Canonical reference for every quantitative formula VolScope implements.
Each section names the citation, the implementation file, the validation
test, and the known approximation limits.

## 1. Black-Scholes-Merton

VolScope uses the continuous-dividend (q-continuous) convention
throughout.

For a European option on an underlying with continuous dividend yield
$q$:

$$
d_1 = \frac{\ln(S/K) + (r - q + \tfrac{1}{2}\sigma^2)T}{\sigma\sqrt{T}}
\qquad
d_2 = d_1 - \sigma\sqrt{T}
$$

$$
C = S e^{-qT} N(d_1) - K e^{-rT} N(d_2)
\qquad
P = K e^{-rT} N(-d_2) - S e^{-qT} N(-d_1)
$$

where $N(\cdot)$ is the standard-normal CDF.

**Implementation:** `volscope/analytics/black_scholes.py::bs_price`.

**Validation:**

- `tests/golden/test_bs_hull.py` — 18 cases against Hull worked
  examples + regression locks.
- `tests/golden/test_quantlib_goldens.py` — 100 random tuples against
  `QuantLib.AnalyticEuropeanEngine`, tolerance 1e-3.
- `tests/properties/test_pyvollib_agreement.py` — 1000 Hypothesis
  cases against `py_vollib_vectorized`, tolerance 1e-8.

**Citations:**

- Hull, J. C. (2018). *Options, Futures, and Other Derivatives*, 10th
  ed., Ch. 15.
- Merton, R. C. (1973). "Theory of rational option pricing." *Bell
  Journal of Economics and Management Science*, 4(1), 141-183.

**Approximation limits:**

- European exercise only — American exercise needs binomial / LSM.
- Constant volatility — for skew / smile see SVI (v0.7.0+ scope).
- Continuous dividends — discrete dividends need PDE solver or jump
  adjustment.

---

## 2. Greeks

$$
\Delta_{\text{call}} = e^{-qT} N(d_1)
\qquad
\Delta_{\text{put}} = e^{-qT}(N(d_1) - 1)
$$

$$
\Gamma = \frac{e^{-qT} n(d_1)}{S \sigma \sqrt{T}}
$$

$$
\mathcal{V} = S e^{-qT} n(d_1) \sqrt{T}
$$

$$
\Theta_{\text{call}} = -\frac{S e^{-qT} n(d_1) \sigma}{2\sqrt{T}}
  - r K e^{-rT} N(d_2)
  + q S e^{-qT} N(d_1)
$$

$$
\rho_{\text{call}} = K T e^{-rT} N(d_2)
\qquad
\rho_{\text{put}} = -K T e^{-rT} N(-d_2)
$$

$n(\cdot)$ is the standard-normal PDF.

**Implementation:** `volscope/analytics/black_scholes.py::bs_delta`,
`bs_gamma`, `bs_vega`, `bs_theta`, `bs_rho`.

**Validation:** Hull Ch. 19 reference values + put-call parity
($\Delta_{\text{call}} - \Delta_{\text{put}} = e^{-qT}$) enforced in
property tests.

**Sign conventions:**

- $\mathcal{V}$ is per unit change in $\sigma$ (decimal). Per 1% IV
  divide by 100.
- $\Theta$ is per unit calendar time (year). Per day divide by 365.

---

## 3. Implied Volatility solver

Given an observed market price $P_{\text{mkt}}$, find $\sigma$ such
that $\text{BSM}(S, K, T, r, \sigma, q, \text{type}) = P_{\text{mkt}}$.

**Algorithm:** Newton-Raphson with Brenner-Subrahmanyam (1988)
initial guess; bisection fallback when vega is near zero or
$\sigma$ escapes the bracket $[10^{-4}, 10]$.

Brenner-Subrahmanyam initial guess:

$$
\sigma_0 \approx \sqrt{\frac{2\pi}{T}} \cdot
  \frac{P - \frac{1}{2}\max(S e^{-qT} - K e^{-rT}, 0)}{S}
$$

**Convergence:** typically 3-5 Newton iterations for tradable
options; bisection always converges in $\le 50$ iterations.

**Arbitrage bounds — refuse to solve:**

$$
\max(S e^{-qT} - K e^{-rT}, 0) \le C \le S e^{-qT}
\qquad
\max(K e^{-rT} - S e^{-qT}, 0) \le P \le K e^{-rT}
$$

If the market price violates these, the solver returns `None`.

**Implementation:** `volscope/analytics/black_scholes.py::implied_volatility`.

**Validation:** `tests/properties/test_iv_round_trip.py` — 2000
Hypothesis examples; $\sigma \rightarrow P \rightarrow \hat{\sigma}$
must satisfy $|\hat{\sigma} - \sigma| < 10^{-4}$.

**Citations:**

- Brenner, M., & Subrahmanyam, M. G. (1988). "A simple formula to
  compute the implied standard deviation." *Financial Analysts
  Journal*, 44(5), 80-83.
- Hull (2018), Ch. 19.

---

## 4. Historical Volatility Estimators

Four estimators, increasing efficiency. All annualised via
$\sigma_{\text{ann}} = \sigma_{\text{daily}} \cdot \sqrt{252}$.

### 4.1 Close-to-Close

$$
\sigma_{CC}^2 = \frac{252}{n-1} \sum_{i=1}^{n} r_i^2
\quad\text{where}\quad
r_i = \ln(C_i / C_{i-1})
$$

**Efficiency:** 1 (baseline).

### 4.2 Parkinson (1980)

$$
\sigma_P^2 = \frac{252}{4 n \ln 2} \sum_{i=1}^{n} [\ln(H_i / L_i)]^2
$$

**Efficiency:** ~5× over CC. **Assumes zero drift.**

### 4.3 Garman-Klass (1980)

$$
\sigma_{GK}^2 = \frac{252}{n}\sum_{i=1}^{n}\left[
  \frac{1}{2}\left[\ln(H_i/L_i)\right]^2
  - (2\ln 2 - 1)\left[\ln(C_i/O_i)\right]^2
\right]
$$

**Efficiency:** ~7.4× over CC. **Assumes zero drift.**

### 4.4 Yang-Zhang (2000)

The min-variance unbiased estimator combining overnight + intraday:

$$
\sigma_{YZ}^2 = \sigma_{\text{overnight}}^2
  + k \sigma_{\text{O→C}}^2
  + (1-k) \sigma_{RS}^2
$$

where $\sigma_{RS}^2$ is the Rogers-Satchell (1991) estimator
(drift-independent) and $k = \frac{0.34}{1.34 + (n+1)/(n-1)}$.

**Efficiency:** ~14× over CC; drift-independent; min-variance unbiased.

**Implementation:** `volscope/analytics/hv_*.py`.

**Validation:** `tests/properties/test_hv_estimators_mc.py` — generates
log-normal returns with known $\sigma$, recovers via all four; asserts
ordering + YZ has lowest sample variance + YZ is drift-independent.

**Citations:**

- Parkinson, M. (1980). "The extreme value method for estimating
  the variance of the rate of return." *Journal of Business*,
  53(1), 61-65.
- Garman, M., & Klass, M. (1980). "On the estimation of security
  price volatilities from historical data." *Journal of Business*,
  53(1), 67-78.
- Rogers, L. C. G., & Satchell, S. E. (1991). "Estimating variance
  from high, low and closing prices." *Annals of Applied
  Probability*, 1(4), 504-512.
- Yang, D., & Zhang, Q. (2000). "Drift-independent volatility
  estimation based on high, low, open, and close prices."
  *Journal of Business*, 73(3), 477-491.

---

## 5. IV Rank, IV Percentile, VRP

### IV Rank

$$
\text{IVR}_t = 100 \cdot
  \frac{\text{IV}_t - \min_{s \in [t-252, t]} \text{IV}_s}
       {\max_{s \in [t-252, t]} \text{IV}_s - \min_{s \in [t-252, t]} \text{IV}_s}
$$

### IV Percentile

$$
\text{IVP}_t = 100 \cdot \frac{|\{s \in [t-252, t] : \text{IV}_s < \text{IV}_t\}|}{252}
$$

### Volatility Risk Premium (VRP) proxy

$$
\text{VRP}_t = \frac{\text{IV}_t^{(30)}}{\text{HV}_t^{(20, YZ)}}
$$

Empirical fact (Bali et al. 2008): VRP > 1 in ~85% of months;
average gap ≈ 4.2 vol points.

**Implementation:** `volscope/signals/factors.py::ivr`, `ivp`,
`iv_hv_ratio`.

**Citations:**

- MenthorQ 10-year SPY study — ROI sweet spot at IVR > 30; peak at
  IVP > 70.
- Bali, T. G., Cakici, N., & Whitelaw, R. F. (2008). "Maxing out:
  Stocks as lotteries and the cross-section of expected returns."
  *Journal of Financial Economics*, 99(2), 427-446.

---

## 6. Composite signal score

Weighted blend:

$$
\text{score} =
  0.15 \cdot s_{\text{IVR}}
+ 0.20 \cdot s_{\text{IVP}}
+ 0.20 \cdot s_{\text{VRP}}
+ 0.15 \cdot s_{\text{term}}
+ 0.05 \cdot s_{\text{skew}}
+ 0.10 \cdot s_{\text{mom}}
+ 0.15 \cdot s_{\text{regime}}
$$

Each sub-score maps to $[0, 100]$ via a direction-aware band.
NaN factors drop out; remaining weights renormalize.

Sizing map: $<50 \to 0$; $[50, 65) \to 0.25$; $[65, 80) \to 0.50$;
$[80, 90) \to 0.75$; $\ge 90 \to 1.00$.

**Implementation:** `volscope/signals/composite.py::composite_score`,
`size_from_score`.

**Derivation of weights:**

Empirical: IVP slightly preferred to IVR in normal regimes (MenthorQ
post-shock data) → weight 0.20 vs 0.15. VRP equally weighted to IVP
(Barclays VRP study). Term + regime jointly capture vol-curve shape
+ regime-conditional persistence → 0.15 each. Skew is a secondary
filter — small weight 0.05. HV momentum is a velocity indicator —
0.10.

Weights are non-negotiable without an ADR + 90-day cooldown
(`config/risk-thresholds.yaml`).

---

## 7. HMM regime detection

Two-state Gaussian HMM over features $(\Delta \text{VIX}, \text{SPY}^{(20d, YZ)})$.

Hidden-state label assignment: the state with higher mean realised
vol is "stress"; the other is "calm." Inference returns
$p_{\text{calm}}(t) = \Pr[\text{state}_t = \text{calm} \mid x_{1:t}]$.

**Hard rule:** short-vol entries require $p_{\text{calm}} > 0.6$.

**Persistence:** the model raises if trained on fewer than 252
observations (research-flagged minimum for stable transition matrix).

**Label-stability fix:** the EM algorithm does NOT guarantee state
ordering across fits. Always reorder post-fit by mean realised vol
so "stress" stays state 1.

**Implementation:** `volscope/analytics/regime.py::RegimeDetector`.

**Citations:**

- López de Prado, M. (2018). *Advances in Financial Machine
  Learning*, Ch. 11.
- Polavarapu (2025). "Cross-asset HMM regime detection." SSRN 6539358.

---

## 8. GARCH(1,1)-t

Conditional variance:

$$
\sigma_t^2 = \omega + \alpha r_{t-1}^2 + \beta \sigma_{t-1}^2
$$

Persistence $\alpha + \beta < 1$ required for stationarity. The model
refuses to forecast if $\alpha + \beta \ge 1$ (raises ValueError).

Forecast: 30-day average annualised $\sigma$ for the composite VRP
proxy.

**Implementation:** `volscope/analytics/garch.py::GarchForecaster`.

**Citations:**

- Bollerslev, T. (1986). "Generalized autoregressive conditional
  heteroskedasticity." *Journal of Econometrics*, 31(3), 307-327.
- Engle, R. F., & Patton, A. J. (2001). "What good is a volatility
  model?" *Quantitative Finance*, 1(2), 237-245.

---

## 9. Validation summary

| Component | Validation method | Tolerance | File |
|---|---|---|---|
| BSM price | Hull Ch.15+19 goldens | 0.01 | `tests/golden/test_bs_hull.py` |
| BSM price | QuantLib `AnalyticEuropeanEngine` | 1e-3 | `tests/golden/test_quantlib_goldens.py` |
| BSM price | `py_vollib_vectorized` | 1e-8 | `tests/properties/test_pyvollib_agreement.py` |
| Put-call parity | Hypothesis property (1000 ex.) | 1e-6 | `tests/properties/test_put_call_parity.py` |
| Arbitrage bounds | Hypothesis property (500 ex.) | 1e-6 | `tests/properties/test_put_call_parity.py` |
| Vega monotonicity | Hypothesis property (200 ex.) | n/a (sign) | `tests/properties/test_put_call_parity.py` |
| IV solver round-trip | Hypothesis property (2000 ex.) | 1e-4 | `tests/properties/test_iv_round_trip.py` |
| HV estimators | Monte-Carlo recovery | 3 SE | `tests/properties/test_hv_estimators_mc.py` |
| HV efficiency ordering | Monte-Carlo (30 seeds) | 2× | `tests/properties/test_hv_estimators_mc.py` |
| HV drift-independence | Monte-Carlo | 1% | `tests/properties/test_hv_estimators_mc.py` |

Total math-validation surface as of v0.6.0: **~3,700 individual
assertions per CI run** (18 goldens + 100 QuantLib + 1000 + 500 + 200
+ 2000 + property tests + 30 MC seeds).

---

## 10. Known approximation limits + open work (v0.7.0+)

- **American exercise:** binomial / LSM Monte-Carlo. Not in scope for
  v0.7.0; banked.
- **Discrete dividends:** PDE solver. Banked.
- **Volatility smile / surface:** SVI per-slice → SSVI joint. v0.7.0+
  (per `docs/roadmap/MASTERPIECE_BACKLOG.md` B7).
- **Jump-diffusion:** Merton (1976) for earnings + Kou (2002) for
  asymmetric jumps. v0.8.0+.
- **Stochastic volatility:** Heston (1993). Not in scope.
- **Multi-asset / basket options:** correlation matrix calibration.
  Not in scope.

All open items are tracked in
`docs/roadmap/MASTERPIECE_BACKLOG.md` Category A (Math + Analytics
Validation).
