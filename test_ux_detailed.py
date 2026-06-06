"""
Detailed test — dump full markdown and state to diagnose what's happening.
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

signal.alarm(0)

print(f"LOAD_SECS={secs:.2f}", flush=True)
print(f"EXCEPTIONS={[str(e.value)[:500] for e in at.exception]}", flush=True)
print(f"BUTTON_COUNT={len(at.button)}", flush=True)

print("\n=== ALL MARKDOWN (full) ===", flush=True)
for i, m in enumerate(at.markdown):
    v = m.value.strip()
    if v:
        print(f"\n[MD {i}] {v[:2000]}", flush=True)

print("\n=== SESSION STATE (selected keys) ===", flush=True)
ss = at.session_state
for k in ["active_page", "selected_ticker", "onboarding_complete", "vs_db_readonly_reason"]:
    print(f"  {k}={ss.get(k, 'NOT SET')}", flush=True)

print("\nDONE", flush=True)
