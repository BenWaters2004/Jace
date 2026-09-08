from __future__ import annotations

import json
from typing import Any, Literal

from pydantic import BaseModel, Field

from jace.config import settings
from jace.control.actions import (
    click_pointer,
    move_pointer,
    press_keys,
    run_blocking,
    scroll_pointer,
    type_text,
)
from jace.control.service import (
    ControlError,
    assert_session_active,
    complete_action_audit,
    create_action_audit,
    increment_step,
    list_windows_with_policy,
    require_window_interaction,
    require_window_observation,
    screenshot_result,
    start_session,
    stop_session,
)
from jace.control.windows import (
    DesktopControlUnavailable,
    absolute_point,
    active_window,
    focus_window,
    get_window,
    window_at_point,
)
from jace.tools.base import ToolContext, ToolDefinition, ToolExecutionResult
from jace.tools.registry import registry


class StartControlSessionInput(BaseModel):
    max_steps: int = Field(default=30, ge=1, le=80)
    store_screenshots: bool = Field(
        default=False,
        description=(
            "Whether action screenshots should also be persisted as conversation attachments. "
            "Images are still shown to the model during the live control loop when auto capture is enabled."
        ),
    )


async def start_control_session_tool(data: BaseModel, context: ToolContext) -> ToolExecutionResult:
    payload = data
    assert isinstance(payload, StartControlSessionInput)
    row = await start_session(
        context.session,
        conversation_id=context.conversation_id,
        max_steps=payload.max_steps,
        store_screenshots=payload.store_screenshots,
    )
    result = {
        "session_id": row.id,
        "status": row.status,
        "step_count": row.step_count,
        "max_steps": row.max_steps,
        "store_screenshots": row.store_screenshots,
        "safety": (
            "Only user-approved application policies can be interacted with. "
            "Sensitive actions require a separate one-time authorization from the Control screen."
        ),
    }
    return ToolExecutionResult(
        content=json.dumps(result, ensure_ascii=False),
        display=f"Interactive control session started ({row.max_steps} step limit).",
        metadata={"control_session_id": row.id},
    )


class ControlSessionInput(BaseModel):
    session_id: str = Field(min_length=36, max_length=36)


async def control_status_tool(data: BaseModel, context: ToolContext) -> ToolExecutionResult:
    payload = data
    assert isinstance(payload, ControlSessionInput)
    row = await assert_session_active(context.session, payload.session_id)
    result = {
        "session_id": row.id,
        "status": row.status,
        "step_count": row.step_count,
        "max_steps": row.max_steps,
        "remaining_steps": max(0, row.max_steps - row.step_count),
        "sensitive_authorized_once": row.sensitive_authorized_once,
    }
    return ToolExecutionResult(content=json.dumps(result), display="Control session is active.")


async def stop_control_session_tool(data: BaseModel, context: ToolContext) -> ToolExecutionResult:
    payload = data
    assert isinstance(payload, ControlSessionInput)
    row = await stop_session(context.session, payload.session_id, reason="Stopped by Jace/user request.")
    return ToolExecutionResult(
        content=json.dumps({"session_id": row.id, "status": row.status}),
        display="Interactive control session stopped.",
    )


class ListControlWindowsInput(BaseModel):
    include_blocked: bool = Field(
        default=False,
        description="Include absolutely blocked credential/secure-desktop windows in the returned list.",
    )


async def list_control_windows_tool(data: BaseModel, context: ToolContext) -> ToolExecutionResult:
    payload = data
    assert isinstance(payload, ListControlWindowsInput)
    try:
        windows = await list_windows_with_policy(context.session)
    except DesktopControlUnavailable as exc:
        raise ControlError(str(exc)) from exc
    # Blocked credential/secure-desktop windows are never exposed to the model,
    # even if it attempts to request them explicitly. They remain visible only
    # to the local user in the Control management screen.
    windows = [item for item in windows if not item["blocked"]]
    return ToolExecutionResult(
        content=json.dumps({"windows": windows[:80]}, ensure_ascii=False),
        display=f"Found {len(windows)} visible application window(s).",
    )


class FocusWindowInput(ControlSessionInput):
    window_handle: int = Field(ge=1)
    action_intent: str = Field(
        min_length=3,
        max_length=300,
        description="Short plain-English reason for focusing this window.",
    )


async def focus_control_window_tool(data: BaseModel, context: ToolContext) -> ToolExecutionResult:
    payload = data
    assert isinstance(payload, FocusWindowInput)
    control = await assert_session_active(context.session, payload.session_id)
    window = await run_blocking(get_window, payload.window_handle)
    await require_window_interaction(context.session, control, window, intent=payload.action_intent)
    audit = await create_action_audit(
        context.session,
        control_session=control,
        action_type="focus_window",
        window=window,
        arguments=payload.model_dump(),
    )
    try:
        focused = await run_blocking(focus_window, payload.window_handle)
        await increment_step(context.session, control)
        images: list[str] | None = None
        attachment_id = None
        if settings.interactive_auto_capture_after_action:
            image, attachment_id = await screenshot_result(
                context.session,
                control,
                window=focused,
                name="control-focus.png",
            )
            images = [image]
        await complete_action_audit(
            context.session,
            audit,
            status="completed",
            result_preview=f'Focused {focused.process_name}: {focused.title}',
            screenshot_attachment_id=attachment_id,
        )
        return ToolExecutionResult(
            content=json.dumps({"window": focused.to_dict(), "step_count": control.step_count}),
            display=f'Focused "{focused.title}".',
            images=images,
        )
    except Exception as exc:
        await complete_action_audit(context.session, audit, status="failed", result_preview=str(exc))
        raise


class CaptureControlScreenInput(ControlSessionInput):
    window_handle: int = Field(
        ge=1,
        description=(
            "Exact visible window handle to capture. Phase 9 deliberately does not expose the whole desktop; "
            "the window must be observation-approved in the Control screen."
        ),
    )


async def capture_control_screen_tool(data: BaseModel, context: ToolContext) -> ToolExecutionResult:
    payload = data
    assert isinstance(payload, CaptureControlScreenInput)
    control = await assert_session_active(context.session, payload.session_id)
    window = await run_blocking(get_window, payload.window_handle)
    await require_window_observation(context.session, control, window)
    image, attachment_id = await screenshot_result(
        context.session,
        control,
        window=window,
        name="control-observe.png",
    )
    await increment_step(context.session, control)
    metadata: dict[str, Any] = {
        "session_id": control.id,
        "step_count": control.step_count,
        "coordinate_space": "window",
    }
    metadata["window"] = window.to_dict()
    return ToolExecutionResult(
        content=json.dumps(metadata, ensure_ascii=False),
        display="Captured the approved control view.",
        metadata={"attachment_id": attachment_id} if attachment_id else None,
        images=[image],
    )


CoordinateSpace = Literal["screen", "window"]


class PointerInput(ControlSessionInput):
    x: int = Field(ge=-20_000, le=40_000)
    y: int = Field(ge=-20_000, le=40_000)
    coordinate_space: CoordinateSpace = "window"
    window_handle: int | None = Field(default=None, ge=1)
    action_intent: str = Field(min_length=3, max_length=300)


async def _target_for_pointer(payload: PointerInput):
    x, y = await run_blocking(
        absolute_point,
        x=payload.x,
        y=payload.y,
        coordinate_space=payload.coordinate_space,
        window_handle=payload.window_handle,
    )
    target = await run_blocking(window_at_point, x, y)
    return x, y, target


class MovePointerInput(PointerInput):
    duration_ms: int = Field(default=150, ge=0, le=2000)


async def move_control_pointer_tool(data: BaseModel, context: ToolContext) -> ToolExecutionResult:
    payload = data
    assert isinstance(payload, MovePointerInput)
    control = await assert_session_active(context.session, payload.session_id)
    x, y, target = await _target_for_pointer(payload)
    await require_window_interaction(context.session, control, target, intent=payload.action_intent)
    audit = await create_action_audit(
        context.session, control_session=control, action_type="move_pointer", window=target,
        arguments={**payload.model_dump(), "absolute_x": x, "absolute_y": y},
    )
    try:
        await run_blocking(move_pointer, x, y, payload.duration_ms)
        await increment_step(context.session, control)
        await complete_action_audit(context.session, audit, status="completed", result_preview=f"Pointer moved to {x},{y}.")
        return ToolExecutionResult(
            content=json.dumps({"x": x, "y": y, "step_count": control.step_count}),
            display=f"Moved pointer to {x}, {y}.",
        )
    except Exception as exc:
        await complete_action_audit(context.session, audit, status="failed", result_preview=str(exc))
        raise


class ClickInput(PointerInput):
    button: Literal["left", "right", "middle"] = "left"
    clicks: int = Field(default=1, ge=1, le=2)


async def click_control_tool(data: BaseModel, context: ToolContext) -> ToolExecutionResult:
    payload = data
    assert isinstance(payload, ClickInput)
    control = await assert_session_active(context.session, payload.session_id)
    x, y, target = await _target_for_pointer(payload)
    await require_window_interaction(
        context.session, control, target,
        intent=f"{context.user_message}\n{payload.action_intent}",
    )
    audit = await create_action_audit(
        context.session, control_session=control, action_type="click", window=target,
        arguments={**payload.model_dump(), "absolute_x": x, "absolute_y": y},
    )
    try:
        await run_blocking(click_pointer, x, y, button=payload.button, clicks=payload.clicks)
        await increment_step(context.session, control)
        images = None
        attachment_id = None
        post_window = await run_blocking(active_window)
        if settings.interactive_auto_capture_after_action:
            image, attachment_id = await screenshot_result(
                context.session, control, window=post_window, name="control-click.png"
            )
            images = [image]
        await complete_action_audit(
            context.session, audit, status="completed",
            result_preview=f"{payload.button} click x{payload.clicks} at {x},{y}.",
            screenshot_attachment_id=attachment_id,
        )
        return ToolExecutionResult(
            content=json.dumps({"x": x, "y": y, "active_window": post_window.to_dict() if post_window else None, "step_count": control.step_count}),
            display=f"Clicked at {x}, {y}.",
            images=images,
        )
    except Exception as exc:
        await complete_action_audit(context.session, audit, status="failed", result_preview=str(exc))
        raise


class ScrollInput(PointerInput):
    amount: int = Field(ge=-20, le=20, description="Positive scrolls up; negative scrolls down.")


async def scroll_control_tool(data: BaseModel, context: ToolContext) -> ToolExecutionResult:
    payload = data
    assert isinstance(payload, ScrollInput)
    control = await assert_session_active(context.session, payload.session_id)
    x, y, target = await _target_for_pointer(payload)
    await require_window_interaction(context.session, control, target, intent=payload.action_intent)
    audit = await create_action_audit(
        context.session, control_session=control, action_type="scroll", window=target,
        arguments={**payload.model_dump(), "absolute_x": x, "absolute_y": y},
    )
    try:
        await run_blocking(scroll_pointer, x, y, payload.amount)
        await increment_step(context.session, control)
        images = None
        attachment_id = None
        if settings.interactive_auto_capture_after_action:
            post_window = await run_blocking(active_window)
            image, attachment_id = await screenshot_result(
                context.session, control, window=post_window, name="control-scroll.png"
            )
            images = [image]
        await complete_action_audit(
            context.session, audit, status="completed", result_preview=f"Scrolled {payload.amount} at {x},{y}.",
            screenshot_attachment_id=attachment_id,
        )
        return ToolExecutionResult(
            content=json.dumps({"amount": payload.amount, "step_count": control.step_count}),
            display=f"Scrolled {payload.amount} wheel step(s).",
            images=images,
        )
    except Exception as exc:
        await complete_action_audit(context.session, audit, status="failed", result_preview=str(exc))
        raise


class TypeTextInput(ControlSessionInput):
    text: str = Field(min_length=1, max_length=4000)
    action_intent: str = Field(min_length=3, max_length=300)


async def type_control_text_tool(data: BaseModel, context: ToolContext) -> ToolExecutionResult:
    payload = data
    assert isinstance(payload, TypeTextInput)
    if len(payload.text) > settings.interactive_max_text_chars:
        raise ControlError("The requested text is too long for one interactive typing action.")
    control = await assert_session_active(context.session, payload.session_id)
    target = await run_blocking(active_window)
    await require_window_interaction(
        context.session, control, target,
        intent=f"{context.user_message}\n{payload.action_intent}", typed_text=payload.text,
    )
    audit = await create_action_audit(
        context.session, control_session=control, action_type="type_text", window=target,
        # Do not place the full typed text into the dedicated action audit; the
        # generic tool audit already records user-approved arguments.
        arguments={"session_id": payload.session_id, "text_length": len(payload.text), "action_intent": payload.action_intent},
    )
    try:
        await run_blocking(type_text, payload.text)
        await increment_step(context.session, control)
        images = None
        attachment_id = None
        if settings.interactive_auto_capture_after_action:
            post_window = await run_blocking(active_window)
            image, attachment_id = await screenshot_result(
                context.session, control, window=post_window, name="control-type.png"
            )
            images = [image]
        await complete_action_audit(
            context.session, audit, status="completed", result_preview=f"Typed {len(payload.text)} character(s).",
            screenshot_attachment_id=attachment_id,
        )
        return ToolExecutionResult(
            content=json.dumps({"typed_characters": len(payload.text), "step_count": control.step_count}),
            display=f"Typed {len(payload.text)} character(s).",
            images=images,
        )
    except Exception as exc:
        await complete_action_audit(context.session, audit, status="failed", result_preview=str(exc))
        raise


class PressKeysInput(ControlSessionInput):
    keys: list[str] = Field(min_length=1, max_length=5)
    action_intent: str = Field(min_length=3, max_length=300)


async def press_control_keys_tool(data: BaseModel, context: ToolContext) -> ToolExecutionResult:
    payload = data
    assert isinstance(payload, PressKeysInput)
    control = await assert_session_active(context.session, payload.session_id)
    target = await run_blocking(active_window)
    await require_window_interaction(
        context.session, control, target,
        intent=f"{context.user_message}\n{payload.action_intent}", keys=payload.keys,
    )
    audit = await create_action_audit(
        context.session, control_session=control, action_type="press_keys", window=target,
        arguments=payload.model_dump(),
    )
    try:
        await run_blocking(press_keys, payload.keys)
        await increment_step(context.session, control)
        images = None
        attachment_id = None
        if settings.interactive_auto_capture_after_action:
            post_window = await run_blocking(active_window)
            image, attachment_id = await screenshot_result(
                context.session, control, window=post_window, name="control-keys.png"
            )
            images = [image]
        await complete_action_audit(
            context.session, audit, status="completed",
            result_preview="Pressed " + "+".join(payload.keys), screenshot_attachment_id=attachment_id,
        )
        return ToolExecutionResult(
            content=json.dumps({"keys": payload.keys, "step_count": control.step_count}),
            display="Pressed " + "+".join(payload.keys) + ".",
            images=images,
        )
    except Exception as exc:
        await complete_action_audit(context.session, audit, status="failed", result_preview=str(exc))
        raise


def register_interactive_tools() -> None:
    if not settings.interactive_control_enabled:
        return

    definitions = [
        ToolDefinition(
            name="start_control_session",
            label="Start interactive control",
            description=(
                "Start a short-lived local GUI-control session. This does not itself grant access to any application; "
                "only apps approved in Jace's Control screen can be interacted with."
            ),
            category="Interactive control",
            risk="execute",
            default_permission="ask",
            input_model=StartControlSessionInput,
            handler=start_control_session_tool,
        ),
        ToolDefinition(
            name="control_status",
            label="Control session status",
            description="Check remaining steps and state for an existing interactive control session.",
            category="Interactive control",
            risk="read",
            default_permission="allow",
            input_model=ControlSessionInput,
            handler=control_status_tool,
        ),
        ToolDefinition(
            name="list_control_windows",
            label="List application windows",
            description="List visible local application windows and whether each has an observation/interaction policy.",
            category="Interactive control",
            risk="read",
            default_permission="allow",
            input_model=ListControlWindowsInput,
            handler=list_control_windows_tool,
        ),
        ToolDefinition(
            name="focus_control_window",
            label="Focus application window",
            description="Bring one user-approved application window to the foreground inside an active control session.",
            category="Interactive control",
            risk="execute",
            default_permission="allow",
            input_model=FocusWindowInput,
            handler=focus_control_window_tool,
        ),
        ToolDefinition(
            name="capture_control_screen",
            label="Observe control screen",
            description=(
                "Capture one observation-approved application window inside an active control session. "
                "Whole-desktop capture is deliberately unavailable so unapproved windows are not exposed. "
                "The returned image provides window-relative coordinates for subsequent actions."
            ),
            category="Interactive control",
            risk="read",
            default_permission="allow",
            input_model=CaptureControlScreenInput,
            handler=capture_control_screen_tool,
        ),
        ToolDefinition(
            name="move_control_pointer",
            label="Move mouse pointer",
            description="Move the pointer inside a user-approved application. Does not click.",
            category="Interactive control",
            risk="execute",
            default_permission="allow",
            input_model=MovePointerInput,
            handler=move_control_pointer_tool,
        ),
        ToolDefinition(
            name="click_control",
            label="Click application UI",
            description=(
                "Click a point in an approved application. action_intent must accurately describe what will be clicked; "
                "sensitive intents/screens require a one-time authorization."
            ),
            category="Interactive control",
            risk="execute",
            default_permission="allow",
            input_model=ClickInput,
            handler=click_control_tool,
        ),
        ToolDefinition(
            name="scroll_control",
            label="Scroll application UI",
            description="Scroll at a point in an approved application and return an updated screenshot when configured.",
            category="Interactive control",
            risk="execute",
            default_permission="allow",
            input_model=ScrollInput,
            handler=scroll_control_tool,
        ),
        ToolDefinition(
            name="type_control_text",
            label="Type into application",
            description=(
                "Type ordinary non-secret text into the currently focused approved application. Jace refuses detected credentials, "
                "private keys and payment-card data. Sensitive screens require one-time authorization."
            ),
            category="Interactive control",
            risk="execute",
            default_permission="allow",
            input_model=TypeTextInput,
            handler=type_control_text_tool,
        ),
        ToolDefinition(
            name="press_control_keys",
            label="Press application keys",
            description=(
                "Press a key or hotkey in the currently focused approved application. Enter/submission or destructive shortcuts "
                "may require a one-time sensitive authorization."
            ),
            category="Interactive control",
            risk="execute",
            default_permission="allow",
            input_model=PressKeysInput,
            handler=press_control_keys_tool,
        ),
        ToolDefinition(
            name="stop_control_session",
            label="Stop interactive control",
            description="Stop an active GUI-control session. Further GUI actions require a new session.",
            category="Interactive control",
            risk="execute",
            default_permission="allow",
            input_model=ControlSessionInput,
            handler=stop_control_session_tool,
        ),
    ]

    for definition in definitions:
        registry.register(definition)
