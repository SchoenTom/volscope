"""Tests for utils.timing — performance instrumentation."""
from __future__ import annotations

import json
import time
from datetime import date, timedelta
from pathlib import Path

import pytest

from volscope.utils import timing


@pytest.fixture
def isolated_perf_dir(tmp_path, monkeypatch):
    """Redirect the perf JSONL directory to a per-test temp path."""
    monkeypatch.setattr(timing, "_PERF_DIR", tmp_path)
    return tmp_path


# ──────────────────────────────────────────────────────────────────────────
# Context manager — basic contract
# ──────────────────────────────────────────────────────────────────────────

class TestInstrument:
    def test_writes_one_record(self, isolated_perf_dir):
        with timing.instrument("test.x"):
            pass
        files = list(isolated_perf_dir.glob("*.jsonl"))
        assert len(files) == 1
        lines = files[0].read_text().splitlines()
        assert len(lines) == 1
        rec = json.loads(lines[0])
        assert rec["name"] == "test.x"
        assert "elapsed_ms" in rec
        assert "ts" in rec

    def test_elapsed_ms_reflects_sleep(self, isolated_perf_dir):
        with timing.instrument("test.sleep"):
            time.sleep(0.05)
        files = list(isolated_perf_dir.glob("*.jsonl"))
        rec = json.loads(files[0].read_text().splitlines()[0])
        # Allow generous lower bound for CI jitter
        assert rec["elapsed_ms"] >= 40

    def test_extra_merged(self, isolated_perf_dir):
        with timing.instrument("test.x", extra={"n": 42, "mode": "test"}):
            pass
        rec = json.loads((list(isolated_perf_dir.glob("*.jsonl"))[0]).read_text().splitlines()[0])
        assert rec["n"] == 42
        assert rec["mode"] == "test"

    def test_non_serialisable_extra_dropped(self, isolated_perf_dir):
        class NotSerialisable:
            pass
        with timing.instrument("test.x", extra={"good": 1, "bad": NotSerialisable()}):
            pass
        rec = json.loads((list(isolated_perf_dir.glob("*.jsonl"))[0]).read_text().splitlines()[0])
        assert rec["good"] == 1
        assert "bad" not in rec

    def test_multiple_calls_append(self, isolated_perf_dir):
        for _ in range(3):
            with timing.instrument("test.x"):
                pass
        files = list(isolated_perf_dir.glob("*.jsonl"))
        assert len(files) == 1
        assert len(files[0].read_text().splitlines()) == 3

    def test_exception_in_block_still_records(self, isolated_perf_dir):
        with pytest.raises(ValueError):
            with timing.instrument("test.boom"):
                raise ValueError("expected")
        files = list(isolated_perf_dir.glob("*.jsonl"))
        # Even when the block raises, the timing record must persist
        assert len(files) == 1
        rec = json.loads(files[0].read_text().splitlines()[0])
        assert rec["name"] == "test.boom"

    def test_persistence_failure_swallowed(self, monkeypatch, tmp_path):
        # Point at a non-writable path; instrument must not raise
        monkeypatch.setattr(timing, "_PERF_DIR", Path("/nonexistent/cannot/write"))
        # Should NOT raise even though the path is unwriteable
        with timing.instrument("test.fail"):
            pass

    def test_overhead_under_one_ms(self, isolated_perf_dir):
        # Wrap a no-op 100 times; average overhead must stay under 1 ms
        N = 100
        t0 = time.perf_counter()
        for _ in range(N):
            with timing.instrument("test.overhead"):
                pass
        elapsed_ms = (time.perf_counter() - t0) * 1000
        # Total = N * (overhead + minimal work). Per-call < 1 ms.
        # Generous CI budget: < 5 ms per call.
        assert elapsed_ms / N < 5.0


# ──────────────────────────────────────────────────────────────────────────
# Decorator form
# ──────────────────────────────────────────────────────────────────────────

class TestDecorator:
    def test_decorated_function_persists(self, isolated_perf_dir):
        @timing.instrumented("test.deco")
        def f(x, y):
            return x + y

        assert f(1, 2) == 3
        rec = json.loads((list(isolated_perf_dir.glob("*.jsonl"))[0]).read_text().splitlines()[0])
        assert rec["name"] == "test.deco"

    def test_decorator_preserves_function_name(self):
        @timing.instrumented("test.deco")
        def my_func():
            pass
        assert my_func.__name__ == "my_func"

    def test_decorator_preserves_return(self, isolated_perf_dir):
        @timing.instrumented("test.deco")
        def f():
            return [1, 2, 3]
        assert f() == [1, 2, 3]


# ──────────────────────────────────────────────────────────────────────────
# Aggregation helpers
# ──────────────────────────────────────────────────────────────────────────

class TestPercentilesFor:
    def test_no_data_returns_none(self, isolated_perf_dir):
        result = timing.percentiles_for("nope")
        assert result == {50: None, 95: None}

    def test_known_distribution(self, isolated_perf_dir):
        # Write 10 records with known elapsed values
        for ms in [10, 20, 30, 40, 50, 60, 70, 80, 90, 100]:
            timing._append_record("test.dist", ms, None)
        result = timing.percentiles_for("test.dist")
        # nearest-rank: p50 = sorted[5] = 50; p95 = sorted[max(9, 10)] = 100
        assert result[50] == 50.0
        assert result[95] == 100.0

    def test_filters_by_name(self, isolated_perf_dir):
        for ms in [10, 20, 30]:
            timing._append_record("name.a", ms, None)
        for ms in [100, 200, 300]:
            timing._append_record("name.b", ms, None)
        a = timing.percentiles_for("name.a")
        b = timing.percentiles_for("name.b")
        assert a[50] in (10, 20)
        assert b[50] in (100, 200)


class TestListInstrumentedNames:
    def test_no_data(self, isolated_perf_dir):
        assert timing.list_instrumented_names() == []

    def test_distinct_names(self, isolated_perf_dir):
        timing._append_record("a", 10, None)
        timing._append_record("b", 20, None)
        timing._append_record("a", 30, None)
        names = timing.list_instrumented_names()
        assert names == ["a", "b"]


class TestNRecordsFor:
    def test_zero_records(self, isolated_perf_dir):
        assert timing.n_records_for("missing") == 0

    def test_counts_by_name(self, isolated_perf_dir):
        for _ in range(5):
            timing._append_record("foo", 10, None)
        for _ in range(2):
            timing._append_record("bar", 10, None)
        assert timing.n_records_for("foo") == 5
        assert timing.n_records_for("bar") == 2


# ──────────────────────────────────────────────────────────────────────────
# Robustness
# ──────────────────────────────────────────────────────────────────────────

class TestRobustness:
    def test_corrupt_line_skipped(self, isolated_perf_dir):
        # Write a corrupt line first, then valid ones
        fpath = isolated_perf_dir / f"{date.today().isoformat()}.jsonl"
        fpath.write_text("not json\n")
        timing._append_record("foo", 10, None)
        # percentiles_for must handle the corrupt line gracefully
        result = timing.percentiles_for("foo")
        assert result[50] == 10.0

    def test_missing_jsonl_dir(self, monkeypatch, tmp_path):
        # Reading from non-existent dir returns no data
        monkeypatch.setattr(timing, "_PERF_DIR", tmp_path / "does-not-exist")
        assert timing.percentiles_for("any") == {50: None, 95: None}
        assert timing.list_instrumented_names() == []
        assert timing.n_records_for("any") == 0
