"""Central configuration. All magic numbers live here."""
from __future__ import annotations

import os
from pathlib import Path

try:
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parent.parent / ".env")
except Exception:
    pass


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None or raw == "":
        return default
    try:
        return float(raw)
    except ValueError:
        return default


PROJECT_ROOT = Path(__file__).parent.parent


def _resolve_data_dir() -> Path:
    """
    Pick a DB location that no cloud File Provider will grab a write handle on.

    Priority:
        1. VOLSCOPE_DATA_DIR env var (explicit override — wins always)
        2. macOS: ~/Library/Application Support/VolScope/
           (standard user-data location, never synced by iCloud/Dropbox/etc.)
        3. Linux/other: ~/.local/share/volscope/
        4. Fallback: <project>/data.nosync/  (iCloud-exclusion convention)

    We explicitly avoid <project>/data/ because on macOS Desktop is often
    iCloud-synced and File Provider holds write handles on files there,
    which collides with DuckDB's exclusive lock.
    """
    override = os.getenv("VOLSCOPE_DATA_DIR")
    if override:
        return Path(override).expanduser()

    import platform

    system = platform.system()
    if system == "Darwin":
        return Path.home() / "Library" / "Application Support" / "VolScope"
    if system == "Linux":
        xdg = os.getenv("XDG_DATA_HOME")
        base = Path(xdg).expanduser() if xdg else Path.home() / ".local" / "share"
        return base / "volscope"
    # Windows / unknown — use project-local with nosync suffix.
    return PROJECT_ROOT / "data.nosync"


DATA_DIR = _resolve_data_dir()
DB_PATH = DATA_DIR / "volscope.db"

TRADING_DAYS_PER_YEAR = 252
CALENDAR_DAYS_PER_YEAR = 365

DEFAULT_HV_SHORT = 20
# v0.7.1 — matched-horizon HV (Yang-Zhang at 30 trading days). This is
# the academically-correct window to compare against IV30: Christensen-
# Prabhala 1998 use 22-day Parkinson against 1-month IV; we use 30
# trading days against IV30 so the apples-to-apples spread holds.
DEFAULT_HV_MATCHED = 30
DEFAULT_HV_LONG = 60
DEFAULT_RANK_LOOKBACK = 252

SCRAPE_DELAY_SECONDS = _env_float("VOLSCOPE_SCRAPE_DELAY", 1.5)
MAX_RETRIES = int(_env_float("VOLSCOPE_MAX_RETRIES", 3))
REQUEST_TIMEOUT = int(_env_float("VOLSCOPE_REQUEST_TIMEOUT", 10))

# Risk-free rate (continuous, annual). Override via VOLSCOPE_RISK_FREE_RATE in
# .env so the IV solver tracks current short-term Treasury yields without code
# edits. Default tracks ~3M Treasury at time of last review.
RISK_FREE_RATE = _env_float("VOLSCOPE_RISK_FREE_RATE", 0.045)

APP_TITLE = "◈ VolScope"
DEFAULT_TICKER = "SPY"
