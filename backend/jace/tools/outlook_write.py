from __future__ import annotations

# JACE_STEP4C3_OUTLOOK_WRITE

import json
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
    recipients_summary,
)
from jace.tools.outlook import (
    GRAPH_API,
    HTTP_TIMEOUT_SECONDS,
    _microsoft_access_token,
)
from jace.tools.registry import registry


def _graph_recipient(
    value: str,
) -> dict[str, Any]:
    return {
        "emailAddress": {
            "address": value,
        },
    }


def _graph_message(
    data: EmailComposeInput | EmailSendInput,
) -> dict[str, Any]:
    return {
        "subject": data.subject,
        "body": {
            "contentType": (
                "HTML"
                if data.body_format == "html"
                else "Text"
            ),
            "content": data.body,
        },
        "toRecipients": [
            _graph_recipient(
                value
            )
            for value in data.to
        ],
        "ccRecipients": [
            _graph_recipient(
                value
            )
            for value in data.cc
        ],
        "bccRecipients": [
            _graph_recipient(
                value
            )
            for value in data.bcc
        ],
    }


def _graph_write_error(
    response: httpx.Response,
    fallback: str,
) -> ToolError:
    detail = ""
    code = ""

    try:
        payload = response.json()
    except ValueError:
        payload = None

    if isinstance(payload, dict):
        raw_error = payload.get("error")

        if isinstance(raw_error, dict):
            raw_code = raw_error.get("code")
            raw_message = raw_error.get("message")

            if isinstance(raw_code, str):
                code = raw_code.strip()

            if isinstance(raw_message, str):
                detail = raw_message.strip()

    detail = detail[:500]

    if response.status_code == 401:
        return ToolError(
            "Microsoft rejected the current access token. Reconnect this "
            "Microsoft account in Settings > Connections."
        )

    if response.status_code == 403:
        return ToolError(
            "Microsoft denied this Outlook write action. Confirm the Jace "
            "app has delegated Mail.ReadWrite for drafts and Mail.Send for "
            "sending, then reconnect the Microsoft account."
        )

    if code:
        return ToolError(
            f"{detail or fallback} ({code})"
        )

    return ToolError(
        detail or fallback
    )


async def _graph_post(
    access_token: str,
    path: str,
    payload: dict[str, Any] | None,
    *,
    expected: tuple[int, ...],
) -> dict[str, Any]:
    headers = {
        "Authorization": (
            f"Bearer {access_token}"
        ),
        "Accept": "application/json",
        "User-Agent": "Jace-Desktop",
    }

    if payload is not None:
        headers[
            "Content-Type"
        ] = "application/json"

    async with httpx.AsyncClient(
        timeout=HTTP_TIMEOUT_SECONDS,
    ) as client:
        response = await client.post(
            f"{GRAPH_API}{path}",
            headers=headers,
            json=payload,
        )

    if response.status_code not in expected:
        raise _graph_write_error(
            response,
            "Microsoft Graph mail write request failed.",
        )

    if not response.content:
        return {}

    try:
        result = response.json()
    except ValueError as exc:
        raise ToolError(
            "Microsoft Graph returned an unreadable write response."
        ) from exc

    if not isinstance(
        result,
        dict,
    ):
        raise ToolError(
            "Microsoft Graph returned an unexpected write response."
        )

    return result


async def outlook_create_draft_tool(
    data: BaseModel,
    context: ToolContext,
) -> ToolExecutionResult:
    payload = data
    assert isinstance(
        payload,
        EmailComposeInput,
    )

    access_token, account = (
        await _microsoft_access_token(
            context
        )
    )

    result = await _graph_post(
        access_token,
        "/me/messages",
        _graph_message(
            payload
        ),
        expected=(201,),
    )

    draft_id = result.get("id")

    response = {
        "account": account,
        "draft_id": draft_id,
        "subject": result.get(
            "subject",
            payload.subject,
        ),
        "recipients": recipients_summary(
            payload
        ),
        "status": "draft_created",
    }

    return ToolExecutionResult(
        content=json.dumps(
            response,
            ensure_ascii=False,
        ),
        display=(
            f'Created Outlook draft "{payload.subject or "(no subject)"}" '
            f"on {account}."
        ),
        metadata={
            "sensitive": True,
            "provider": "microsoft",
            "draft_id": draft_id,
        },
    )


async def outlook_send_email_tool(
    data: BaseModel,
    context: ToolContext,
) -> ToolExecutionResult:
    payload = data
    assert isinstance(
        payload,
        EmailSendInput,
    )

    access_token, account = (
        await _microsoft_access_token(
            context
        )
    )

    if payload.draft_id:
        await _graph_post(
            access_token,
            (
                "/me/messages/"
                f"{payload.draft_id}/send"
            ),
            None,
            expected=(202,),
        )

        response = {
            "account": account,
            "draft_id": payload.draft_id,
            "status": "accepted_for_send",
            "source": "existing_draft",
        }

        display = (
            f"Submitted Outlook draft {payload.draft_id} "
            f"for sending from {account}."
        )
    else:
        await _graph_post(
            access_token,
            "/me/sendMail",
            {
                "message": _graph_message(
                    payload
                ),
                "saveToSentItems": True,
            },
            expected=(202,),
        )

        response = {
            "account": account,
            "subject": payload.subject,
            "recipients": recipients_summary(
                payload
            ),
            "status": "accepted_for_send",
            "source": "new_message",
        }

        display = (
            f'Submitted Outlook message "{payload.subject or "(no subject)"}" '
            f"for sending from {account}."
        )

    return ToolExecutionResult(
        content=json.dumps(
            response,
            ensure_ascii=False,
        ),
        display=display,
        metadata={
            "sensitive": True,
            "provider": "microsoft",
            "draft_id": payload.draft_id,
        },
    )


def register_outlook_write_tools() -> None:
    definitions = [
        ToolDefinition(
            name="outlook_create_draft",
            label="Create Outlook draft",
            description=(
                "Create an unsent Outlook draft with the specified recipients, "
                "subject and complete message body."
            ),
            category="Email",
            risk="write",
            default_permission="ask",
            input_model=EmailComposeInput,
            handler=outlook_create_draft_tool,
            provider_id="microsoft",
            capability_id="email.draft",
        ),
        ToolDefinition(
            name="outlook_send_email",
            label="Send Outlook email",
            description=(
                "Send a new Outlook message, or send an existing Outlook draft ID. "
                "This transmits email to external recipients."
            ),
            category="Email",
            risk="write",
            default_permission="ask",
            input_model=EmailSendInput,
            handler=outlook_send_email_tool,
            provider_id="microsoft",
            capability_id="email.send",
        ),
    ]

    for definition in definitions:
        registry.register(
            definition,
            replace=True,
        )
