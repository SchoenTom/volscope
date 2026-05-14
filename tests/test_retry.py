"""Retry decorator unit tests."""
from __future__ import annotations

import pytest

from volscope.utils.retry import retry


def test_retry_succeeds_on_first_attempt():
    calls = {"n": 0}

    @retry(attempts=3, base_delay=0.0)
    def f():
        calls["n"] += 1
        return "ok"

    assert f() == "ok"
    assert calls["n"] == 1


def test_retry_succeeds_after_transient_failure():
    calls = {"n": 0}

    @retry(attempts=3, base_delay=0.0)
    def flaky():
        calls["n"] += 1
        if calls["n"] < 2:
            raise ConnectionError("yfinance hiccup")
        return 42

    assert flaky() == 42
    assert calls["n"] == 2


def test_retry_raises_after_exhausted_attempts():
    calls = {"n": 0}

    @retry(attempts=3, base_delay=0.0)
    def always_fails():
        calls["n"] += 1
        raise RuntimeError("dead api")

    with pytest.raises(RuntimeError):
        always_fails()
    assert calls["n"] == 3
