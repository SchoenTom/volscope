"""
Interactive Brokers options-chain scraper — stub / second opinion path.

Primary purpose: serve as a SECONDARY IV source so VolScope can cross-check
its Yahoo-derived IV against an independent broker feed. Disagreement
between the two is a quality signal — agreement validates the scraper,
divergence flags likely Yahoo data bugs.

Requirements (checked lazily — the module imports cleanly even on systems
without an IBKR setup):

  1. An IBKR account (trading restrictions don't matter — market data
     permissions are separate from trading permissions; a locked-for-
     trading account can still pull delayed data via API).
  2. TWS (Trader Workstation) or IB Gateway installed and running locally
     with API access enabled in settings.
  3. `ib_insync` installed: `pip install ib_insync`. Optional dep, only
     needed when the IBKR path is actually used.
  4. Connection parameters (host, port, client_id) configured via env vars:
       IBKR_HOST      (default 127.0.0.1)
       IBKR_PORT      (default 7497 for TWS paper, 4002 for Gateway paper)
       IBKR_CLIENT_ID (default 13 — arbitrary, just needs to be unique)

Realtime data requires paid market-data subscriptions per exchange.
15-minute delayed data is free for account holders and perfectly adequate
for VolScope's daily analysis — we don't care about sub-minute moves.

Usage example (once TWS is running):

    from volscope.data.ibkr_scraper import IBKRScraper
    with IBKRScraper() as ibkr:
        snap = ibkr.scrape_atm_iv("SPY")
        print(snap)  # {'iv_30d': 14.87, 'spot': 693.82, 'source': 'ibkr'}

If the module can't connect — no TWS, no ib_insync installed, wrong port —
every method returns None and logs a warning. VolScope never crashes
because the IBKR path isn't available.
"""
from __future__ import annotations

import logging
import math
import os
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any, Optional

from volscope.analytics.black_scholes import implied_volatility
from volscope.config import RISK_FREE_RATE

log = logging.getLogger(__name__)


@dataclass
class IBKRSnapshot:
    """Single-snapshot IV reading from IBKR for one underlying."""

    ticker: str
    iv_30d: Optional[float]
    spot: Optional[float]
    expiry: Optional[date]
    source: str = "ibkr"
    delayed: bool = True  # assume delayed until we see real-time subs


class IBKRScraper:
    """
    Thin wrapper over ib_insync that pulls the ATM option chain for a
    ticker, computes IV via our own BSM solver, and returns a snapshot.

    Never use `contract.modelGreeks.impliedVol` — same rule as yfinance.
    We always compute our own IV so the two sources are comparable.
    """

    def __init__(
        self,
        host: Optional[str] = None,
        port: Optional[int] = None,
        client_id: Optional[int] = None,
    ):
        self.host = host or os.getenv("IBKR_HOST", "127.0.0.1")
        self.port = port or int(os.getenv("IBKR_PORT", "7497"))
        self.client_id = client_id or int(os.getenv("IBKR_CLIENT_ID", "13"))
        self._ib: Any = None
        self._ib_insync: Any = None

    def connect(self) -> bool:
        """Attempt connection. Returns False on any failure — never raises."""
        try:
            import ib_insync
        except ImportError:
            log.warning(
                "ib_insync not installed. Run `pip install ib_insync` to "
                "enable the IBKR data path."
            )
            return False
        try:
            self._ib_insync = ib_insync
            self._ib = ib_insync.IB()
            self._ib.connect(
                self.host,
                self.port,
                clientId=self.client_id,
                readonly=True,
                timeout=8,
            )
        except Exception as exc:
            log.warning("IBKR connect failed: %s", exc)
            self._ib = None
            return False
        # Request delayed data as default — real-time requires paid subs.
        try:
            self._ib.reqMarketDataType(3)  # 3 = DELAYED
        except Exception as exc:
            log.debug("reqMarketDataType(3) failed: %s", exc)
        log.info(
            "IBKR connected: %s:%s (delayed market data)",
            self.host,
            self.port,
        )
        return True

    def disconnect(self) -> None:
        if self._ib is not None:
            try:
                self._ib.disconnect()
            except Exception:
                pass
            self._ib = None

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.disconnect()

    def is_connected(self) -> bool:
        return self._ib is not None and getattr(self._ib, "isConnected", lambda: False)()

    def scrape_atm_iv(
        self, ticker: str, target_dte: int = 30
    ) -> Optional[IBKRSnapshot]:
        """
        Pull ATM option chain for `ticker` near `target_dte` expiry,
        compute IV via our BSM solver, return a snapshot.

        Returns None if:
          - Not connected (no TWS)
          - Contract lookup failed
          - No options found
          - Computed IV is out of plausible range

        Conservative: on any error, log a warning and return None.
        """
        if not self.is_connected():
            return None
        ibi = self._ib_insync
        ib = self._ib

        # 1. Stock contract + spot.
        try:
            stock = ibi.Stock(ticker, "SMART", "USD")
            ib.qualifyContracts(stock)
            ib.reqMarketDataType(3)
            ticker_data = ib.reqMktData(stock, "", False, False)
            ib.sleep(1.5)
            spot = float(
                ticker_data.last
                or ticker_data.close
                or ticker_data.marketPrice()
            )
        except Exception as exc:
            log.warning("IBKR spot fetch failed for %s: %s", ticker, exc)
            return None
        if spot is None or spot <= 0 or math.isnan(spot):
            return None

        # 2. Option chain parameters.
        try:
            chains = ib.reqSecDefOptParams(stock.symbol, "", stock.secType, stock.conId)
        except Exception as exc:
            log.warning("IBKR chain params failed for %s: %s", ticker, exc)
            return None
        if not chains:
            return None
        smart_chain = next(
            (c for c in chains if c.exchange == "SMART"), chains[0]
        )

        # 3. Pick the expiry closest to target_dte.
        today = date.today()
        expiries: list[tuple[date, str]] = []
        for exp_str in smart_chain.expirations:
            try:
                exp = datetime.strptime(exp_str, "%Y%m%d").date()
                if exp > today:
                    expiries.append((exp, exp_str))
            except Exception:
                continue
        if not expiries:
            return None
        target = today + timedelta(days=target_dte)
        expiry_date, expiry_str = min(expiries, key=lambda p: abs((p[0] - target).days))

        # 4. Find ATM strike.
        strikes = sorted(smart_chain.strikes)
        if not strikes:
            return None
        atm_strike = min(strikes, key=lambda s: abs(s - spot))

        # 5. Request the call contract, get bid/ask, compute IV.
        try:
            call = ibi.Option(
                ticker, expiry_str, atm_strike, "C", "SMART", tradingClass=smart_chain.tradingClass
            )
            ib.qualifyContracts(call)
            opt_data = ib.reqMktData(call, "", False, False)
            ib.sleep(1.5)
            bid = float(opt_data.bid) if opt_data.bid and opt_data.bid > 0 else None
            ask = float(opt_data.ask) if opt_data.ask and opt_data.ask > 0 else None
        except Exception as exc:
            log.warning("IBKR option fetch failed for %s: %s", ticker, exc)
            return None

        if bid is None or ask is None or ask < bid:
            return None
        mid = 0.5 * (bid + ask)
        T = max((expiry_date - today).days, 1) / 365.0

        iv_frac = implied_volatility(
            market_price=mid,
            S=spot,
            K=atm_strike,
            T=T,
            r=RISK_FREE_RATE,
            option_type="call",
        )
        if iv_frac is None or not (0.01 < iv_frac < 5.0):
            return None

        return IBKRSnapshot(
            ticker=ticker,
            iv_30d=iv_frac * 100.0,
            spot=spot,
            expiry=expiry_date,
            delayed=True,
        )


def probe_ibkr_availability() -> dict:
    """
    Quick health check — safe to call at app startup. Returns a dict
    describing whether IBKR is reachable and what's blocking it if not.

    Used by the Discover data-quality panel to decide whether to offer
    IBKR cross-check as a second-opinion source.
    """
    try:
        import ib_insync  # noqa: F401
    except ImportError:
        return {
            "available": False,
            "reason": "ib_insync not installed",
            "fix": "pip install ib_insync",
        }
    scraper = IBKRScraper()
    try:
        ok = scraper.connect()
    except Exception as exc:
        return {
            "available": False,
            "reason": f"connect raised: {exc}",
            "fix": f"Start TWS or IB Gateway on {scraper.host}:{scraper.port}",
        }
    finally:
        scraper.disconnect()
    if ok:
        return {
            "available": True,
            "host": scraper.host,
            "port": scraper.port,
        }
    return {
        "available": False,
        "reason": "connect returned False",
        "fix": (
            f"Start TWS or IB Gateway on {scraper.host}:{scraper.port} "
            f"and enable API access in Global Configuration → API → Settings"
        ),
    }
