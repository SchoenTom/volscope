"""Tests for the Help / Glossary page (Pillar 14)."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from volscope.ui.views import help_page


class TestHelpPageStructure:
    def test_module_exposes_renderer(self):
        assert hasattr(help_page, "render_help_page")
        assert callable(help_page.render_help_page)

    def test_renderer_runs_without_db_calls(self):
        """Help page is purely static — should never touch the DB."""
        db = MagicMock()
        with patch.object(help_page, "st") as st:
            st.title = MagicMock()
            help_page.render_help_page(db, settings={})

        # No DB read or write should have occurred.
        assert not db.method_calls, f"Help page touched DB: {db.method_calls}"

    def test_renderer_calls_title_and_render_html(self):
        db = MagicMock()
        with patch.object(help_page, "st") as st, \
             patch.object(help_page, "render_html") as render_html:
            help_page.render_help_page(db, settings={})

        st.title.assert_called_once()
        # Glossary covers a lot of terms — expect many render_html calls.
        assert render_html.call_count >= 20


class TestHelpPageContent:
    def test_help_page_imports_design_tokens(self):
        """Drift guard — page must use COLORS, not raw hex."""
        from volscope.ui.styles.theme import COLORS
        assert help_page.COLORS is COLORS

    def test_help_page_uses_mono_constant(self):
        assert "JetBrains Mono" in help_page._MONO


class TestHelpPageRegistered:
    def test_help_in_page_registry(self):
        from volscope.ui import app
        assert "Help" in app._PAGE_REGISTRY
        mod, fn = app._PAGE_REGISTRY["Help"]
        assert "help_page" in mod
        assert fn == "render_help_page"

    def test_help_in_sidebar_nav(self):
        """Help must appear in the sidebar's NAV_GROUPS so users can reach it."""
        import inspect
        from volscope.ui.components import sidebar
        src = inspect.getsource(sidebar)
        assert '"Help"' in src
