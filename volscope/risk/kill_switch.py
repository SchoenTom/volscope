"""
Kill switch — Phase 2 core scaffold.

Three manual paths (file flag, env var, DB row) + five auto-check
functions (drawdown, VIX level, daily loss, IBKR disconnect, term
inversion). Any can trip; manual trip blocks all new entries until
explicit human reset with a literal date-stamped confirmation token.

Sticky: tripping writes a JSON file at `sticky_path` that survives
process restarts. Resetting requires the literal token
``I-RESET-VOLSCOPE-<YYYYMMDD>`` for *today's* date — any other input
refused. This is intentional: typing today's date forces the operator
to acknowledge "yes, today, I am resuming live trading."
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any


class KillSwitchTripped(Exception):
    """Raised when an operator action is attempted while the kill is hot."""


@dataclass
class KillSwitchState:
    active: bool
    reason: str | None
    tripped_at: str | None       # ISO-8601 UTC


class KillSwitch:
    """Three manual trip paths + sticky persistence."""

    def __init__(self, *, sticky_path: Path, env_var: str = "BOT_KILL",
                 db_check: "Callable[[], KillSwitchState | None] | None" = None,   # noqa: F821
                 db_write: "Callable[[KillSwitchState], None] | None" = None):     # noqa: F821
        self.sticky_path = sticky_path
        self.env_var = env_var
        self._db_check = db_check
        self._db_write = db_write

    def is_tripped(self) -> tuple[bool, str | None]:
        """
        Returns ``(tripped, reason)``. Checks all three manual paths in
        order: file → env var → DB row. First hit wins.
        """
        # 1) File flag
        if self.sticky_path.exists():
            try:
                data = json.loads(self.sticky_path.read_text(encoding="utf-8"))
                return (True, str(data.get("reason", "unknown")))
            except Exception:           # noqa: BLE001
                # File exists but not parseable — still treat as tripped
                return (True, "sticky file present (unparseable)")
        # 2) Env var
        if os.environ.get(self.env_var, "").strip() == "1":
            return (True, f"env var {self.env_var}=1")
        # 3) DB row
        if self._db_check is not None:
            try:
                state = self._db_check()
                if state and state.active:
                    return (True, state.reason or "db row active")
            except Exception:           # noqa: BLE001
                pass
        return (False, None)

    def trip(self, reason: str) -> None:
        """Trip the switch via all three paths. Idempotent."""
        ts = datetime.now(tz=timezone.utc).isoformat()
        # File
        self.sticky_path.parent.mkdir(parents=True, exist_ok=True)
        self.sticky_path.write_text(json.dumps({
            "reason": reason, "tripped_at": ts,
        }), encoding="utf-8")
        # DB
        if self._db_write is not None:
            try:
                self._db_write(KillSwitchState(
                    active=True, reason=reason, tripped_at=ts,
                ))
            except Exception:           # noqa: BLE001
                pass

    def reset(self, *, human_confirmation: str) -> None:
        """
        Reset all three manual paths.

        Requires the literal token ``I-RESET-VOLSCOPE-<YYYYMMDD>`` for
        today's date. Any other input raises ValueError.
        """
        expected = f"I-RESET-VOLSCOPE-{date.today():%Y%m%d}"
        if human_confirmation != expected:
            raise ValueError(
                "human_confirmation must be the literal "
                f"{expected!r} — got {human_confirmation!r}"
            )
        # File
        try:
            self.sticky_path.unlink(missing_ok=True)
        except Exception:               # noqa: BLE001
            pass
        # Env (can only clear in the current process — operator must
        # also clear it from their shell config)
        os.environ.pop(self.env_var, None)
        # DB
        if self._db_write is not None:
            try:
                self._db_write(KillSwitchState(
                    active=False, reason=None, tripped_at=None,
                ))
            except Exception:           # noqa: BLE001
                pass


# ── Auto-check functions ──────────────────────────────────────────
# Caller (the scheduler loop) calls these every cycle; on first True
# it calls `KillSwitch.trip(reason)`.


def check_drawdown(nlv_today: float, nlv_30d_peak: float,
                   threshold_pct: float = 0.20) -> tuple[bool, str]:
    """Trip if drawdown from 30-day NLV peak ≥ threshold (default 20%)."""
    if nlv_30d_peak <= 0:
        return (False, "no peak yet")
    dd = (nlv_30d_peak - nlv_today) / nlv_30d_peak
    if dd >= threshold_pct:
        return (True, f"drawdown {dd:.1%} >= {threshold_pct:.1%}")
    return (False, "")


def check_vix(vix_level: float, threshold: float = 40.0) -> tuple[bool, str]:
    """Trip if VIX > threshold (default 40 → liquidate undefined)."""
    if vix_level > threshold:
        return (True, f"VIX {vix_level:.1f} > {threshold:.1f}")
    return (False, "")


def check_daily_loss(today_pnl_pct: float,
                     threshold_pct: float = -0.03) -> tuple[bool, str]:
    """Trip if today's realised P&L ≤ -3% NLV."""
    if today_pnl_pct <= threshold_pct:
        return (True, f"daily P&L {today_pnl_pct:.1%} <= {threshold_pct:.1%}")
    return (False, "")


def check_disconnect(seconds_disconnected: float,
                     threshold_seconds: float = 60.0) -> tuple[bool, str]:
    """Trip if IBKR has been disconnected longer than threshold."""
    if seconds_disconnected > threshold_seconds:
        return (True, f"IBKR disconnected {seconds_disconnected:.0f}s > "
                f"{threshold_seconds:.0f}s")
    return (False, "")


def check_term_inversion(vix9d: float, vix: float,
                          threshold_ratio: float = 1.0) -> tuple[bool, str]:
    """Trip if VIX9D/VIX > threshold (vol-curve inversion)."""
    if vix <= 0:
        return (False, "VIX not yet observed")
    ratio = vix9d / vix
    if ratio > threshold_ratio:
        return (True, f"VIX9D/VIX {ratio:.2f} > {threshold_ratio:.2f} (backwardation)")
    return (False, "")
