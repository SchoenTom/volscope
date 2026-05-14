"""Tests for the paper-trader engine.

Each test runs against a fresh in-memory DuckDB so cash + journal
state is independent.
"""
from __future__ import annotations

import os
import tempfile

import pandas as pd
import pytest

from volscope.analytics.strategy_templates import TEMPLATES


@pytest.fixture
def db():
    """Fresh DuckDB instance in a temp dir — fully isolated.

    Pass `db_path` directly to VolScopeDB so we don't depend on env
    var caching in `volscope.config`.
    """
    from volscope.data.database import VolScopeDB
    tmp = tempfile.mkdtemp(prefix="vs_pt_test_")
    path = os.path.join(tmp, "volscope.db")
    db = VolScopeDB(db_path=path)
    yield db
    db.close()


class TestCashAccount:
    def test_default_balance_initialised(self, db):
        from volscope.data.paper_trader import (
            DEFAULT_CASH, get_cash_balance, get_cash_initial,
        )
        assert get_cash_balance(db) == DEFAULT_CASH
        assert get_cash_initial(db) == DEFAULT_CASH

    def test_reset_changes_both(self, db):
        from volscope.data.paper_trader import (
            get_cash_balance, get_cash_initial, reset_cash,
        )
        reset_cash(db, initial=25_000.0)
        assert get_cash_balance(db) == 25_000.0
        assert get_cash_initial(db) == 25_000.0


class TestPaperBuy:
    def test_straddle_inserts_two_rows(self, db):
        from volscope.data.paper_trader import paper_buy_strategy
        mat = TEMPLATES["Long Straddle"].materialize(
            ticker="AAA", spot=100.0, iv_pct=25.0, dte=30, contracts=1,
        )
        gid, cash_after = paper_buy_strategy(db, mat, entry_iv_pct=25.0)
        rows = db.get_positions(ticker="AAA", active_only=True)
        assert len(rows) == 2
        assert (rows["strategy_group_id"] == gid).all()
        assert (rows["strategy_template"] == "Long Straddle").all()

    def test_iron_condor_inserts_four_rows(self, db):
        from volscope.data.paper_trader import paper_buy_strategy
        mat = TEMPLATES["Short Iron Condor"].materialize(
            ticker="AAA", spot=100.0, iv_pct=30.0, dte=45, contracts=1,
        )
        gid, cash_after = paper_buy_strategy(db, mat)
        rows = db.get_positions(ticker="AAA", active_only=True)
        assert len(rows) == 4
        actions = rows["action"].tolist()
        assert actions.count("buy") == 2
        assert actions.count("sell") == 2

    def test_cash_debited_on_buy(self, db):
        from volscope.data.paper_trader import (
            get_cash_balance, paper_buy_strategy,
        )
        cash_before = get_cash_balance(db)
        mat = TEMPLATES["Long Call"].materialize(
            ticker="AAA", spot=100.0, iv_pct=25.0, dte=30, contracts=1,
        )
        _, cash_after = paper_buy_strategy(db, mat)
        # Long-only debit → cash decreases by net_debit
        assert cash_after == pytest.approx(cash_before - mat.net_debit, abs=0.01)

    def test_cash_credited_on_condor(self, db):
        from volscope.data.paper_trader import (
            get_cash_balance, paper_buy_strategy,
        )
        cash_before = get_cash_balance(db)
        mat = TEMPLATES["Short Iron Condor"].materialize(
            ticker="AAA", spot=100.0, iv_pct=30.0, dte=45, contracts=1,
        )
        _, cash_after = paper_buy_strategy(db, mat)
        # Short condor → net credit (cash rises)
        assert cash_after > cash_before

    def test_journal_records_buy(self, db):
        from volscope.data.paper_trader import (
            get_trade_journal, paper_buy_strategy,
        )
        mat = TEMPLATES["Long Call"].materialize(
            ticker="AAA", spot=100.0, iv_pct=25.0, dte=30, contracts=1,
        )
        paper_buy_strategy(db, mat)
        df = get_trade_journal(db)
        assert len(df) >= 1
        latest = df.iloc[0]
        assert latest["event_type"] == "buy"
        assert latest["ticker"] == "AAA"


class TestPaperClose:
    def test_close_marks_all_legs_inactive(self, db, monkeypatch):
        from volscope.data.paper_trader import (
            paper_buy_strategy, paper_close_strategy,
        )
        mat = TEMPLATES["Long Straddle"].materialize(
            ticker="AAA", spot=100.0, iv_pct=25.0, dte=30, contracts=1,
        )
        gid, _ = paper_buy_strategy(db, mat)
        # Synthetic history so close has a mark
        from datetime import date as _d
        hist = pd.DataFrame({
            "date": [_d.today()],
            "spot_price": [100.0], "iv_30d": [25.0],
        })
        pl, cash_after = paper_close_strategy(
            db, gid, history_by_ticker={"AAA": hist},
        )
        active = db.get_positions(ticker="AAA", active_only=True)
        assert active.empty
        all_rows = db.get_positions(ticker="AAA")
        assert len(all_rows) == 2
        # P&L near zero (same day, same IV → no move)
        assert pl == pytest.approx(0.0, abs=2.0)

    def test_close_journals_event(self, db):
        from volscope.data.paper_trader import (
            get_trade_journal, paper_buy_strategy, paper_close_strategy,
        )
        mat = TEMPLATES["Long Call"].materialize(
            ticker="AAA", spot=100.0, iv_pct=25.0, dte=30, contracts=1,
        )
        gid, _ = paper_buy_strategy(db, mat)
        from datetime import date as _d
        hist = pd.DataFrame({
            "date": [_d.today()],
            "spot_price": [100.0], "iv_30d": [25.0],
        })
        paper_close_strategy(db, gid, history_by_ticker={"AAA": hist})
        df = get_trade_journal(db)
        events = df["event_type"].tolist()
        assert "buy" in events
        assert "close" in events


class TestStrategyGroups:
    def test_groups_listed(self, db):
        from volscope.data.paper_trader import (
            list_strategy_groups, paper_buy_strategy,
        )
        mat1 = TEMPLATES["Long Straddle"].materialize(
            ticker="AAA", spot=100.0, iv_pct=25.0, dte=30, contracts=1,
        )
        mat2 = TEMPLATES["Bull Call Spread"].materialize(
            ticker="BBB", spot=50.0, iv_pct=30.0, dte=45, contracts=2,
        )
        paper_buy_strategy(db, mat1)
        paper_buy_strategy(db, mat2)
        groups = list_strategy_groups(db)
        assert len(groups) == 2
        templates = {g.strategy_template for g in groups}
        assert "Long Straddle" in templates
        assert "Bull Call Spread" in templates
