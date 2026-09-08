from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel, Field

from jace.attachments.processors import prepare_attachment
from jace.attachments.service import (
    AttachmentError,
    create_attachment_from_bytes,
    get_attachment,
    latest_conversation_attachment,
    media_kind_for_name,
)
from jace.computer.security import ComputerPathError, relative_display, resolve_workspace_path
from jace.computer.service import ensure_workspace_readable, get_workspace
from jace.config import settings
from jace.tools.base import ToolContext, ToolDefinition, ToolError, ToolExecutionResult
from jace.tools.registry import registry


class InspectAttachmentInput(BaseModel):
    attachment_id: str | None = Field(
        default=None,
        description=(
            "Exact attachment ID when known. Omit it to inspect the most recent attachment "
            "in the current conversation."
        ),
    )


async def inspect_attachment_tool(data: BaseModel, context: ToolContext) -> ToolExecutionResult:
    payload = data
    assert isinstance(payload, InspectAttachmentInput)
    if not context.conversation_id:
        raise ToolError("There is no active conversation attachment context.")

    if payload.attachment_id:
        attachment = await get_attachment(context.session, payload.attachment_id)
        if attachment is None or attachment.conversation_id != context.conversation_id:
            raise ToolError("That attachment is not available in the active conversation.")
    else:
        attachment = await latest_conversation_attachment(context.session, context.conversation_id)
        if attachment is None:
            raise ToolError("This conversation has no attachments to inspect.")

    try:
        prepared = await prepare_attachment(context.session, attachment)
    except Exception as exc:
        raise ToolError(str(exc)) from exc

    payload_result = {
        "attachment_id": attachment.id,
        "name": attachment.original_name,
        "kind": attachment.media_kind,
        "source_type": attachment.source_type,
        "source_path": attachment.source_path,
        "context": prepared.context,
        "image_count": len(prepared.images),
        "metadata": prepared.metadata,
    }
    return ToolExecutionResult(
        content=json.dumps(payload_result, ensure_ascii=False),
        display=f'Inspected attachment "{attachment.original_name}".',
        metadata={"attachment_id": attachment.id, "kind": attachment.media_kind},
        images=prepared.images or None,
    )


class InspectWorkspaceMediaInput(BaseModel):
    workspace_id: str = Field(min_length=36, max_length=36)
    path: str = Field(min_length=1, max_length=800)


async def inspect_workspace_media_tool(data: BaseModel, context: ToolContext) -> ToolExecutionResult:
    payload = data
    assert isinstance(payload, InspectWorkspaceMediaInput)
    if not context.conversation_id:
        raise ToolError("There is no active conversation for the inspected media.")

    workspace = await get_workspace(context.session, payload.workspace_id)
    if workspace is None:
        raise ToolError("Unknown computer workspace. Call list_computer_workspaces first.")
    try:
        ensure_workspace_readable(workspace)
        root, path = resolve_workspace_path(workspace.root_path, payload.path, must_exist=True)
    except ComputerPathError as exc:
        raise ToolError(str(exc)) from exc

    if not path.is_file():
        raise ToolError("The requested workspace path is not a file.")

    try:
        media_kind_for_name(path.name)
    except AttachmentError as exc:
        raise ToolError(
            "That file is not a supported image, PDF/document, or audio attachment. "
            "Use read_workspace_file for ordinary text files."
        ) from exc

    try:
        data_bytes = path.read_bytes()
    except OSError as exc:
        raise ToolError("Could not read the workspace media file.") from exc

    relative = relative_display(root, path)
    try:
        attachment = await create_attachment_from_bytes(
            context.session,
            conversation_id=context.conversation_id,
            original_name=path.name,
            data=data_bytes,
            source_type="workspace",
            source_path=f"{workspace.label}:{relative}",
        )
        prepared = await prepare_attachment(context.session, attachment)
    except Exception as exc:
        raise ToolError(str(exc)) from exc

    result = {
        "attachment_id": attachment.id,
        "workspace": workspace.label,
        "path": relative,
        "kind": attachment.media_kind,
        "context": prepared.context,
        "image_count": len(prepared.images),
        "metadata": prepared.metadata,
    }
    return ToolExecutionResult(
        content=json.dumps(result, ensure_ascii=False),
        display=f"Inspected {workspace.label}:{relative} as {attachment.media_kind}.",
        metadata={"attachment_id": attachment.id, "kind": attachment.media_kind},
        images=prepared.images or None,
    )


class CaptureScreenInput(BaseModel):
    monitor: int = Field(
        default=1,
        ge=0,
        le=8,
        description=(
            "Monitor number. 1 is normally the primary physical monitor. "
            "Use 0 only when the user asks for the combined virtual desktop."
        ),
    )


async def capture_screen_tool(data: BaseModel, context: ToolContext) -> ToolExecutionResult:
    payload = data
    assert isinstance(payload, CaptureScreenInput)
    if not settings.screen_capture_enabled:
        raise ToolError("Screen capture is disabled.")
    if not context.conversation_id:
        raise ToolError("There is no active conversation to receive the screenshot.")

    try:
        import mss
        import mss.tools
    except ImportError as exc:
        raise ToolError("Screen capture dependency is not installed.") from exc

    try:
        with mss.mss() as capture:
            if payload.monitor >= len(capture.monitors):
                raise ToolError(
                    f"Monitor {payload.monitor} is unavailable; this computer reports "
                    f"{max(0, len(capture.monitors) - 1)} physical monitor(s)."
                )
            monitor = capture.monitors[payload.monitor]
            shot = capture.grab(monitor)
            png = mss.tools.to_png(shot.rgb, shot.size)
    except ToolError:
        raise
    except Exception as exc:
        raise ToolError(f"Could not capture the screen: {exc}") from exc

    attachment = await create_attachment_from_bytes(
        context.session,
        conversation_id=context.conversation_id,
        original_name="screen-capture.png",
        data=png,
        mime_type="image/png",
        source_type="screen_capture",
        source_path=f"monitor:{payload.monitor}",
    )
    prepared = await prepare_attachment(context.session, attachment)
    result = {
        "attachment_id": attachment.id,
        "monitor": payload.monitor,
        "name": attachment.original_name,
        "kind": "image",
        "width": prepared.metadata.get("width"),
        "height": prepared.metadata.get("height"),
    }
    return ToolExecutionResult(
        content=json.dumps(result, ensure_ascii=False),
        display=f"Captured monitor {payload.monitor}.",
        metadata={"attachment_id": attachment.id},
        images=prepared.images,
    )


def register_multimodal_tools() -> None:
    if not settings.multimodal_enabled:
        return

    definitions = [
        ToolDefinition(
            name="inspect_attachment",
            label="Inspect attachment",
            description=(
                "Re-open and inspect an image, PDF/document or audio attachment from the current "
                "conversation. Omit attachment_id to inspect the most recent attachment."
            ),
            category="Multimodal",
            risk="read",
            default_permission="allow",
            input_model=InspectAttachmentInput,
            handler=inspect_attachment_tool,
        ),
        ToolDefinition(
            name="inspect_workspace_media",
            label="Inspect workspace media",
            description=(
                "Inspect an image, PDF/document or audio file inside one approved computer workspace. "
                "The workspace must allow reads and normal workspace path protections still apply."
            ),
            category="Multimodal",
            risk="read",
            default_permission="ask",
            input_model=InspectWorkspaceMediaInput,
            handler=inspect_workspace_media_tool,
        ),
    ]

    if settings.screen_capture_enabled:
        definitions.append(
            ToolDefinition(
                name="capture_screen",
                label="Capture screen",
                description=(
                    "Capture a screenshot of a local monitor so Jace can visually inspect what is "
                    "currently displayed. This is a privacy-sensitive read and requires permission."
                ),
                category="Multimodal",
                risk="read",
                default_permission="ask",
                input_model=CaptureScreenInput,
                handler=capture_screen_tool,
            )
        )

    for definition in definitions:
        registry.register(definition)
