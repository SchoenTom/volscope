"""Tests for volscope/scheduler/jobs.py."""
from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

pytest.importorskip("apscheduler")
pytest.importorskip("sqlalchemy")

from volscope.scheduler.jobs import (   # noqa: E402
    BotScheduler, DEFAULT_TIMEZONE, JOB_SCHEDULE, SchedulerSettings,
)


@pytest.fixture
def temp_jobstore():
    with tempfile.TemporaryDirectory() as d:
        yield Path(d) / "scheduler.sqlite"


def test_timezone_is_new_york():
    assert DEFAULT_TIMEZONE == "America/New_York"


def test_job_schedule_has_8_default_jobs():
    assert len(JOB_SCHEDULE) == 8


def test_register_default_jobs_registers_all(temp_jobstore):
    sched = BotScheduler(SchedulerSettings(jobstore_path=temp_jobstore))
    sched.register_default_jobs({})       # no handlers — falls back to stubs
    assert len(sched.registered_jobs) >= 8
    sched.shutdown()


def test_register_with_handlers(temp_jobstore):
    called: list[str] = []

    def make_handler(name):
        return lambda: called.append(name)

    handlers = {name: make_handler(name) for name, *_ in JOB_SCHEDULE}
    sched = BotScheduler(SchedulerSettings(jobstore_path=temp_jobstore))
    sched.register_default_jobs(handlers)
    expected = {name for name, *_ in JOB_SCHEDULE}
    assert expected.issubset(set(sched.registered_jobs))
    sched.shutdown()


def test_heartbeat_only_registered_when_url_set(temp_jobstore):
    s_no_hc = SchedulerSettings(jobstore_path=temp_jobstore, healthchecks_url=None)
    s_with_hc = SchedulerSettings(jobstore_path=temp_jobstore,
                                    healthchecks_url="https://example.test/hc")

    sched1 = BotScheduler(s_no_hc)
    sched1.register_default_jobs({})
    assert "heartbeat" not in sched1.registered_jobs
    sched1.shutdown()

    # Need a fresh jobstore for the second scheduler
    s_with_hc.jobstore_path = temp_jobstore.parent / "sched2.sqlite"
    sched2 = BotScheduler(s_with_hc)
    sched2.register_default_jobs({})
    assert "heartbeat" in sched2.registered_jobs
    sched2.shutdown()


def test_shutdown_is_idempotent(temp_jobstore):
    sched = BotScheduler(SchedulerSettings(jobstore_path=temp_jobstore))
    sched.shutdown()                      # no scheduler created yet — must not raise
    sched.register_default_jobs({})
    sched.shutdown()
    sched.shutdown()
