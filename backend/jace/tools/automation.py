import json
from typing import Literal

from pydantic import BaseModel, Field

from jace.automations.scheduler import reschedule_automation, run_automation_now
from jace.automations.service import (
    allowed_tool_names,
    create_automation,
    get_automation,
    list_automations,
    schedule_from_row,
    update_automation,
)
from jace.schemas import AutomationSchedule
from jace.tools.base import ToolContext, ToolDefinition, ToolError, ToolExecutionResult
from jace.tools.registry import registry


class ListAutomationsInput(BaseModel):
    include_disabled: bool = True


async def list_automations_tool(data: BaseModel, context: ToolContext) -> ToolExecutionResult:
    payload = data
    assert isinstance(payload, ListAutomationsInput)
    rows = await list_automations(context.session)
    if not payload.include_disabled:
        rows = [row for row in rows if row.enabled]
    result = [
        {
            "id": row.id,
            "name": row.name,
            "type": row.automation_type,
            "enabled": row.enabled,
            "schedule": schedule_from_row(row).model_dump(mode="json"),
            "watcher_condition": row.watcher_condition,
            "allowed_tools": allowed_tool_names(row),
            "next_run_at": row.next_run_at.isoformat() if row.next_run_at else None,
            "last_status": row.last_status,
        }
        for row in rows[:30]
    ]
    return ToolExecutionResult(
        content=json.dumps({"automations": result}, ensure_ascii=False),
        display=f"Found {len(result)} automation{'s' if len(result) != 1 else ''}.",
    )


class CreateAutomationInput(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    instruction: str = Field(min_length=1, max_length=20_000)
    automation_type: Literal["task", "watcher"] = "task"
    schedule: AutomationSchedule
    watcher_condition: str | None = Field(default=None, max_length=5_000)
    allowed_tools: list[str] = Field(default_factory=list, max_length=40)
    notify_on_success: bool = True
    notify_on_failure: bool = True
    notify_on_condition: bool = True
    timeout_seconds: int = Field(default=300, ge=30, le=1800)


async def create_automation_tool(data: BaseModel, context: ToolContext) -> ToolExecutionResult:
    payload = data
    assert isinstance(payload, CreateAutomationInput)
    try:
        row = await create_automation(
            context.session,
            name=payload.name,
            instruction=payload.instruction,
            automation_type=payload.automation_type,
            schedule=payload.schedule,
            watcher_condition=payload.watcher_condition,
            allowed_tools=payload.allowed_tools,
            enabled=True,
            notify_on_success=payload.notify_on_success,
            notify_on_failure=payload.notify_on_failure,
            notify_on_condition=payload.notify_on_condition,
            timeout_seconds=payload.timeout_seconds,
            model=None,
            reasoning_mode="fast",
        )
    except ValueError as exc:
        raise ToolError(str(exc)) from exc

    await reschedule_automation(row.id)
    return ToolExecutionResult(
        content=json.dumps(
            {
                "automation_id": row.id,
                "name": row.name,
                "enabled": row.enabled,
                "schedule": schedule_from_row(row).model_dump(mode="json"),
                "allowed_tools": allowed_tool_names(row),
            },
            ensure_ascii=False,
        ),
        display=f'Created automation "{row.name}".',
    )


class SetAutomationEnabledInput(BaseModel):
    automation_id: str = Field(min_length=36, max_length=36)
    enabled: bool


async def set_automation_enabled_tool(data: BaseModel, context: ToolContext) -> ToolExecutionResult:
    payload = data
    assert isinstance(payload, SetAutomationEnabledInput)
    row = await get_automation(context.session, payload.automation_id)
    if row is None:
        raise ToolError("Automation not found.")
    row = await update_automation(context.session, row, enabled=payload.enabled)
    await reschedule_automation(row.id)
    return ToolExecutionResult(
        content=json.dumps({"automation_id": row.id, "name": row.name, "enabled": row.enabled}),
        display=f'{"Enabled" if row.enabled else "Disabled"} automation "{row.name}".',
    )


class RunAutomationNowInput(BaseModel):
    automation_id: str = Field(min_length=36, max_length=36)


async def run_automation_now_tool(data: BaseModel, context: ToolContext) -> ToolExecutionResult:
    payload = data
    assert isinstance(payload, RunAutomationNowInput)
    row = await get_automation(context.session, payload.automation_id)
    if row is None:
        raise ToolError("Automation not found.")
    await run_automation_now(row.id)
    return ToolExecutionResult(
        content=json.dumps({"automation_id": row.id, "accepted": True}),
        display=f'Started automation "{row.name}".',
    )


def register_automation_tools() -> None:
    definitions = [
        ToolDefinition(
            name="list_automations",
            label="List automations",
            description="List Jace's configured scheduled tasks and condition watchers.",
            category="Automation",
            risk="read",
            default_permission="allow",
            input_model=ListAutomationsInput,
            handler=list_automations_tool,
        ),
        ToolDefinition(
            name="create_automation",
            label="Create automation",
            description=(
                "Create a persistent scheduled task or watcher. The arguments include the schedule and exact "
                "background tool capabilities, so review them before approval."
            ),
            category="Automation",
            risk="write",
            default_permission="ask",
            input_model=CreateAutomationInput,
            handler=create_automation_tool,
        ),
        ToolDefinition(
            name="set_automation_enabled",
            label="Enable or disable automation",
            description="Enable or disable one existing automation by exact ID.",
            category="Automation",
            risk="write",
            default_permission="ask",
            input_model=SetAutomationEnabledInput,
            handler=set_automation_enabled_tool,
        ),
        ToolDefinition(
            name="run_automation_now",
            label="Run automation now",
            description="Start one existing automation immediately by exact ID.",
            category="Automation",
            risk="execute",
            default_permission="ask",
            input_model=RunAutomationNowInput,
            handler=run_automation_now_tool,
        ),
    ]
    for definition in definitions:
        registry.register(definition)
