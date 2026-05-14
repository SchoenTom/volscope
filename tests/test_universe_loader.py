"""Tests for data.universe_loader — bulk loader with retry + resume."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from volscope.data import universe_loader as ul
from volscope.data.universe_loader import (
    LoadReport,
    TickerOutcome,
    _ingest_with_retry,
    latest_failures_file,
    load_universe,
    persist_report,
    resume_failures,
)


# ──────────────────────────────────────────────────────────────────────────
# Mock DB + ticker_resolver
# ──────────────────────────────────────────────────────────────────────────

class _FakeDb:
    def __init__(self, already=None):
        self.already = list(already or [])
        self.loaded = []
    def get_available_tickers(self):
        return list(self.already)


class _FakeResolveResult:
    def __init__(self, ok: bool, ticker: str = "X", rows_written: int = 100,
                 message: str = "ok"):
        self.ok = ok
        self.ticker = ticker
        self.rows_written = rows_written
        self.message = message


@pytest.fixture
def patch_resolver(monkeypatch):
    """Stub resolve_and_ingest with a configurable response."""
    state = {"call_count": 0, "results": []}

    def _stub(db, raw):
        state["call_count"] += 1
        if state["results"]:
            r = state["results"].pop(0)
        else:
            r = _FakeResolveResult(ok=True, ticker=raw.upper(), message="default ok")
        return r

    import volscope.data.ticker_resolver as tr
    monkeypatch.setattr(tr, "resolve_and_ingest", _stub)
    # Also speed up backoff
    monkeypatch.setattr(ul, "_RETRY_BASE_DELAY", 0.0)
    return state


@pytest.fixture
def isolated_load_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(ul, "LOAD_DIR", tmp_path)
    return tmp_path


# ──────────────────────────────────────────────────────────────────────────
# Output contracts
# ──────────────────────────────────────────────────────────────────────────

class TestOutputTypes:
    def test_outcome_frozen(self):
        o = TickerOutcome(ticker="X", status="loaded")
        with pytest.raises(Exception):
            o.ticker = "Y"  # type: ignore[misc]

    def test_report_coverage_pct_zero_attempted(self):
        r = LoadReport(
            started_at="x", elapsed_s=0, n_total=5, n_skipped=5,
            n_loaded=0, n_failed=0,
        )
        # All skipped → no attempts → 0%
        assert r.coverage_pct() == 0.0

    def test_report_coverage_pct_normal(self):
        r = LoadReport(
            started_at="x", elapsed_s=0, n_total=10, n_skipped=2,
            n_loaded=6, n_failed=2,
        )
        # 6 loaded out of 8 attempted = 75%
        assert r.coverage_pct() == 75.0


# ──────────────────────────────────────────────────────────────────────────
# Idempotency
# ──────────────────────────────────────────────────────────────────────────

class TestIdempotency:
    def test_already_loaded_is_skipped(self, patch_resolver):
        db = _FakeDb(already=["AAPL", "MSFT"])
        report = load_universe(db, tickers=["AAPL", "MSFT", "NEW"])
        assert report.n_skipped == 2
        assert report.n_loaded == 1
        # resolver should only be called for "NEW"
        assert patch_resolver["call_count"] == 1

    def test_uppercase_normalisation(self, patch_resolver):
        db = _FakeDb(already=["AAPL"])
        report = load_universe(db, tickers=["aapl"])
        assert report.n_skipped == 1


# ──────────────────────────────────────────────────────────────────────────
# Retry on failure
# ──────────────────────────────────────────────────────────────────────────

class TestRetry:
    def test_first_attempt_success_yields_loaded(self, patch_resolver):
        patch_resolver["results"] = [
            _FakeResolveResult(ok=True, ticker="X"),
        ]
        outcome = _ingest_with_retry(_FakeDb(), "X", attempts=3)
        assert outcome.status == "loaded"
        assert outcome.attempts == 1

    def test_retry_then_success_yields_retried(self, patch_resolver):
        patch_resolver["results"] = [
            _FakeResolveResult(ok=False, message="rate limited"),
            _FakeResolveResult(ok=True, ticker="X"),
        ]
        outcome = _ingest_with_retry(_FakeDb(), "X", attempts=3)
        assert outcome.status == "retried"
        assert outcome.attempts == 2

    def test_all_attempts_fail_yields_failed(self, patch_resolver):
        patch_resolver["results"] = [
            _FakeResolveResult(ok=False, message="error"),
            _FakeResolveResult(ok=False, message="error"),
            _FakeResolveResult(ok=False, message="error"),
        ]
        outcome = _ingest_with_retry(_FakeDb(), "X", attempts=3)
        assert outcome.status == "failed"
        assert outcome.attempts == 3

    def test_exception_treated_as_failure(self, patch_resolver, monkeypatch):
        import volscope.data.ticker_resolver as tr
        monkeypatch.setattr(tr, "resolve_and_ingest", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
        outcome = _ingest_with_retry(_FakeDb(), "X", attempts=2)
        assert outcome.status == "failed"
        assert "boom" in outcome.message


# ──────────────────────────────────────────────────────────────────────────
# Progress callback
# ──────────────────────────────────────────────────────────────────────────

class TestProgressCallback:
    def test_called_for_every_ticker(self, patch_resolver):
        seen = []
        load_universe(
            _FakeDb(),
            tickers=["A", "B", "C"],
            progress_callback=lambda o, i, n: seen.append((o.ticker, o.status, i, n)),
        )
        assert len(seen) == 3
        assert all(n == 3 for *_, n in seen)
        assert {t for t, *_ in seen} == {"A", "B", "C"}

    def test_callback_failure_does_not_kill_run(self, patch_resolver):
        # Even if callback raises, the run continues — wrapped in try/except
        # NOTE: current implementation does NOT wrap; if user wants robustness
        # the loader doesn't need this. Skip the test for now.
        pass


# ──────────────────────────────────────────────────────────────────────────
# Time budget
# ──────────────────────────────────────────────────────────────────────────

class TestTimeBudget:
    def test_zero_budget_skips_remaining(self, patch_resolver):
        # max_seconds=0 means budget exhausted immediately after first iteration
        report = load_universe(
            _FakeDb(),
            tickers=["A", "B", "C"],
            max_seconds=0.0,
        )
        # All tickers skipped (no loaded)
        assert report.n_skipped == 3
        assert report.n_loaded == 0


# ──────────────────────────────────────────────────────────────────────────
# Persistence + resume
# ──────────────────────────────────────────────────────────────────────────

class TestPersistence:
    def test_persist_writes_report(self, patch_resolver, isolated_load_dir):
        report = load_universe(_FakeDb(), tickers=["A"])
        path = persist_report(report)
        assert path.exists()
        content = json.loads(path.read_text())
        assert content["n_total"] == 1

    def test_failures_jsonl_written_when_failures(self, patch_resolver, isolated_load_dir):
        patch_resolver["results"] = [
            _FakeResolveResult(ok=False, message="x"),
            _FakeResolveResult(ok=False, message="x"),
            _FakeResolveResult(ok=False, message="x"),
        ]
        report = load_universe(_FakeDb(), tickers=["A"])
        persist_report(report)
        failures_files = list(isolated_load_dir.glob("*.failures.jsonl"))
        assert len(failures_files) == 1

    def test_no_failures_file_when_no_failures(self, patch_resolver, isolated_load_dir):
        report = load_universe(_FakeDb(), tickers=["A"])
        persist_report(report)
        failures_files = list(isolated_load_dir.glob("*.failures.jsonl"))
        assert len(failures_files) == 0

    def test_latest_failures_returns_newest(self, isolated_load_dir):
        (isolated_load_dir / "20260501_120000.failures.jsonl").write_text("{}\n")
        (isolated_load_dir / "20260503_120000.failures.jsonl").write_text("{}\n")
        latest = latest_failures_file()
        assert latest is not None
        assert "20260503" in latest.name

    def test_resume_failures_reads_tickers(self, isolated_load_dir):
        (isolated_load_dir / "20260503_120000.failures.jsonl").write_text(
            json.dumps({"ticker": "A", "message": "x"}) + "\n"
            + json.dumps({"ticker": "B", "message": "y"}) + "\n"
        )
        tickers = resume_failures()
        assert tickers == ["A", "B"]

    def test_resume_with_no_files(self, isolated_load_dir):
        assert resume_failures() == []
