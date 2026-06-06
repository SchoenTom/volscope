"""
Run all three pages in sequence within the same Python process.
AppTest calls share the @st.cache_resource DB connection.
"""
import signal
import sys
import time
import os
import tempfile

sys.path.insert(0, '/Users/tomschoen/dev/VolScope')

HARD_TIMEOUT = 300


def handler(sig, frame):
    print("TIMEOUT_KILLED", flush=True)
    sys.exit(0)


signal.signal(signal.SIGALRM, handler)
signal.alarm(HARD_TIMEOUT)


# Build one app that routes based on session state
APP_CODE = """
import sys
sys.path.insert(0, "/Users/tomschoen/dev/VolScope")
import streamlit as st
from volscope.data.database import VolScopeDB
from volscope.config import DEFAULT_TICKER

@st.cache_resource
def _get_db():
    try:
        return VolScopeDB()
    except Exception:
        return VolScopeDB(read_only=True)

from volscope.ui.styles.theme import inject_theme, COLORS
from volscope.ui.components.keyboard_shortcuts import inject_keyboard_shortcuts
from volscope.ui.components.sidebar import render_sidebar

st.set_page_config(page_title="VolScope Test", layout="wide")
inject_theme()
inject_keyboard_shortcuts()

db = _get_db()

page = st.session_state.get("active_page", "Discover")
ticker = st.session_state.get("selected_ticker", "AAPL")

with st.sidebar:
    ticker_out, page_out, settings = render_sidebar(db, ticker, page)
st.session_state["selected_ticker"] = ticker_out
st.session_state["active_page"] = page_out

if page == "Discover":
    from volscope.ui.views.discover_page import render_discover_page
    render_discover_page(db, {})
elif page == "Heatmap":
    from volscope.ui.views.heatmap_page import render_heatmap_page
    render_heatmap_page(db, {})
elif page == "Scanner":
    from volscope.ui.views.scan_page import render_scan_page
    render_scan_page(db, {})
"""

tmpfile = tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False)
tmpfile.write(APP_CODE)
tmpfile.close()
APP_PATH = tmpfile.name

from streamlit.testing.v1 import AppTest


def make_at(page, ticker="AAPL"):
    at = AppTest.from_file(APP_PATH, default_timeout=120)
    at.session_state["selected_ticker"] = ticker
    at.session_state["active_page"] = page
    at.session_state["onboarding_complete"] = True
    at.session_state["onboarding_dismissed"] = True
    return at


def run_page(page, ticker="AAPL"):
    at = make_at(page, ticker)
    t0 = time.time()
    at.run()
    dt = time.time() - t0
    return at, dt


def report(at, secs, page):
    print(f"\n{'='*60}", flush=True)
    print(f"PAGE: {page}", flush=True)
    print(f"LOAD_SECS={secs:.2f}", flush=True)
    exceptions = [str(e.value)[:400] for e in at.exception]
    print(f"EXCEPTIONS({len(exceptions)})={exceptions}", flush=True)

    # Page-specific buttons (skip sidebar)
    SIDEBAR_LABELS = {
        '+ ADD', '↻ Refresh market data', 'Manage rules →',
    }
    btns = at.button
    page_btns = [b for b in btns if not (
        b.label.startswith('  ') or b.label.startswith('▸ ') or
        b.label in SIDEBAR_LABELS or b.label.startswith('+ load')
    )]
    print(f"BUTTON_COUNT_TOTAL={len(btns)}", flush=True)
    print(f"BUTTON_COUNT_PAGE={len(page_btns)}", flush=True)
    print(f"RADIOS: {[r.label for r in at.radio]}", flush=True)
    print(f"TOGGLES: {[t.label for t in at.toggle]}", flush=True)
    print(f"SLIDERS: {[s.label for s in at.slider]}", flush=True)
    print(f"SELECTBOXES: {[s.label for s in at.selectbox]}", flush=True)

    print("\nPage buttons:", flush=True)
    for b in page_btns:
        print(f"  '{b.label}'", flush=True)

    print("\nCaptions:", flush=True)
    for c in at.caption:
        print(f"  '{c.value[:200]}'", flush=True)

    print("\nInfo/Warnings/Errors:", flush=True)
    for info in at.info:
        print(f"  INFO: '{info.value[:300]}'", flush=True)
    for w in at.warning:
        print(f"  WARN: '{w.value[:300]}'", flush=True)
    for e in at.error:
        print(f"  ERR: '{e.value[:300]}'", flush=True)

    # Check for stale data banner
    stale_found = any("STALE" in m.value or "stale" in m.value.lower()
                      for m in at.markdown)
    print(f"STALE_BANNER_VISIBLE={stale_found}", flush=True)

    # Check for key jargon in page markdown (excluding sidebar)
    all_md = " ".join([m.value for m in at.markdown])
    jargon_check = {}
    terms = {
        "IV Percentile": "iv_percentile",
        "IV Rank": "iv_rank",
        "IV−HV Spread": "spread",
        "HV": "hv",
        "P {number}": "P pill",
        "S {number}": "S pill",
        "EDGE": "edge score",
        "crowded": "crowded score",
        "QUALITY": "quality score",
        "PERC TREND": "perc_trend",
        "VOL_CRISIS": "vol_crisis",
    }
    explained_terms = {
        "IV Percentile": "IV Percentile" in all_md and ("fraction" in all_md or "percentile" in all_md.lower()),
        "Spread label": "P " in all_md and "IV" in all_md,
    }
    print(f"\nJargon/explanation presence:", flush=True)
    for term, present in explained_terms.items():
        print(f"  {term}: present={present}", flush=True)

    # VOL_CRISIS, BLOCK, STALE visible on-page?
    for keyword in ["VOL_CRISIS", "BLOCK", "STALE", "IQR", "EDGE / 100", "P 0", "S +", "S -"]:
        found = keyword in all_md
        if found:
            print(f"  '{keyword}' visible on page", flush=True)


print("Starting all-page test...", flush=True)

# Test Discover
at_d, secs_d = run_page("Discover", "AAPL")
report(at_d, secs_d, "Discover")

# Test Heatmap
at_h, secs_h = run_page("Heatmap", "AAPL")
report(at_h, secs_h, "Heatmap")

# Test Scanner
at_s, secs_s = run_page("Scanner", "AAPL")
report(at_s, secs_s, "Scanner")

# Edge case: sparse ticker (if exists)
print("\n\n=== EDGE CASE: Sparse/unknown ticker ===", flush=True)
at_edge, secs_edge = run_page("Discover", "ZZZTEST")
print(f"LOAD_SECS={secs_edge:.2f}", flush=True)
print(f"EXCEPTIONS={[str(e.value)[:200] for e in at_edge.exception]}", flush=True)
print(f"BUTTONS={len(at_edge.button)}", flush=True)

os.unlink(APP_PATH)
signal.alarm(0)
print("\n=== ALL DONE ===", flush=True)
