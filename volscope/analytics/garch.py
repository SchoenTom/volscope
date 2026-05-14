"""
GARCH(1,1)-t volatility forecast wrapper — Phase 1 finishing.

Thin wrapper over the `arch` library. Used to project realised
volatility forward 30 days. Paired with the HMM regime detector
(`volscope/analytics/regime.py`), this is the "forward-looking RV"
side of the composite signal score.

Deferred import: `arch` is in the `bot` extras (`uv sync --extra bot`).
The rest of the codebase imports `analytics.garch` safely even without
the dep installed; `GarchForecaster.fit()` raises a clear error at
that point.

References:
- Bollerslev (1986) — GARCH foundational paper.
- Engle & Patton (2001) — "What good is a volatility model?"
- arch library docs: https://arch.readthedocs.io/
"""
from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np
import pandas as pd

if TYPE_CHECKING:
    pass


class GarchForecaster:
    """
    GARCH(1,1) with Student-t innovations.

    Defaults are the practitioner-standard model for equity returns:
    - p=1 (one ARCH lag)
    - q=1 (one GARCH lag)
    - dist="t" (Student-t residuals — captures fat tails)
    """

    def __init__(self, *, p: int = 1, q: int = 1, dist: str = "t"):
        self.p = p
        self.q = q
        self.dist = dist
        self._result = None
        self._is_fit = False

    def fit(self, log_returns: pd.Series) -> "GarchForecaster":
        """
        Fit the model on a series of daily log returns.

        Returns self (chainable). Raises if the persistence (α+β) is
        ≥ 1 — that means the model is non-stationary and forecasts
        will diverge.
        """
        try:
            from arch import arch_model  # type: ignore[import-not-found]
        except ImportError as exc:
            raise ImportError(
                "GarchForecaster.fit() requires the `arch` library. "
                "Install with `uv sync --extra bot`."
            ) from exc

        x = log_returns.dropna().to_numpy(dtype=float)
        if x.shape[0] < 60:
            raise ValueError(
                f"need at least 60 observations to fit GARCH(1,1), got {x.shape[0]}"
            )
        # Scale to percent — `arch` recommends this for numerical stability
        # on small daily returns. We unscale on output.
        x_pct = x * 100.0

        model = arch_model(x_pct, vol="GARCH", p=self.p, q=self.q,
                            dist=self.dist, rescale=False)
        self._result = model.fit(disp="off", show_warning=False)
        alpha = float(self._result.params.get("alpha[1]", 0.0))
        beta = float(self._result.params.get("beta[1]", 0.0))
        persistence = alpha + beta
        if persistence >= 1.0:
            raise ValueError(
                f"GARCH non-stationary (α+β = {persistence:.4f} >= 1.0); "
                "refusing to forecast — try a different sample or model."
            )
        self._is_fit = True
        return self

    def forecast_vol(self, horizon: int = 30) -> float:
        """
        Forecast the average volatility over the next ``horizon`` days,
        annualised (σ × √252) and returned in *decimal* form (0.20 = 20%).
        """
        if not self._is_fit:
            raise RuntimeError("GarchForecaster.fit() must be called first.")
        fc = self._result.forecast(horizon=horizon, reindex=False)
        # `arch` returns variances in (pct return)² space. We need:
        #   daily σ in decimal = sqrt(variance) / 100
        #   horizon-average → mean of daily variances over the horizon
        #   annualise → × sqrt(252)
        var_pct2 = fc.variance.values[-1, :]   # shape (horizon,)
        avg_daily_var_pct2 = float(np.mean(var_pct2))
        daily_sigma_decimal = float(np.sqrt(avg_daily_var_pct2) / 100.0)
        return daily_sigma_decimal * float(np.sqrt(252.0))

    def conditional_vol(self) -> pd.Series:
        """
        In-sample conditional volatility series, annualised and in
        decimal form. Useful for diagnostics + plotting.
        """
        if not self._is_fit:
            raise RuntimeError("GarchForecaster.fit() must be called first.")
        cv_pct = self._result.conditional_volatility   # daily σ in pct
        cv_decimal = pd.Series(np.asarray(cv_pct, dtype=float) / 100.0)
        return cv_decimal * float(np.sqrt(252.0))

    @property
    def is_fit(self) -> bool:
        return self._is_fit

    @property
    def params(self) -> dict[str, float]:
        """Fitted parameters dict (empty if not fit)."""
        if not self._is_fit:
            return {}
        return {k: float(v) for k, v in self._result.params.items()}
