"""Install a macOS launchd job that runs check_alarms.py every 30 min.

Operator feedback 2026-05-19: "erhalte ich auch Benachrichtigungen
wenn VolScope aus ist?" — yes IF this scheduler is installed.

Behaviour:
  - Plist registered at ~/Library/LaunchAgents/com.volscope.alarms.plist
  - Runs every 1800 s (30 min)
  - The script itself (`check_alarms.py`) gates on NYSE business
    hours (09-21 NY time, weekdays). Outside those hours it logs and
    exits early. So the launchd cadence can be aggressive without
    spamming the operator.
  - Logs to ~/.claude/volscope-cron-logs/alarms.log

Uninstall: ``make unschedule-alerts``.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
PLIST_PATH = Path.home() / "Library" / "LaunchAgents" / "com.volscope.alarms.plist"
LOG_DIR = Path.home() / ".claude" / "volscope-cron-logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)
LOG_FILE = LOG_DIR / "alarms.log"

PY = REPO_ROOT / ".venv" / "bin" / "python"
CHECK_SCRIPT = REPO_ROOT / "scripts" / "ops" / "check_alarms.py"


def render_plist() -> str:
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.volscope.alarms</string>

    <key>ProgramArguments</key>
    <array>
        <string>{PY}</string>
        <string>{CHECK_SCRIPT}</string>
        <string>--quiet</string>
    </array>

    <key>WorkingDirectory</key>
    <string>{REPO_ROOT}</string>

    <key>StartInterval</key>
    <integer>1800</integer>

    <key>StandardOutPath</key>
    <string>{LOG_FILE}</string>

    <key>StandardErrorPath</key>
    <string>{LOG_FILE}</string>

    <key>RunAtLoad</key>
    <true/>

    <key>EnvironmentVariables</key>
    <dict>
        <key>PYTHONUNBUFFERED</key>
        <string>1</string>
    </dict>
</dict>
</plist>
"""


def main() -> int:
    if not PY.exists():
        print(f"✗ Python venv not found at {PY}.")
        print("  Run `python3 -m venv .venv && pip install -e .` first.")
        return 1
    if not CHECK_SCRIPT.exists():
        print(f"✗ check_alarms.py not found at {CHECK_SCRIPT}.")
        return 1

    # Unload any previous instance (idempotent)
    subprocess.run(
        ["launchctl", "unload", str(PLIST_PATH)],
        check=False, capture_output=True,
    )

    PLIST_PATH.parent.mkdir(parents=True, exist_ok=True)
    PLIST_PATH.write_text(render_plist())
    os.chmod(PLIST_PATH, 0o644)

    rc = subprocess.run(
        ["launchctl", "load", str(PLIST_PATH)],
        capture_output=True, text=True,
    )
    if rc.returncode != 0:
        print(f"✗ launchctl load failed: {rc.stderr.strip()}")
        return rc.returncode

    print(f"✓ VolScope alarm scheduler installed.")
    print(f"   Plist : {PLIST_PATH}")
    print(f"   Logs  : {LOG_FILE}")
    print(f"   Runs  : every 30 min (gated on NYSE hours by the script).")
    print(f"   Stop  : make unschedule-alerts")
    return 0


if __name__ == "__main__":
    sys.exit(main())
