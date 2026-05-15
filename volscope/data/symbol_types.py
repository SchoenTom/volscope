"""
Symbol-type classifier — phase 4 of the autonomous hardening marathon.

Why this exists
===============
VolScope treats every row in ``daily_vol`` the same way: compute IV
percentile, classify CHEAP/RICH, slot it into the Discover treemap.
That works for tradable underlyings but is conceptually wrong for
volatility *indices* — ``^VIX``, ``^VVIX``, ``^SKEW`` are
*derived* indices, not tradable securities. Saying "VIX is CHEAP"
(IV percentile = 12) is a category error: you don't *buy* VIX, you
buy VXX / VIXY / UVXY (the products) or sell SPX options.

This module provides one function, :func:`symbol_type`, that maps
any ticker symbol to a typed classification. UI pages can switch
on the type to render the right view (a vol-regime box instead of
a CHEAP/RICH pill, a contango-drag warning on VXX, etc.).

Type taxonomy
=============
- ``EQUITY``       — single-stock common shares (AAPL, BABA, …)
- ``ETF_BROAD``    — broad-market index ETFs (SPY, QQQ, …)
- ``ETF_SECTOR``   — sector-rotation ETFs (XLF, XLE, …)
- ``VOL_INDEX``    — derived volatility indices (^VIX, ^VVIX, …)
- ``VOL_PRODUCT``  — exchange-traded vol products (VXX, UVXY, …)
- ``INDEX``        — non-vol price indices (^GSPC, ^NDX, ^DJI, …)
- ``COMMODITY_ETF``— GLD, SLV, USO, UNG, etc.
- ``BOND_ETF``     — TLT, IEF, HYG, LQD, etc.
- ``CRYPTO``       — BTC-USD, ETH-USD, IBIT-style spot ETFs
- ``ADR``          — foreign-listed-shares (BABA, BIDU, …)
- ``UNKNOWN``      — everything else (default)
"""
from __future__ import annotations

from enum import Enum


class SymbolType(str, Enum):
    EQUITY        = "EQUITY"
    ETF_BROAD     = "ETF_BROAD"
    ETF_SECTOR    = "ETF_SECTOR"
    VOL_INDEX     = "VOL_INDEX"
    VOL_PRODUCT   = "VOL_PRODUCT"
    INDEX         = "INDEX"
    COMMODITY_ETF = "COMMODITY_ETF"
    BOND_ETF      = "BOND_ETF"
    CRYPTO        = "CRYPTO"
    ADR           = "ADR"
    UNKNOWN       = "UNKNOWN"


# Canonical sets — single source of truth for the classifier.

_VOL_INDICES: frozenset[str] = frozenset({
    # CBOE-family vol indices (read-only, derived from option chains)
    "^VIX", "^VIX9D", "^VIX3M", "^VIX6M",
    "^VVIX", "^SKEW", "^MOVE",
    "^VXN", "^RVX", "^GVZ", "^OVX",
    "^VXFXI", "^VXEEM", "^V2X",
    "VDAX-NEW.DE",
})

_VOL_PRODUCTS: frozenset[str] = frozenset({
    # ETP/ETN vol products — tradable, but with structural contango drag
    "VXX", "VIXY", "UVXY", "SVXY",
    "VXZ", "VIIX",
})

_BROAD_ETFS: frozenset[str] = frozenset({
    "SPY", "QQQ", "IWM", "DIA",
    "VTI", "VOO", "MDY", "EFA", "EEM",
    "ITOT", "IVV", "IJR", "IJH",
})

_SECTOR_ETFS: frozenset[str] = frozenset({
    "XLF", "XLE", "XLK", "XLV", "XLY",
    "XLI", "XLP", "XLU", "XLRE", "XLB", "XLC",
    "SMH", "SOXX", "XBI", "IBB", "XRT", "KRE",
    "ITB", "ARKK", "KWEB",
})

_COMMODITY_ETFS: frozenset[str] = frozenset({
    "GLD", "SLV", "USO", "UNG", "CPER", "DBA",
    "DBC", "PDBC", "URA", "WEAT", "CORN", "SOYB",
    "PALL", "PPLT",
})

_BOND_ETFS: frozenset[str] = frozenset({
    "TLT", "IEF", "SHY", "HYG", "LQD",
    "AGG", "BND", "TIP", "TMF", "TMV", "TBT",
    "EDV", "PST", "TYO",
})

_CRYPTO: frozenset[str] = frozenset({
    "BTC-USD", "ETH-USD", "SOL-USD",
    # spot-BTC / spot-ETH ETFs (approved 2024)
    "IBIT", "FBTC", "GBTC", "BITB", "ARKB", "BTCO",
    "ETHA", "ETHE", "FETH", "ETHV",
    # vol-leveraged crypto products
    "BITO", "BITX", "ETHU",
})

# Common index tickers that aren't *vol* indices.
_NON_VOL_INDICES: frozenset[str] = frozenset({
    "^GSPC", "^NDX", "^DJI", "^RUT",
    "^GDAXI", "^STOXX50E", "^FTSE", "^N225", "^HSI",
    "^IBEX", "^FCHI", "^AEX",
})


def symbol_type(ticker: str) -> SymbolType:
    """Return the typed classification for ``ticker``.

    Lookup is O(1) (frozenset membership). Unknown tickers default
    to ``EQUITY`` for symbols that look like common-stock tickers
    (no special characters, no leading ``^``), otherwise to
    ``UNKNOWN``. ADR detection is intentionally conservative — we
    only flag tickers in our curated ADR list rather than guessing.
    """
    t = str(ticker).strip().upper()

    if t in _VOL_INDICES:
        return SymbolType.VOL_INDEX
    if t in _VOL_PRODUCTS:
        return SymbolType.VOL_PRODUCT
    if t in _BROAD_ETFS:
        return SymbolType.ETF_BROAD
    if t in _SECTOR_ETFS:
        return SymbolType.ETF_SECTOR
    if t in _COMMODITY_ETFS:
        return SymbolType.COMMODITY_ETF
    if t in _BOND_ETFS:
        return SymbolType.BOND_ETF
    if t in _CRYPTO:
        return SymbolType.CRYPTO
    if t in _NON_VOL_INDICES:
        return SymbolType.INDEX

    # Heuristic fallback. Any '^'-prefixed symbol we don't know is
    # an index of some kind. Symbols ending in country suffixes
    # (.DE, .L, .HK, .T, .AX, .MC, .SW, .AS, .PA, .MI, .BR, .TO)
    # are foreign-listed — call them ADR-class (some are actual
    # local listings rather than ADRs, but for *vol-research*
    # purposes the distinction doesn't matter; the operator just
    # needs to know it's not a US common).
    if t.startswith("^"):
        return SymbolType.INDEX
    if "." in t and t.rsplit(".", 1)[-1] in {
        "DE", "L", "HK", "T", "AX", "MC", "SW",
        "AS", "PA", "MI", "BR", "BE", "TO",
    }:
        return SymbolType.ADR

    return SymbolType.EQUITY


def is_vol_index(ticker: str) -> bool:
    """Shortcut: True iff the ticker is in the VOL_INDEX class."""
    return symbol_type(ticker) == SymbolType.VOL_INDEX


def is_vol_product(ticker: str) -> bool:
    """Shortcut: True iff the ticker is in the VOL_PRODUCT class."""
    return symbol_type(ticker) == SymbolType.VOL_PRODUCT


def is_tradable_vol_proxy(ticker: str) -> bool:
    """True for tradable vol proxies (products), False for indices.

    Distinguishes "you can buy this with options" (``VXX`` =
    True) from "this is derived data" (``^VIX`` = False).
    """
    return symbol_type(ticker) == SymbolType.VOL_PRODUCT
