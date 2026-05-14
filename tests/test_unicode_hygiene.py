"""
Unicode hygiene regression test.

Certain Unicode characters render as tofu boxes (missing glyph) in many
system fonts — especially the CJK-range `＋` (FULLWIDTH PLUS, U+FF0B) and
other fullwidth variants. Users see a square instead of the intended
character, which makes the UI look broken.

This test pins the invariant: no UI source file may use a fullwidth-form
character or other known-problematic codepoints in user-facing strings.
"""
from __future__ import annotations

from pathlib import Path

import pytest

# Characters that are known to render inconsistently in system fonts.
# Each is (codepoint, human-readable name, ASCII-safe replacement).
_BLACKLIST = {
    0xFF0B: ("FULLWIDTH PLUS SIGN", "+"),
    0xFF0D: ("FULLWIDTH HYPHEN-MINUS", "-"),
    0xFF08: ("FULLWIDTH LEFT PARENTHESIS", "("),
    0xFF09: ("FULLWIDTH RIGHT PARENTHESIS", ")"),
    0xFF1F: ("FULLWIDTH QUESTION MARK", "?"),
    0xFF01: ("FULLWIDTH EXCLAMATION MARK", "!"),
    0xFF1A: ("FULLWIDTH COLON", ":"),
    0xFF1B: ("FULLWIDTH SEMICOLON", ";"),
    0x200B: ("ZERO WIDTH SPACE", ""),
    0x200C: ("ZERO WIDTH NON-JOINER", ""),
    0x200D: ("ZERO WIDTH JOINER", ""),
    0xFEFF: ("BYTE ORDER MARK", ""),
}


def _scan(path: Path) -> list[tuple[int, int, str]]:
    """Return [(line_no, codepoint, char_name)] for blacklisted chars in file."""
    out: list[tuple[int, int, str]] = []
    try:
        text = path.read_text(encoding="utf-8")
    except Exception:
        return out
    for line_no, line in enumerate(text.splitlines(), start=1):
        for ch in line:
            cp = ord(ch)
            if cp in _BLACKLIST:
                name, _ = _BLACKLIST[cp]
                out.append((line_no, cp, name))
    return out


def _ui_files() -> list[Path]:
    root = Path(__file__).resolve().parent.parent / "volscope" / "ui"
    return [p for p in root.rglob("*.py") if "__pycache__" not in str(p)]


class TestNoFullwidthChars:
    def test_ui_files_clean(self):
        offenders: dict[str, list[tuple[int, int, str]]] = {}
        for path in _ui_files():
            hits = _scan(path)
            if hits:
                offenders[str(path)] = hits
        if offenders:
            lines = []
            for fp, hits in offenders.items():
                for line_no, cp, name in hits:
                    replacement = _BLACKLIST[cp][1]
                    lines.append(
                        f"  {fp}:{line_no} — U+{cp:04X} {name} "
                        f"(use {replacement!r} instead)"
                    )
            pytest.fail(
                "Found problematic unicode in UI source:\n" + "\n".join(lines)
            )


class TestNoFullwidthInAnalytics:
    """Analytics + data files are less user-facing but should still be clean."""

    def _analytics_files(self) -> list[Path]:
        root = Path(__file__).resolve().parent.parent / "volscope"
        return [
            p
            for p in root.rglob("*.py")
            if "__pycache__" not in str(p) and "ui" not in p.parts
        ]

    def test_analytics_clean(self):
        offenders: list[str] = []
        for path in self._analytics_files():
            hits = _scan(path)
            for line_no, cp, name in hits:
                offenders.append(f"{path}:{line_no} U+{cp:04X} {name}")
        assert not offenders, (
            "Problematic unicode in analytics/data files:\n" + "\n".join(offenders)
        )
