"""Timeout + 429-detection wrapper for yfinance calls.

yfinance 1.3 has no explicit timeout argument on Ticker.history /
option_chain — it inherits requests' default of *None* (block forever).
When Yahoo's free tier slows down (peak ratelimit windows, weekend
maintenance, regional CDN issues) the unwrapped call can hang
Streamlit reruns or daily_scrape iterations indefinitely.

This module wraps the common yfinance entry points with:

  - hard wall-clock timeout (ThreadPoolExecutor + future.result(timeout=N))
  - 429-rate-limit detection: the wrapper catches HTTPError 429 and
    surfaces it as `YFRateLimitError`, letting callers back off
    deterministically instead of swallowing it as a generic Exception
  - stdout/stderr capture so yfinance's chatty "$SYMBOL: possibly
    delisted" prints don't leak into Streamlit logs (mirrors the
    pattern already in vol_index_fetcher)

Default timeout is 12 s — enough for normal yfinance latency
(2-6 s warm, <12 s cold) but short enough that an outage doesn't
hang the UI for a minute.
"""
from __future__ import annotations

import concurrent.futures
import contextlib
import io
import logging
from typing import Any, Optional

import pandas as pd

log = logging.getLogger(__name__)

DEFAULT_TIMEOUT_S: float = 12.0


class YFTimeoutError(TimeoutError):
    """yfinance call exceeded the wall-clock budget."""


class YFRateLimitError(RuntimeError):
    """Yahoo returned HTTP 429 — back off and retry later."""


def _silenced_call(fn, *args, **kwargs):
    """Run fn(*args, **kwargs) with stdout/stderr redirected to /dev/null."""
    with contextlib.redirect_stdout(io.StringIO()), \
         contextlib.redirect_stderr(io.StringIO()):
        return fn(*args, **kwargs)


def _run_with_timeout(fn, *args, timeout: float = DEFAULT_TIMEOUT_S, **kwargs):
    """Execute fn(*args, **kwargs) under a wall-clock timeout.

    Raises YFTimeoutError if it exceeds <timeout>. Raises YFRateLimitError
    if the underlying call returned HTTP 429. Other exceptions propagate.
    """
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
        future = ex.submit(_silenced_call, fn, *args, **kwargs)
        try:
            return future.result(timeout=timeout)
        except concurrent.futures.TimeoutError as exc:
            raise YFTimeoutError(
                f"yfinance call exceeded {timeout}s wall-clock budget"
            ) from exc
        except Exception as exc:                                   # noqa: BLE001
            # Detect 429 from common requests / curl_cffi error shapes.
            msg = str(exc).lower()
            if "429" in msg or "rate limit" in msg or "too many requests" in msg:
                raise YFRateLimitError(f"Yahoo 429 rate-limit: {exc}") from exc
            raise


def safe_history(
    ticker_obj, *,
    period: str = "1y",
    interval: Optional[str] = None,
    auto_adjust: bool = True,
    timeout: float = DEFAULT_TIMEOUT_S,
) -> pd.DataFrame:
    """Wrap yf.Ticker(...).history() with timeout + 429 detection.

    `interval` is forwarded only when explicitly set — passing
    interval="1d" unconditionally broke callers that mock yfinance
    with a Ticker.history(period, auto_adjust) signature.

    Returns an empty DataFrame on timeout / rate-limit / network failure.
    Logs at WARNING so operator can see it; no exception bubbles up.
    """
    kwargs: dict = {"period": period, "auto_adjust": auto_adjust}
    if interval is not None:
        kwargs["interval"] = interval
    try:
        return _run_with_timeout(
            ticker_obj.history, timeout=timeout, **kwargs,
        )
    except YFTimeoutError as exc:
        log.warning(
            "safe_history(%s) timed out after %.1fs: %s",
            getattr(ticker_obj, "ticker", "?"), timeout, exc,
        )
    except YFRateLimitError as exc:
        log.warning(
            "safe_history(%s) hit Yahoo 429: %s — back off before retry",
            getattr(ticker_obj, "ticker", "?"), exc,
        )
    except Exception as exc:                                       # noqa: BLE001
        log.debug(
            "safe_history(%s) failed: %s",
            getattr(ticker_obj, "ticker", "?"), exc,
        )
    return pd.DataFrame()


def safe_option_chain(
    ticker_obj, expiry: str, *,
    timeout: float = DEFAULT_TIMEOUT_S,
) -> Optional[Any]:
    """Wrap yf.Ticker(...).option_chain(expiry) with timeout + 429 detection.

    Returns None on timeout / rate-limit / failure. The chain
    namedtuple has .calls and .puts DataFrames when successful.
    """
    try:
        return _run_with_timeout(
            ticker_obj.option_chain, expiry, timeout=timeout,
        )
    except YFTimeoutError as exc:
        log.warning(
            "safe_option_chain(%s, %s) timed out after %.1fs: %s",
            getattr(ticker_obj, "ticker", "?"), expiry, timeout, exc,
        )
    except YFRateLimitError as exc:
        log.warning(
            "safe_option_chain(%s, %s) hit Yahoo 429: %s",
            getattr(ticker_obj, "ticker", "?"), expiry, exc,
        )
    except Exception as exc:                                       # noqa: BLE001
        log.debug(
            "safe_option_chain(%s, %s) failed: %s",
            getattr(ticker_obj, "ticker", "?"), expiry, exc,
        )
    return None
