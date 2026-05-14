"""
Tests for volscope.alerts.alert_engine and related DB methods.

Covers:
  - AlertRule / AlertFired dataclass contracts (frozen, field types)
  - compute_metric_value() for all supported metrics + edge cases
  - evaluate_rule() — operator logic, wildcard, disabled, missing data
  - evaluate_rules() — multi-rule/multi-ticker matrix
  - dispatch_log() — writes correct line to temp file
  - dispatch_desktop() — non-macOS returns False without crashing
  - alert_rule_html() / alert_fired_html() — rendering contracts
  - VolScopeDB alert CRUD — add, delete, enable/disable, query, log
"""
from __future__ import annotations

import math
import tempfile
from pathlib import Path

import pandas as pd
import pytest

from volscope.alerts.alert_engine import (
    SUPPORTED_CHANNELS,
    SUPPORTED_METRICS,
    SUPPORTED_OPERATORS,
    AlertFired,
    AlertRule,
    _compare,
    _to_float,
    alert_fired_html,
    alert_rule_html,
    compute_metric_value,
    dispatch_log,
    evaluate_rule,
    evaluate_rules,
)
from volscope.data.database import VolScopeDB


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def db(tmp_path):
    return VolScopeDB(db_path=str(tmp_path / "test.db"))


def _make_rule(
    id: int = 1,
    ticker: str = "QQQ",
    metric: str = "iv_percentile",
    operator: str = "<",
    threshold: float = 20.0,
    channel: str = "log",
    label: str = "Test rule",
    enabled: bool = True,
) -> AlertRule:
    return AlertRule(
        id=id,
        ticker=ticker,
        metric=metric,
        operator=operator,
        threshold=threshold,
        channel=channel,
        label=label,
        enabled=enabled,
    )


def _make_row(**kwargs) -> pd.Series:
    defaults = {
        "iv_percentile": 15.0,
        "iv_rank": 12.0,
        "iv_30d": 18.0,
        "hv_20d": 20.0,
    }
    defaults.update(kwargs)
    return pd.Series(defaults)


def _make_fired(
    rule_id: int = 1,
    rule_label: str = "Test rule",
    ticker: str = "QQQ",
    metric: str = "iv_percentile",
    value: float = 15.0,
    threshold: float = 20.0,
    operator: str = "<",
    message: str = "QQQ fired",
    fired_at: str = "2026-04-23T10:00:00",
) -> AlertFired:
    return AlertFired(
        rule_id=rule_id,
        rule_label=rule_label,
        ticker=ticker,
        metric=metric,
        value=value,
        threshold=threshold,
        operator=operator,
        message=message,
        fired_at=fired_at,
    )


# ---------------------------------------------------------------------------
# Constants / registry completeness
# ---------------------------------------------------------------------------

class TestConstants:
    def test_supported_metrics_non_empty(self):
        assert len(SUPPORTED_METRICS) > 0

    def test_supported_operators_non_empty(self):
        assert len(SUPPORTED_OPERATORS) > 0

    def test_supported_channels_non_empty(self):
        assert len(SUPPORTED_CHANNELS) > 0

    def test_metrics_include_iv_percentile(self):
        assert "iv_percentile" in SUPPORTED_METRICS

    def test_metrics_include_iv_rank(self):
        assert "iv_rank" in SUPPORTED_METRICS

    def test_metrics_include_vrp(self):
        assert "vrp" in SUPPORTED_METRICS

    def test_operators_include_lt(self):
        assert "<" in SUPPORTED_OPERATORS

    def test_operators_include_gt(self):
        assert ">" in SUPPORTED_OPERATORS

    def test_channels_include_log(self):
        assert "log" in SUPPORTED_CHANNELS

    def test_channels_include_desktop(self):
        assert "desktop" in SUPPORTED_CHANNELS


# ---------------------------------------------------------------------------
# AlertRule — dataclass contract
# ---------------------------------------------------------------------------

class TestAlertRuleDataclass:
    def test_is_frozen(self):
        rule = _make_rule()
        with pytest.raises((AttributeError, TypeError)):
            rule.threshold = 999.0  # type: ignore[misc]

    def test_fields_accessible(self):
        rule = _make_rule(id=5, ticker="AAPL", metric="vrp", operator=">",
                          threshold=1.1, channel="email", label="lbl", enabled=False)
        assert rule.id == 5
        assert rule.ticker == "AAPL"
        assert rule.metric == "vrp"
        assert rule.operator == ">"
        assert rule.threshold == pytest.approx(1.1)
        assert rule.channel == "email"
        assert rule.label == "lbl"
        assert rule.enabled is False


# ---------------------------------------------------------------------------
# AlertFired — dataclass contract
# ---------------------------------------------------------------------------

class TestAlertFiredDataclass:
    def test_is_frozen(self):
        f = _make_fired()
        with pytest.raises((AttributeError, TypeError)):
            f.value = 999.0  # type: ignore[misc]

    def test_fields_accessible(self):
        f = _make_fired(rule_id=7, ticker="SNOW", metric="vrp",
                        value=0.85, threshold=0.9, operator="<")
        assert f.rule_id == 7
        assert f.ticker == "SNOW"
        assert f.metric == "vrp"
        assert f.value == pytest.approx(0.85)
        assert f.threshold == pytest.approx(0.9)
        assert f.operator == "<"


# ---------------------------------------------------------------------------
# _to_float helper
# ---------------------------------------------------------------------------

class TestToFloat:
    def test_normal(self):
        assert _to_float(25.5) == pytest.approx(25.5)

    def test_int(self):
        assert _to_float(10) == pytest.approx(10.0)

    def test_none_returns_none(self):
        assert _to_float(None) is None

    def test_nan_returns_none(self):
        assert _to_float(float("nan")) is None

    def test_inf_returns_none(self):
        assert _to_float(float("inf")) is None

    def test_string_invalid_returns_none(self):
        assert _to_float("bad") is None


# ---------------------------------------------------------------------------
# _compare helper
# ---------------------------------------------------------------------------

class TestCompare:
    def test_lt_true(self):
        assert _compare(5.0, "<", 10.0) is True

    def test_lt_false(self):
        assert _compare(15.0, "<", 10.0) is False

    def test_gt_true(self):
        assert _compare(85.0, ">", 80.0) is True

    def test_gt_false(self):
        assert _compare(75.0, ">", 80.0) is False

    def test_lte_equal(self):
        assert _compare(20.0, "<=", 20.0) is True

    def test_gte_equal(self):
        assert _compare(20.0, ">=", 20.0) is True

    def test_unknown_operator_returns_false(self):
        assert _compare(5.0, "!=", 10.0) is False


# ---------------------------------------------------------------------------
# compute_metric_value
# ---------------------------------------------------------------------------

class TestComputeMetricValue:
    def test_iv_percentile(self):
        row = _make_row(iv_percentile=15.0)
        assert compute_metric_value("iv_percentile", row) == pytest.approx(15.0)

    def test_iv_rank(self):
        row = _make_row(iv_rank=22.0)
        assert compute_metric_value("iv_rank", row) == pytest.approx(22.0)

    def test_vrp_normal(self):
        row = _make_row(iv_30d=20.0, hv_20d=25.0)
        assert compute_metric_value("vrp", row) == pytest.approx(20.0 / 25.0)

    def test_vrp_zero_hv_returns_none(self):
        row = _make_row(iv_30d=20.0, hv_20d=0.0)
        assert compute_metric_value("vrp", row) is None

    def test_vrp_none_iv_returns_none(self):
        row = _make_row(iv_30d=None, hv_20d=20.0)
        assert compute_metric_value("vrp", row) is None

    def test_vrp_nan_iv_returns_none(self):
        row = _make_row(iv_30d=float("nan"), hv_20d=20.0)
        assert compute_metric_value("vrp", row) is None

    def test_unknown_metric_returns_none(self):
        row = _make_row()
        assert compute_metric_value("nonexistent_metric", row) is None

    def test_iv_percentile_none_returns_none(self):
        row = _make_row(iv_percentile=None)
        assert compute_metric_value("iv_percentile", row) is None


# ---------------------------------------------------------------------------
# evaluate_rule
# ---------------------------------------------------------------------------

class TestEvaluateRule:
    def test_fires_when_condition_met(self):
        rule = _make_rule(metric="iv_percentile", operator="<", threshold=20.0)
        row  = _make_row(iv_percentile=15.0)
        result = evaluate_rule(rule, "QQQ", row)
        assert result is not None
        assert result.ticker == "QQQ"
        assert result.value == pytest.approx(15.0)

    def test_no_fire_when_condition_not_met(self):
        rule = _make_rule(metric="iv_percentile", operator="<", threshold=20.0)
        row  = _make_row(iv_percentile=25.0)
        assert evaluate_rule(rule, "QQQ", row) is None

    def test_disabled_rule_never_fires(self):
        rule = _make_rule(enabled=False)
        row  = _make_row(iv_percentile=1.0)  # Would otherwise fire
        assert evaluate_rule(rule, "QQQ", row) is None

    def test_ticker_mismatch_no_fire(self):
        rule = _make_rule(ticker="AAPL")
        row  = _make_row(iv_percentile=5.0)
        assert evaluate_rule(rule, "QQQ", row) is None

    def test_wildcard_ticker_fires_any(self):
        rule = _make_rule(ticker="*")
        row  = _make_row(iv_percentile=5.0)
        result = evaluate_rule(rule, "ANYTHING", row)
        assert result is not None
        assert result.ticker == "ANYTHING"

    def test_ticker_case_insensitive(self):
        rule = _make_rule(ticker="qqq")
        row  = _make_row(iv_percentile=5.0)
        result = evaluate_rule(rule, "QQQ", row)
        assert result is not None

    def test_missing_metric_data_no_fire(self):
        rule = _make_rule(metric="iv_percentile")
        row  = pd.Series({"iv_rank": 10.0})  # no iv_percentile
        assert evaluate_rule(rule, "QQQ", row) is None

    def test_fired_message_contains_ticker(self):
        rule = _make_rule()
        row  = _make_row(iv_percentile=10.0)
        result = evaluate_rule(rule, "QQQ", row)
        assert result is not None
        assert "QQQ" in result.message

    def test_fired_at_is_iso_format(self):
        rule = _make_rule()
        row  = _make_row(iv_percentile=10.0)
        result = evaluate_rule(rule, "QQQ", row)
        assert result is not None
        # Should be parseable as ISO datetime
        assert len(result.fired_at) == 19
        assert "T" in result.fired_at

    def test_vrp_threshold_fires(self):
        rule = _make_rule(metric="vrp", operator="<", threshold=0.9)
        row  = _make_row(iv_30d=18.0, hv_20d=20.0)  # vrp = 0.9
        # vrp = 0.9, threshold = 0.9, operator "<" → should NOT fire (0.9 is not < 0.9)
        assert evaluate_rule(rule, "QQQ", row) is None

    def test_vrp_threshold_fires_lte(self):
        rule = _make_rule(metric="vrp", operator="<=", threshold=0.9)
        row  = _make_row(iv_30d=18.0, hv_20d=20.0)  # vrp = 0.9
        result = evaluate_rule(rule, "QQQ", row)
        assert result is not None
        assert result.value == pytest.approx(0.9)

    def test_gt_operator_fires(self):
        rule = _make_rule(metric="iv_percentile", operator=">", threshold=80.0)
        row  = _make_row(iv_percentile=85.0)
        result = evaluate_rule(rule, "QQQ", row)
        assert result is not None

    def test_gte_operator_at_boundary(self):
        rule = _make_rule(metric="iv_percentile", operator=">=", threshold=80.0)
        row  = _make_row(iv_percentile=80.0)
        result = evaluate_rule(rule, "QQQ", row)
        assert result is not None


# ---------------------------------------------------------------------------
# evaluate_rules
# ---------------------------------------------------------------------------

class TestEvaluateRules:
    def test_empty_rules_returns_empty(self):
        rows = {"QQQ": _make_row(iv_percentile=10.0)}
        assert evaluate_rules([], rows) == []

    def test_empty_rows_returns_empty(self):
        rules = [_make_rule()]
        assert evaluate_rules(rules, {}) == []

    def test_single_rule_fires(self):
        rules = [_make_rule(metric="iv_percentile", operator="<", threshold=20.0)]
        rows  = {"QQQ": _make_row(iv_percentile=10.0)}
        fired = evaluate_rules(rules, rows)
        assert len(fired) == 1
        assert fired[0].ticker == "QQQ"

    def test_wildcard_checks_all_tickers(self):
        rules = [_make_rule(ticker="*", metric="iv_percentile", operator="<", threshold=20.0)]
        rows  = {
            "QQQ":  _make_row(iv_percentile=10.0),
            "AAPL": _make_row(iv_percentile=5.0),
            "SPY":  _make_row(iv_percentile=50.0),  # won't fire
        }
        fired = evaluate_rules(rules, rows)
        tickers = {f.ticker for f in fired}
        assert "QQQ" in tickers
        assert "AAPL" in tickers
        assert "SPY" not in tickers

    def test_disabled_rule_skipped(self):
        rules = [
            _make_rule(id=1, enabled=True, metric="iv_percentile", operator="<", threshold=20.0),
            _make_rule(id=2, enabled=False, metric="iv_percentile", operator="<", threshold=20.0),
        ]
        rows = {"QQQ": _make_row(iv_percentile=10.0)}
        fired = evaluate_rules(rules, rows)
        assert all(f.rule_id == 1 for f in fired)

    def test_multiple_rules_multiple_tickers(self):
        rules = [
            _make_rule(id=1, ticker="QQQ", metric="iv_percentile", operator="<", threshold=20.0),
            _make_rule(id=2, ticker="SNOW", metric="iv_rank", operator=">", threshold=70.0),
        ]
        rows = {
            "QQQ":  _make_row(iv_percentile=15.0, iv_rank=10.0),
            "SNOW": _make_row(iv_percentile=50.0, iv_rank=80.0),
        }
        fired = evaluate_rules(rules, rows)
        rule_ids = {f.rule_id for f in fired}
        assert 1 in rule_ids
        assert 2 in rule_ids


# ---------------------------------------------------------------------------
# dispatch_log
# ---------------------------------------------------------------------------

class TestDispatchLog:
    def test_writes_to_file(self, tmp_path):
        log_path = tmp_path / "alerts.log"
        fired = _make_fired(message="test message here")
        dispatch_log(fired, log_path=log_path)
        assert log_path.exists()
        content = log_path.read_text()
        assert "test message here" in content

    def test_appends_on_second_call(self, tmp_path):
        log_path = tmp_path / "alerts.log"
        dispatch_log(_make_fired(message="first"), log_path=log_path)
        dispatch_log(_make_fired(message="second"), log_path=log_path)
        content = log_path.read_text()
        assert "first" in content
        assert "second" in content

    def test_creates_parent_dir(self, tmp_path):
        log_path = tmp_path / "nested" / "dir" / "alerts.log"
        dispatch_log(_make_fired(), log_path=log_path)
        assert log_path.exists()

    def test_line_contains_fired_at(self, tmp_path):
        log_path = tmp_path / "alerts.log"
        fired = _make_fired(fired_at="2026-04-23T10:00:00")
        dispatch_log(fired, log_path=log_path)
        assert "2026-04-23T10:00:00" in log_path.read_text()


# ---------------------------------------------------------------------------
# dispatch_desktop (non-macOS: must not raise, returns bool)
# ---------------------------------------------------------------------------

class TestDispatchDesktop:
    def test_returns_bool(self):
        from volscope.alerts.alert_engine import dispatch_desktop
        fired = _make_fired()
        result = dispatch_desktop(fired)
        assert isinstance(result, bool)

    def test_does_not_raise_on_any_platform(self):
        from volscope.alerts.alert_engine import dispatch_desktop
        # Should not raise even if osascript is unavailable
        dispatch_desktop(_make_fired())


# ---------------------------------------------------------------------------
# HTML builders
# ---------------------------------------------------------------------------

class TestAlertRuleHtml:
    def test_contains_ticker(self):
        rule = _make_rule(ticker="AAPL")
        html = alert_rule_html(rule)
        assert "AAPL" in html

    def test_contains_operator(self):
        rule = _make_rule(operator="<")
        html = alert_rule_html(rule)
        assert "&lt;" in html or "<" in html

    def test_contains_threshold(self):
        rule = _make_rule(threshold=25.0)
        html = alert_rule_html(rule)
        assert "25" in html

    def test_contains_label(self):
        rule = _make_rule(label="My custom alert")
        html = alert_rule_html(rule)
        assert "My custom alert" in html

    def test_returns_string(self):
        assert isinstance(alert_rule_html(_make_rule()), str)

    def test_wildcard_shows_all(self):
        rule = _make_rule(ticker="*")
        html = alert_rule_html(rule)
        assert "all" in html

    def test_desktop_channel_has_bell_icon(self):
        rule = _make_rule(channel="desktop")
        html = alert_rule_html(rule)
        assert "🔔" in html

    def test_log_channel_has_doc_icon(self):
        rule = _make_rule(channel="log")
        html = alert_rule_html(rule)
        assert "📄" in html


class TestAlertFiredHtml:
    def test_contains_ticker(self):
        f = _make_fired(ticker="SNOW")
        html = alert_fired_html(f)
        assert "SNOW" in html

    def test_contains_metric(self):
        f = _make_fired(metric="iv_percentile")
        html = alert_fired_html(f)
        assert "iv_percentile" in html

    def test_contains_value(self):
        f = _make_fired(value=15.0)
        html = alert_fired_html(f)
        assert "15" in html

    def test_returns_string(self):
        assert isinstance(alert_fired_html(_make_fired()), str)


# ---------------------------------------------------------------------------
# VolScopeDB — alert CRUD
# ---------------------------------------------------------------------------

class TestDatabaseAlertRules:
    def test_add_rule_returns_id(self, db):
        rid = db.add_alert_rule(
            ticker="QQQ",
            metric="iv_percentile",
            operator="<",
            threshold=20.0,
            channel="log",
            label="Test",
        )
        assert isinstance(rid, int)
        assert rid >= 1

    def test_add_two_rules_different_ids(self, db):
        r1 = db.add_alert_rule("QQQ", "iv_percentile", "<", 20.0)
        r2 = db.add_alert_rule("AAPL", "iv_rank", ">", 80.0)
        assert r1 != r2

    def test_get_rules_empty(self, db):
        df = db.get_alert_rules()
        assert df.empty

    def test_get_rules_returns_added(self, db):
        db.add_alert_rule("QQQ", "iv_percentile", "<", 20.0, label="MyRule")
        df = db.get_alert_rules()
        assert len(df) == 1
        assert df.iloc[0]["label"] == "MyRule"

    def test_delete_rule(self, db):
        rid = db.add_alert_rule("QQQ", "iv_percentile", "<", 20.0)
        db.delete_alert_rule(rid)
        df = db.get_alert_rules()
        assert df.empty

    def test_set_rule_disabled(self, db):
        rid = db.add_alert_rule("QQQ", "iv_percentile", "<", 20.0)
        db.set_alert_rule_enabled(rid, False)
        df = db.get_alert_rules()
        assert df.iloc[0]["enabled"] == False

    def test_set_rule_re_enabled(self, db):
        rid = db.add_alert_rule("QQQ", "iv_percentile", "<", 20.0)
        db.set_alert_rule_enabled(rid, False)
        db.set_alert_rule_enabled(rid, True)
        df = db.get_alert_rules()
        assert df.iloc[0]["enabled"] == True

    def test_get_rules_filtered_by_ticker(self, db):
        db.add_alert_rule("QQQ", "iv_percentile", "<", 20.0)
        db.add_alert_rule("AAPL", "iv_rank", ">", 80.0)
        df = db.get_alert_rules(ticker="QQQ")
        assert len(df) == 1
        assert df.iloc[0]["ticker"] == "QQQ"

    def test_get_rules_wildcard_included_in_ticker_filter(self, db):
        db.add_alert_rule("*", "iv_percentile", "<", 20.0, label="Any")
        db.add_alert_rule("QQQ", "iv_rank", ">", 80.0, label="QQQ-specific")
        db.add_alert_rule("AAPL", "iv_percentile", ">", 90.0, label="AAPL-only")
        df = db.get_alert_rules(ticker="QQQ")
        labels = df["label"].tolist()
        assert "Any" in labels          # wildcard included
        assert "QQQ-specific" in labels  # ticker match
        assert "AAPL-only" not in labels # different ticker excluded

    def test_auto_label_when_empty(self, db):
        db.add_alert_rule("QQQ", "iv_percentile", "<", 20.0, label="")
        df = db.get_alert_rules()
        label = df.iloc[0]["label"]
        assert "QQQ" in label and "iv_percentile" in label


class TestDatabaseAlertLog:
    def test_log_alert_fired(self, db):
        db.log_alert_fired(
            rule_id=1,
            fired_at="2026-04-23T10:00:00",
            ticker="QQQ",
            metric="iv_percentile",
            metric_value=15.0,
            message="QQQ iv_percentile = 15.0 < 20.0",
        )
        df = db.get_alert_log()
        assert len(df) == 1
        assert df.iloc[0]["ticker"] == "QQQ"

    def test_get_alert_log_limit(self, db):
        for i in range(5):
            db.log_alert_fired(
                rule_id=1,
                fired_at=f"2026-04-23T10:0{i}:00",
                ticker="QQQ",
                metric="iv_percentile",
                metric_value=float(i),
                message=f"msg {i}",
            )
        df = db.get_alert_log(limit=3)
        assert len(df) == 3

    def test_get_alert_log_empty(self, db):
        assert db.get_alert_log().empty

    def test_log_metric_value_stored(self, db):
        db.log_alert_fired(1, "2026-04-23T10:00:00", "QQQ", "iv_percentile", 12.5, "msg")
        df = db.get_alert_log()
        assert df.iloc[0]["metric_value"] == pytest.approx(12.5)
