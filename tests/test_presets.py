"""Tests for strategy preset persistence + idempotent seeding."""
from __future__ import annotations

import os
import tempfile

import pytest

from volscope.data.presets import (
    ScalingTranche,
    StrategyPreset,
    delete_preset,
    get_preset,
    list_presets,
    upsert_preset,
)


@pytest.fixture
def db():
    from volscope.data.database import VolScopeDB
    tmp = tempfile.mkdtemp(prefix="vs_presets_")
    path = os.path.join(tmp, "volscope.db")
    db = VolScopeDB(db_path=path)
    yield db
    db.close()


class TestSchema:
    def test_table_exists(self, db):
        df = db.con.execute(
            "SELECT * FROM strategy_presets LIMIT 1"
        ).fetchdf()
        assert "id" in df.columns
        assert "legs_spec_json" in df.columns


class TestCRUD:
    def _preset(self, _id: str = "test-1") -> StrategyPreset:
        return StrategyPreset(
            id=_id, ticker="AAPL", strategy_name="Long Call",
            legs_spec={"strike": 200.0, "expiry": "2027-01-15", "dte": 540},
            thesis="test thesis",
            scaling_plan=[ScalingTranche("now", 0.5, "starter")],
        )

    def test_insert_and_get(self, db):
        upsert_preset(db, self._preset("a"))
        got = get_preset(db, "a")
        assert got is not None
        assert got.ticker == "AAPL"
        assert got.legs_spec.get("strike") == 200.0
        assert len(got.scaling_plan) == 1
        assert got.scaling_plan[0].qty_pct == 0.5

    def test_list_filtered_by_ticker(self, db):
        upsert_preset(db, self._preset("a"))
        upsert_preset(db, StrategyPreset(
            id="b", ticker="MSFT", strategy_name="Long Call",
            legs_spec={"strike": 400}, thesis="msft",
        ))
        aapl = list_presets(db, ticker="AAPL")
        msft = list_presets(db, ticker="MSFT")
        assert len(aapl) == 1 and aapl[0].id == "a"
        assert len(msft) == 1 and msft[0].id == "b"

    def test_idempotent_insert_does_not_overwrite(self, db):
        upsert_preset(db, self._preset("a"))
        # User edits thesis manually
        db.con.execute(
            "UPDATE strategy_presets SET thesis = ? WHERE id = ?",
            ["user-edited", "a"],
        )
        # Seed re-runs with overwrite=False
        upsert_preset(db, self._preset("a"))   # default overwrite=False
        assert get_preset(db, "a").thesis == "user-edited"

    def test_overwrite_flag_does_replace(self, db):
        upsert_preset(db, self._preset("a"))
        new_preset = self._preset("a")
        new_preset.thesis = "fresh thesis"
        upsert_preset(db, new_preset, overwrite=True)
        assert get_preset(db, "a").thesis == "fresh thesis"

    def test_delete(self, db):
        upsert_preset(db, self._preset("a"))
        assert get_preset(db, "a") is not None
        delete_preset(db, "a")
        assert get_preset(db, "a") is None


class TestSeeder:
    def test_seed_inserts_three_starter_presets(self, db):
        from volscope.data.presets_seed import seed
        added = seed(db)
        assert added >= 3
        all_p = list_presets(db)
        ids = {p.id for p in all_p}
        assert "pypl-long-call-80-jan2029" in ids
        assert "ewz-long-call-50-jan2028" in ids
        assert "jd-long-call-otm-jan" in ids

    def test_seed_is_idempotent(self, db):
        from volscope.data.presets_seed import seed
        seed(db)
        added = seed(db)
        assert added == 0     # second run inserts nothing
        assert len(list_presets(db)) >= 3
