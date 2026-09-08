import asyncio
import logging
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger
from apscheduler.triggers.interval import IntervalTrigger

from jace.automations.runner import execute_automation
from jace.automations.service import get_automation, list_automations, schedule_from_row, utc_now
from jace.config import settings
from jace.database import SessionLocal
from jace.db.models import Automation


logger = logging.getLogger("uvicorn.error")
_scheduler: AsyncIOScheduler | None = None
_run_semaphore = asyncio.Semaphore(max(1, settings.automation_max_parallel_runs))


DAY_NAMES = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


def scheduler_running() -> bool:
    return bool(_scheduler and _scheduler.running)


def _aware_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def build_trigger(automation: Automation):
    schedule = schedule_from_row(automation)
    zone = ZoneInfo(schedule.timezone)

    if schedule.schedule_type == "once":
        assert schedule.run_at is not None
        return DateTrigger(run_date=schedule.run_at)

    if schedule.schedule_type == "interval":
        assert schedule.interval_minutes is not None
        start = schedule.run_at
        if start is None:
            start = datetime.now(zone) + timedelta(minutes=schedule.interval_minutes)
        return IntervalTrigger(minutes=schedule.interval_minutes, start_date=start, timezone=zone)

    hour, minute = (0, 0)
    if schedule.time_of_day:
        hour, minute = [int(part) for part in schedule.time_of_day.split(":", 1)]

    if schedule.schedule_type == "daily":
        return CronTrigger(hour=hour, minute=minute, timezone=zone)

    if schedule.schedule_type == "weekly":
        days = ",".join(DAY_NAMES[index] for index in sorted(set(schedule.days_of_week)))
        return CronTrigger(day_of_week=days, hour=hour, minute=minute, timezone=zone)

    if schedule.schedule_type == "cron":
        assert schedule.cron_expression is not None
        return CronTrigger.from_crontab(schedule.cron_expression, timezone=zone)

    raise ValueError(f"Unsupported schedule type: {schedule.schedule_type}")


async def _update_next_run(automation_id: str) -> None:
    if _scheduler is None:
        return
    job = _scheduler.get_job(automation_id)
    next_run = _aware_utc(job.next_run_time) if job and job.next_run_time else None
    async with SessionLocal() as session:
        row = await session.get(Automation, automation_id)
        if row is None:
            return
        row.next_run_at = next_run
        await session.commit()


async def _job_wrapper(automation_id: str, trigger_type: str = "scheduled") -> None:
    async with _run_semaphore:
        try:
            await execute_automation(automation_id, trigger_type=trigger_type)
        except Exception:
            logger.exception("Automation %s crashed outside the runner.", automation_id)
        finally:
            # APScheduler advances recurring jobs before this coroutine runs.
            await _update_next_run(automation_id)


async def schedule_automation(automation_id: str, *, recover_missed: bool = False) -> None:
    if _scheduler is None or not _scheduler.running:
        return

    _scheduler.remove_job(automation_id) if _scheduler.get_job(automation_id) else None

    async with SessionLocal() as session:
        automation = await get_automation(session, automation_id)
        if automation is None or not automation.enabled:
            if automation is not None:
                automation.next_run_at = None
                await session.commit()
            return

        previous_next = _aware_utc(automation.next_run_at)
        now = utc_now()
        missed = previous_next is not None and previous_next < now
        lateness = (now - previous_next).total_seconds() if missed else 0

        if recover_missed and missed and lateness <= settings.automation_misfire_grace_seconds:
            # A recovered one-time job must not also be registered with a date
            # trigger in the past or APScheduler may execute it twice.
            if automation.schedule_type == "once":
                automation.next_run_at = None
                await session.commit()
                asyncio.create_task(_job_wrapper(automation.id, "recovered"))
                return
            asyncio.create_task(_job_wrapper(automation.id, "recovered"))
        elif recover_missed and automation.schedule_type == "once" and missed:
            automation.enabled = False
            automation.last_status = "missed"
            automation.next_run_at = None
            await session.commit()
            return

        trigger = build_trigger(automation)

    _scheduler.add_job(
        _job_wrapper,
        trigger=trigger,
        args=[automation_id, "scheduled"],
        id=automation_id,
        replace_existing=True,
        coalesce=True,
        max_instances=1,
        misfire_grace_time=settings.automation_misfire_grace_seconds,
    )
    await _update_next_run(automation_id)


async def unschedule_automation(automation_id: str) -> None:
    if _scheduler is not None and _scheduler.get_job(automation_id):
        _scheduler.remove_job(automation_id)
    async with SessionLocal() as session:
        row = await session.get(Automation, automation_id)
        if row is not None:
            row.next_run_at = None
            await session.commit()


async def reschedule_automation(automation_id: str) -> None:
    await schedule_automation(automation_id, recover_missed=False)


async def start_automation_scheduler() -> None:
    global _scheduler
    if not settings.automation_enabled:
        logger.info("Jace automation scheduler is disabled.")
        return
    if _scheduler is not None and _scheduler.running:
        return

    _scheduler = AsyncIOScheduler(timezone=ZoneInfo(settings.automation_scheduler_timezone))
    _scheduler.start()

    async with SessionLocal() as session:
        rows = await list_automations(session)

    for automation in rows:
        if automation.enabled:
            try:
                await schedule_automation(automation.id, recover_missed=True)
            except Exception as exc:
                logger.warning("Could not schedule automation %s (%s): %s", automation.name, automation.id, exc)

    logger.info("Jace automation scheduler started with %s automation(s).", len(rows))


async def stop_automation_scheduler() -> None:
    global _scheduler
    if _scheduler is None:
        return
    if _scheduler.running:
        _scheduler.shutdown(wait=False)
    _scheduler = None


async def run_automation_now(automation_id: str) -> None:
    asyncio.create_task(_job_wrapper(automation_id, "manual"))
