"""
Fast headless UX test - single load per page, no re-runs.
"""
import time
import sys
sys.path.insert(0, '/Users/tomschoen/dev/VolScope')

from streamlit.testing.v1 import AppTest


def load_page(page, ticker="AAPL", timeout=120):
    at = AppTest.from_file(
        "/Users/tomschoen/dev/VolScope/volscope/ui/app.py",
        default_timeout=timeout,
    )
    at.session_state["selected_ticker"] = ticker
    at.session_state["active_page"] = page
    at.session_state["onboarding_complete"] = True
    at.session_state["onboarding_dismissed"] = True
    t0 = time.time()
    at.run()
    dt = time.time() - t0
    return at, dt


PAGE = sys.argv[1] if len(sys.argv) > 1 else "Discover"
TICKER = sys.argv[2] if len(sys.argv) > 2 else "AAPL"

print(f"Testing page: {PAGE}, ticker: {TICKER}")
at, secs = load_page(PAGE, ticker=TICKER)

print(f"LOAD_SECS={secs:.2f}")
print(f"EXCEPTIONS={[str(e.value)[:300] for e in at.exception]}")
print(f"BUTTON_COUNT={len(at.button)}")
print(f"SELECTBOX_COUNT={len(at.selectbox)}")
print(f"TOGGLE_COUNT={len(at.toggle)}")
print(f"RADIO_COUNT={len(at.radio)}")
print(f"SLIDER_COUNT={len(at.slider)}")

print("\nBUTTONS:")
for i, b in enumerate(at.button):
    print(f"  [{i}] '{b.label}'")

print("\nRADIOS:")
for i, r in enumerate(at.radio):
    print(f"  [{i}] label='{r.label}' options={r.options} value={r.value}")

print("\nSELECTBOXES:")
for i, s in enumerate(at.selectbox):
    print(f"  [{i}] label='{s.label}' options_count={len(s.options) if s.options else 0}")

print("\nTOGGLES:")
for i, t in enumerate(at.toggle):
    print(f"  [{i}] '{t.label}' value={t.value}")

print("\nCAP TIONS:")
for c in at.caption:
    print(f"  '{c.value[:200]}'")

print("\nINFO BOXES:")
for info in at.info:
    print(f"  '{info.value[:400]}'")

print("\nWARNINGS:")
for w in at.warning:
    print(f"  '{w.value[:300]}'")

print("\nSUCCESS:")
for s in at.success:
    print(f"  '{s.value[:200]}'")

print("\nMARKDOWN (short entries, up to 50 chars each):")
for m in at.markdown:
    v = m.value.strip()
    if v:
        print(f"  '{v[:80]}'")

print("\nDONE")
