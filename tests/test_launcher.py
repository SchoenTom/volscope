"""Integrity guards for the macOS VolScope.app launcher.

The launcher is what turns VolScope into a double-click app for non-technical
users. If a refactor renames the seed script, moves app.py, or breaks the
bootstrap's shell syntax, the app silently fails to open — these tests fail
loudly instead.
"""
from __future__ import annotations

import plistlib
import shutil
import subprocess
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
_APP = _ROOT / "VolScope.app"
_BOOT = _APP / "Contents" / "MacOS" / "VolScope"
_PLIST = _APP / "Contents" / "Info.plist"
_ICNS = _APP / "Contents" / "Resources" / "VolScope.icns"
_SPLASH = _APP / "Contents" / "Resources" / "splash.html"


def test_bundle_files_exist():
    for p in (_BOOT, _PLIST, _ICNS, _SPLASH):
        assert p.exists(), f"missing launcher file: {p.relative_to(_ROOT)}"


def test_info_plist_valid_and_points_at_bootstrap():
    with _PLIST.open("rb") as fh:
        meta = plistlib.load(fh)
    assert meta["CFBundleExecutable"] == "VolScope"
    assert meta["CFBundleIdentifier"] == "com.volscope.app"
    # The icon file the plist names must exist (".icns" optional in the key).
    icon = meta["CFBundleIconFile"]
    assert (_APP / "Contents" / "Resources" / icon).with_suffix(".icns").exists()


@pytest.mark.skipif(shutil.which("bash") is None, reason="bash not available")
def test_bootstrap_shell_syntax_is_valid():
    res = subprocess.run(["bash", "-n", str(_BOOT)], capture_output=True, text=True)
    assert res.returncode == 0, res.stderr


def test_bootstrap_references_real_paths():
    text = _BOOT.read_text()
    # The things the bootstrap drives must actually exist in the repo.
    assert (_ROOT / "volscope" / "ui" / "app.py").exists()
    assert "volscope/ui/app.py" in text
    assert (_ROOT / "scripts" / "ops" / "seed_database.py").exists()
    assert "scripts/ops/seed_database.py" in text
    assert (_ROOT / "requirements.txt").exists()
    # Must launch headless with no stdin prompt (the documented hang fix).
    assert "--server.headless true" in text
    assert "</dev/null" in text


def test_splash_targets_the_health_endpoint():
    html = _SPLASH.read_text()
    assert "_stcore/health" in html
    assert "127.0.0.1:8501" in html
