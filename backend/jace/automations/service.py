import json
from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from apscheduler.triggers.cron import CronTrigger

from jace.config import settings
from jace.db.models import (
    Automation,
    AutomationNotification,
    AutomationRun,
    AutomationToolPermission,
)
from jace.schemas import AutomationSchedule
from jace.tools import ensure_tools_registered
from jace.tools.registry import registry


# Background automations may inspect the automation list, but they cannot
# create/modify/trigger other automations. Allowing those tools inside a
# background scope would let one automation grant capabilities to another.
BACKGROUND_FORBIDDEN_TOOLS = {
    "create_automation",
    "set_automation_enabled",
    "run_automation_now",
    # Phase 9 GUI control is deliberately interactive-only. Background jobs
    # must never click/type into the desktop while nobody is present.
    "start_control_session",
    "control_status",
    "list_control_windows",
    "focus_control_window",
    "capture_control_screen",
    "move_control_pointer",
    "click_control",
    "scroll_control",
    "type_control_text",
    "press_control_keys",
    "stop_control_session",
}


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _loads(value: str, fallback: Any) -> Any:
    try:
        parsed = json.loads(value)
        return parsed
    except (json.JSONDecodeError, TypeError):
        return fallback


def validate_timezone(name: str) -> str:
    try:
        ZoneInfo(name)
    except ZoneInfoNotFoundError as exc:
        raise ValueError(f"Unknown timezone: {name}") from exc
    return name


def validate_schedule(schedule: AutomationSchedule) -> AutomationSchedule:
    validate_timezone(schedule.timezone)

    if schedule.schedule_type == "once":
        if schedule.run_at is None:
            raise ValueError("A one-time automation requires run_at.")
        if schedule.run_at.tzinfo is None:
            raise ValueError("run_at must include a timezone offset.")
        # New one-time jobs must be in the future. Missed-run recovery only
        # applies to jobs that were valid when originally saved.
        if schedule.run_at.astimezone(timezone.utc) <= utc_now():
            raise ValueError("A one-time automation must be scheduled in the future.")

    elif schedule.schedule_type == "interval":
        if schedule.interval_minutes is None:
            raise ValueError("An interval automation requires interval_minutes.")

    elif schedule.schedule_type == "daily":
        if not schedule.time_of_day:
            raise ValueError("A daily automation requires time_of_day.")

    elif schedule.schedule_type == "weekly":
        if not schedule.time_of_day:
            raise ValueError("A weekly automation requires time_of_day.")
        if not schedule.days_of_week:
            raise ValueError("A weekly automation requires at least one day.")
        if any(day < 0 or day > 6 for day in schedule.days_of_week):
            raise ValueError("days_of_week values must be between 0 (Monday) and 6 (Sunday).")

    elif schedule.schedule_type == "cron":
        if not schedule.cron_expression:
            raise ValueError("A cron automation requires cron_expression.")
        if len(schedule.cron_expression.split()) != 5:
            raise ValueError("Cron expressions must use five fields: minute hour day month weekday.")
        try:
            CronTrigger.from_crontab(schedule.cron_expression, timezone=ZoneInfo(schedule.timezone))
        except (TypeError, ValueError) as exc:
            raise ValueError(f"Invalid cron expression: {exc}") from exc

    return schedule


def schedule_to_json(schedule: AutomationSchedule) -> str:
    payload = schedule.model_dump(mode="json")
    payload.pop("schedule_type", None)
    payload.pop("timezone", None)
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def schedule_from_row(row: Automation) -> AutomationSchedule:
    payload = _loads(row.schedule_json, {})
    payload["schedule_type"] = row.schedule_type
    payload["timezone"] = row.timezone
    return AutomationSchedule.model_validate(payload)


def allowed_tool_names(row: Automation) -> list[str]:
    return sorted(permission.tool_name for permission in row.tool_permissions if permission.allowed)


def validate_tool_names(names: list[str], *, background_scope: bool = False) -> list[str]:
    ensure_tools_registered()
    valid = {definition.name for definition in registry.all()}
    clean = sorted(set(name.strip() for name in names if name.strip()))
    unknown = [name for name in clean if name not in valid]
    if unknown:
        raise ValueError(f"Unknown automation tools: {', '.join(unknown)}")
    if background_scope:
        forbidden = sorted(set(clean) & BACKGROUND_FORBIDDEN_TOOLS)
        if forbidden:
            raise ValueError(
                "Automations cannot be granted automation-management tools: "
                + ", ".join(forbidden)
            )
    return clean


async def _set_tool_scope(session: AsyncSession, automation: Automation, names: list[str]) -> None:
    names = validate_tool_names(names, background_scope=True)
    await session.execute(
        delete(AutomationToolPermission).where(AutomationToolPermission.automation_id == automation.id)
    )
    for name in names:
        session.add(
            AutomationToolPermission(
                automation_id=automation.id,
                tool_name=name,
                allowed=True,
            )
        )
    await session.flush()


async def get_automation(session: AsyncSession, automation_id: str) -> Automation | None:
    result = await session.execute(
        select(Automation)
        .options(selectinload(Automation.tool_permissions))
        .where(Automation.id == automation_id)
    )
    return result.scalar_one_or_none()


async def list_automations(session: AsyncSession) -> list[Automation]:
    result = await session.execute(
        select(Automation)
        .options(selectinload(Automation.tool_permissions))
        .order_by(Automation.enabled.desc(), Automation.next_run_at.asc(), Automation.created_at.desc())
    )
    return list(result.scalars().all())


async def create_automation(
    session: AsyncSession,
    *,
    name: str,
    instruction: str,
    automation_type: str,
    schedule: AutomationSchedule,
    watcher_condition: str | None,
    allowed_tools: list[str],
    enabled: bool,
    notify_on_success: bool,
    notify_on_failure: bool,
    notify_on_condition: bool,
    timeout_seconds: int,
    model: str | None,
    reasoning_mode: str,
) -> Automation:
    if automation_type not in {"task", "watcher"}:
        raise ValueError("Invalid automation type.")
    if automation_type == "watcher" and not (watcher_condition or "").strip():
        raise ValueError("A watcher requires a condition describing when to notify you.")

    validate_schedule(schedule)
    timeout_seconds = max(30, min(int(timeout_seconds), settings.automation_max_timeout_seconds))

    automation = Automation(
        name=name.strip(),
        instruction=instruction.strip(),
        automation_type=automation_type,
        schedule_type=schedule.schedule_type,
        schedule_json=schedule_to_json(schedule),
        timezone=schedule.timezone,
        watcher_condition=(watcher_condition or "").strip() or None,
        enabled=enabled,
        notify_on_success=notify_on_success,
        notify_on_failure=notify_on_failure,
        notify_on_condition=notify_on_condition,
        timeout_seconds=timeout_seconds,
        model=(model or "").strip() or None,
        reasoning_mode=reasoning_mode,
    )
    session.add(automation)
    await session.flush()
    await _set_tool_scope(session, automation, allowed_tools)
    await session.commit()
    return (await get_automation(session, automation.id)) or automation


async def update_automation(
    session: AsyncSession,
    automation: Automation,
    *,
    name: str | None = None,
    instruction: str | None = None,
    automation_type: str | None = None,
    schedule: AutomationSchedule | None = None,
    watcher_condition: str | None = None,
    watcher_condition_provided: bool = False,
    allowed_tools: list[str] | None = None,
    enabled: bool | None = None,
    notify_on_success: bool | None = None,
    notify_on_failure: bool | None = None,
    notify_on_condition: bool | None = None,
    timeout_seconds: int | None = None,
    model: str | None = None,
    model_provided: bool = False,
    reasoning_mode: str | None = None,
) -> Automation:
    if name is not None:
        automation.name = name.strip()
    if instruction is not None:
        automation.instruction = instruction.strip()
    if automation_type is not None:
        if automation_type not in {"task", "watcher"}:
            raise ValueError("Invalid automation type.")
        automation.automation_type = automation_type
    if schedule is not None:
        validate_schedule(schedule)
        automation.schedule_type = schedule.schedule_type
        automation.schedule_json = schedule_to_json(schedule)
        automation.timezone = schedule.timezone
    if watcher_condition_provided:
        automation.watcher_condition = (watcher_condition or "").strip() or None
    if enabled is not None:
        automation.enabled = enabled
    if notify_on_success is not None:
        automation.notify_on_success = notify_on_success
    if notify_on_failure is not None:
        automation.notify_on_failure = notify_on_failure
    if notify_on_condition is not None:
        automation.notify_on_condition = notify_on_condition
    if timeout_seconds is not None:
        automation.timeout_seconds = max(30, min(int(timeout_seconds), settings.automation_max_timeout_seconds))
    if model_provided:
        automation.model = (model or "").strip() or None
    if reasoning_mode is not None:
        automation.reasoning_mode = reasoning_mode
    if allowed_tools is not None:
        await _set_tool_scope(session, automation, allowed_tools)

    if automation.automation_type == "watcher" and not (automation.watcher_condition or "").strip():
        raise ValueError("A watcher requires a condition describing when to notify you.")

    automation.updated_at = utc_now()
    await session.commit()
    return (await get_automation(session, automation.id)) or automation


async def delete_automation(session: AsyncSession, automation: Automation) -> None:
    await session.delete(automation)
    await session.commit()


async def create_run(
    session: AsyncSession,
    automation: Automation,
    *,
    trigger_type: str,
) -> AutomationRun:
    started_at = utc_now()
    run = AutomationRun(
        automation_id=automation.id,
        trigger_type=trigger_type,
        status="running",
        started_at=started_at,
        model=automation.model,
    )
    session.add(run)
    automation.last_run_at = started_at
    automation.last_status = "running"
    await session.commit()
    await session.refresh(run)
    return run


async def finish_run(
    session: AsyncSession,
    run: AutomationRun,
    automation: Automation,
    *,
    status: str,
    result: str | None = None,
    error: str | None = None,
    condition_met: bool | None = None,
    tool_names: list[str] | None = None,
    model: str | None = None,
) -> AutomationRun:
    now = utc_now()
    clean_result = (result or "")[: settings.automation_max_result_chars] or None
    run.status = status
    run.completed_at = now
    run.result = clean_result
    run.error = (error or "")[: settings.automation_max_result_chars] or None
    run.condition_met = condition_met
    run.tool_names_json = json.dumps(sorted(set(tool_names or [])), ensure_ascii=False)
    if model:
        run.model = model

    automation.last_run_at = run.started_at
    automation.last_status = status
    automation.last_result = clean_result or run.error
    automation.updated_at = now

    if (
        automation.schedule_type == "once"
        and run.trigger_type != "manual"
        and status != "running"
    ):
        automation.enabled = False
        automation.next_run_at = None

    await session.commit()
    await session.refresh(run)
    return run


async def list_runs(
    session: AsyncSession,
    automation_id: str,
    *,
    limit: int = 50,
) -> list[AutomationRun]:
    result = await session.execute(
        select(AutomationRun)
        .where(AutomationRun.automation_id == automation_id)
        .order_by(AutomationRun.started_at.desc())
        .limit(max(1, min(limit, settings.automation_run_history_limit)))
    )
    return list(result.scalars().all())


def run_tool_names(run: AutomationRun) -> list[str]:
    value = _loads(run.tool_names_json, [])
    return [str(item) for item in value] if isinstance(value, list) else []


async def create_notification(
    session: AsyncSession,
    *,
    automation_id: str,
    run_id: str | None,
    title: str,
    body: str,
    level: str = "info",
) -> AutomationNotification:
    notification = AutomationNotification(
        automation_id=automation_id,
        run_id=run_id,
        title=title[:240],
        body=body[:4_000],
        level=level,
    )
    session.add(notification)
    await session.commit()
    await session.refresh(notification)
    return notification


async def list_notifications(
    session: AsyncSession,
    *,
    unread_only: bool = True,
    limit: int = 100,
) -> list[AutomationNotification]:
    statement = select(AutomationNotification)
    if unread_only:
        statement = statement.where(AutomationNotification.read_at.is_(None))
    statement = statement.order_by(AutomationNotification.created_at.desc()).limit(max(1, min(limit, 500)))
    result = await session.execute(statement)
    return list(result.scalars().all())


async def mark_notification_read(session: AsyncSession, notification_id: str) -> AutomationNotification | None:
    row = await session.get(AutomationNotification, notification_id)
    if row is None:
        return None
    row.read_at = utc_now()
    await session.commit()
    await session.refresh(row)
    return row


async def mark_all_notifications_read(session: AsyncSession) -> int:
    result = await session.execute(
        select(AutomationNotification).where(AutomationNotification.read_at.is_(None))
    )
    rows = list(result.scalars().all())
    now = utc_now()
    for row in rows:
        row.read_at = now
    await session.commit()
    return len(rows)


async def automation_counts(session: AsyncSession) -> dict[str, int]:
    total = await session.scalar(select(func.count()).select_from(Automation)) or 0
    enabled = await session.scalar(
        select(func.count()).select_from(Automation).where(Automation.enabled.is_(True))
    ) or 0
    watchers = await session.scalar(
        select(func.count()).select_from(Automation).where(Automation.automation_type == "watcher")
    ) or 0
    unread = await session.scalar(
        select(func.count()).select_from(AutomationNotification).where(AutomationNotification.read_at.is_(None))
    ) or 0
    return {
        "automation_count": int(total),
        "enabled_count": int(enabled),
        "watcher_count": int(watchers),
        "unread_notifications": int(unread),
    }
