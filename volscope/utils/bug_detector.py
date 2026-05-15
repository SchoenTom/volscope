"""
Automated bug-pattern detector — phase 5 part 1 of the hardening marathon.

A tiny pre-commit-hook-style scanner that flags known classes of
bugs the operator has reported. Runs over the volscope/ tree and
reports each match with (file, line, severity, fix-hint). Designed
to be called from CI or from a make target.

Patterns detected (each backed by an actual real-world bug we hit):

  - **Letter "O" in hex codes** — ``#OO`` mistyped for ``#00``,
    Plotly rejects.
  - **8-char hex in fillcolor** — Plotly rejects ``#00d4aa22``,
    use ``rgba()`` helper.
  - **Material-Symbol "keyboard" ghost text** — leaks when fonts
    load slowly.
  - **st.metric() calls** — deprecated in favour of kpi_grid_html
    because st.metric truncates.
  - **pandas .iterrows()** — strong perf-cost hint; should be
    vectorised unless the loop is rendering N HTML cards.
  - **Plotly Express imports** — ADR-0001 (eq) bans plotly.express;
    use plotly.graph_objects.
  - **f-string SQL injection** — direct interpolation of user input
    into ``db.con.execute(f"...{x}...")``.

The detector is non-fatal — it only *reports*. Up to the operator
whether each match is a real bug or a known-acceptable exception.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


@dataclass(frozen=True)
class BugMatch:
    """One match against a known bug pattern."""
    file:     Path
    line_no:  int
    line:     str
    pattern:  str
    severity: str          # "error" | "warning" | "info"
    fix_hint: str


_PATTERNS: tuple[tuple[str, re.Pattern, str, str], ...] = (
    # name, regex, severity, fix hint
    (
        "letter_O_in_hex",
        re.compile(r"#[0-9A-Fa-f]*O[0-9A-Fa-f]*", re.IGNORECASE),
        "error",
        "Letter 'O' in a hex code — did you mean '0'? Plotly will reject.",
    ),
    (
        "8char_hex_in_fillcolor",
        re.compile(r"fillcolor\s*=\s*['\"]#[0-9A-Fa-f]{8}['\"]"),
        "error",
        "Plotly fillcolor rejects 8-char hex — use rgba() from theme.py.",
    ),
    (
        "keyboard_ghost_text",
        re.compile(r"['\"]keyboard['\"]"),
        "warning",
        "Material-Symbol 'keyboard' literal — replace with a real label or icon.",
    ),
    (
        "st_metric_call",
        re.compile(r"\bst\.metric\s*\("),
        "warning",
        "st.metric() truncates long values — use kpi_grid_html() instead.",
    ),
    (
        "pandas_iterrows",
        re.compile(r"\.iterrows\s*\(\s*\)"),
        "info",
        "pandas .iterrows() is slow — vectorise unless rendering N HTML cards.",
    ),
    (
        "plotly_express_import",
        re.compile(r"^\s*(?:import|from)\s+plotly\.express\b"),
        "error",
        "ADR-0001: use plotly.graph_objects only, not plotly.express.",
    ),
    (
        "fstring_sql_user_input",
        re.compile(r"db\.con\.execute\s*\(\s*f['\"]"),
        "warning",
        "f-string SQL is injection-prone — use parameterised .execute(sql, params).",
    ),
)


def _iter_py_files(root: Path) -> Iterable[Path]:
    """Yield every .py file under ``root`` (excluding caches / venv)."""
    skip_dirs = {"__pycache__", ".venv", "venv", ".git", "build", "dist"}
    for p in root.rglob("*.py"):
        if any(part in skip_dirs for part in p.parts):
            continue
        yield p


def scan_file(path: Path) -> list[BugMatch]:
    """Return every bug-pattern match for one file."""
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return []
    out: list[BugMatch] = []
    for idx, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()
        # Skip comments and docstrings — false positives.
        if stripped.startswith("#") or stripped.startswith('"""'):
            continue
        for name, regex, severity, fix in _PATTERNS:
            if regex.search(line):
                # Self-exempt: this detector module mentions the
                # patterns it scans for inside docstrings + regex
                # literals. Skip our own file.
                if path.name == "bug_detector.py":
                    continue
                out.append(BugMatch(
                    file=path, line_no=idx, line=line.rstrip(),
                    pattern=name, severity=severity, fix_hint=fix,
                ))
                break                                           # first match wins
    return out


def scan_tree(root: Path) -> list[BugMatch]:
    """Scan every .py under ``root``."""
    all_matches: list[BugMatch] = []
    for f in _iter_py_files(root):
        all_matches.extend(scan_file(f))
    return all_matches


def format_match(m: BugMatch) -> str:
    """Pretty single-line representation for CLI / CI output."""
    return (
        f"{m.severity.upper():7}  {m.file}:{m.line_no}  [{m.pattern}]  "
        f"{m.line.strip()[:80]}\n         → {m.fix_hint}"
    )


def main(argv: list[str] | None = None) -> int:
    """CLI entry-point. Exits 0 if no errors, 1 if any error-severity match."""
    import argparse
    parser = argparse.ArgumentParser(
        description="Scan the VolScope tree for known bug patterns.",
    )
    parser.add_argument(
        "root", nargs="?", default="volscope",
        help="Directory to scan (default: volscope).",
    )
    args = parser.parse_args(argv)

    matches = scan_tree(Path(args.root))
    n_err  = sum(1 for m in matches if m.severity == "error")
    n_warn = sum(1 for m in matches if m.severity == "warning")
    n_info = sum(1 for m in matches if m.severity == "info")
    for m in matches:
        print(format_match(m))
    print(f"\nSummary: {n_err} errors · {n_warn} warnings · {n_info} info ({len(matches)} total)")
    return 0 if n_err == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
