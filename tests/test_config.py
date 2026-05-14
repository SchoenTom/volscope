"""Config loader honors environment variables."""
from __future__ import annotations

import importlib

import volscope.config as config_module


def test_risk_free_rate_default():
    assert isinstance(config_module.RISK_FREE_RATE, float)
    assert 0.0 <= config_module.RISK_FREE_RATE < 0.20


def test_risk_free_rate_env_override(monkeypatch):
    monkeypatch.setenv("VOLSCOPE_RISK_FREE_RATE", "0.0325")
    reloaded = importlib.reload(config_module)
    try:
        assert abs(reloaded.RISK_FREE_RATE - 0.0325) < 1e-9
    finally:
        monkeypatch.delenv("VOLSCOPE_RISK_FREE_RATE", raising=False)
        importlib.reload(config_module)


def test_risk_free_rate_invalid_env_falls_back(monkeypatch):
    monkeypatch.setenv("VOLSCOPE_RISK_FREE_RATE", "not-a-number")
    reloaded = importlib.reload(config_module)
    try:
        assert reloaded.RISK_FREE_RATE == 0.045
    finally:
        monkeypatch.delenv("VOLSCOPE_RISK_FREE_RATE", raising=False)
        importlib.reload(config_module)
