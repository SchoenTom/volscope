"""Integrity guards for the macOS VolScope launcher.

VolScope.app is an AppleScript applet (a real Mach-O executable that macOS
launches reliably — a plain shell-script .app fails with a "(null)" error).
Its launch logic lives in scripts/ops/launch_app.sh. These tests fail loudly
if a refactor breaks the bundle structure or the paths the launcher drives.
"""
from __future__ import annotations

import plistlib
import shutil
import subprocess
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
_APP = _ROOT / "VolScope.app"
_EXEC = _APP / "Contents" / "MacOS" / "applet"
_PLIST = _APP / "Contents" / "Info.plist"
_ICON = _APP / "Contents" / "Resources" / "applet.icns"
_SPLASH = _APP / "Contents" / "Resources" / "splash.html"
_SCPT = _APP / "Contents" / "Resources" / "Scripts" / "main.scpt"
_LAUNCH = _ROOT / "scripts" / "ops" / "launch_app.sh"
_COMMAND = _ROOT / "Start VolScope.command"

_MACHO_MAGICS = {
    b"\xca\xfe\xba\xbe",  # universal (fat) binary
    b"\xcf\xfa\xed\xfe",  # 64-bit little-endian
    b"\xfe\xed\xfa\xcf",  # 64-bit big-endian
}


def test_bundle_files_exist():
    for p in (_EXEC, _PLIST, _ICON, _SPLASH, _SCPT, _LAUNCH, _COMMAND):
        assert p.exists(), f"missing launcher file: {p.relative_to(_ROOT)}"


def test_app_executable_is_a_macho_binary():
    # The whole point of the applet: a real launchable executable, not a script.
    with _EXEC.open("rb") as fh:
        magic = fh.read(4)
    assert magic in _MACHO_MAGICS, f"applet is not a Mach-O binary (magic={magic!r})"


def test_info_plist_points_at_the_applet():
    with _PLIST.open("rb") as fh:
        meta = plistlib.load(fh)
    assert meta["CFBundleExecutable"] == "applet"
    assert meta["CFBundleIdentifier"] == "com.volscope.app"
    assert meta["CFBundleName"] == "VolScope"


@pytest.mark.skipif(shutil.which("bash") is None, reason="bash not available")
def test_launch_script_shell_syntax_is_valid():
    res = subprocess.run(["bash", "-n", str(_LAUNCH)], capture_output=True, text=True)
    assert res.returncode == 0, res.stderr
    res2 = subprocess.run(["bash", "-n", str(_COMMAND)], capture_output=True, text=True)
    assert res2.returncode == 0, res2.stderr


def test_launch_script_references_real_paths():
    text = _LAUNCH.read_text()
    assert (_ROOT / "volscope" / "ui" / "app.py").exists()
    assert "volscope/ui/app.py" in text
    assert (_ROOT / "scripts" / "ops" / "seed_database.py").exists()
    assert "scripts/ops/seed_database.py" in text
    assert (_ROOT / "requirements.txt").exists()
    assert "--server.headless true" in text
    assert "</dev/null" in text
    # The first-run launcher must call the launch logic.
    assert "scripts/ops/launch_app.sh" in _COMMAND.read_text()


def test_splash_targets_the_health_endpoint():
    html = _SPLASH.read_text()
    assert "_stcore/health" in html
    assert "127.0.0.1:8501" in html
