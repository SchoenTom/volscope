#!/bin/bash
# VolScope launch logic — invoked by VolScope.app (an AppleScript applet whose
# real Mach-O executable macOS launches reliably on a double-click, which a
# plain shell-script .app does not). Sets up a private Python environment on
# first launch, starts the local server, and opens VolScope in a clean window.
set -u

PORT=8501
URL="http://127.0.0.1:${PORT}"
HEALTH="${URL}/_stcore/health"

# This script lives at <REPO>/scripts/ops/launch_app.sh
SELF="$0"
while [ -h "$SELF" ]; do SELF="$(readlink "$SELF")"; done
REPO="$(cd "$(dirname "$SELF")/../.." && pwd)"
APP_DIR="$REPO/VolScope.app"
RES_DIR="$APP_DIR/Contents/Resources"

LOG_DIR="$HOME/Library/Logs/VolScope"
mkdir -p "$LOG_DIR"
SETUP_LOG="$LOG_DIR/setup.log"
SERVER_LOG="$LOG_DIR/server.log"

VENV="$REPO/.venv"
STREAMLIT="$VENV/bin/streamlit"
APP_PY="$REPO/volscope/ui/app.py"

notify() { osascript -e "display notification \"$1\" with title \"VolScope\"" >/dev/null 2>&1 || true; }
alertbox() { osascript -e "display dialog \"$1\" with title \"VolScope\" buttons {\"OK\"} default button \"OK\" with icon caution" >/dev/null 2>&1 || true; }

# ── Self-heal the download so re-launches stay smooth ──────────────────
chmod -R +x "$APP_DIR/Contents/MacOS" 2>/dev/null || true
xattr -cr "$APP_DIR" 2>/dev/null || true
codesign --force --deep --sign - "$APP_DIR" 2>/dev/null || true

if [ ! -f "$APP_PY" ]; then
  alertbox "VolScope couldn't find its program files. Please keep VolScope.app inside the VolScope folder you downloaded, then open it again."
  exit 1
fi

open_window() {
  local target="$1" b
  for b in "Google Chrome" "Brave Browser" "Microsoft Edge" "Chromium"; do
    if [ -d "/Applications/$b.app" ]; then
      open -na "$b" --args --app="$target" >/dev/null 2>&1 && return 0
    fi
  done
  open "$target" >/dev/null 2>&1
}

[ -f "$RES_DIR/splash.html" ] && open_window "file://$RES_DIR/splash.html"

# Already running? The splash (or default browser) lands the user there.
if curl -sf "$HEALTH" >/dev/null 2>&1; then
  [ -f "$RES_DIR/splash.html" ] || open_window "$URL"
  exit 0
fi

_py_ok() { "$1" -c 'import sys; raise SystemExit(0 if sys.version_info[:2] >= (3, 11) else 1)' 2>/dev/null; }

find_python() {
  # When launched from Finder (the .app icon), $PATH is the minimal launchd
  # one — it does NOT include Homebrew / Anaconda / python.org. So search the
  # PATH first, then the common install locations explicitly, so the icon
  # finds the same Python the user's Terminal would.
  local c d p names dirs
  names="python3.13 python3.12 python3.11 python3"
  for c in $names; do
    p="$(command -v "$c" 2>/dev/null)" || continue
    _py_ok "$p" && { echo "$p"; return 0; }
  done
  dirs="/opt/homebrew/bin /usr/local/bin /opt/anaconda3/bin \
        $HOME/anaconda3/bin $HOME/miniconda3/bin $HOME/miniforge3/bin \
        /Library/Frameworks/Python.framework/Versions/3.13/bin \
        /Library/Frameworks/Python.framework/Versions/3.12/bin \
        /Library/Frameworks/Python.framework/Versions/3.11/bin"
  for d in $dirs; do
    for c in $names; do
      p="$d/$c"
      [ -x "$p" ] && _py_ok "$p" && { echo "$p"; return 0; }
    done
  done
  return 1
}

# ── First launch: build the private environment (all wheels, no compiler) ─
if [ ! -x "$STREAMLIT" ]; then
  notify "Setting up VolScope — about 2 minutes (one time only)…"
  PY="$(find_python)"
  if [ -z "${PY:-}" ]; then
    alertbox "VolScope needs Python 3.11 or newer. Install it from python.org, then open VolScope again."
    exit 1
  fi
  {
    echo "== $(date) VolScope setup =="
    "$PY" -m venv "$VENV"
    VSITE="$("$VENV/bin/python" -c 'import site; print(site.getsitepackages()[0])' 2>/dev/null)"
    if [ -n "$VSITE" ]; then
      printf '%s\n' \
        'import sys as _s' \
        'if "Anaconda" in _s.version and _s.version.count("|") >= 2:' \
        '    _p = _s.version.split("|")' \
        '    if len(_p) >= 3:' \
        '        try: _s.version = _p[0].strip() + " " + " ".join(x.strip() for x in _p[2:])' \
        '        except Exception: pass' \
        > "$VSITE/sitecustomize.py"
    fi
    "$VENV/bin/python" -m pip install --upgrade pip
    "$VENV/bin/python" -m pip install -r "$REPO/requirements.txt"
  } >>"$SETUP_LOG" 2>&1
  if [ ! -x "$STREAMLIT" ]; then
    alertbox "Setup didn't finish. Details are in: ~/Library/Logs/VolScope/setup.log"
    exit 1
  fi
  notify "Fetching starter market data…"
  ( cd "$REPO" && PYTHONPATH="$REPO" "$VENV/bin/python" scripts/ops/seed_database.py \
      --tickers SPY,QQQ,AAPL,NVDA,TSLA,META,GLD,TLT ) >>"$SETUP_LOG" 2>&1 &
  SEED_PID=$!
  ( sleep 120; kill "$SEED_PID" >/dev/null 2>&1 ) >/dev/null 2>&1 &
  wait "$SEED_PID" 2>/dev/null || true
  notify "VolScope is ready."
fi

# ── Start the server, detached (nohup) so it survives the applet returning. ─
cd "$REPO" || exit 1
PYTHONPATH="$REPO" nohup "$STREAMLIT" run "$APP_PY" \
  --server.headless true \
  --server.port "$PORT" \
  --server.address 127.0.0.1 \
  --browser.gatherUsageStats false \
  </dev/null >>"$SERVER_LOG" 2>&1 &
disown 2>/dev/null || true
# The splash window polls the health endpoint and switches itself to VolScope.
exit 0
