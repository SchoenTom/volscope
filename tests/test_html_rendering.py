"""
Tests for the HTML rendering invariant.

The bug we're pinning: Streamlit's `st.markdown(..., unsafe_allow_html=True)`
runs the body through a markdown parser first, and any line with 4+ leading
spaces becomes an indented code block. That's why the Discover cards were
rendering as literal `<div class="volscope-card ...">` source text.

These tests guarantee:
  1. `render_html()` dedents common leading whitespace before rendering.
  2. No UI source file passes an indented triple-quoted HTML block to
     `st.markdown` — every such site must go through `render_html`.
  3. The legacy `volscope/ui/pages/` directory is gone (it collided with
     Streamlit's multipage auto-discovery).
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from volscope.ui.components.html_utils import render_html


class _FakeSt:
    def __init__(self):
        self.bodies: list[str] = []

    def markdown(self, body: str, unsafe_allow_html: bool = False) -> None:
        assert unsafe_allow_html is True, "render_html must always opt in"
        self.bodies.append(body)


class TestRenderHtml:
    def test_strips_common_leading_whitespace(self):
        fake = _FakeSt()
        render_html(
            fake,
            """
            <div class="volscope-card">
              <span>hello</span>
            </div>
            """,
        )
        assert fake.bodies, "render_html should call st.markdown"
        rendered = fake.bodies[0]
        # The first line of actual content must start at column 0 (no 4+ space indent).
        first_line = rendered.splitlines()[0]
        assert not first_line.startswith("    "), rendered
        assert first_line.startswith("<div")

    def test_strips_surrounding_blank_lines(self):
        fake = _FakeSt()
        render_html(fake, "\n\n<p>x</p>\n\n")
        assert fake.bodies[0] == "<p>x</p>"

    def test_every_line_left_stripped(self):
        """Every line must be left-stripped. Even 4+ space inner indents that
        would become a markdown code block get flattened. We lose pretty
        source indentation but gain correctness: the render bug can't return
        via a nested f-string template."""
        fake = _FakeSt()
        render_html(
            fake,
            """
            <div>
              <span>nested</span>
                <em>deeper</em>
            </div>
            """,
        )
        rendered = fake.bodies[0]
        assert "<div>" in rendered
        assert "<span>nested</span>" in rendered
        assert "<em>deeper</em>" in rendered
        for line in rendered.splitlines():
            assert not line.startswith(" "), f"line leads with space: {line!r}"

    def test_protects_against_nested_template_indents(self):
        """The exact bug path: an f-string indented 8 spaces inside a function
        body, with nested content at 10/12/14 spaces. After the old dedent,
        inner lines still had 2/4/6 spaces and tripped the code-block rule."""
        fake = _FakeSt()
        render_html(
            fake,
            """
                <div class="card">
                  <div class="header">
                    <span>A</span>
                      <span>B</span>
                  </div>
                </div>
            """,
        )
        rendered = fake.bodies[0]
        for line in rendered.splitlines():
            assert not line.startswith("    "), (
                f"4+ space leading line is a markdown code block trap: {line!r}"
            )
        assert '<div class="card">' in rendered
        assert "<span>A</span>" in rendered
        assert "<span>B</span>" in rendered

    def test_single_line_unchanged(self):
        fake = _FakeSt()
        render_html(fake, "<div>simple</div>")
        assert fake.bodies[0] == "<div>simple</div>"

    def test_always_sets_unsafe_allow_html(self):
        fake = _FakeSt()
        render_html(fake, "<p>x</p>")
        # Assertion in _FakeSt.markdown already verifies this.


class TestNoIndentedHtmlInSource:
    '''
    Scan the UI source tree for the bug pattern: `st.markdown(` + triple-quoted
    string with 4+ spaces on the next line. Any match is a regression of the
    HTML-as-code render bug — every such site must now use `render_html`.
    '''

    _BUG_RE = re.compile(
        r'st\.markdown\(\s*\n?\s*f?"""\s*\n\s{4,}<',
        re.MULTILINE,
    )

    def _ui_files(self):
        root = Path(__file__).resolve().parent.parent / "volscope" / "ui"
        return [p for p in root.rglob("*.py") if "__pycache__" not in str(p)]

    def test_no_indented_markdown_html(self):
        offenders: list[str] = []
        for path in self._ui_files():
            text = path.read_text()
            if self._BUG_RE.search(text):
                offenders.append(str(path))
        assert not offenders, (
            "Indented HTML passed to st.markdown in:\n  "
            + "\n  ".join(offenders)
            + "\nUse render_html(st, ...) from volscope.ui.components.html_utils."
        )


class TestPagesDirectoryGone:
    """Streamlit auto-discovers any sibling `pages/` directory next to the main
    script and creates multipage nav links from each file. That's why the
    sidebar used to show 'app · discover page · scan page · scope page'. We
    renamed the directory to `views/` — this test pins that rename."""

    def test_pages_directory_does_not_exist(self):
        ui = Path(__file__).resolve().parent.parent / "volscope" / "ui"
        assert not (ui / "pages").exists(), (
            "volscope/ui/pages/ must not exist — it gets auto-picked up by "
            "Streamlit's multipage router. Use volscope/ui/views/ instead."
        )

    def test_views_directory_exists_with_all_modules(self):
        ui = Path(__file__).resolve().parent.parent / "volscope" / "ui"
        views = ui / "views"
        assert views.exists(), "volscope/ui/views/ missing"
        for name in ("scope_page.py", "scan_page.py", "discover_page.py"):
            assert (views / name).exists(), f"{name} missing from views/"

    def test_imports_resolve_from_views(self):
        from volscope.ui.views.discover_page import render_discover_page
        from volscope.ui.views.scan_page import render_scan_page
        from volscope.ui.views.scope_page import render_scope_page

        assert callable(render_discover_page)
        assert callable(render_scan_page)
        assert callable(render_scope_page)

    def test_old_pages_module_no_longer_importable(self):
        with pytest.raises(ImportError):
            __import__("volscope.ui.pages.discover_page")
