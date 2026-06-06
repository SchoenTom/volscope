"""
Run a page test with a hard python-level timeout.
"""
import signal
import sys
import time

sys.path.insert(0, '/Users/tomschoen/dev/VolScope')

PAGE = sys.argv[1] if len(sys.argv) > 1 else "Discover"
TICKER = sys.argv[2] if len(sys.argv) > 2 else "AAPL"
HARD_TIMEOUT = int(sys.argv[3]) if len(sys.argv) > 3 else 75


def handler(sig, frame):
    print("TIMEOUT_KILLED", flush=True)
    sys.exit(0)


signal.signal(signal.SIGALRM, handler)
signal.alarm(HARD_TIMEOUT)

from streamlit.testing.v1 import AppTest  # noqa: E402


def load_page(page, ticker="AAPL"):
    at = AppTest.from_file(
        "/Users/tomschoen/dev/VolScope/volscope/ui/app.py",
        default_timeout=70,
    )
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

signal.alarm(0)  # cancel alarm

print(f"LOAD_SECS={secs:.2f}", flush=True)
print(f"EXCEPTIONS={[str(e.value)[:300] for e in at.exception]}", flush=True)
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

print("\nSUCCESS:", flush=True)
for s in at.success:
    print(f"  '{s.value[:200]}'", flush=True)

print("\nMARKDOWN (non-empty, up to 100 chars each):", flush=True)
for m in at.markdown:
    v = m.value.strip()
    if v and len(v) > 3:
        print(f"  '{v[:100]}'", flush=True)

print("\nDONE", flush=True)
