"""Tests for the RiskLockManager."""
from __future__ import annotations

import asyncio

import pytest

from volscope.risk.locks import RiskLockManager


@pytest.mark.asyncio
async def test_lock_blocks_concurrent_callers():
    """
    Two coroutines race for the lock; only one inside the critical
    section at a time. The other has to wait for the first to exit.
    """
    rlm = RiskLockManager()
    order: list[str] = []

    async def worker(name: str, sleep: float):
        async with rlm.exclusive(name):
            order.append(f"{name}-in")
            await asyncio.sleep(sleep)
            order.append(f"{name}-out")

    await asyncio.gather(
        worker("A", 0.05),
        worker("B", 0.01),
    )
    # The sequence MUST be A-in, A-out, B-in, B-out (or B before A, but
    # never interleaved). Either way each in must be followed by its
    # own out before the other can enter.
    assert order in (
        ["A-in", "A-out", "B-in", "B-out"],
        ["B-in", "B-out", "A-in", "A-out"],
    )


@pytest.mark.asyncio
async def test_lock_released_after_exception():
    """A raise inside the block must NOT leave the lock held."""
    rlm = RiskLockManager()
    with pytest.raises(RuntimeError):
        async with rlm.exclusive("fail"):
            raise RuntimeError("kaboom")
    assert not rlm.is_held


@pytest.mark.asyncio
async def test_holder_tracked():
    rlm = RiskLockManager()
    async with rlm.exclusive("foo"):
        assert rlm.holder == "foo"
        assert rlm.is_held
    assert rlm.holder is None
    assert not rlm.is_held


@pytest.mark.asyncio
async def test_many_concurrent_callers_serialised():
    """100 concurrent callers; never two inside the section."""
    rlm = RiskLockManager()
    inside_count = {"v": 0, "max": 0}

    async def worker():
        async with rlm.exclusive("w"):
            inside_count["v"] += 1
            inside_count["max"] = max(inside_count["max"], inside_count["v"])
            await asyncio.sleep(0)         # yield to scheduler
            inside_count["v"] -= 1

    await asyncio.gather(*(worker() for _ in range(100)))
    assert inside_count["max"] == 1
