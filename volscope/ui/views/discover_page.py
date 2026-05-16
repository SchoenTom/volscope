"""
Discover page — the hero. The opportunity dashboard a retail trader lands on.

Layout (2x2):
    💎 CHEAPEST VOL       🔥 RICHEST PREMIUM
    ⚡ TODAY'S VOL MOVERS 🎯 CROWDED TRADES

Each card is left-border-accented green (cheap) or red (rich) so the screen
parses at a glance: the user finds the PayPal-is-historically-cheap moment
without reading a single label.
"""
from __future__ import annotations

from datetime import date, timedelta
from html import escape
from typing import Optional

import pandas as pd

from volscope.analytics.crowded_trades import compute_crowded_score
from volscope.analytics.data_quality import summarize_quality
from volscope.analytics.opportunity import (
    find_cheapest_vol,
    find_daily_outliers,
    find_richest_premium,
)
from volscope.data.ticker_resolver import resolve_and_ingest
from volscope.ui.components.html_utils import page_banner_html, render_html
from volscope.ui.styles.theme import COLORS
from volscope.utils.safe import safe_num, safe_str


def _section_header(st, icon: str, title: str) -> None:
    """Themed section divider — keeps emoji in a span that resets letter-spacing."""
    render_html(
        st,
        f'<div class="volscope-section-header">'
        f'<span class="volscope-section-icon">{icon}</span>'
        f'{title}'
        f'</div>',
    )


def _earnings_within(db, ticker: str, days: int = 30) -> bool:
    try:
        df = db.get_upcoming_earnings(ticker, date.today())
    except Exception:
        return False
    if df is None or df.empty:
        return False
    cutoff = date.today() + timedelta(days=days)
    try:
        for d in df["earnings_date"]:
            if pd.Timestamp(d).date() <= cutoff:
                return True
    except Exception:
        return False
    return False


def _company_name(db, row: pd.Series) -> str:
    name = row.get("company_name")
    if name and not pd.isna(name):
        return str(name)
    ticker = row.get("ticker")
    if ticker is None:
        return ""
    try:
        return db.get_company_name(ticker) or ""
    except Exception:
        return ""


def _card(
    st,
    variant: str,
    ticker: str,
    company: str,
    iv: float,
    perc: float,
    spread: float,
    context: str,
    earnings_flag: bool = False,
    quality_level: Optional[str] = None,
    quality_one_liner: str = "",
) -> None:
    """Render a single opportunity card. `variant` ∈ {'cheap','rich','neutral'}.

    Shows TWO signals as pills so the user sees both:
      - IV Percentile (vs own 52-week history) — top right
      - IV − HV Spread (vs realized) — inline next to IV value
    A card is coherently cheap only when BOTH pills are green.

    When the source row has data-quality issues (stale, incomplete, suspect),
    a small inline badge surfaces it so the trader doesn't act on bad data.
    """
    # v0.9.3 — canonical thresholds from analytics/iv_thresholds.py.
    # Was hard-coded 20/80 (matched recommender but not signal.py at
    # 25/75). Now sourced from the single source of truth.
    from volscope.analytics.iv_thresholds import PERC_VERY_CHEAP, PERC_VERY_RICH
    perc_cls = (
        "low"  if perc < PERC_VERY_CHEAP else
        "high" if perc > PERC_VERY_RICH  else
        "mid"
    )
    spread_cls = "low" if spread < 0 else "high" if spread > 0 else "mid"
    badge = (
        '<span class="volscope-earnings-badge">⚠ ER ≤30d</span>' if earnings_flag else ""
    )
    company_html = (
        f'<span class="volscope-card-name">{escape(company)}</span>' if company else ""
    )
    quality_html = ""
    if quality_level and quality_level != "OK":
        q_color = {
            "WARN":    COLORS["amber"],
            "SUSPECT": COLORS["warn"],
            "STALE":   COLORS["amber"],
            "PARTIAL": COLORS["accent2"],
        }.get(quality_level, COLORS["muted"])
        title = quality_one_liner or quality_level
        quality_html = (
            f'<span style="background:{q_color}22;color:{q_color};'
            f'border-left:2px solid {q_color};padding:1px 6px;border-radius:3px;'
            f'font-size:9px;font-weight:600;margin-left:6px;letter-spacing:0.4px;'
            f'font-family:JetBrains Mono,monospace;" title="{escape(title)}">'
            f'{quality_level}</span>'
        )
    html = f"""
<div class="volscope-card volscope-card-{variant}">
<div style="display:flex; justify-content:space-between; align-items:flex-start; gap:8px;">
<div style="min-width:0;">
<span class="volscope-card-ticker">◈ {escape(ticker)}</span>{badge}{quality_html}
{company_html}
</div>
<span class="volscope-pill volscope-pill-{perc_cls}" title="IV percentile vs 52w">P {perc:.0f}</span>
</div>
<div class="volscope-card-context">{escape(context)}</div>
<div class="volscope-card-stats">
IV <strong>{iv:.1f}%</strong>
&nbsp;·&nbsp;
<span class="volscope-pill volscope-pill-{spread_cls}" title="IV − HV spread" style="padding:1px 8px;">S {spread:+.1f}</span>
</div>
</div>
"""
    render_html(st, html)


def _render_cards(
    st,
    df: pd.DataFrame,
    header: str,
    variant: str,
    db=None,
    flag_earnings: bool = False,
) -> None:
    _section_header(st, "", header)
    if df.empty:
        render_html(
            st,
            f'<div style="color:{COLORS["muted"]};font-size:11px;font-family:\'JetBrains Mono\',monospace;'
            f'padding:8px 0;">No data yet — add tickers in the sidebar.</div>',
        )
        return
    for _, row in df.iterrows():
        iv = safe_num(row.get("iv_30d"))
        perc = safe_num(row.get("iv_percentile"))
        hv = safe_num(row.get("hv_20d"))
        spread = iv - hv
        context = safe_str(row.get("context"))
        ticker = safe_str(row.get("ticker"), default="?")
        company = _company_name(db, row) if db is not None else ""
        flag = bool(
            flag_earnings and db is not None and _earnings_within(db, ticker, 30)
        )
        # Data-quality inline badge — STALE / PARTIAL / SUSPECT shown on the
        # card so the trader knows when not to act on this row.
        quality_level: Optional[str] = None
        quality_oneliner: str = ""
        try:
            from volscope.analytics.data_quality import composite_quality
            cq = composite_quality(row, history=None)
            quality_level = cq.overall_level
            quality_oneliner = cq.one_liner
        except Exception:
            pass
        _card(
            st,
            variant=variant,
            ticker=ticker,
            company=company,
            iv=iv,
            perc=perc,
            spread=spread,
            context=context,
            earnings_flag=flag,
            quality_level=quality_level,
            quality_one_liner=quality_oneliner,
        )
        # Compact action row beneath every card. "Scope" is the
        # primary CTA (direct navigation, the most common follow-up
        # action). "Alert" routes to Command Center's alerts panel
        # with the ticker pre-filled, so the operator can express
        # *what* should fire — a v0.7.2 stopgap until the v0.8.0
        # writable-on-demand connection enables a one-click
        # "add to watchlist" persistence.
        a1, a2, _ = st.columns([1, 1, 2])
        with a1:
            if st.button(
                "▶ Scope",
                key=f"disc_scope_{variant}_{ticker}",
                width='stretch',
                help=f"Open Scope page for {ticker} — full IV/HV deep dive.",
            ):
                from volscope.ui.components.navigation import NavIntent, nav_to
                nav_to(NavIntent(page="Scope", ticker=ticker, source="Discover"))
                st.rerun()
        with a2:
            if st.button(
                "★ Alert",
                key=f"disc_alert_{variant}_{ticker}",
                width='stretch',
                help=(
                    f"Pre-fill an alert rule for {ticker} on the Command "
                    "Center alerts panel."
                ),
            ):
                from volscope.ui.components.navigation import NavIntent, nav_to
                st.session_state["cc_prefill_alert_ticker"] = ticker
                # Page-registry key is "Command" not the human-
                # readable "Command Center" — using the wrong name
                # was silently hitting the sidebar's unknown-page
                # fallback. Fixed here so the Alert CTA actually
                # lands the operator on the Command page.
                nav_to(NavIntent(page="Command", ticker=ticker,
                                  source="Discover"))
                st.rerun()


def _render_movers(
    st,
    latest: pd.DataFrame,
    bulk_history: dict[str, pd.DataFrame],
) -> None:
    _section_header(st, "⚡", "TODAY'S VOL MOVERS")
    tickers = latest["ticker"].tolist() if "ticker" in latest.columns else []
    prev_frames = []
    for t in tickers:
        hist = bulk_history.get(t)
        if hist is not None and hist.shape[0] >= 2:
            prev_frames.append(hist.iloc[-2:-1])
    if not prev_frames:
        st.caption("Need at least two days of data per ticker.")
        return
    prev = pd.concat(prev_frames)
    history_map = {
        t: (hist["iv_30d"] if hist is not None and "iv_30d" in hist.columns else None)
        for t, hist in bulk_history.items()
    }
    movers = find_daily_outliers(latest, prev, n=5, history=history_map)
    if movers.empty:
        st.caption("No significant movers.")
        return
    for _, row in movers.iterrows():
        ticker = safe_str(row.get("ticker"), default="?")
        change = safe_num(row.get("iv_change"))
        iv = safe_num(row.get("iv_30d"))
        arrow = "▲" if change > 0 else "▼"
        color = COLORS["warn"] if change > 0 else COLORS["accent"]
        variant = "rich" if change > 0 else "cheap"
        company = _company_name(None, row) if row.get("company_name") else ""
        company_html = (
            f'<span class="volscope-card-name">{escape(company)}</span>'
            if company
            else ""
        )
        html = f"""
<div class="volscope-card volscope-card-{variant}">
<div style="display:flex; justify-content:space-between; align-items:baseline;">
<div>
<span class="volscope-card-ticker">◈ {escape(ticker)}</span>
{company_html}
</div>
<span style="color:{color};font-family:'JetBrains Mono',monospace;font-size:14px;font-weight:600;">{arrow} {abs(change):.1f}</span>
</div>
<div class="volscope-card-stats">IV {iv:.1f}%</div>
</div>
"""
        render_html(st, html)


def _crowded_band(score: float) -> tuple[str, str, str]:
    """Return (label, hex color, variant class) for a 0-100 crowded score.

    Bands are symmetric around the z=0 neutral point:
      0-25   calm     · positioning well below average
      25-60  normal   · positioning near the long-term mean
      60-80  elevated · above-average positioning, watch for reversal
      >80    crowded  · extreme consensus, high reversal / squeeze risk
    """
    if score >= 80:
        return ("crowded", COLORS["warn"], "rich")
    if score >= 60:
        return ("elevated", COLORS["amber"], "neutral")
    if score >= 25:
        return ("normal", COLORS["accent2"], "neutral")
    return ("calm", COLORS["accent"], "cheap")


def _render_crowded(
    st,
    latest: pd.DataFrame,
    bulk_history: dict[str, pd.DataFrame],
) -> None:
    _section_header(st, "🎯", "CROWDED TRADES")

    # Legend strip — the user must see the scale before they see the numbers.
    render_html(
        st,
        f"""
<div style="font-family:'JetBrains Mono',monospace;font-size:10px;color:{COLORS['muted']};margin-bottom:10px;display:flex;gap:12px;flex-wrap:wrap;">
<span><span style="color:{COLORS['accent']};">●</span> calm 0–24</span>
<span><span style="color:{COLORS['accent2']};">●</span> normal 25–59</span>
<span><span style="color:{COLORS['amber']};">●</span> elevated 60–79</span>
<span><span style="color:{COLORS['warn']};">●</span> crowded 80–100</span>
</div>
""",
    )

    scores: list[dict] = []
    for _, row in latest.iterrows():
        ticker = row.get("ticker")
        if ticker is None:
            continue
        hist = bulk_history.get(ticker, pd.DataFrame())
        # Require at least 20 rows for the z-score components to be
        # statistically meaningful. Sparse history → score is noise.
        if hist is None or hist.shape[0] < 20:
            continue
        score = compute_crowded_score(row, hist)
        scores.append({"ticker": ticker, "score": score})
    if not scores:
        render_html(
            st,
            f"""
<div style="color:{COLORS['muted']};font-size:11px;padding:8px 0;">
Need at least 20 days of history per ticker. Run <code>make scrape</code>
for a few days to accumulate enough data for crowded scoring.
</div>
""",
        )
        return
    crowded = pd.DataFrame(scores).sort_values("score", ascending=False).head(10)
    for _, row in crowded.iterrows():
        score = float(row["score"])
        label, color, variant = _crowded_band(score)
        bar_width = max(4, min(100, int(score)))
        html = f"""
<div class="volscope-card volscope-card-{variant}" style="padding:10px 14px;">
<div style="display:flex; justify-content:space-between; align-items:center;">
<span class="volscope-card-ticker" style="font-size:14px;">◈ {escape(str(row['ticker']))}</span>
<div style="font-family:'JetBrains Mono',monospace;">
<span style="color:{COLORS['muted']};font-size:10px;text-transform:uppercase;letter-spacing:1px;">{label}</span>
&nbsp;
<span style="color:{color};font-weight:600;font-size:14px;">{score:.0f}</span>
</div>
</div>
<div style="background:{COLORS['border']};height:4px;border-radius:2px;margin-top:6px;">
<div style="background:{color};height:4px;width:{bar_width}%;border-radius:2px;"></div>
</div>
</div>
"""
        render_html(st, html)

    with st.expander("How is the crowded score computed?", expanded=False):
        st.markdown(
            """
**Scale.** 0–100 symmetric around **50 = neutral**. 50 means every
component is at its own long-term mean. 100 means all four components
are at +3σ simultaneously — an extremely unlikely alignment that only
happens in genuine squeeze setups.

**Components (equal 25% weight each):**

1. **Put/Call ratio z-score** — how skewed today's options flow is
   toward puts vs calls, relative to the last 20 days.
2. **Open Interest vs 20-day average** — whether more contracts are
   outstanding than typical (commitment).
3. **Volume vs 20-day average** — whether more trading is happening
   than typical (attention).
4. **IV-HV spread z-score** — whether options are pricing more volatility
   than realized vol justifies, vs this ticker's own history.

**How to read it.**

- **&lt;25 · calm** — positioning well below average. No crowd to
  squeeze. Options flow is quiet. Safe to hold bought premium.
- **25–59 · normal** — positioning near the long-term mean. Nothing
  unusual. Most tickers sit here most of the time.
- **60–79 · elevated** — above-average positioning. Watch the tape.
  Not yet a contrarian signal but worth knowing.
- **80+ · crowded** — extreme consensus. Historically ~5% of days,
  usually clustered around macro stress, earnings, or major expirations.
  Counter-trades (fade the move, sell the premium, or position for a
  reversal) have historically worked in this regime.

**Why SPY 62 isn't really crowded.** A 62 reading means one component
is at ~z=1.0, or several are at z~0.5 each — only mildly above average.
SPY rarely crosses 80 outside of VIX spikes. Take 62 as "mildly elevated,
watch but don't fade yet".
            """
        )


def _render_sector_vol_map(st, latest: pd.DataFrame) -> None:
    """
    Sector Vol Map — for each sector, show the median IV percentile across
    its member tickers. Low median = sector-wide quiet tape (long vol).
    High median = sector-wide premium (short vol or reduce delta).

    This is the "hedge-fund manager glance" — where is vol cheap or rich at
    the SECTOR level, not just the single-name level.
    """
    _section_header(st, "🗺", "SECTOR VOL MAP")
    if "sector" not in latest.columns:
        st.caption("No sector data.")
        return

    grouped = (
        latest.dropna(subset=["sector"])
        .groupby("sector")
        .agg(
            median_perc=("iv_percentile", "median"),
            median_iv=("iv_30d", "median"),
            n=("ticker", "count"),
        )
        .reset_index()
    )
    grouped = grouped[grouped["n"] >= 2]
    if grouped.empty:
        st.caption("Need at least two tickers per sector to compute a median.")
        return
    grouped = grouped.sort_values("median_perc", ascending=True).reset_index(drop=True)

    rows: list[str] = []
    for _, r in grouped.iterrows():
        mp = float(r["median_perc"]) if pd.notna(r["median_perc"]) else 50.0
        miv = float(r["median_iv"]) if pd.notna(r["median_iv"]) else 0.0
        n = int(r["n"])
        sector = str(r["sector"])
        if mp < 20:
            color = COLORS["accent"]
            label = "cheap"
        elif mp > 80:
            color = COLORS["warn"]
            label = "rich"
        else:
            color = COLORS["accent2"]
            label = "normal"
        bar_width = max(3, min(100, int(mp)))
        rows.append(
            f'<div style="display:flex;align-items:center;gap:12px;padding:6px 0;border-bottom:1px solid {COLORS["border"]};">'
            f'<div style="flex:0 0 160px;color:{COLORS["text"]};font-size:12px;font-weight:500;">{escape(sector)}</div>'
            f'<div style="flex:0 0 36px;color:{COLORS["muted"]};font-size:10px;font-family:\'JetBrains Mono\',monospace;">n={n}</div>'
            f'<div style="flex:1;background:{COLORS["border"]};height:6px;border-radius:3px;position:relative;">'
            f'<div style="background:{color};height:6px;width:{bar_width}%;border-radius:3px;"></div>'
            f'</div>'
            f'<div style="flex:0 0 110px;text-align:right;font-family:\'JetBrains Mono\',monospace;font-size:11px;color:{color};">{mp:.0f} · IV {miv:.1f}% · {label}</div>'
            f'</div>'
        )

    body = (
        f'<div style="background:{COLORS["card"]};border:1px solid {COLORS["border"]};'
        f'border-radius:8px;padding:14px 18px;">'
        + "".join(rows)
        + '</div>'
    )
    render_html(st, body)


def _render_regime_strip(st, latest: pd.DataFrame) -> None:
    """
    Market regime indicator — computed from the cross-sectional distribution
    of IV percentiles across the whole tracked universe.

    The idea: in a high-vol regime many names cluster at high percentile
    (broad premium). In a calm regime most names cluster low. The median is
    the single number that captures "where is the crowd right now".
    """
    _section_header(st, "🌡", "MARKET REGIME")
    if "iv_percentile" not in latest.columns:
        st.caption("No data.")
        return
    series = latest["iv_percentile"].dropna()
    if len(series) < 5:
        st.caption("Need at least 5 tickers with IV data.")
        return

    median = float(series.median())
    q25 = float(series.quantile(0.25))
    q75 = float(series.quantile(0.75))
    n = len(series)

    if median < 25:
        regime = "RISK ON"
        regime_color = COLORS["accent"]
        commentary = "Universe-wide IV is at a floor. Premium is cheap — long vol setups are in favor."
    elif median > 75:
        regime = "RISK OFF"
        regime_color = COLORS["warn"]
        commentary = "Universe-wide IV is elevated. Premium is rich — short vol / covered calls in favor."
    elif median > 55:
        regime = "ELEVATED"
        regime_color = COLORS["amber"]
        commentary = "Vol is trading above average. Selective short premium; watch earnings."
    else:
        regime = "NORMAL"
        regime_color = COLORS["accent2"]
        commentary = "Cross-sectional vol is in the normal band. No broad thesis — pick your spots."

    body = f"""
<div style="background:{COLORS['card']};border:1px solid {COLORS['border']};border-left:4px solid {regime_color};border-radius:8px;padding:16px 20px;">
<div style="display:flex;align-items:baseline;gap:14px;">
<div style="font-family:'JetBrains Mono',monospace;font-size:20px;font-weight:700;color:{regime_color};letter-spacing:0.05em;">● {regime}</div>
<div style="color:{COLORS['muted']};font-size:11px;font-family:'JetBrains Mono',monospace;">across {n} tickers</div>
</div>
<div style="margin-top:8px;color:{COLORS['text']};font-size:12px;line-height:1.5;">{commentary}</div>
<div style="margin-top:12px;font-family:'JetBrains Mono',monospace;font-size:11px;color:{COLORS['muted']};">
IQR <span style="color:{COLORS['text']};">{q25:.0f}</span> — <span style="color:{COLORS['text']};">{q75:.0f}</span>
&nbsp;·&nbsp; median <span style="color:{COLORS['text']};">{median:.0f}</span>
</div>
</div>
"""
    render_html(st, body)


#: The 8-ticker starter pack — same list as the quickstart Makefile target.
#: Stays in sync: if you change one, change the other.
_STARTER_PACK = ("SPY", "QQQ", "AAPL", "NVDA", "TSLA", "META", "GLD", "TLT")


def _render_first_run_welcome(st, db) -> None:
    """
    First-run welcome card for an empty DB. Gives the user a one-click path
    to a populated Discover page without touching the CLI. The button loads
    the same starter pack as `make quickstart` — SPY, QQQ, AAPL, NVDA, TSLA,
    META, GLD, TLT — via the on-demand resolver.
    """
    render_html(
        st,
        f"""
<div style="background:{COLORS['card']};border:1px solid {COLORS['border']};border-left:4px solid {COLORS['accent']};border-radius:10px;padding:24px 28px;margin-top:16px;">
<div style="color:{COLORS['accent']};font-family:'JetBrains Mono',monospace;font-size:14px;font-weight:700;letter-spacing:0.08em;margin-bottom:8px;">◈ WELCOME TO VOLSCOPE</div>
<div style="color:{COLORS['text']};font-size:14px;line-height:1.6;margin-bottom:16px;">
Your database is empty. Load the 8-ticker starter pack to see a populated Discover page,
or add any Yahoo symbol from the sidebar.
</div>
<div style="color:{COLORS['muted']};font-size:12px;line-height:1.6;">
Starter pack: <code>SPY QQQ AAPL NVDA TSLA META GLD TLT</code><br>
Takes ~20 seconds. You can always add more later via the sidebar.
</div>
</div>
""",
    )

    col1, col2 = st.columns([1, 3])
    with col1:
        if st.button(
            "Load starter pack",
            type="primary",
            help="Fetches 2 years of OHLCV for the 8 starter tickers and backfills HV.",
        ):
            added = 0
            failed = 0
            progress = st.progress(0.0, text="Starting...")
            for i, ticker in enumerate(_STARTER_PACK):
                progress.progress(
                    (i + 1) / len(_STARTER_PACK),
                    text=f"Resolving {ticker} ({i + 1}/{len(_STARTER_PACK)})",
                )
                try:
                    result = resolve_and_ingest(db, ticker)
                    if result.ok:
                        added += 1
                    else:
                        failed += 1
                except Exception:
                    failed += 1
            progress.empty()
            if added > 0:
                st.success(
                    f"Loaded {added}/{len(_STARTER_PACK)} starter tickers. "
                    f"Refreshing..."
                )
                st.rerun()
            else:
                st.error(
                    f"Failed to load any starter tickers. Check your internet "
                    f"connection and try again. ({failed} failures)"
                )
    with col2:
        st.caption(
            "Or: open the sidebar and type a symbol into the 'Add any Yahoo symbol' box, "
            "then hit '+ Add to universe'."
        )


def _render_data_quality(
    st, latest: pd.DataFrame, bulk_history: dict[str, pd.DataFrame]
) -> None:
    """
    Data-quality panel: surfaces rows where our computed IV looks wrong.
    SUSPECT rows hit a hard ceiling (SPY at 78% old bug), WARN rows have
    an unusual IV-HV spread vs their own history.
    """
    _section_header(st, "🧪", "DATA QUALITY")
    try:
        reports = summarize_quality(latest, bulk_history)
    except Exception:
        st.caption("Quality check failed.")
        return
    if reports.empty:
        render_html(
            st,
            f"""
<div style="color:{COLORS['accent']};font-size:11px;font-family:'JetBrains Mono',monospace;padding:6px 10px;background:rgba(0,212,170,0.08);border-radius:4px;">
● All {len(latest)} tickers passed quality checks
</div>
""",
        )
        return
    for _, row in reports.iterrows():
        level = str(row["level"])
        ticker = str(row["ticker"])
        reason = str(row["reason"])
        color = COLORS["warn"] if level == "SUSPECT" else COLORS["amber"]
        variant = "rich" if level == "SUSPECT" else "neutral"
        html = f"""
<div class="volscope-card volscope-card-{variant}" style="padding:10px 14px;">
<div style="display:flex; justify-content:space-between; align-items:center;">
<span class="volscope-card-ticker" style="font-size:14px;">◈ {escape(ticker)}</span>
<span style="color:{color};font-family:'JetBrains Mono',monospace;font-weight:600;font-size:10px;text-transform:uppercase;letter-spacing:1px;">● {level}</span>
</div>
<div style="color:{COLORS['muted']};font-size:10px;margin-top:4px;font-family:'JetBrains Mono',monospace;">{escape(reason)}</div>
</div>
"""
        render_html(st, html)


def _render_best_setup_hero(st, latest: pd.DataFrame, db) -> None:
    """The "Today's Best Setup" hero — single concrete recommendation.

    Pulls the highest Edge Score across the universe, asks Strategy
    Recommender for the matching multi-leg structure, and overlays the
    backtest hit-rate for that (strategy, ticker) pair from the persisted
    calibration. Result: one banner answering "if I had to do ONE trade
    today, what should it be?"
    """
    from volscope.analytics.edge_score import compute_edge_table
    from volscope.analytics.strategy_recommender import recommend_strategies
    from volscope.analytics.strategy_calibration import get_stats_for

    # Build per-ticker edge scores from the latest snapshot (no ML/regime
    # to keep this fast — confidence is shown separately).
    if "ticker" not in latest.columns:
        return
    rows: dict[str, pd.Series] = {row["ticker"]: row for _, row in latest.iterrows()}
    edges = compute_edge_table(list(rows.keys()), rows)
    if not edges:
        return
    liquid = [e for e in edges if not e.illiquid]
    if not liquid:
        # All candidates are illiquid — show a calmer notice rather than
        # promoting an unexecutable trade as "best setup".
        st.warning(
            "🔍 No liquid candidates — every ticker has total OI below the "
            "threshold. Add liquid majors via the sidebar before relying on "
            "Discover recommendations.",
        )
        return
    top = liquid[0]
    row = rows[top.ticker]

    # Strategy + backtest stats
    iv_30d = float(row.get("iv_30d") or 0.0)
    iv_60d = row.get("iv_60d")
    iv_perc = float(row.get("iv_percentile") or 50.0)
    skew = row.get("iv_skew_25d")
    term_slope = (
        float(iv_60d) - iv_30d
        if iv_60d is not None and not pd.isna(iv_60d)
        else None
    )
    recs = recommend_strategies(
        iv_percentile=iv_perc,
        skew_25=float(skew) if skew is not None and not pd.isna(skew) else None,
        term_slope=term_slope,
    )
    if not recs or recs[0].name == "WAIT":
        return
    rec = recs[0]

    stats = get_stats_for(rec.name, ticker=top.ticker)
    if stats is None:
        stats = get_stats_for(rec.name)
    hitrate_str = (
        f'{stats.hit_rate*100:.0f}% hit · {stats.n_trades} trades · Sharpe {stats.sharpe:+.2f}'
        if stats and stats.n_trades > 0 else 'no backtest yet — run make simulate'
    )

    # Render the hero card
    accent = COLORS["accent"] if top.score >= 70 else COLORS["accent2"]
    bar_w = max(2, int(top.score))
    company = ""
    try:
        company = db.get_company_name(top.ticker) or ""
    except Exception:
        pass

    render_html(
        st,
        f'<div style="background:{COLORS["card"]};border:1px solid {COLORS["border"]};'
        f'border-left:4px solid {accent};border-radius:10px;padding:18px 22px;'
        f'margin-bottom:18px;font-family:JetBrains Mono,monospace;">'
        # Header row
        f'<div style="display:flex;align-items:center;justify-content:space-between;'
        f'gap:14px;margin-bottom:10px;">'
        f'<div>'
        f'<div style="color:{COLORS["label"]};font-size:9px;letter-spacing:1.6px;'
        f'text-transform:uppercase;font-weight:600;">today\'s best setup</div>'
        f'<div style="color:{COLORS["text"]};font-size:18px;font-weight:700;'
        f'margin-top:2px;">'
        f'◈ {escape(top.ticker)} '
        f'<span style="color:{COLORS["muted"]};font-size:11px;font-weight:400;'
        f'margin-left:6px;">{escape(company)}</span>'
        f'</div>'
        f'</div>'
        f'<div style="text-align:right;">'
        f'<div style="color:{accent};font-size:24px;font-weight:700;line-height:1;">'
        f'{top.score:.0f}</div>'
        f'<div style="color:{COLORS["muted"]};font-size:9px;letter-spacing:1px;">'
        f'EDGE / 100</div>'
        f'</div>'
        f'</div>'
        # Score bar
        f'<div style="height:6px;background:{COLORS["border"]};border-radius:3px;'
        f'overflow:hidden;margin-bottom:10px;">'
        f'<div style="width:{bar_w}%;height:100%;background:{accent};"></div>'
        f'</div>'
        # Why
        f'<div style="color:{COLORS["text"]};font-size:11px;margin-bottom:10px;">'
        f'<span style="color:{COLORS["muted"]};">why:</span> {escape(top.one_liner)}'
        f'</div>'
        # Recommended structure
        f'<div style="background:{COLORS["bg"]};border-radius:6px;padding:10px 12px;'
        f'border-left:2px solid {accent};">'
        f'<div style="color:{accent};font-size:10px;font-weight:700;letter-spacing:1px;'
        f'text-transform:uppercase;margin-bottom:4px;">recommended structure</div>'
        f'<div style="color:{COLORS["text"]};font-size:13px;font-weight:600;'
        f'margin-bottom:4px;">{escape(rec.name)}</div>'
        f'<div style="color:{COLORS["muted"]};font-size:10px;margin-bottom:6px;">'
        f'{escape(rec.thesis)}</div>'
        f'<div style="color:{COLORS["accent2"]};font-size:11px;font-weight:600;">'
        f'historical: {hitrate_str}</div>'
        f'</div>'
        # Footer
        f'<div style="margin-top:8px;color:{COLORS["muted"]};font-size:9px;">'
        f'open Pre-Trade for {escape(top.ticker)} to size + price the structure'
        f'</div>'
        f'</div>',
    )

    # Quick-jump button to Pre-Trade for this ticker
    if st.button(
        f"▷ Open Pre-Trade for {top.ticker}",
        key="best_setup_pretrade_btn",
        width='content',
    ):
        st.session_state["selected_ticker"] = top.ticker
        st.session_state["active_page"] = "Pre-Trade"
        st.rerun()


def render_discover_page(db, settings: dict | None = None) -> None:
    import streamlit as st

    from volscope.ui.components.auto_refresh import auto_refresh_toggle
    from volscope.ui.components.regime_header import render_regime_header
    from volscope.ui.components.freshness_banner import render_freshness_banner
    from volscope.ui.components.phase_header import render_phase_header
    from volscope.ui.components.next_step import render_next_step_footer

    # v0.9.0 — persistent vol-regime header strip.
    render_regime_header(db)
    # v0.9.7 — 4-phase orientation strip (master plan §2).
    render_phase_header(st, page_name="Discover",
                         ticker=st.session_state.get("selected_ticker"))
    # v0.9.3 — NYSE-aware freshness banner (hidden when FRESH so the
    # operator only sees it when data is actually stale).
    render_freshness_banner(db)
    st.markdown("## ◈ Discover")
    render_html(
        st,
        page_banner_html(
            title="Discover",
            what="ranked opportunity board across the universe",
            when="idea-generation mode",
        ),
    )
    st.caption("Where volatility is cheap, rich, moving, or crowded — right now.")
    # v3: explicit data-freshness bar + 1-click refresh
    from volscope.ui.components.data_freshness_bar import render_data_freshness_bar
    render_data_freshness_bar(db)
    auto_refresh_toggle("discover")

    # First-time onboarding banner — dismissable, only shown until the user
    # opts out via session state. New users get a 1-line orientation:
    # what each card on this page actually means.
    if not st.session_state.get("onboarding_dismissed", False):
        c1, c2 = st.columns([10, 1])
        with c1:
            st.info(
                "**New here? Read this once.** "
                "💎 CHEAPEST = options below their own annual percentile and below realized vol. "
                "🔥 RICHEST = options above. ⚡ MOVERS = today's biggest IV jumps. "
                "🌐 CROWDED = consensus extremes (reversal risk). "
                "Click any card to drill into Scope.",
                # Streamlit ≥1.32 rejects ``ℹ`` (U+2139) as icon — it
                # is Emoji=Yes but Emoji_Presentation=No. ``💡`` is
                # unambiguously emoji-presentation and reads well in
                # an info-style banner.
                icon="💡",
            )
        with c2:
            if st.button("✕", key="onboarding_dismiss", help="Hide this onboarding banner"):
                st.session_state["onboarding_dismissed"] = True
                st.rerun()

    # Cached snapshot (60s TTL) — avoids re-querying DuckDB on every rerun.
    from volscope.ui.components.cached_data import get_all_latest_cached, make_cache_key
    latest = get_all_latest_cached(make_cache_key(db), db)
    if latest.empty:
        _render_first_run_welcome(st, db)
        return

    # v0.6.1 — IV quality filter. Excludes BLOCK-recommended tickers
    # by default (FISV-class contamination). User can opt out to see
    # the full universe including dirty rows.
    exclude_low_quality = st.toggle(
        "Exclude low-quality data",
        value=True,
        key="discover_quality_filter",
        help=(
            "Hides tickers whose IV metrics are flagged as BLOCK by the "
            "robustness subsystem (single-spike contamination, recent "
            "structural break, or insufficient data). See docs/IV_ROBUSTNESS.md."
        ),
    )
    if exclude_low_quality and "iv_recommendation" in latest.columns:
        n_before = len(latest)
        latest = latest[latest["iv_recommendation"] != "BLOCK"]
        n_filtered = n_before - len(latest)
        if n_filtered > 0:
            st.caption(
                f"_filter hid {n_filtered} ticker{'s' if n_filtered != 1 else ''} "
                f"flagged as BLOCK — disable the toggle above to include them_"
            )

    # ── TODAY'S BEST SETUP — hero card above all sections ───────────
    # Combines Edge Score (cheapness) + Strategy Recommender (structure) +
    # Backtest hit-rate (calibration) into a single concrete trade idea.
    _render_best_setup_hero(st, latest, db)

    # Market regime strip — the one-glance "where is vol" indicator.
    _render_regime_strip(st, latest)

    # v0.9.0 — Crisis-tier hard filter: a ticker flagged as
    # ``VOL_CRISIS`` (per the HMM + override in compute_vol_regime.py)
    # is excluded from the CHEAPEST panel because in a vol-explosion
    # regime "cheap" is a snapshot artifact, not a tradable signal.
    # The ticker still appears in RICHEST / MOVERS / CROWDED so the
    # operator can see *why* it's flagged.
    if "vol_regime" in latest.columns:
        crisis_mask = latest["vol_regime"] == "VOL_CRISIS"
        cheapest_pool = latest[~crisis_mask.fillna(False)]
        n_crisis_blocked = int(crisis_mask.fillna(False).sum())
    else:
        cheapest_pool = latest
        n_crisis_blocked = 0

    # v0.9.3 phase-4: vol-indices (^VIX, ^VVIX, ^SKEW, …) are derived
    # data, not tradable. Saying "VIX is CHEAP" is a category error
    # — you don't BUY VIX, you buy VXX/UVXY or sell SPX options. Drop
    # vol-indices from both CHEAPEST and RICHEST pools so the operator
    # only sees actionable tickers there. They still appear elsewhere
    # (Heatmap, dedicated VIX Scope view) for context.
    if "ticker" in latest.columns:
        from volscope.data.symbol_types import is_vol_index
        vol_idx_mask = latest["ticker"].astype(str).map(is_vol_index)
        cheapest_pool = cheapest_pool[
            ~latest["ticker"].astype(str).map(is_vol_index).reindex(
                cheapest_pool.index, fill_value=False,
            ).fillna(False)
        ]
        n_vol_index_blocked = int(vol_idx_mask.fillna(False).sum())
    else:
        n_vol_index_blocked = 0

    cheapest = find_cheapest_vol(cheapest_pool, n=10)
    # Richest pool also drops vol-indices for the same reason.
    if "ticker" in latest.columns:
        from volscope.data.symbol_types import is_vol_index
        richest_pool = latest[
            ~latest["ticker"].astype(str).map(is_vol_index).fillna(False)
        ]
    else:
        richest_pool = latest
    richest = find_richest_premium(richest_pool, n=10)

    if n_crisis_blocked > 0:
        render_html(
            st,
            f'<div style="background:{COLORS["card"]};border:1px solid '
            f'{COLORS["warn"]}55;border-left:3px solid {COLORS["warn"]};'
            f'border-radius:6px;padding:8px 12px;margin:6px 0 10px 0;'
            f'font-family:\'DM Sans\',sans-serif;font-size:11px;'
            f'color:{COLORS["text"]};">'
            f'⚠ <strong>{n_crisis_blocked}</strong> ticker(s) flagged as '
            f'<span style="color:{COLORS["warn"]};">VOL_CRISIS</span> '
            f'were excluded from CHEAPEST. In a vol-explosion regime '
            f'"cheap" is a snapshot artifact — long-vega entries are '
            f'risk-managed away by the HMM + VIX/IV-HV override.'
            f'</div>',
        )

    from volscope.ui.components.cached_data import get_recent_for_tickers_cached
    all_ticker_list = (
        latest["ticker"].dropna().tolist() if "ticker" in latest.columns else []
    )
    with st.spinner("Scanning universe..."):
        bulk_history = get_recent_for_tickers_cached(
            make_cache_key(db),
            tuple(all_ticker_list),
            60,
            db,
        )

    # ── Tabbed view replaces the previous 4-quadrant grid ─────────────
    # One tab per trade thesis. Same renderer underneath; visual budget
    # frees up significant vertical real-estate vs the 2x2 grid.
    tab_cheap, tab_rich, tab_movers, tab_crowded, tab_sectors = st.tabs([
        "💎 Cheap",
        "🔥 Rich",
        "⚡ Movers",
        "🌐 Crowded",
        "📊 Sectors",
    ])
    with tab_cheap:
        _render_cards(st, cheapest, "💎 CHEAPEST VOL", variant="cheap", db=db)
    with tab_rich:
        _render_cards(
            st, richest, "🔥 RICHEST PREMIUM", variant="rich", db=db, flag_earnings=True,
        )
    with tab_movers:
        _render_movers(st, latest, bulk_history)
    with tab_crowded:
        _render_crowded(st, latest, bulk_history)
    with tab_sectors:
        c1, c2 = st.columns(2)
        with c1:
            _render_sector_vol_map(st, latest)
        with c2:
            _render_data_quality(st, latest, bulk_history)

    # v0.9.7 — cross-page weave footer (master plan §4)
    render_next_step_footer(
        st, page="Discover",
        ticker=st.session_state.get("selected_ticker"),
    )
