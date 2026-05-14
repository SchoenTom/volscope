"""
IBKR connectivity scaffold — Phase 1 finishing.

Never raises on connect failure. ``connect()`` returns False; ``ping()``
returns -1 while disconnected. This is on purpose: the rest of the bot
loop needs to keep running even when IB Gateway is down, so it can
trigger the kill-switch's IBKR-disconnect auto-check (see
``volscope/risk/kill_switch.py::check_disconnect``).

Deferred import of ``ib_async`` so the module loads without the
`bot` extras installed. Phase 2.5 will replace this stub with a
full client (`volscope/execution/ibkr_client.py`) that adds Watchdog,
rate-limit semaphore, BAG combo builder, and walk-price algorithm.

See ADR-0003 for why `ib_async` over `ib_insync`.
"""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any


@dataclass
class IBKRSettings:
    """Settings dataclass — populated from pydantic Settings in production."""
    host: str = "127.0.0.1"
    port: int = 7497          # paper
    client_id: int = 1
    account: str = ""
    timeout_seconds: int = 20


@dataclass
class IBKRClient:
    """
    Thin scaffold around an ``ib_async.IB`` instance.

    Public API:
        await client.connect()    -> bool
        await client.disconnect() -> None
        client.is_connected()     -> bool
        await client.ping()       -> float  (ms; -1 if disconnected)
    """
    settings: IBKRSettings = field(default_factory=IBKRSettings)
    _ib: Any = None
    _connected: bool = False
    _last_error: str | None = None

    async def connect(self) -> bool:
        """
        Attempt to connect to IB Gateway / TWS.

        Returns True on success, False on failure (never raises). The
        failure reason is captured in ``self._last_error`` for the
        caller to log if useful.
        """
        if self._connected:
            return True
        try:
            from ib_async import IB     # type: ignore[import-not-found]
        except ImportError as exc:
            self._last_error = f"ib_async not installed: {exc}"
            return False
        try:
            self._ib = IB()
            await self._ib.connectAsync(
                self.settings.host,
                self.settings.port,
                clientId=self.settings.client_id,
                timeout=self.settings.timeout_seconds,
                account=self.settings.account or None,
            )
            self._connected = bool(self._ib.isConnected())
            self._last_error = None if self._connected else "connect returned False"
            return self._connected
        except Exception as exc:        # noqa: BLE001  (any failure → False)
            self._last_error = f"{type(exc).__name__}: {exc}"
            self._connected = False
            return False

    async def disconnect(self) -> None:
        """Disconnect if currently connected. Never raises."""
        if self._ib is None:
            return
        try:
            self._ib.disconnect()
        except Exception:               # noqa: BLE001
            pass
        finally:
            self._connected = False

    def is_connected(self) -> bool:
        """Cheap state query — does NOT round-trip to the broker."""
        if not self._connected or self._ib is None:
            return False
        try:
            return bool(self._ib.isConnected())
        except Exception:               # noqa: BLE001
            return False

    async def ping(self) -> float:
        """
        Round-trip latency in milliseconds.

        Uses ``reqCurrentTime`` (cheapest valid IBKR call). Returns -1
        if disconnected or on any failure — does NOT raise.
        """
        if not self.is_connected():
            return -1.0
        try:
            t0 = time.perf_counter()
            await self._ib.reqCurrentTimeAsync()
            return (time.perf_counter() - t0) * 1000.0
        except Exception as exc:        # noqa: BLE001
            self._last_error = f"{type(exc).__name__}: {exc}"
            return -1.0

    @property
    def last_error(self) -> str | None:
        return self._last_error


async def _self_test() -> None:
    """Sanity check — run directly with `python -m volscope.execution.ibkr_stub`."""
    client = IBKRClient()
    ok = await client.connect()
    print(f"connect: {ok}")
    if ok:
        print(f"ping: {await client.ping():.1f} ms")
        await client.disconnect()
    else:
        print(f"last_error: {client.last_error}")


if __name__ == "__main__":
    asyncio.run(_self_test())
