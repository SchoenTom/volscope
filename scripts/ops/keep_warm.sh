#!/usr/bin/env bash
# Touch every .py file in the project so iCloud File Provider keeps
# the bytecode locally instead of evicting after idle.
#
# Run before `make run` if the app has been idle for > 30 min. The
# real fix is to mark the directory "Keep Downloaded" in Finder, but
# this is the band-aid that doesn't require macOS-level settings.

PROJECT="$(cd "$(dirname "$0")/.." && pwd)"
echo "Pre-warming iCloud cache for $PROJECT…"
COUNT=$(find "$PROJECT" -name "*.py" -not -path "*/.venv/*" | wc -l | tr -d ' ')
START=$SECONDS

# `head -c 1` triggers iCloud File Provider to materialise the file
# locally without dumping content. Faster than `cat`.
find "$PROJECT" -name "*.py" -not -path "*/.venv/*" \
    -exec head -c 1 {} \; > /dev/null

# Also warm the venv site-packages — numpy etc. are huge and live here.
if [ -d "$PROJECT/.venv/lib" ]; then
  find "$PROJECT/.venv/lib" \( -name "*.py" -o -name "*.so" \) \
      -exec head -c 1 {} \; > /dev/null 2>&1
fi

echo "✓ Warmed $COUNT project files in $((SECONDS - START))s"
echo
echo "Tip: for permanent fix, right-click the VolScope folder in"
echo "Finder → 'Keep Downloaded' or move the project to ~/dev/."
