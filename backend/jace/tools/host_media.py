from __future__ import annotations

# JACE_STEP4B2_V3_HOST_MEDIA

import json
from pathlib import Path

from pydantic import BaseModel, Field

from jace.attachments.processors import prepare_attachment
from jace.attachments.service import (
    AttachmentError,
    create_attachment_from_bytes,
    media_kind_for_name,
)
from jace.computer.host_access import HostPathError, expand_host_path
from jace.config import settings
from jace.tools.base import (
    ToolContext,
    ToolDefinition,
    ToolError,
    ToolExecutionResult,
)
from jace.tools.registry import registry


class InspectHostMediaInput(BaseModel):
    path: str = Field(
        min_length=1,
        max_length=2000,
        description=(
            "Absolute host path, or a path relative to the current user's home, "
            "for an image, PDF/document, DOCX, or audio file."
        ),
    )


async def inspect_host_media_tool(
    data: BaseModel,
    context: ToolContext,
) -> ToolExecutionResult:
    payload = data
    assert isinstance(
        payload,
        InspectHostMediaInput,
    )

    if not context.conversation_id:
        raise ToolError(
            "There is no active conversation for the inspected host file."
        )

    try:
        path = expand_host_path(
            payload.path,
            must_exist=True,
        )
    except HostPathError as exc:
        raise ToolError(
            str(exc)
        ) from exc

    if not path.is_file():
        raise ToolError(
            "The requested host path is not a file."
        )

    try:
        media_kind_for_name(
            path.name
        )
    except AttachmentError as exc:
        raise ToolError(
            "That file is not a supported image, PDF/document, DOCX, or audio "
            "file. Use read_host_file for ordinary text files."
        ) from exc

    try:
        data_bytes = path.read_bytes()
    except OSError as exc:
        raise ToolError(
            "Could not read the requested host media file."
        ) from exc

    try:
        attachment = await create_attachment_from_bytes(
            context.session,
            conversation_id=context.conversation_id,
            original_name=path.name,
            data=data_bytes,
            source_type="host_file",
            source_path=str(path),
        )
        prepared = await prepare_attachment(
            context.session,
            attachment,
        )
    except Exception as exc:
        raise ToolError(
            str(exc)
        ) from exc

    result = {
        "attachment_id":
            attachment.id,
        "path":
            str(path),
        "name":
            attachment.original_name,
        "kind":
            attachment.media_kind,
        "context":
            prepared.context,
        "image_count":
            len(
                prepared.images
            ),
        "metadata":
            prepared.metadata,
    }

    return ToolExecutionResult(
        content=json.dumps(
            result,
            ensure_ascii=False,
        ),
        display=(
            f"Inspected host file {path} as "
            f"{attachment.media_kind}."
        ),
        metadata={
            "attachment_id":
                attachment.id,
            "kind":
                attachment.media_kind,
            "path":
                str(path),
        },
        images=prepared.images or None,
    )


def register_host_media_tools() -> None:
    if (
        not settings.computer_enabled
        or not settings.multimodal_enabled
    ):
        return

    registry.register(
        ToolDefinition(
            name="inspect_host_media",
            label="Inspect host media/document",
            description=(
                "Inspect an image, PDF, DOCX/document or audio file anywhere "
                "the current OS user can access. For images, the actual pixels "
                "are passed to the vision-capable model. For DOCX/PDF/document "
                "files, text is extracted through Jace's attachment processor."
            ),
            category="Computer",
            risk="read",
            default_permission="allow",
            input_model=InspectHostMediaInput,
            handler=inspect_host_media_tool,
        ),
        replace=True,
    )
