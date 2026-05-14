"""
Curated universe of liquid, optionable US-listed tickers grouped by sector.

Expanded from the original ~80 to ~200 names — covers all S&P 500 sector
leaders, the mega-caps, the highly-traded ETFs, vol / crypto / commodity
plays, and the usual meme roster. Hedge-fund-managery names like the major
banks, pharma, semis, and industrials all have entries.

Users can still add any Yahoo symbol on demand via the sidebar; this list
just seeds the pre-populated dropdown and the default `make seed` target.
"""
from __future__ import annotations

TICKER_UNIVERSE: dict[str, list[str]] = {
    "Index ETF": ["SPY", "QQQ", "IWM", "DIA", "VTI", "VOO", "MDY", "EFA", "EEM"],
    "Sector ETF": [
        "XLF", "XLE", "XLK", "XLV", "XLY", "XLI", "XLP",
        "XLU", "XLRE", "XLB", "XLC",
    ],
    "Thematic ETF": ["SMH", "SOXX", "XBI", "IBB", "ARKK", "KWEB", "ITB", "KRE", "XRT"],
    "Vol ETF": ["VIXY", "VXX", "UVXY", "SVXY"],
    "Commodity ETF": ["GLD", "SLV", "USO", "UNG", "CPER", "DBA", "DBC", "PDBC"],
    "Bond ETF": ["TLT", "IEF", "SHY", "HYG", "LQD", "AGG", "BND", "TIP"],
    "Currency / Macro": ["UUP", "FXE", "FXY", "BITO"],

    "Mega Cap Tech": [
        "AAPL", "MSFT", "GOOGL", "GOOG", "AMZN", "META", "NVDA",
        "TSLA", "AVGO", "ORCL",
    ],
    "Semiconductors": [
        "AMD", "INTC", "TSM", "QCOM", "MU", "ASML", "AMAT", "LRCX",
        "KLAC", "MRVL", "ADI", "NXPI", "ON", "MCHP",
    ],
    "Software": [
        "CRM", "ADBE", "NOW", "INTU", "CRWD", "PANW", "FTNT", "DDOG",
        "NET", "ZS", "SNOW", "MDB", "TEAM", "WDAY", "SHOP",
    ],
    "Internet / Consumer Tech": [
        "NFLX", "PYPL", "UBER", "LYFT", "ABNB", "DASH", "SPOT",
        "ROKU", "PINS", "SNAP",
    ],
    "Financials — Banks": [
        "JPM", "BAC", "GS", "MS", "C", "WFC", "USB", "PNC", "TFC",
        "SCHW", "COF",
    ],
    "Financials — Asset Mgmt / Payments": [
        "BLK", "BX", "KKR", "V", "MA", "AXP", "ICE", "CME", "SPGI",
        "MCO", "COIN", "HOOD", "SQ",
    ],
    "Insurance": ["BRK-B", "PGR", "TRV", "ALL", "AIG", "MET", "CB"],

    "Consumer Discretionary": [
        "WMT", "HD", "NKE", "MCD", "SBUX", "DIS", "TGT", "LOW",
        "COST", "BKNG", "CMG", "YUM", "ROST", "TJX", "DLTR", "DG",
    ],
    "Consumer Staples": [
        "PG", "KO", "PEP", "PM", "MO", "CL", "MDLZ", "KMB", "GIS",
        "K", "SYY", "STZ",
    ],

    "Healthcare — Pharma": [
        "JNJ", "PFE", "LLY", "MRK", "ABBV", "BMY", "AZN", "NVO",
        "GSK", "SNY",
    ],
    "Healthcare — Devices / Services": [
        "UNH", "TMO", "DHR", "ABT", "MDT", "ISRG", "SYK", "BSX",
        "ELV", "CVS", "HCA", "HUM", "CI",
    ],
    "Biotech": ["REGN", "VRTX", "GILD", "BIIB", "MRNA", "BNTX", "ILMN"],

    "Energy": [
        "XOM", "CVX", "COP", "OXY", "SLB", "EOG", "PSX", "MPC",
        "VLO", "HAL", "BKR", "FANG",
    ],
    "Industrials": [
        "BA", "CAT", "GE", "HON", "LMT", "RTX", "UPS", "FDX",
        "DE", "MMM", "ETN", "EMR", "ITW", "NOC", "GD",
    ],
    "Transports / Airlines": ["DAL", "UAL", "AAL", "LUV", "CSX", "UNP", "NSC"],
    "Materials / Mining": [
        "LIN", "APD", "SHW", "FCX", "NEM", "GOLD", "ALB", "DOW",
        "DD", "MOS", "CF",
    ],
    "Utilities": ["NEE", "DUK", "SO", "D", "AEP", "EXC", "XEL"],
    "Real Estate": ["AMT", "PLD", "CCI", "EQIX", "PSA", "SPG", "O", "DLR"],
    "Communications": ["T", "VZ", "TMUS", "CMCSA", "CHTR"],

    "Meme / High Vol": [
        "GME", "AMC", "PLTR", "RIVN", "LCID", "MARA", "RIOT", "MSTR",
        "SMCI", "BB", "SOFI",
    ],
    "China / ADRs": ["BABA", "BIDU", "NIO", "PDD", "JD", "LI", "XPEV"],

    "Indices (read-only)": [
        # Equity benchmarks
        "^GSPC", "^NDX", "^DJI", "^RUT", "^GDAXI", "^STOXX50E", "^FTSE",
        "^N225", "^HSI",
        # Vol indices — required for cross-asset cheap/rich comparison
        "^VIX",       # CBOE S&P 500 vol
        "^VXN",       # CBOE Nasdaq-100 vol
        "^RVX",       # CBOE Russell 2000 vol
        "^VXFXI",     # CBOE China ETF vol
        "^V2X",       # VSTOXX (Euro Stoxx 50 vol)
        "^GVZ",       # CBOE Gold vol
        "^OVX",       # CBOE Crude Oil vol
        "^VXEEM",     # CBOE Emerging Markets vol
        "VDAX-NEW.DE",  # DAX vol (Yahoo's broken-but-sometimes-works ticker)
    ],
    "Crypto (spot pairs)": ["BTC-USD", "ETH-USD", "SOL-USD"],

    # ── DAX 40 — full constituents (German blue-chips) ─────────────────
    "DAX 40 (Germany)": [
        "ADS.DE", "AIR.DE", "ALV.DE", "BAS.DE", "BAYN.DE", "BMW.DE",
        "BNR.DE", "CBK.DE", "CON.DE", "1COV.DE", "DAI.DE", "DB1.DE",
        "DBK.DE", "DHL.DE", "DTE.DE", "DTG.DE", "ENR.DE", "EOAN.DE",
        "FME.DE", "FRE.DE", "HEI.DE", "HEN3.DE", "IFX.DE", "MBG.DE",
        "MRK.DE", "MTX.DE", "MUV2.DE", "P911.DE", "PAH3.DE", "QIA.DE",
        "RHM.DE", "RWE.DE", "SAP.DE", "SHL.DE", "SIE.DE", "SY1.DE",
        "VNA.DE", "VOW3.DE", "ZAL.DE", "BEI.DE",
    ],
    # ── MDAX leaders (mid-caps Germany) ─────────────────────────────
    "MDAX (Germany mid-cap)": [
        "AFX.DE", "AIXA.DE", "BC8.DE", "COK.DE", "EVK.DE", "FIE.DE",
        "FNTN.DE", "G24.DE", "GBF.DE", "GXI.DE", "HFG.DE", "HLAG.DE",
        "JUN3.DE", "KGX.DE", "LEG.DE", "LXS.DE", "NDA.DE", "PUM.DE",
        "RAA.DE", "SDF.DE", "TKA.DE", "WCH.DE", "WAF.DE", "TLX.DE",
    ],
    # ── CAC 40 (France) ──────────────────────────────────────────────
    "CAC 40 (France)": [
        "AC.PA", "ACA.PA", "AI.PA", "AIR.PA", "BN.PA", "BNP.PA",
        "CA.PA", "CAP.PA", "CS.PA", "DG.PA", "DSY.PA", "EL.PA",
        "EN.PA", "ENGI.PA", "GLE.PA", "HO.PA", "KER.PA", "LR.PA",
        "MC.PA", "ML.PA", "OR.PA", "PUB.PA", "RI.PA", "RMS.PA",
        "RNO.PA", "SAF.PA", "SAN.PA", "SGO.PA", "SU.PA", "STM.PA",
        "STMPA.PA", "TTE.PA", "URW.AS", "VIE.PA", "VIV.PA", "WLN.PA",
    ],
    # ── SMI (Switzerland) ────────────────────────────────────────────
    "SMI (Switzerland)": [
        "ABBN.SW", "CSGN.SW", "GIVN.SW", "HOLN.SW", "LONN.SW", "NESN.SW",
        "NOVN.SW", "ROG.SW", "SCMN.SW", "SGSN.SW", "SIKA.SW", "SREN.SW",
        "UBSG.SW", "ZURN.SW", "PGHN.SW",
    ],
    # ── AEX (Netherlands) ────────────────────────────────────────────
    "AEX (Netherlands)": [
        "ASML.AS", "ADYEN.AS", "AD.AS", "AKZA.AS", "DSM.AS", "HEIA.AS",
        "ING.AS", "KPN.AS", "MT.AS", "PHIA.AS", "REN.AS", "RDSA.AS",
        "UNA.AS", "WKL.AS", "PRX.AS",
    ],
    # ── IBEX 35 (Spain) ─────────────────────────────────────────────
    "IBEX (Spain)": [
        "ACS.MC", "ANA.MC", "BBVA.MC", "ELE.MC", "ENG.MC", "FER.MC",
        "GRF.MC", "IBE.MC", "ITX.MC", "MAP.MC", "REP.MC", "SAB.MC",
        "SAN.MC", "TEF.MC", "ACX.MC",
    ],
    # ── FTSE 100 leaders (UK) ───────────────────────────────────────
    "FTSE 100 (UK)": [
        "AZN.L", "BARC.L", "BATS.L", "BP.L", "DGE.L", "GSK.L",
        "HSBA.L", "LLOY.L", "NWG.L", "RIO.L", "SHEL.L", "STAN.L",
        "TSCO.L", "ULVR.L", "VOD.L", "GLEN.L", "BHP.L", "PRU.L",
        "REL.L", "RR.L",
    ],
    # ── Euro Stoxx 50 (cross-EU benchmark adds) ─────────────────────
    "Euro Stoxx 50 leaders": [
        "INGA.AS", "ABI.BR", "ENI.MI", "G.MI", "ISP.MI", "ENEL.MI",
        "STLA.MI", "STLAM.MI", "UCG.MI", "ITC.MI",
    ],
    # ── Hong Kong / Hang Seng top 30 ────────────────────────────────
    "Hang Seng (HKEX)": [
        "0001.HK", "0002.HK", "0003.HK", "0005.HK", "0006.HK",
        "0011.HK", "0012.HK", "0016.HK", "0017.HK", "0027.HK",
        "0066.HK", "0083.HK", "0101.HK", "0175.HK", "0267.HK",
        "0288.HK", "0386.HK", "0388.HK", "0688.HK", "0700.HK",
        "0762.HK", "0823.HK", "0857.HK", "0883.HK", "0939.HK",
        "0941.HK", "1093.HK", "1109.HK", "1113.HK", "1177.HK",
        "1299.HK", "1398.HK", "1810.HK", "1928.HK", "1997.HK",
        "2018.HK", "2318.HK", "2382.HK", "2388.HK", "2628.HK",
        "3690.HK", "3988.HK", "9618.HK", "9888.HK", "9988.HK",
        "9999.HK",
    ],
    # ── Nikkei 225 leaders (Japan) ──────────────────────────────────
    "Nikkei (Japan)": [
        "6758.T", "7203.T", "9984.T", "8306.T", "9432.T", "6098.T",
        "6861.T", "8035.T", "7974.T", "6367.T", "9433.T", "8316.T",
        "4063.T", "6501.T", "6594.T", "6902.T", "7267.T", "8001.T",
        "8031.T", "9983.T",
    ],
    # ── Australia (ASX 200 leaders) ─────────────────────────────────
    "ASX (Australia)": [
        "BHP.AX", "CBA.AX", "CSL.AX", "FMG.AX", "MQG.AX", "NAB.AX",
        "RIO.AX", "TLS.AX", "WBC.AX", "WES.AX", "WOW.AX",
    ],
    # ── Canada (TSX leaders) ────────────────────────────────────────
    "TSX (Canada)": [
        "RY.TO", "TD.TO", "BNS.TO", "BMO.TO", "CM.TO", "ENB.TO",
        "TRP.TO", "SU.TO", "CNQ.TO", "MFC.TO", "BCE.TO", "T.TO",
        "SHOP.TO", "ATD.TO", "L.TO",
    ],
    # ── Indian ADRs ─────────────────────────────────────────────────
    "India (ADRs)": [
        "INFY", "WIT", "HDB", "IBN", "TTM", "RDY",
    ],
}


def all_tickers() -> list[str]:
    """Flat de-duplicated list of all tickers in the universe."""
    seen: set[str] = set()
    out: list[str] = []
    for tickers in TICKER_UNIVERSE.values():
        for t in tickers:
            if t not in seen:
                seen.add(t)
                out.append(t)
    return out


def sector_of(ticker: str) -> str | None:
    """Return the sector label for a ticker, or None if not in the universe."""
    for sector, tickers in TICKER_UNIVERSE.items():
        if ticker in tickers:
            return sector
    return None
