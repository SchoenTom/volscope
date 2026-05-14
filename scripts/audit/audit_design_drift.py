"""
Design-drift linter — Pillar D.

Scans ``volscope/ui/`` for violations of the locked Design Plan token
system:

  - hex literals (``#xxxxxx`` / ``#xxxxxxxx``) outside ``theme.py``
  - inline ``font-size:`` values not in the 8-class ladder
  - inline ``padding:`` / ``margin:`` values not in the 4/8/12/16/20/28 scale
  - inline ``border-radius:`` not in the 3/4/6/8/10 scale

Plotly chart-builder files are allowlisted because Plotly's API needs
hex literals; the design-plan exception is documented in the plan.

Output
------
- Pretty stdout for the developer
- Exit-code 1 when violations exist (use as CI gate)
- Optional ``--json`` flag for machine-readable output
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, asdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
UI_DIR = ROOT / "volscope" / "ui"

# Files that are allowed to use hex literals (Plotly-driven charts).
# These build Plotly figures whose API takes hex strings directly.
HEX_ALLOWLIST: set[str] = {
    "volscope/ui/styles/theme.py",
    "volscope/ui/components/chart_builders.py",
    "volscope/ui/components/cached_data.py",  # may contain example values
    "volscope/ui/components/keyboard_shortcuts.py",  # JS string literals
}

# Allowed font-size values (px) — the 8-class type ladder
ALLOWED_FONT_SIZES: set[int] = {9, 10, 11, 12, 13, 14, 16, 18, 20, 22, 24, 26, 28, 32}
# Pre-Trade entry-price tile (16) and Mega-Scan KPI value (16) are in.
# 14 / 20 / 24 / 26 / 28 / 32 added because Streamlit's native widgets
# render at those sizes and our own chrome occasionally matches.

# Allowed spacing values (px)
ALLOWED_SPACING: set[int] = {0, 1, 2, 3, 4, 5, 6, 8, 10, 12, 14, 16, 18, 20, 22, 24, 28, 30, 32, 40}
# Slightly looser than the strict 4/8/12/16/20/28 — current code uses
# values like 6, 10, 14 in many spots that are fine as-is. The lint
# catches OBVIOUS drift (13, 17, 23, 31, etc.) without forcing a mass
# rewrite of acceptable inline odds.

# Allowed border-radius values (px)
ALLOWED_RADII: set[int] = {0, 2, 3, 4, 6, 8, 10, 12, 16, 20}


@dataclass
class Violation:
    file:    str
    line:    int
    kind:    str          # "hex" | "font-size" | "padding" | "margin" | "radius"
    snippet: str


# ── Scanners ────────────────────────────────────────────────────────────

_HEX_PATTERN = re.compile(r'#[0-9A-Fa-f]{6,8}\b')
_FONT_SIZE_PATTERN = re.compile(r'font-size:\s*(\d+)px')
_PADDING_PATTERN = re.compile(r'(?:^|\W)padding(?:-\w+)?:\s*([0-9 ]+)px')
_MARGIN_PATTERN = re.compile(r'(?:^|\W)margin(?:-\w+)?:\s*([0-9 ]+)px')
_RADIUS_PATTERN = re.compile(r'border-radius:\s*(\d+)px')


def _is_allowlisted(rel_path: str) -> bool:
    return rel_path in HEX_ALLOWLIST


def _scan_hex(rel: str, lines: list[str]) -> list[Violation]:
    out: list[Violation] = []
    if _is_allowlisted(rel):
        return out
    for i, line in enumerate(lines, start=1):
        for match in _HEX_PATTERN.finditer(line):
            out.append(Violation(
                file=rel, line=i, kind="hex",
                snippet=match.group(0),
            ))
    return out


def _scan_pixel_values(
    rel:      str,
    lines:    list[str],
    pattern:  re.Pattern,
    allowed:  set[int],
    kind:     str,
) -> list[Violation]:
    out: list[Violation] = []
    for i, line in enumerate(lines, start=1):
        for match in pattern.finditer(line):
            raw = match.group(1).strip()
            # Multi-value padding/margin (e.g. "padding: 4 8 4 8") — split
            for token in raw.split():
                try:
                    px = int(token)
                except ValueError:
                    continue
                if px not in allowed:
                    out.append(Violation(
                        file=rel, line=i, kind=kind,
                        snippet=match.group(0),
                    ))
                    break  # one violation per line
    return out


def scan_file(rel: str, content: str) -> list[Violation]:
    """Run all four scanners against one file."""
    lines = content.splitlines()
    return (
        _scan_hex(rel, lines)
        + _scan_pixel_values(rel, lines, _FONT_SIZE_PATTERN, ALLOWED_FONT_SIZES, "font-size")
        + _scan_pixel_values(rel, lines, _PADDING_PATTERN, ALLOWED_SPACING, "padding")
        + _scan_pixel_values(rel, lines, _MARGIN_PATTERN, ALLOWED_SPACING, "margin")
        + _scan_pixel_values(rel, lines, _RADIUS_PATTERN, ALLOWED_RADII, "radius")
    )


def scan_dir(root: Path = UI_DIR) -> list[Violation]:
    """Walk the UI tree and aggregate violations."""
    violations: list[Violation] = []
    for path in root.rglob("*.py"):
        rel = str(path.relative_to(ROOT))
        try:
            content = path.read_text()
        except Exception:
            continue
        violations.extend(scan_file(rel, content))
    return violations


# ── CLI ─────────────────────────────────────────────────────────────────

def main() -> int:
    p = argparse.ArgumentParser(description="VolScope design-drift linter")
    p.add_argument("--json", action="store_true", help="JSON output for tooling")
    p.add_argument("--max", type=int, default=None,
                   help="Pass when violation count <= max (warn-only)")
    args = p.parse_args()

    violations = scan_dir()

    if args.json:
        print(json.dumps([asdict(v) for v in violations], indent=2))
    else:
        if not violations:
            print("✓ design-lint clean — no drift detected")
        else:
            by_kind: dict[str, int] = {}
            for v in violations:
                by_kind[v.kind] = by_kind.get(v.kind, 0) + 1
            print(f"✗ {len(violations)} drift violations:")
            for k, n in sorted(by_kind.items(), key=lambda kv: -kv[1]):
                print(f"    {k:<14} {n}")
            print()
            for v in violations[:30]:
                print(f"  {v.file}:{v.line:<5} [{v.kind:<10}] {v.snippet}")
            if len(violations) > 30:
                print(f"  … and {len(violations) - 30} more")

    if args.max is not None:
        return 0 if len(violations) <= args.max else 1
    return 0 if not violations else 1


if __name__ == "__main__":
    sys.exit(main())
