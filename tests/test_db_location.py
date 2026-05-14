"""
Tests for the DB location logic.

These pin the behavior that caused the real-world bug: the DB used to live
inside the Desktop-synced project folder, where macOS File Provider held a
write handle on the file and collided with DuckDB's exclusive lock. The
config now resolves to a non-synced location by default, and the
VOLSCOPE_DATA_DIR env var can override it.
"""
from __future__ import annotations

import importlib
import os
import platform
from pathlib import Path


def _reload_config():
    import volscope.config as cfg

    return importlib.reload(cfg)


def test_env_override_wins(monkeypatch, tmp_path):
    monkeypatch.setenv("VOLSCOPE_DATA_DIR", str(tmp_path))
    cfg = _reload_config()
    assert cfg.DATA_DIR == Path(str(tmp_path))
    assert cfg.DB_PATH == Path(str(tmp_path)) / "volscope.db"


def test_default_location_is_not_in_desktop(monkeypatch):
    monkeypatch.delenv("VOLSCOPE_DATA_DIR", raising=False)
    cfg = _reload_config()
    # Must not live inside any Desktop-shaped path — that's exactly the
    # folder File Provider / iCloud love to grab a handle on.
    assert "Desktop" not in str(cfg.DATA_DIR)
    assert "Desktop" not in str(cfg.DB_PATH)


def test_default_location_on_macos_is_application_support(monkeypatch):
    if platform.system() != "Darwin":
        return
    monkeypatch.delenv("VOLSCOPE_DATA_DIR", raising=False)
    cfg = _reload_config()
    assert "Application Support" in str(cfg.DATA_DIR)
    assert str(cfg.DATA_DIR).endswith("VolScope")


def test_db_opens_at_new_location(monkeypatch, tmp_path):
    monkeypatch.setenv("VOLSCOPE_DATA_DIR", str(tmp_path))
    _reload_config()
    # Reload database module so it picks up the new DB_PATH default.
    import volscope.data.database as dbmod

    importlib.reload(dbmod)
    db = dbmod.VolScopeDB()
    try:
        from datetime import date

        db.upsert_daily("ZZZ", date(2026, 4, 14), iv_30d=15.0, company_name="Z Corp")
        hist = db.get_ticker_history("ZZZ")
        assert len(hist) == 1
        assert db.get_company_name("ZZZ") == "Z Corp"
    finally:
        db.close()
    assert (tmp_path / "volscope.db").exists()


def test_config_reloads_cleanly(monkeypatch):
    """Sanity check that reloading the config doesn't break downstream imports."""
    monkeypatch.delenv("VOLSCOPE_DATA_DIR", raising=False)
    cfg1 = _reload_config()
    cfg2 = _reload_config()
    assert cfg1.DB_PATH == cfg2.DB_PATH
