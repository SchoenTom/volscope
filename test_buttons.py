"""
Button interaction test — click each non-nav button and check for exceptions.
"""
import signal
import sys
import time
import os
import tempfile

sys.path.insert(0, '/Users/tomschoen/dev/VolScope')

PAGE = sys.argv[1] if len(sys.argv) > 1 else "Discover"
TICKER = sys.argv[2] if len(sys.argv) > 2 else "AAPL"
HARD_TIMEOUT = int(sys.argv[3]) if len(sys.argv) > 3 else 180


def handler(sig, frame):
    print("TIMEOUT_KILLED", flush=True)
    sys.exit(0)


signal.signal(signal.SIGALRM, handler)
signal.alarm(HARD_TIMEOUT)


APP_CODE = f"""
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
from volscope.ui.components.html_utils import render_html

st.set_page_config(page_title="VolScope Test", layout="wide")
inject_theme()
inject_keyboard_shortcuts()

db = _get_db()

page = st.session_state.get("active_page", "{PAGE}")
ticker = st.session_state.get("selected_ticker", "{TICKER}")

with st.sidebar:
    ticker_out, page_out, settings = render_sidebar(db, ticker, page)

st.session_state["selected_ticker"] = ticker_out
st.session_state["active_page"] = page_out

if page == "Discover":
    from volscope.ui.views.discover_page import render_discover_page
    render_discover_page(db, {{}})
elif page == "Heatmap":
    from volscope.ui.views.heatmap_page import render_heatmap_page
    render_heatmap_page(db, {{}})
elif page == "Scanner":
    from volscope.ui.views.scan_page import render_scan_page
    render_scan_page(db, {{}})
"""

tmpfile = tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False)
tmpfile.write(APP_CODE)
tmpfile.close()
APP_PATH = tmpfile.name

from streamlit.testing.v1 import AppTest


def fresh_at(page, ticker):
    at = AppTest.from_file(APP_PATH, default_timeout=60)
    at.session_state["selected_ticker"] = ticker
    at.session_state["active_page"] = page
    at.session_state["onboarding_complete"] = True
    at.session_state["onboarding_dismissed"] = True
    at.run()
    return at


print(f"=== Button test: {PAGE} / {TICKER} ===", flush=True)
at = fresh_at(PAGE, TICKER)
print(f"Initial load: {len(at.button)} buttons, {len(at.exception)} exceptions", flush=True)

# Separate sidebar buttons from page buttons
# Sidebar buttons have labels like "▸ Page", "  Page", "+ ADD", "+ load..."
# Page-specific buttons are the rest
SIDEBAR_LABELS = {
    '▸ Discover', '  Scope', '  Heatmap', '  Earnings Hub',
    '  Vol Insights', '  Scanner', '  Alerts  (721)', '  Watchlist',
    '  Command', '  Options Lab', '  Help', '+ ADD',
    '↻ Refresh market data',
}


print("\n--- Page button clicks (skipping nav/sidebar) ---", flush=True)
for i, b in enumerate(at.button):
    label = b.label
    # Skip sidebar navigation buttons
    if label in SIDEBAR_LABELS or label.startswith('  ') or label.startswith('▸ ') or label.startswith('+ load'):
        print(f"  SKIP[{i}] '{label}'", flush=True)
        continue

    # Skip buttons with raw ticker names in label (content buttons) that
    # would navigate away — test just the functional ones
    print(f"\n  CLICK[{i}] '{label}'", flush=True)
    try:
        # Reload fresh state each time
        at2 = fresh_at(PAGE, TICKER)
        # Find button by label
        target = None
        for btn in at2.button:
            if btn.label == label:
                target = btn
                break
        if target is None:
            print(f"    -> NOT FOUND on fresh load", flush=True)
            continue

        target.click().run()
        exc = [str(e.value)[:200] for e in at2.exception]
        new_page = at2.session_state.get("active_page", "UNKNOWN") if hasattr(at2.session_state, 'get') else "?"
        print(f"    -> exceptions={exc}", flush=True)
        print(f"    -> buttons_after={len(at2.button)}", flush=True)
    except Exception as ex:
        print(f"    -> DRIVE ERROR: {repr(ex)[:300]}", flush=True)

os.unlink(APP_PATH)
print("\n=== DONE ===", flush=True)
