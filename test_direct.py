"""
Direct render test — bypasses the app.py entry point and calls render functions
directly with a real read-only DB opened outside Streamlit's cache.
"""
import signal
import sys
import time
import os

sys.path.insert(0, '/Users/tomschoen/dev/VolScope')

PAGE = sys.argv[1] if len(sys.argv) > 1 else "Discover"
TICKER = sys.argv[2] if len(sys.argv) > 2 else "AAPL"
HARD_TIMEOUT = int(sys.argv[3]) if len(sys.argv) > 3 else 120


def handler(sig, frame):
    print("TIMEOUT_KILLED", flush=True)
    sys.exit(0)


signal.signal(signal.SIGALRM, handler)
signal.alarm(HARD_TIMEOUT)

# Build a tiny app file that opens DB outside of the app's cache mechanism
APP_CODE = f"""
import sys
sys.path.insert(0, "/Users/tomschoen/dev/VolScope")

import streamlit as st

# Open the DB directly, bypassing app.py's get_db()
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

# Route to page
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

import tempfile
tmpfile = tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False)
tmpfile.write(APP_CODE)
tmpfile.close()
APP_PATH = tmpfile.name

from streamlit.testing.v1 import AppTest  # noqa: E402


def load_page(page, ticker="AAPL"):
    at = AppTest.from_file(APP_PATH, default_timeout=HARD_TIMEOUT - 5)
    at.session_state["selected_ticker"] = ticker
    at.session_state["active_page"] = page
    at.session_state["onboarding_complete"] = True
    at.session_state["onboarding_dismissed"] = True
    t0 = time.time()
    at.run()
    dt = time.time() - t0
    return at, dt


print(f"Testing page: {PAGE}, ticker: {TICKER}", flush=True)
at, secs = load_page(PAGE, ticker=TICKER)

signal.alarm(0)

print(f"LOAD_SECS={secs:.2f}", flush=True)
print(f"EXCEPTIONS={[str(e.value)[:500] for e in at.exception]}", flush=True)
print(f"BUTTON_COUNT={len(at.button)}", flush=True)
print(f"SELECTBOX_COUNT={len(at.selectbox)}", flush=True)
print(f"TOGGLE_COUNT={len(at.toggle)}", flush=True)
print(f"RADIO_COUNT={len(at.radio)}", flush=True)
print(f"SLIDER_COUNT={len(at.slider)}", flush=True)

print("\nBUTTONS:", flush=True)
for i, b in enumerate(at.button):
    print(f"  [{i}] '{b.label}'", flush=True)

print("\nRADIOS:", flush=True)
for i, r in enumerate(at.radio):
    print(f"  [{i}] label='{r.label}' options={r.options} value={r.value}", flush=True)

print("\nSELECTBOXES:", flush=True)
for i, s in enumerate(at.selectbox):
    print(f"  [{i}] label='{s.label}' options_count={len(s.options) if s.options else 0}", flush=True)

print("\nTOGGLES:", flush=True)
for i, t in enumerate(at.toggle):
    print(f"  [{i}] '{t.label}' value={t.value}", flush=True)

print("\nCAPTIONS:", flush=True)
for c in at.caption:
    print(f"  '{c.value[:200]}'", flush=True)

print("\nINFO BOXES:", flush=True)
for info in at.info:
    print(f"  '{info.value[:400]}'", flush=True)

print("\nWARNINGS:", flush=True)
for w in at.warning:
    print(f"  '{w.value[:300]}'", flush=True)

print("\nERRORS:", flush=True)
for e in at.error:
    print(f"  '{e.value[:300]}'", flush=True)

print("\nSUCCESS:", flush=True)
for s in at.success:
    print(f"  '{s.value[:200]}'", flush=True)

# Key MD entries (skip style/script)
print("\nKEY MARKDOWN (non-style/script):", flush=True)
for i, m in enumerate(at.markdown):
    v = m.value.strip()
    if v and len(v) > 10 and not v.startswith('<style>') and not v.startswith('<script>'):
        print(f"  [MD {i}] '{v[:200]}'", flush=True)

os.unlink(APP_PATH)
print("\nDONE", flush=True)
