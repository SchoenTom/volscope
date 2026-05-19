"""Reusable Streamlit button that spawns a `make` target.

Operator feedback 2026-05-19: every empty-state card that said
"run `make scrape`" needs a clickable button right next to it so
the operator doesn't have to drop to a terminal. Same for
`make schedule-alerts` (background-alert installer) and
`make unschedule-alerts`.

Usage:
    from volscope.ui.components.make_runner import run_make_button
    run_make_button(
        st,
        target="scrape",
        label="↻ Run scrape now",
        key="some_unique_key",
        help_text="Fetch latest IV/HV snapshot in the background (~5-15 min).",
    )

Single source of truth for repo-root + log-dir computation so we
never hardcode iCloud Desktop paths again.
"""
from __future__ import annotations

import datetime as _dt
import logging
import os
import subprocess
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)


def _repo_root() -> Path:
    """Resolve the project root from this file's location.

    Was hardcoded to the old Desktop iCloud path in three
    places — silently broken since the 2026-05-15 migration to
    ~/dev/VolScope. Anchoring on __file__ removes the footgun.
    """
    return Path(__file__).resolve().parents[3]


def _log_dir() -> Path:
    p = Path.home() / ".claude" / "volscope-cron-logs"
    p.mkdir(parents=True, exist_ok=True)
    return p


def spawn_make(target: str, *, label_for_log: Optional[str] = None) -> tuple[bool, str]:
    """Spawn ``make <target>`` in a detached process. Returns
    (ok, log_path_or_error_message)."""
    name = label_for_log or target
    log_file = _log_dir() / f"manual-{name}-{_dt.datetime.now():%Y%m%d-%H%M%S}.log"
    try:
        with open(log_file, "w") as lf:
            subprocess.Popen(
                ["make", target],
                cwd=str(_repo_root()),
                stdout=lf, stderr=subprocess.STDOUT,
                start_new_session=True,
            )
        return True, str(log_file)
    except Exception as exc:                                       # noqa: BLE001
        log.exception("make %s spawn failed", target)
        return False, str(exc)


def run_make_sync(target: str, timeout: int = 60) -> tuple[bool, str]:
    """Run ``make <target>`` synchronously and return (ok, stdout_or_err).

    Use for FAST, idempotent targets (schedule-alerts, unschedule-
    alerts). Spawn the background variant for long-running ones.
    """
    try:
        result = subprocess.run(
            ["make", target],
            cwd=str(_repo_root()),
            capture_output=True, text=True, timeout=timeout,
        )
        out = (result.stdout or "") + (("\n" + result.stderr) if result.stderr else "")
        return result.returncode == 0, out.strip()
    except subprocess.TimeoutExpired:
        return False, f"make {target} timed out after {timeout}s"
    except Exception as exc:                                       # noqa: BLE001
        log.exception("make %s sync failed", target)
        return False, str(exc)


def run_make_button(
    st, *,
    target: str,
    label: str,
    key: str,
    help_text: str = "",
    button_type: str = "secondary",
    confirm_label: Optional[str] = None,
    success_message: Optional[str] = None,
    use_width_stretch: bool = True,
) -> None:
    """Inline button that spawns ``make <target>`` on click.

    Async / background spawn (`subprocess.Popen` + start_new_session)
    — UI stays responsive while the make target runs. Click toasts
    a success/failure indicator and points to the log file.

    If ``confirm_label`` is provided, the click reveals a confirm
    button (two-step gate against accidental clicks for destructive
    or long-running targets like `quickstart-full`).
    """
    state_key_armed = f"{key}__armed"

    if confirm_label and not st.session_state.get(state_key_armed, False):
        kwargs = {"key": key, "help": help_text, "type": button_type}
        if use_width_stretch:
            kwargs["width"] = "stretch"
        if st.button(label, **kwargs):
            st.session_state[state_key_armed] = True
            st.rerun()
        return

    btn_label = confirm_label if confirm_label else label
    kwargs = {"key": f"{key}__go", "help": help_text,
              "type": "primary" if confirm_label else button_type}
    if use_width_stretch:
        kwargs["width"] = "stretch"
    if st.button(btn_label, **kwargs):
        ok, info = spawn_make(target)
        st.session_state.pop(state_key_armed, None)
        if ok:
            st.toast(
                success_message or f"`make {target}` started — log: {os.path.basename(info)}",
                icon="🔄" if target == "scrape" else "🔔",
            )
        else:
            st.error(f"Could not start `make {target}`: {info}")


def run_make_button_sync(
    st, *,
    target: str,
    label: str,
    key: str,
    help_text: str = "",
    button_type: str = "secondary",
    success_message: Optional[str] = None,
    use_width_stretch: bool = True,
    timeout: int = 60,
) -> None:
    """Synchronous variant — runs the target inline + reports result.

    Use for short idempotent targets (schedule-alerts, unschedule-
    alerts). Blocks the UI for ``timeout`` seconds max.
    """
    kwargs = {"key": key, "help": help_text, "type": button_type}
    if use_width_stretch:
        kwargs["width"] = "stretch"
    if st.button(label, **kwargs):
        with st.spinner(f"Running `make {target}` …"):
            ok, info = run_make_sync(target, timeout=timeout)
        if ok:
            st.toast(success_message or f"✓ `make {target}` finished", icon="✅")
            with st.expander("Output", expanded=False):
                st.code(info or "(no output)", language="text")
        else:
            st.error(f"`make {target}` failed")
            st.code(info or "(no output)", language="text")
