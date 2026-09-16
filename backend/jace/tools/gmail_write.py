from __future__ import annotations

# JACE_STEP4C3_GMAIL_WRITE

import base64
import json
from email.message import EmailMessage
from typing import Any

import httpx
from pydantic import BaseModel

from jace.tools.base import (
    ToolContext,
    ToolDefinition,
    ToolError,
    ToolExecutionResult,
)
from jace.tools.email_common import (
    EmailComposeInput,
    EmailSendInput,
    plain_text_from_html,
    recipients_summary,
)
from jace.tools.gmail import (
    GMAIL_API,
    HTTP_TIMEOUT_SECONDS,
    _google_access_token,
)
from jace.tools.registry import registry


def _mime_message(
    data: EmailComposeInput | EmailSendInput,
) -> str:
    message = EmailMessage()

    if data.to:
        message["To"] = ", ".join(
            data.to
        )

    if data.cc:
        message["Cc"] = ", ".join(
            data.cc
        )

    if data.bcc:
        message["Bcc"] = ", ".join(
            data.bcc
        )

    message["Subject"] = (
        data.subject
    )

    if data.body_format == "html":
        fallback = (
            plain_text_from_html(
                data.body
            )
            or " "
        )
        message.set_content(
            fallback
        )
        message.add_alternative(
            data.body,
            subtype="html",
        )
    else:
        message.set_content(
            data.body
        )

    return base64.urlsafe_b64encode(
        message.as_bytes()
    ).decode("ascii")


def _gmail_write_error(
    response: httpx.Response,
    fallback: str,
) -> ToolError:
    detail = ""

    try:
        payload = response.json()
    except ValueError:
        payload = None

    if isinstance(payload, dict):
        raw_error = payload.get("error")

        if isinstance(raw_error, dict):
            raw_message = raw_error.get("message")
            if isinstance(raw_message, str):
                detail = raw_message.strip()
        elif isinstance(raw_error, str):
            detail = raw_error.strip()

    detail = detail[:500]

    if response.status_code == 401:
        return ToolError(
            "Google rejected the current access token. Reconnect this "
            "Google account in Settings > Connections."
        )

    if response.status_code == 403:
        return ToolError(
            "Google denied this Gmail write action. Reconnect the Google "
            "account and confirm Jace has gmail.compose for drafts and "
            "gmail.send for sending."
        )

    return ToolError(
        detail or fallback
    )


async def _gmail_post(
    access_token: str,
    path: str,
    payload: dict[str, Any] | None,
    *,
    empty_ok: bool = False,
) -> dict[str, Any]:
    headers = {
        "Authorization": (
            f"Bearer {access_token}"
        ),
        "Accept": "application/json",
        "Content-Type": "application/json",
        "User-Agent": "Jace-Desktop",
    }

    async with httpx.AsyncClient(
        timeout=HTTP_TIMEOUT_SECONDS,
    ) as client:
        response = await client.post(
            f"{GMAIL_API}{path}",
            headers=headers,
            json=payload,
        )

    if response.status_code >= 400:
        raise _gmail_write_error(
            response,
            "Gmail write request failed.",
        )

    if (
        empty_ok
        and not response.content
    ):
        return {}

    try:
        result = response.json()
    except ValueError as exc:
        if empty_ok:
            return {}

        raise ToolError(
            "Gmail returned an unreadable write response."
        ) from exc

    if not isinstance(
        result,
        dict,
    ):
        raise ToolError(
            "Gmail returned an unexpected write response."
        )

    return result


async def gmail_create_draft_tool(
    data: BaseModel,
    context: ToolContext,
) -> ToolExecutionResult:
    payload = data
    assert isinstance(
        payload,
        EmailComposeInput,
    )

    access_token, account = (
        await _google_access_token(
            context
        )
    )

    result = await _gmail_post(
        access_token,
        "/users/me/drafts",
        {
            "message": {
                "raw": _mime_message(
                    payload
                ),
            },
        },
    )

    draft_id = result.get("id")
    message = result.get("message")
    message_id = (
        message.get("id")
        if isinstance(message, dict)
        else None
    )

    response = {
        "account": account,
        "draft_id": draft_id,
        "message_id": message_id,
        "subject": payload.subject,
        "recipients": recipients_summary(
            payload
        ),
        "body_format": payload.body_format,
        "status": "draft_created",
    }

    return ToolExecutionResult(
        content=json.dumps(
            response,
            ensure_ascii=False,
        ),
        display=(
            f'Created Gmail draft "{payload.subject or "(no subject)"}" '
            f"on {account}."
        ),
        metadata={
            "sensitive": True,
            "provider": "google",
            "draft_id": draft_id,
            "message_id": message_id,
        },
    )


async def gmail_send_email_tool(
    data: BaseModel,
    context: ToolContext,
) -> ToolExecutionResult:
    payload = data
    assert isinstance(
        payload,
        EmailSendInput,
    )

    access_token, account = (
        await _google_access_token(
            context
        )
    )

    if payload.draft_id:
        result = await _gmail_post(
            access_token,
            "/users/me/drafts/send",
            {
                "id": payload.draft_id,
            },
        )

        response = {
            "account": account,
            "draft_id": payload.draft_id,
            "message_id": result.get(
                "id"
            ),
            "thread_id": result.get(
                "threadId"
            ),
            "status": "sent",
            "source": "existing_draft",
        }

        display = (
            f"Sent Gmail draft {payload.draft_id} "
            f"from {account}."
        )
    else:
        result = await _gmail_post(
            access_token,
            "/users/me/messages/send",
            {
                "raw": _mime_message(
                    payload
                ),
            },
        )

        response = {
            "account": account,
            "message_id": result.get(
                "id"
            ),
            "thread_id": result.get(
                "threadId"
            ),
            "subject": payload.subject,
            "recipients": recipients_summary(
                payload
            ),
            "status": "sent",
            "source": "new_message",
        }

        display = (
            f'Sent Gmail message "{payload.subject or "(no subject)"}" '
            f"from {account}."
        )

    return ToolExecutionResult(
        content=json.dumps(
            response,
            ensure_ascii=False,
        ),
        display=display,
        metadata={
            "sensitive": True,
            "provider": "google",
            "draft_id": payload.draft_id,
            "message_id": response.get(
                "message_id"
            ),
        },
    )


def register_gmail_write_tools() -> None:
    definitions = [
        ToolDefinition(
            name="gmail_create_draft",
            label="Create Gmail draft",
            description=(
                "Create an unsent Gmail draft with the specified recipients, "
                "subject and complete message body."
            ),
            category="Email",
            risk="write",
            default_permission="ask",
            input_model=EmailComposeInput,
            handler=gmail_create_draft_tool,
            provider_id="google",
            capability_id="email.draft",
        ),
        ToolDefinition(
            name="gmail_send_email",
            label="Send Gmail email",
            description=(
                "Send a new Gmail message, or send an existing Gmail draft ID. "
                "This transmits email to external recipients."
            ),
            category="Email",
            risk="write",
            default_permission="ask",
            input_model=EmailSendInput,
            handler=gmail_send_email_tool,
            provider_id="google",
            capability_id="email.send",
        ),
    ]

    for definition in definitions:
        registry.register(
            definition,
            replace=True,
        )
