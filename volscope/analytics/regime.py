"""
2-state Gaussian HMM regime detector — Phase 1 scaffold.

Why HMM over rolling-VIX thresholds: regimes are persistent (not noisy
day-to-day flips) and the model assigns a *probability* of being in each
state, which lets the composite scorer gate trades by ``p_calm > 0.6``
instead of a hard yes/no.

Reference: López de Prado, *Advances in Financial Machine Learning*
(2018), Ch. 11. Two-state Gaussian HMM on
``[VIX daily Δ, SPY 20d realised vol]``. The state with higher mean RV
is labelled "stress"; the other is "calm."

Train monthly on an expanding window. Persist the fitted model to disk
so daily inference doesn't refit from scratch.

This is a scaffold — the actual training pipeline + persistence is
wired up in Phase 2 when the scheduler exists.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np


class RegimeDetector:
    """Two-state Gaussian HMM over (ΔVIX, SPY 20d RV) features."""

    def __init__(self, retrain_freq_days: int = 30, random_state: int = 42):
        self.retrain_freq_days = retrain_freq_days
        self.random_state = random_state
        self.model = None
        self.scaler = None
        self.stress_state: int | None = None
        self._is_fit = False

    def fit(self, vix_chg: np.ndarray, spy_rv20: np.ndarray) -> None:
        """
        Fit the HMM on two aligned feature arrays.

        Imports are deferred so the rest of the codebase can ``import
        analytics.regime`` without hmmlearn/sklearn installed yet (Phase
        1 ships the scaffold; the deps land in Phase 2 via uv add).
        """
        from hmmlearn.hmm import GaussianHMM
        from sklearn.preprocessing import StandardScaler

        x_raw = np.column_stack([np.asarray(vix_chg, dtype=float),
                                 np.asarray(spy_rv20, dtype=float)])
        if x_raw.shape[0] < 60:
            raise ValueError(
                f"need >=60 observations to fit a 2-state HMM, got {x_raw.shape[0]}"
            )
        self.scaler = StandardScaler()
        x = self.scaler.fit_transform(x_raw)
        self.model = GaussianHMM(
            n_components=2,
            covariance_type="full",
            n_iter=1000,
            random_state=self.random_state,
            init_params="stmc",
        )
        self.model.fit(x)
        # The "stress" state is the one whose mean SPY 20d RV (column 1) is higher.
        means_rv = [float(self.model.means_[i][1]) for i in range(2)]
        self.stress_state = int(np.argmax(means_rv))
        self._is_fit = True

    def predict_proba_calm(self, vix_chg: np.ndarray, spy_rv20: np.ndarray) -> float:
        """Probability the LAST observation belongs to the calm state."""
        if not self._is_fit:
            raise RuntimeError("RegimeDetector.fit() must be called first")
        x_raw = np.column_stack([np.asarray(vix_chg, dtype=float),
                                 np.asarray(spy_rv20, dtype=float)])
        x = self.scaler.transform(x_raw)
        probs = self.model.predict_proba(x)
        calm_state = 1 - int(self.stress_state)
        return float(probs[-1, calm_state])

    def save(self, path: Path | str) -> None:
        """Pickle the fitted model + scaler to disk."""
        import pickle
        if not self._is_fit:
            raise RuntimeError("nothing to save — fit() first")
        Path(path).write_bytes(pickle.dumps({
            "model": self.model,
            "scaler": self.scaler,
            "stress_state": self.stress_state,
            "retrain_freq_days": self.retrain_freq_days,
            "random_state": self.random_state,
        }))

    @classmethod
    def load(cls, path: Path | str) -> "RegimeDetector":
        """Load a previously-fitted model."""
        import pickle
        d = pickle.loads(Path(path).read_bytes())
        inst = cls(retrain_freq_days=d["retrain_freq_days"],
                   random_state=d["random_state"])
        inst.model = d["model"]
        inst.scaler = d["scaler"]
        inst.stress_state = d["stress_state"]
        inst._is_fit = True
        return inst
