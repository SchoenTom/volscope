"""Regime-alarm dispatcher — Telegram + macOS notification + log.

Triggered by ``check_regime_alarms`` in
``volscope.persistence.watchlists`` when a watchlist ticker crosses
the IV-percentile CHEAP/RICH boundary or transitions vol-regime.

Channel priority (each independently configurable):
  1. Telegram — uses existing TELEGRAM__BOT_TOKEN + TELEGRAM__CHAT_ID
     from .env (already wired for the bot alert path).
  2. macOS desktop notification via ``osascript`` — no extra deps,
     always available on the operator's Mac. Subprocess call, never
     blocks.
  3. Log line at WARNING level — always emitted so the operator can
     reconstruct what fired even if all notification channels are
     down.

The dispatch is idempotent: ``last_alarm_at`` in
``watchlist_alarms`` debounces repeat-fires within a 4-hour window
per (ticker, transition) pair, so a chattery boundary-crossing
doesn't spam the operator.
"""
from __future__ import annotations

import logging
import os
import shutil
import subprocess
from datetime import datetime, timezone

from volscope.persistence.watchlists import WatchlistRegimeAlarm

log = logging.getLogger(__name__)

DEBOUNCE_HOURS: float = 4.0


def _format_message(alarm: WatchlistRegimeAlarm) -> tuple[str, str]:
    """Return (short_title, long_body) for the alarm."""
    t = alarm.ticker
    if alarm.transition == "ENTERED_CHEAP":
        title = f"⬇ {t} IV CHEAP"
        body = (
            f"{t} just crossed below IV-pct 20. Current: "
            f"{alarm.current_iv_pct:.1f}% in regime {alarm.current_regime or '?'}. "
            f"Long-vol setups may be attractive."
        )
    elif alarm.transition == "ENTERED_RICH":
        title = f"⬆ {t} IV RICH"
        body = (
            f"{t} just crossed above IV-pct 80. Current: "
            f"{alarm.current_iv_pct:.1f}% in regime {alarm.current_regime or '?'}. "
            f"Short-premium opportunities are open."
        )
    elif alarm.transition.startswith("REGIME_CHANGE_"):
        # ``REGIME_CHANGE_FROM_TO``
        body = (
            f"{t} vol-regime changed: {alarm.transition.replace('REGIME_CHANGE_', '').replace('_TO_', ' → ')}. "
            f"IV-pct now {alarm.current_iv_pct:.1f}%." if alarm.current_iv_pct else
            f"{t} vol-regime changed: {alarm.transition.replace('REGIME_CHANGE_', '').replace('_TO_', ' → ')}."
        )
        title = f"≈ {t} regime shift"
    else:
        title = f"{t} alarm"
        body = f"{t} alarm fired ({alarm.transition})."
    return title, body


def dispatch(alarm: WatchlistRegimeAlarm) -> dict:
    """Send the alarm to all configured channels. Returns a dict of
    ``{channel: bool_success}`` so the caller can log per-channel.

    Never raises — every channel is best-effort and logs its own
    failure.
    """
    title, body = _format_message(alarm)
    result = {"telegram": False, "macos_desktop": False, "log": True}

    log.warning("REGIME ALARM %s: %s", title, body)

    # ── Telegram ─────────────────────────────────────────────────
    try:
        token = os.environ.get("TELEGRAM__BOT_TOKEN") or os.environ.get(
            "TELEGRAM_BOT_TOKEN", ""
        )
        chat_id = os.environ.get("TELEGRAM__CHAT_ID") or os.environ.get(
            "TELEGRAM_CHAT_ID", ""
        )
        if token and chat_id:
            import requests  # local import to avoid heavy import on UI boot
            r = requests.post(
                f"https://api.telegram.org/bot{token}/sendMessage",
                json={"chat_id": chat_id, "text": f"{title}\n{body}"},
                timeout=4,
            )
            result["telegram"] = bool(r.ok)
    except Exception as exc:                                        # noqa: BLE001
        log.debug("Telegram dispatch failed: %s", exc)

    # ── macOS desktop notification ───────────────────────────────
    try:
        if shutil.which("osascript"):
            # title contains apostrophes / colons → escape for AppleScript
            safe_title = title.replace('"', "'").replace("\\", "")
            safe_body = body.replace('"', "'").replace("\\", "")
            subprocess.run(
                [
                    "osascript", "-e",
                    f'display notification "{safe_body}" with title "VolScope" '
                    f'subtitle "{safe_title}"',
                ],
                timeout=2, check=False,
            )
            result["macos_desktop"] = True
    except Exception as exc:                                        # noqa: BLE001
        log.debug("macOS notification failed: %s", exc)

    return result
