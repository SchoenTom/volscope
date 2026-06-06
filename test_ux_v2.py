"""
Improved headless UX test — injects DB via session state before run.
Streamlit AppTest re-imports the module so monkey-patching doesn't work.
Instead we use a patched version of the app that reads from session state.
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

from streamlit.testing.v1 import AppTest

# Write a thin wrapper app that patches get_db to use read_only=True
WRAPPER_PATH = "/tmp/vs_test_app.py"
with open(WRAPPER_PATH, "w") as f:
    f.write('''
import sys
sys.path.insert(0, "/Users/tomschoen/dev/VolScope")

# Patch get_db before importing app logic
import streamlit as st
from volscope.data.database import VolScopeDB

@st.cache_resource
def get_db():
    return VolScopeDB(read_only=True)

# Inject the patched get_db into the app module namespace
import volscope.ui.app as _app
_app.get_db = get_db

# Now run main
_app.main()
''')


def load_page(page, ticker="AAPL"):
    at = AppTest.from_file(WRAPPER_PATH, default_timeout=HARD_TIMEOUT - 5)
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

print("\nMARKDOWN KEY ENTRIES (non-style/script, first 200 chars):", flush=True)
for i, m in enumerate(at.markdown):
    v = m.value.strip()
    if v and len(v) > 3 and not v.startswith('<style>') and not v.startswith('<script>'):
        print(f"  [MD {i}] '{v[:200]}'", flush=True)

print("\nDONE", flush=True)
