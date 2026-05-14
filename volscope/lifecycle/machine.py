"""
Trade lifecycle state machine — Phase 2 core.

11 states for a multi-leg options trade. Every transition emits an
immutable audit row via the `audit_callback` injected at construction.
The callback wires into `bot_signals_log` / `bot_orders_log` per the
WORM invariant in `docs/ARCHITECTURE.md`.

States:
    SIGNALED → SIZED → SUBMITTED → PARTIAL_FILL → FILLED → MANAGED → CLOSING → CLOSED
                ↓         ↓                                    ↓
            ABANDONED  REJECTED                          EXPIRED / ASSIGNED / ROLLED

Hard rules (encoded as transition conditions):

- ``SIGNALED → SIZED`` requires ``risk_check_passed=True`` in payload.
- ``SIZED → SUBMITTED`` requires ``order_ref`` in payload (idempotency
  key sent to IBKR as ``Order.orderRef``).
- Any state → ``ABANDONED`` on ``reason="manual_override"``.

Deferred import: `transitions` lives in the `bot` extras.
"""
from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any

STATES: list[str] = [
    "SIGNALED",
    "SIZED",
    "SUBMITTED",
    "PARTIAL_FILL",
    "FILLED",
    "MANAGED",
    "CLOSING",
    "CLOSED",
    "ABANDONED",
    "REJECTED",
    "EXPIRED",
    "ASSIGNED",
    "ROLLED",
]


class TradeLifecycle:
    """
    Wraps a `transitions.Machine` instance for a single trade.

    Usage::

        def audit(event): db.log(event)

        life = TradeLifecycle("trade-uuid", audit_callback=audit)
        life.size(reason="passed risk check", payload={"risk_check_passed": True})
        life.submit(reason="order built", payload={"order_ref": "ic_45dte_001"})
    """

    def __init__(self, trade_id: str,
                 audit_callback: Callable[[dict[str, Any]], None] | None = None,
                 initial_state: str = "SIGNALED"):
        try:
            from transitions import Machine                    # type: ignore[import-not-found]
        except ImportError as exc:
            raise ImportError(
                "TradeLifecycle requires the `transitions` library. "
                "Install with `uv sync --extra bot`."
            ) from exc

        self.trade_id = trade_id
        self._audit_callback = audit_callback or (lambda _: None)
        self._last_payload: dict[str, Any] | None = None

        transitions_spec = [
            # name,           source,           dest,            conditions / unless
            {"trigger": "size",        "source": "SIGNALED",
             "dest": "SIZED",          "conditions": "_risk_check_passed"},
            {"trigger": "submit",      "source": "SIZED",
             "dest": "SUBMITTED",      "conditions": "_has_order_ref"},
            {"trigger": "partial",     "source": "SUBMITTED",
             "dest": "PARTIAL_FILL"},
            {"trigger": "fill",        "source": ["SUBMITTED", "PARTIAL_FILL"],
             "dest": "FILLED"},
            {"trigger": "manage",      "source": "FILLED",
             "dest": "MANAGED"},
            {"trigger": "begin_close", "source": "MANAGED",
             "dest": "CLOSING"},
            {"trigger": "complete",    "source": "CLOSING",
             "dest": "CLOSED"},
            # Terminal-from-anywhere paths
            {"trigger": "abandon",     "source": "*",            "dest": "ABANDONED"},
            {"trigger": "reject",      "source": ["SUBMITTED", "PARTIAL_FILL"],
             "dest": "REJECTED"},
            {"trigger": "expire",      "source": ["FILLED", "MANAGED"],
             "dest": "EXPIRED"},
            {"trigger": "assign",      "source": ["FILLED", "MANAGED"],
             "dest": "ASSIGNED"},
            {"trigger": "roll",        "source": "MANAGED",
             "dest": "ROLLED"},
        ]
        self.machine = Machine(
            model=self, states=STATES, transitions=transitions_spec,
            initial=initial_state, send_event=True,
            after_state_change="_emit_audit",
        )

    # ── condition predicates ────────────────────────────────────────
    def _risk_check_passed(self, event: Any) -> bool:
        payload = event.kwargs.get("payload") or {}
        return bool(payload.get("risk_check_passed", False))

    def _has_order_ref(self, event: Any) -> bool:
        payload = event.kwargs.get("payload") or {}
        return bool(payload.get("order_ref"))

    # ── audit emission (called automatically) ───────────────────────
    def _emit_audit(self, event: Any) -> None:
        prev = event.transition.source if event.transition else None
        new = event.transition.dest if event.transition else self.state
        reason = (event.kwargs.get("reason")
                  if hasattr(event, "kwargs") else None) or "(unspecified)"
        payload = event.kwargs.get("payload") if hasattr(event, "kwargs") else None
        self._last_payload = payload
        self._audit_callback({
            "trade_id": self.trade_id,
            "from_state": prev,
            "to_state": new,
            "ts": datetime.now(tz=timezone.utc).isoformat(),
            "reason": reason,
            "payload": payload,
        })

    # ── introspection ───────────────────────────────────────────────
    @property
    def is_terminal(self) -> bool:
        return self.state in {"CLOSED", "ABANDONED", "REJECTED",
                              "EXPIRED", "ASSIGNED", "ROLLED"}
