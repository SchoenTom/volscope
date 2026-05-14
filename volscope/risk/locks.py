"""
asyncio.Lock manager for risk-critical paths — v0.5.0.

Wraps every "check current state → decide → act" sequence that touches
the bot's risk surface. Without this lock, two coroutines awaiting the
same upstream (e.g. an IBKR fetch) can both pass a risk gate and both
fire orders.

Pattern:
    rlm = RiskLockManager()
    async with rlm.exclusive("place_order"):
        if not kill_switch.is_tripped():
            await execute_blueprint(...)

The lock holds for in-memory checks only — never around external I/O
or broker round-trips. If you need to call IBKR inside the critical
section, refactor: do the network call first, hold the lock only for
the local DB write + risk update.

Reference: research-prompt 2026-05-14 — "asyncio is single-threaded
so I'm safe" is the most common bot-loop misconception. Every `await`
is a yield point; every read-then-modify is a race.
"""
from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

log = logging.getLogger(__name__)


class RiskLockManager:
    """A single global asyncio.Lock + named-context wrapper.

    The manager is intentionally a single lock — risk decisions are
    serialized end-to-end. If a future stage needs fine-grained
    locking (per-underlying, per-strategy), introduce named locks but
    document the deadlock-ordering rule.
    """

    def __init__(self, *, slow_warn_seconds: float = 1.0):
        self._lock = asyncio.Lock()
        self._slow_warn_seconds = slow_warn_seconds
        self._holder: str | None = None
        self._held_since: float | None = None

    @asynccontextmanager
    async def exclusive(self, name: str) -> AsyncIterator[None]:
        """
        Acquire the lock, run the block, release.

        ``name`` is for diagnostics — logged if the critical section
        exceeds ``slow_warn_seconds``. Keep critical sections short.
        """
        wait_start = time.perf_counter()
        await self._lock.acquire()
        try:
            wait_ms = (time.perf_counter() - wait_start) * 1000.0
            self._holder = name
            self._held_since = time.perf_counter()
            if wait_ms > self._slow_warn_seconds * 1000.0:
                log.warning(
                    "RiskLockManager: %.0f ms wait for %s (consider "
                    "shortening critical sections held by previous owners)",
                    wait_ms, name,
                )
            yield
        finally:
            if self._held_since is not None:
                held_ms = (time.perf_counter() - self._held_since) * 1000.0
                if held_ms > self._slow_warn_seconds * 1000.0:
                    log.warning(
                        "RiskLockManager: %s held lock for %.0f ms — "
                        "should be <1ms (in-memory checks only)",
                        name, held_ms,
                    )
            self._holder = None
            self._held_since = None
            self._lock.release()

    @property
    def is_held(self) -> bool:
        return self._lock.locked()

    @property
    def holder(self) -> str | None:
        return self._holder
