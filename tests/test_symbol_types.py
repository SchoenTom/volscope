"""Tests for the symbol-type classifier."""
from __future__ import annotations

from volscope.data.symbol_types import (
    SymbolType,
    is_tradable_vol_proxy,
    is_vol_index,
    is_vol_product,
    symbol_type,
)


def test_vix_is_vol_index():
    assert symbol_type("^VIX") == SymbolType.VOL_INDEX
    assert is_vol_index("^VIX") is True
    assert is_vol_product("^VIX") is False
    assert is_tradable_vol_proxy("^VIX") is False


def test_vxx_is_vol_product_tradable():
    assert symbol_type("VXX") == SymbolType.VOL_PRODUCT
    assert is_vol_product("VXX") is True
    assert is_tradable_vol_proxy("VXX") is True


def test_aapl_is_equity():
    assert symbol_type("AAPL") == SymbolType.EQUITY


def test_spy_is_broad_etf():
    assert symbol_type("SPY") == SymbolType.ETF_BROAD


def test_xlf_is_sector_etf():
    assert symbol_type("XLF") == SymbolType.ETF_SECTOR


def test_gld_is_commodity_etf():
    assert symbol_type("GLD") == SymbolType.COMMODITY_ETF


def test_tlt_is_bond_etf():
    assert symbol_type("TLT") == SymbolType.BOND_ETF


def test_btc_usd_is_crypto():
    assert symbol_type("BTC-USD") == SymbolType.CRYPTO


def test_ibit_is_crypto():
    assert symbol_type("IBIT") == SymbolType.CRYPTO


def test_gspc_is_index_not_vol():
    assert symbol_type("^GSPC") == SymbolType.INDEX
    assert is_vol_index("^GSPC") is False


def test_unknown_caret_symbol_falls_to_index():
    # Defensive: any ^-prefixed ticker we don't know about is still
    # treated as some kind of index rather than equity.
    assert symbol_type("^ZZZUNKNOWN") == SymbolType.INDEX


def test_german_symbol_is_adr():
    assert symbol_type("SAP.DE") == SymbolType.ADR


def test_japanese_symbol_is_adr():
    assert symbol_type("7203.T") == SymbolType.ADR


def test_case_insensitive():
    assert symbol_type("aapl") == SymbolType.EQUITY
    assert symbol_type("^vix") == SymbolType.VOL_INDEX
