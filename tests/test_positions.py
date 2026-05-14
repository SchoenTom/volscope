"""Tests for the positions (trade journal) DB layer and UI HTML builders."""
from __future__ import annotations

import datetime

import pandas as pd
import pytest

from volscope.data.database import VolScopeDB
from volscope.ui.views.command_center_page import (
    _position_row_html,
    _positions_table_html,
)


@pytest.fixture
def db(tmp_path):
    return VolScopeDB(db_path=str(tmp_path / "test.db"))


# ---------------------------------------------------------------------------
# DB layer
# ---------------------------------------------------------------------------

class TestPositionsDB:
    def test_add_position_returns_id(self, db):
        pid = db.add_position("QQQ", datetime.date(2026, 1, 15), entry_iv_30d=18.5)
        assert isinstance(pid, int)
        assert pid >= 1

    def test_get_positions_returns_row(self, db):
        db.add_position("QQQ", datetime.date(2026, 1, 15), entry_iv_30d=18.5, notes="test")
        df = db.get_positions("QQQ")
        assert len(df) == 1
        assert float(df.iloc[0]["entry_iv_30d"]) == pytest.approx(18.5)

    def test_get_positions_multiple(self, db):
        db.add_position("QQQ", datetime.date(2026, 1, 10), entry_iv_30d=20.0)
        db.add_position("QQQ", datetime.date(2026, 1, 20), entry_iv_30d=22.0)
        df = db.get_positions("QQQ")
        assert len(df) == 2

    def test_positions_ordered_by_entry_date_desc(self, db):
        db.add_position("QQQ", datetime.date(2026, 1, 10), entry_iv_30d=20.0)
        db.add_position("QQQ", datetime.date(2026, 2, 5), entry_iv_30d=18.0)
        df = db.get_positions("QQQ")
        assert str(df.iloc[0]["entry_date"]) >= str(df.iloc[1]["entry_date"])

    def test_close_position_sets_inactive(self, db):
        pid = db.add_position("QQQ", datetime.date(2026, 1, 15), entry_iv_30d=18.5)
        db.close_position(pid)
        df = db.get_positions("QQQ")
        assert bool(df.iloc[0]["active"]) is False

    def test_delete_position_removes_row(self, db):
        pid = db.add_position("QQQ", datetime.date(2026, 1, 15), entry_iv_30d=18.5)
        db.delete_position(pid)
        df = db.get_positions("QQQ")
        assert df.empty

    def test_delete_position_other_rows_unaffected(self, db):
        pid1 = db.add_position("QQQ", datetime.date(2026, 1, 15), entry_iv_30d=18.5)
        pid2 = db.add_position("QQQ", datetime.date(2026, 1, 20), entry_iv_30d=20.0)
        db.delete_position(pid1)
        df = db.get_positions("QQQ")
        assert len(df) == 1
        assert int(df.iloc[0]["id"]) == pid2

    def test_delete_position_idempotent(self, db):
        pid = db.add_position("QQQ", datetime.date(2026, 1, 15), entry_iv_30d=18.5)
        db.delete_position(pid)
        db.delete_position(pid)  # second call is a no-op, must not raise
        assert db.get_positions("QQQ").empty

    def test_active_only_filter(self, db):
        pid1 = db.add_position("QQQ", datetime.date(2026, 1, 10), entry_iv_30d=20.0)
        db.add_position("QQQ", datetime.date(2026, 1, 20), entry_iv_30d=22.0)
        db.close_position(pid1)
        df = db.get_positions("QQQ", active_only=True)
        assert len(df) == 1
        assert bool(df.iloc[0]["active"]) is True

    def test_get_all_positions_no_ticker_filter(self, db):
        db.add_position("QQQ", datetime.date(2026, 1, 10), entry_iv_30d=20.0)
        db.add_position("MSTR", datetime.date(2026, 1, 11), entry_iv_30d=55.0)
        df = db.get_positions()
        assert len(df) == 2

    def test_add_position_stores_all_fields(self, db):
        db.add_position(
            "SNOW",
            datetime.date(2026, 3, 1),
            entry_iv_30d=40.0,
            entry_iv_percentile=25.0,
            entry_vrp=0.85,
            notes="bought on spike",
        )
        df = db.get_positions("SNOW")
        row = df.iloc[0]
        assert float(row["entry_iv_percentile"]) == pytest.approx(25.0)
        assert float(row["entry_vrp"]) == pytest.approx(0.85)
        assert row["notes"] == "bought on spike"

    def test_new_position_is_active_by_default(self, db):
        db.add_position("QQQ", datetime.date(2026, 1, 15))
        df = db.get_positions("QQQ")
        assert bool(df.iloc[0]["active"]) is True

    def test_empty_db_returns_empty_df(self, db):
        df = db.get_positions("QQQ")
        assert df.empty

    def test_sequential_ids_are_unique(self, db):
        pid1 = db.add_position("QQQ", datetime.date(2026, 1, 10))
        pid2 = db.add_position("QQQ", datetime.date(2026, 1, 20))
        assert pid1 != pid2


# ---------------------------------------------------------------------------
# HTML builders
# ---------------------------------------------------------------------------

def _make_pos(entry_iv=18.5, entry_pct=20.0, entry_vrp=0.9, notes="test", pos_id=1):
    return pd.Series({
        "id": pos_id,
        "ticker": "QQQ",
        "entry_date": datetime.date(2026, 1, 15),
        "entry_iv_30d": entry_iv,
        "entry_iv_percentile": entry_pct,
        "entry_vrp": entry_vrp,
        "notes": notes,
        "active": True,
    })


class TestPositionRowHtml:
    def test_shows_entry_date(self):
        html = _position_row_html(_make_pos(), current_iv=20.0)
        assert "2026-01-15" in html

    def test_shows_entry_iv(self):
        html = _position_row_html(_make_pos(entry_iv=18.5), current_iv=20.0)
        assert "18.5%" in html

    def test_shows_current_iv(self):
        html = _position_row_html(_make_pos(), current_iv=22.3)
        assert "22.3%" in html

    def test_delta_positive_uses_warn_color(self):
        from volscope.ui.styles.theme import COLORS
        html = _position_row_html(_make_pos(entry_iv=18.0), current_iv=25.0)
        assert COLORS["warn"] in html

    def test_delta_negative_uses_accent_color(self):
        from volscope.ui.styles.theme import COLORS
        html = _position_row_html(_make_pos(entry_iv=25.0), current_iv=18.0)
        assert COLORS["accent"] in html

    def test_none_current_iv_shows_dash(self):
        html = _position_row_html(_make_pos(), current_iv=None)
        # delta cell should show —
        assert "—" in html

    def test_long_notes_truncated(self):
        long_notes = "this is a very long note that exceeds thirty characters easily"
        html = _position_row_html(_make_pos(notes=long_notes), current_iv=20.0)
        assert "…" in html

    def test_short_notes_not_truncated(self):
        html = _position_row_html(_make_pos(notes="buy signal"), current_iv=20.0)
        assert "buy signal" in html
        assert "…" not in html


class TestPositionsTableHtml:
    def test_empty_df_returns_empty_string(self):
        result = _positions_table_html("QQQ", pd.DataFrame(), current_iv=20.0)
        assert result == ""

    def test_table_includes_ticker_label(self):
        df = pd.DataFrame([_make_pos().to_dict()])
        html = _positions_table_html("QQQ", df, current_iv=20.0)
        assert "QQQ" in html

    def test_shows_max_three_rows(self):
        rows = [_make_pos(pos_id=i).to_dict() for i in range(5)]
        df = pd.DataFrame(rows)
        html = _positions_table_html("QQQ", df, current_iv=20.0)
        assert html.count("2026-01-15") <= 3
