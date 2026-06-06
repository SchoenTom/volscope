"""
Headless UX test for Discover page.
Measures load time, exceptions, button interactions, jargon presence.
"""
import time
import sys
sys.path.insert(0, '/Users/tomschoen/dev/VolScope')

from streamlit.testing.v1 import AppTest


def load_page(page, ticker="AAPL", timeout=90):
    at = AppTest.from_file(
        "/Users/tomschoen/dev/VolScope/volscope/ui/app.py",
        default_timeout=timeout,
    )
    at.session_state["selected_ticker"] = ticker
    at.session_state["active_page"] = page
    t0 = time.time()
    at.run()
    dt = time.time() - t0
    return at, dt


print("=" * 60)
print("DISCOVER PAGE TEST")
print("=" * 60)

at, secs = load_page("Discover")
print(f"Load time: {secs:.1f}s")
print(f"Exceptions on load: {[e.value for e in at.exception]}")
print(f"Button count: {len(at.button)}")
print(f"Selectbox count: {len(at.selectbox)}")
print(f"Toggle count: {len(at.toggle)}")
print(f"Tab count: {len(at.tabs) if hasattr(at, 'tabs') else 'N/A'}")

# List all button labels
print("\nButtons found:")
for i, b in enumerate(at.button):
    print(f"  [{i}] '{b.label}'")

# List all markdowns for jargon check
print("\nMarkdown content preview (first 2000 chars):")
all_md = " ".join([m.value for m in at.markdown])
print(all_md[:2000])

# Check for jargon
jargon_terms = ["IVR", "IVP", "VRP", "HV", "skew", "contango", "backwardation",
                "iv_30d", "iv_percentile", "put_call_ratio", "crowded_score",
                "IV Percentile", "IV Rank", "iv_rank", "edge score", "Edge Score",
                "PERC", "SPREAD", "CROWD"]
print("\nJargon check:")
for term in jargon_terms:
    # Check in markdown + captions
    all_text = " ".join([m.value for m in at.markdown])
    if term.lower() in all_text.lower():
        print(f"  JARGON PRESENT: '{term}'")

# Check captions
print("\nCaption text:")
for c in at.caption:
    print(f"  '{c.value}'")

# Check info/warning/error messages
print("\nInfo boxes:")
for info in at.info:
    print(f"  '{info.value[:200]}'")

print("\nWarning boxes:")
for w in at.warning:
    print(f"  '{w.value[:200]}'")

# Now click buttons one by one
print("\n--- Button click test ---")
for i, b in enumerate(at.button):
    label = b.label
    try:
        b.click().run()
        exceptions = [str(e.value) for e in at.exception]
        if exceptions:
            print(f"  BUTTON[{i}] '{label}' -> EXCEPTION: {exceptions}")
        else:
            print(f"  BUTTON[{i}] '{label}' -> OK")
    except Exception as ex:
        print(f"  BUTTON[{i}] '{label}' -> DRIVE ERROR: {repr(ex)[:200]}")
    # Reset after each click to keep state clean
    at2, _ = load_page("Discover")
    at = at2

print("\n--- Toggle test ---")
for i, toggle in enumerate(at.toggle):
    print(f"  Toggle[{i}] label='{toggle.label}' value={toggle.value}")
    try:
        toggle.set_value(not toggle.value).run()
        exceptions = [str(e.value) for e in at.exception]
        if exceptions:
            print(f"    -> After toggle: EXCEPTION: {exceptions[:2]}")
        else:
            print(f"    -> After toggle: OK")
    except Exception as ex:
        print(f"    -> DRIVE ERROR: {repr(ex)[:200]}")
    at, _ = load_page("Discover")

print("\nDISCOVER DONE")
