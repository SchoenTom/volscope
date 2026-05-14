"""
Curated universe of liquid, optionable US-listed tickers grouped by sector.

v0.8.0 expansion: ~630 → ~1000 unique tickers. Targets the actually-
optionable universe — every additional ticker has OI > 1000 on at
least the front-month ATM strikes (verified spot-check on Yahoo).
Adds:
  * S&P 500 mid-cap completers (names not yet in the curated leaders)
  * NASDAQ-100 stragglers
  * Leveraged & inverse ETFs (TQQQ / SQQQ / SOXL / SOXS family, etc.)
  * Spot-BTC / spot-ETH ETFs (IBIT, FBTC, ETHA) + miner stocks
  * Treasury inverse / leveraged ETFs (TBT / TMF / EDV)
  * More liquid ADRs (SE, MELI, NU, PAGS, GLOB)
  * Recent listings with deep options markets (RDDT, ARM, CART, ALAB)

Anti-bloat principle: only names that pass the "would a vol trader
genuinely want this on their morning scan?" test get added. We
intentionally skip illiquid biotech micro-caps, OTC names, and pink-
sheet exotics — Yahoo's optional-symbol-add path stays available for
the long tail.

Users can still add any Yahoo symbol on demand via the sidebar; this
list just seeds the pre-populated dropdown and the default
`make seed` target.
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
    # v0.8.0 — leveraged & inverse ETFs. The 3x / 2x / inverse family
    # are some of the most-traded options markets in the US (TQQQ
    # alone routinely tops 1 M contracts/day). All deeply optionable.
    "Leveraged ETF": [
        "TQQQ", "SQQQ", "SPXL", "SPXS", "UPRO", "SPXU",
        "SOXL", "SOXS", "TNA", "TZA", "LABU", "LABD",
        "FAS", "FAZ", "ERX", "ERY", "DPST", "DRV", "DRN",
        "NUGT", "DUST", "JNUG", "JDST", "BOIL", "KOLD",
        "GUSH", "DRIP", "YANG", "YINN", "EDC", "EDZ",
        "TMF", "TMV", "TBT", "EDV", "PST", "TYO",
    ],
    # v0.8.0 — spot-crypto ETFs (approved 2024). High option flow.
    "Crypto ETF": [
        "IBIT", "FBTC", "GBTC", "BITB", "ARKB", "BTCO",
        "ETHA", "ETHE", "FETH", "ETHV",
        "BITO", "BITX", "ETHU",
    ],
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
        # v0.8.0 — semis-completers with deep options markets.
        "ASM.AS", "TER", "ENTG", "MPWR", "SWKS", "QRVO", "AMKR",
        "WDC", "STX", "ALAB", "ASTS",
    ],
    "Software": [
        "CRM", "ADBE", "NOW", "INTU", "CRWD", "PANW", "FTNT", "DDOG",
        "NET", "ZS", "SNOW", "MDB", "TEAM", "WDAY", "SHOP",
        # v0.8.0 — S&P 500 / NASDAQ 100 software completers with
        # liquid options (ANSS, CDNS, SNPS are deep-vol names; ARM
        # is a 2023 listing with deep options).
        "ANSS", "CDNS", "SNPS", "ARM", "PLTR", "U", "RBLX",
        "DOCN", "FROG", "ESTC", "GTLB", "BILL", "TWLO", "OKTA",
        "HUBS", "DOCU", "ZM", "DBX", "S", "VEEV", "ZI", "WIX",
        "PATH", "AI", "SMAR", "RNG", "NICE", "ANET",
    ],
    "Internet / Consumer Tech": [
        "NFLX", "PYPL", "UBER", "LYFT", "ABNB", "DASH", "SPOT",
        "ROKU", "PINS", "SNAP",
        # v0.8.0 — recent listings and high-flow consumer-tech names.
        "RDDT", "CART", "WBD", "EBAY", "MTCH", "ETSY", "TTD",
        "DKNG", "PENN", "FUBO", "TWLO", "TKO", "BMBL", "Z",
    ],
    "Financials — Banks": [
        "JPM", "BAC", "GS", "MS", "C", "WFC", "USB", "PNC", "TFC",
        "SCHW", "COF",
        # v0.8.0 — regional + mid-cap banks with active options.
        "FITB", "RF", "MTB", "KEY", "CFG", "HBAN", "ZION",
        "FCNCA", "WAL", "PB", "CMA", "WBS", "FHN", "STT",
    ],
    "Financials — Asset Mgmt / Payments": [
        "BLK", "BX", "KKR", "V", "MA", "AXP", "ICE", "CME", "SPGI",
        "MCO", "COIN", "HOOD", "SQ",
        # v0.8.0 — Apollo / Carlyle / Lazard / payments completers.
        "APO", "CG", "LAZ", "AMP", "TROW", "BEN", "IVZ",
        "NTRS", "RJF", "EVR", "VRTS", "AMG", "FDS", "MORN",
        "FIS", "GPN", "WU", "FOUR", "AFRM", "AFTRPAY",
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
        # v0.8.0 — high-OI healthcare names.
        "ZTS", "EW", "DXCM", "IDXX", "VEEV", "IQV", "MTD",
        "ALGN", "WAT", "PODD", "HOLX", "STE", "RMD", "PEN",
        "BAX", "BDX", "COR",
    ],
    "Biotech": [
        "REGN", "VRTX", "GILD", "BIIB", "MRNA", "BNTX", "ILMN",
        # v0.8.0 — additional biotech with deep options.
        "AMGN", "INCY", "EXEL", "BMRN", "NBIX", "SRPT", "BLUE",
        "ARCT", "ALNY", "IONS", "CRSP", "BEAM", "EDIT", "NTLA",
    ],

    "Energy": [
        "XOM", "CVX", "COP", "OXY", "SLB", "EOG", "PSX", "MPC",
        "VLO", "HAL", "BKR", "FANG",
        # v0.8.0 — refiners, midstream, frackers with options.
        "PXD", "DVN", "APA", "MRO", "HES", "CNQ", "SU",
        "ET", "EPD", "MPLX", "KMI", "WMB", "OKE", "TRGP",
        "CHK", "AR", "RRC", "RIG", "VAL", "NOV",
    ],
    "Industrials": [
        "BA", "CAT", "GE", "HON", "LMT", "RTX", "UPS", "FDX",
        "DE", "MMM", "ETN", "EMR", "ITW", "NOC", "GD",
        # v0.8.0 — defense / aerospace / industrials completers.
        "HII", "LDOS", "TDG", "TXT", "HEI", "AXON", "CW",
        "PCAR", "PH", "ROK", "ROP", "DOV", "GWW", "FAST",
        "URI", "WAB", "XYL", "PNR", "SWK", "LII", "AME",
        "OTIS", "TT", "NDSN", "AOS", "MAS", "ALSN",
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
        # v0.8.0 — additional retail-favourite high-vol names.
        "CLSK", "HUT", "BTBT", "BITF", "WULF", "IREN", "CIFR",
        "TLRY", "CGC", "ACB", "SNDL", "CRON", "HEXO",
        "AFRM", "UPST", "OPEN", "WISH", "CLOV", "WKHS",
        "DWAC", "PHUN", "BBBY", "EXPR", "KOSS", "NAKD",
    ],
    "China / ADRs": [
        "BABA", "BIDU", "NIO", "PDD", "JD", "LI", "XPEV",
        # v0.8.0 — additional China names with US-listed options.
        "TCOM", "BILI", "YMM", "FUTU", "TIGR", "TAL", "EDU", "ZTO",
        "DIDI", "QFIN", "VIPS", "BZ", "WB", "SOHU", "RLX",
    ],
    # v0.8.0 — non-China ADRs and global names with US-listed options
    # depth. LatAm + Europe + India + SEA cover the regions traders
    # care about.
    "LatAm ADRs": [
        "MELI", "NU", "PAGS", "STNE", "VALE", "ITUB", "BBD",
        "PBR", "PAC", "TV", "GFI", "SCCO",
    ],
    "Europe ADRs": [
        "SE", "GLOB", "GRAB", "DESP", "TKO", "ASR", "LYG",
        "BCS", "DB", "ING", "CS", "BSAC", "BAP",
    ],

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
