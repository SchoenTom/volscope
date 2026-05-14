"""Tiny retry helper with exponential backoff. No external deps."""
from __future__ import annotations

import logging
import time
from functools import wraps
from typing import Callable, TypeVar

log = logging.getLogger(__name__)

T = TypeVar("T")


def retry(attempts: int = 3, base_delay: float = 1.0, factor: float = 2.0):
    """
    Retry a callable that may raise. Sleeps base_delay * factor**i between
    attempts. Returns the last exception's None equivalent (callable's choice)
    via re-raise on final failure.
    """

    def decorator(fn: Callable[..., T]) -> Callable[..., T]:
        @wraps(fn)
        def wrapper(*args, **kwargs) -> T:
            last_exc: Exception | None = None
            for i in range(attempts):
                try:
                    return fn(*args, **kwargs)
                except Exception as exc:
                    last_exc = exc
                    if i == attempts - 1:
                        log.warning("%s failed after %d attempts: %s", fn.__name__, attempts, exc)
                        raise
                    delay = base_delay * (factor ** i)
                    log.info("%s attempt %d/%d failed (%s) — sleeping %.1fs", fn.__name__, i + 1, attempts, exc, delay)
                    time.sleep(delay)
            assert last_exc is not None
            raise last_exc

        return wrapper

    return decorator
