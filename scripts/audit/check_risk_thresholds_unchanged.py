"""
CI guard — fail any PR that mutates `config/risk-thresholds.yaml`
without an `OPERATOR_APPROVED=yes` trailer in the commit message.

The committed reference hash lives at
`config/.risk-thresholds.sha256`. To rotate (after an operator-approved
change):

    sha256sum config/risk-thresholds.yaml | cut -d' ' -f1 > config/.risk-thresholds.sha256

Exit codes:
    0 — file unchanged OR change authorised
    1 — file changed AND no operator approval
    2 — required files missing
"""
from __future__ import annotations

import hashlib
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
THRESHOLDS_PATH = REPO_ROOT / "config" / "risk-thresholds.yaml"
REF_PATH = REPO_ROOT / "config" / ".risk-thresholds.sha256"


def _sha256_of_file(path: Path) -> str:
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()


def _last_commit_message() -> str:
    """Read HEAD's commit message (used to look for the approval trailer)."""
    try:
        out = subprocess.check_output(
            ["git", "log", "-1", "--pretty=%B"],
            cwd=str(REPO_ROOT), text=True,
        )
        return out
    except Exception:                              # noqa: BLE001
        return ""


def main() -> int:
    if not THRESHOLDS_PATH.is_file():
        print(f"missing: {THRESHOLDS_PATH}", file=sys.stderr)
        return 2
    if not REF_PATH.is_file():
        print(
            f"missing reference at {REF_PATH}. Initialise with:\n"
            f"  sha256sum {THRESHOLDS_PATH.relative_to(REPO_ROOT)} | "
            f"cut -d' ' -f1 > {REF_PATH.relative_to(REPO_ROOT)}",
            file=sys.stderr,
        )
        return 2

    expected = REF_PATH.read_text().strip()
    actual = _sha256_of_file(THRESHOLDS_PATH)
    if actual == expected:
        print(f"risk-thresholds unchanged (sha={actual[:8]}...)")
        return 0

    msg = _last_commit_message()
    if "OPERATOR_APPROVED=yes" in msg or os.environ.get("OPERATOR_APPROVED") == "yes":
        print(f"risk-thresholds changed but OPERATOR_APPROVED — allowed (sha={actual[:8]})")
        # Auto-rotate the reference so subsequent CI runs are clean.
        REF_PATH.write_text(actual + "\n")
        return 0

    print(
        f"❌ risk-thresholds.yaml changed without operator approval.\n"
        f"   expected sha:  {expected}\n"
        f"   actual sha:    {actual}\n"
        f"   To approve: add 'OPERATOR_APPROVED=yes' trailer to the commit "
        f"message OR set OPERATOR_APPROVED=yes in env.",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
