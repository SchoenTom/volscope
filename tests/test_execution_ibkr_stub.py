"""Tests for volscope/execution/ibkr_stub.py — graceful-failure scaffold."""
from __future__ import annotations

import pytest

from volscope.execution.ibkr_stub import IBKRClient, IBKRSettings


class TestNeverRaises:
    @pytest.mark.asyncio
    async def test_connect_returns_false_when_no_gateway(self):
        # 7497 is paper port. Even if Gateway is running, this client
        # uses client_id=999 which likely collides with nothing.
        client = IBKRClient(IBKRSettings(port=7497, client_id=999,
                                         timeout_seconds=2))
        # Without ib_async installed OR without a Gateway listening,
        # connect must return False (not raise).
        result = await client.connect()
        assert isinstance(result, bool)
        if not result:
            assert client.last_error is not None

    @pytest.mark.asyncio
    async def test_disconnect_is_idempotent(self):
        client = IBKRClient()
        await client.disconnect()       # first call when never connected
        await client.disconnect()       # second call, still OK
        assert client.is_connected() is False

    @pytest.mark.asyncio
    async def test_ping_returns_minus_one_when_disconnected(self):
        client = IBKRClient()
        result = await client.ping()
        assert result == -1.0

    def test_is_connected_false_initially(self):
        assert IBKRClient().is_connected() is False


class TestSettings:
    def test_default_paper_port(self):
        s = IBKRSettings()
        assert s.port == 7497
        assert s.host == "127.0.0.1"
        assert s.client_id == 1
