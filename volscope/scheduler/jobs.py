"""
APScheduler 3.11 AsyncIOScheduler — Phase 2 core scaffold.

8 default daily jobs + 1 weekly + 1 heartbeat. All times in
``America/New_York`` (NOT Berlin — DST transitions differ by ~2 weeks,
breaking CET-anchored schedules).

Jobs are registered with `coalesce=True, max_instances=1,
misfire_grace_time=300`. SQLAlchemy SQLite jobstore so jobs persist
across restarts.

This module is a SCAFFOLD: it wires up the scheduler skeleton and
exposes the job table. Wiring real handlers (`generate_signals`,
`execute_entries`, ...) is the start of Phase 2.5.

Deferred imports of `apscheduler`, `sqlalchemy`.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

DEFAULT_TIMEZONE = "America/New_York"

# (handler_name, hour, minute, day_of_week | "*", weekday-flag)
JOB_SCHEDULE: list[tuple[str, int, int, str]] = [
    ("premarket_load",   8,  0, "mon-fri"),
    ("connect_ibkr",     8, 30, "mon-fri"),
    ("generate_signals", 9, 45, "mon-fri"),
    ("execute_entries", 10,  0, "mon-fri"),
    ("midday_check",    12,  0, "mon-fri"),
    ("eod_management",  15,  0, "mon-fri"),
    ("eod_reconcile",   16, 15, "mon-fri"),
    ("weekly_report",    9,  0, "sat"),
]


@dataclass
class SchedulerSettings:
    """Subset of settings the scheduler needs."""
    jobstore_path: Path = Path.home() / "Library/Application Support/VolScope/scheduler.sqlite"
    healthchecks_url: str | None = None
    heartbeat_interval_seconds: int = 300


class BotScheduler:
    """
    Wraps an `apscheduler.schedulers.asyncio.AsyncIOScheduler`.

    Public API:
        sched = BotScheduler(settings)
        sched.register_default_jobs({"generate_signals": my_handler, ...})
        sched.start()
        sched.shutdown()
    """

    def __init__(self, settings: SchedulerSettings):
        self.settings = settings
        self._sched: Any = None
        self._registered: list[str] = []

    def _lazy_scheduler(self) -> Any:
        if self._sched is not None:
            return self._sched
        try:
            from apscheduler.schedulers.asyncio import AsyncIOScheduler   # type: ignore[import-not-found]
            from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore  # type: ignore[import-not-found]
        except ImportError as exc:
            raise ImportError(
                "BotScheduler requires `apscheduler` and `sqlalchemy`. "
                "Install with `uv sync --extra bot`."
            ) from exc

        self.settings.jobstore_path.parent.mkdir(parents=True, exist_ok=True)
        jobstores = {
            "default": SQLAlchemyJobStore(
                url=f"sqlite:///{self.settings.jobstore_path}"
            ),
        }
        job_defaults = {
            "coalesce": True,
            "max_instances": 1,
            "misfire_grace_time": 300,
        }
        self._sched = AsyncIOScheduler(
            jobstores=jobstores,
            job_defaults=job_defaults,
            timezone=DEFAULT_TIMEZONE,
        )
        return self._sched

    def register_default_jobs(self, handlers: dict[str, Callable[..., Any]]) -> None:
        """
        Register the 8 default daily jobs + the weekly report.

        ``handlers`` maps job name → callable. Any name missing from the
        map is registered as a no-op stub that logs a warning.

        Heartbeat (every 5 min by default) is auto-registered if
        ``HEALTHCHECKS_URL`` is set in settings.
        """
        from apscheduler.triggers.cron import CronTrigger          # type: ignore[import-not-found]
        from apscheduler.triggers.interval import IntervalTrigger  # type: ignore[import-not-found]

        sched = self._lazy_scheduler()

        def _stub(name: str) -> Callable[[], None]:
            def _f():
                import logging
                logging.getLogger("volscope.scheduler").warning(
                    "Job '%s' fired but no handler registered.", name)
            return _f

        for job_name, hour, minute, dow in JOB_SCHEDULE:
            trigger = CronTrigger(
                day_of_week=dow, hour=hour, minute=minute,
                timezone=DEFAULT_TIMEZONE,
            )
            sched.add_job(
                handlers.get(job_name, _stub(job_name)),
                trigger=trigger,
                id=job_name,
                replace_existing=True,
            )
            self._registered.append(job_name)

        if self.settings.healthchecks_url:
            sched.add_job(
                self._heartbeat,
                trigger=IntervalTrigger(
                    seconds=self.settings.heartbeat_interval_seconds,
                    timezone=DEFAULT_TIMEZONE,
                ),
                id="heartbeat",
                replace_existing=True,
            )
            self._registered.append("heartbeat")

    def _heartbeat(self) -> None:
        """Ping Healthchecks.io. No-op on any failure (must not break the loop)."""
        try:
            import httpx
            httpx.get(self.settings.healthchecks_url, timeout=5.0)
        except Exception:               # noqa: BLE001
            pass

    def start(self, *, paused: bool = False) -> None:
        sched = self._lazy_scheduler()
        sched.start(paused=paused)

    def shutdown(self, *, wait: bool = True) -> None:
        if self._sched is None:
            return
        try:
            self._sched.shutdown(wait=wait)
        except Exception:               # noqa: BLE001  (already stopped)
            pass

    @property
    def registered_jobs(self) -> list[str]:
        return list(self._registered)
