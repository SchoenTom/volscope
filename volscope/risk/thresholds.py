"""
Read-only loader for `config/risk-thresholds.yaml`.

Per the Paperclip 6-agent firm postmortem rule (and the decision
recorded in `docs/decisions.md` 2026-05-14): no Claude / agent code
should be able to mutate the bot's safety governors. This module
provides a frozen read API; anything that tries to write fails fast.
"""
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Mapping

import yaml

DEFAULT_PATH = Path(__file__).resolve().parents[2] / "config" / "risk-thresholds.yaml"


class _FrozenDict(Mapping):
    """Read-only Mapping view of a dict — mutation raises TypeError."""

    def __init__(self, data: dict[str, Any]):
        self._data = {
            k: _FrozenDict(v) if isinstance(v, dict) else v
            for k, v in data.items()
        }

    def __getitem__(self, key: str) -> Any:
        return self._data[key]

    def __iter__(self):
        return iter(self._data)

    def __len__(self) -> int:
        return len(self._data)

    def __setitem__(self, key, value) -> None:                # noqa: D401
        raise TypeError(
            "config/risk-thresholds.yaml is operator-only. "
            "Mutation in code is forbidden — edit the YAML in the "
            "Sunday review window with `OPERATOR_APPROVED=yes` in the "
            "commit message."
        )

    def __repr__(self) -> str:
        return f"FrozenThresholds({self._data!r})"

    def to_dict(self) -> dict[str, Any]:
        """Materialise back to a plain dict for printing / debugging."""
        return {
            k: (v.to_dict() if isinstance(v, _FrozenDict) else v)
            for k, v in self._data.items()
        }


@lru_cache(maxsize=1)
def load_thresholds(path: Path | None = None) -> _FrozenDict:
    """Read + parse + freeze the YAML. Cached — subsequent calls are no-ops."""
    p = path or DEFAULT_PATH
    if not p.is_file():
        raise FileNotFoundError(
            f"risk thresholds missing at {p}. The bot refuses to start "
            "without a configured safety governor."
        )
    with p.open() as f:
        raw = yaml.safe_load(f)
    if not isinstance(raw, dict):
        raise ValueError(f"expected mapping at YAML root, got {type(raw)}")
    return _FrozenDict(raw)


@dataclass(frozen=True)
class CircuitBreakers:
    """Convenience accessor — type-hint your call sites."""
    daily_loss_halt_pct: float
    drawdown_no_new_entries_pct: float
    drawdown_liquidate_undefined_pct: float
    drawdown_full_halt_pct: float
    vix_no_new_entries: float
    vix_liquidate_undefined: float
    vix_intraday_spike_pct: float
    vix_term_invert_ratio: float
    consecutive_losses_pause: int
    ibkr_disconnect_seconds: int

    @classmethod
    def from_loaded(cls, t: _FrozenDict) -> "CircuitBreakers":
        cb = t["circuit_breakers"]
        return cls(
            daily_loss_halt_pct=float(cb["daily_loss_halt_pct"]),
            drawdown_no_new_entries_pct=float(cb["drawdown_no_new_entries_pct"]),
            drawdown_liquidate_undefined_pct=float(cb["drawdown_liquidate_undefined_pct"]),
            drawdown_full_halt_pct=float(cb["drawdown_full_halt_pct"]),
            vix_no_new_entries=float(cb["vix_no_new_entries"]),
            vix_liquidate_undefined=float(cb["vix_liquidate_undefined"]),
            vix_intraday_spike_pct=float(cb["vix_intraday_spike_pct"]),
            vix_term_invert_ratio=float(cb["vix_term_invert_ratio"]),
            consecutive_losses_pause=int(cb["consecutive_losses_pause"]),
            ibkr_disconnect_seconds=int(cb["ibkr_disconnect_seconds"]),
        )
