from __future__ import annotations

# JACE_STEP4C2_OUTLOOK_READONLY

import html
import json
import re
from html.parser import HTMLParser
from typing import Any

import httpx
from pydantic import BaseModel, Field

from jace.connections.oauth import valid_access_token
from jace.connections.service import get_connection
from jace.tools.base import (
    ToolContext,
    ToolDefinition,
    ToolError,
    ToolExecutionResult,
)
from jace.tools.registry import registry


GRAPH_API = "https://graph.microsoft.com/v1.0"
HTTP_TIMEOUT_SECONDS = 20.0
MAX_BODY_CHARS = 12_000

MESSAGE_SELECT = (
    "id,conversationId,subject,from,toRecipients,ccRecipients,"
    "receivedDateTime,sentDateTime,bodyPreview,isRead,importance,"
    "hasAttachments,parentFolderId"
)

FULL_MESSAGE_SELECT = (
    MESSAGE_SELECT
    + ",body,replyTo,internetMessageId"
)


class _HTMLTextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        value = data.strip()
        if value:
            self.parts.append(value)

    def text(self) -> str:
        return " ".join(self.parts)


class OutlookReadInput(BaseModel):
    message_id: str | None = Field(
        default=None,
        max_length=1_000,
        description=(
            "Exact Outlook/Graph message ID returned by outlook_search_email. "
            "Leave empty to read the newest message currently in the Inbox."
        ),
    )


class OutlookSearchInput(BaseModel):
    query: str = Field(
        min_length=1,
        max_length=1_000,
        description=(
            "Outlook message search text. Plain text searches common message "
            "properties such as sender, subject and body. Microsoft message "
            "search keywords such as from:, subject:, participants:, received: "
            "and hasAttachments: are also supported."
        ),
    )
    limit: int = Field(
        default=5,
        ge=1,
        le=10,
        description="Maximum number of matching messages to return.",
    )


def _binding_connection_id(context: ToolContext) -> str:
    binding = context.capability_binding or {}

    if binding.get("provider_id") != "microsoft":
        raise ToolError(
            "Outlook execution requires a Microsoft capability binding."
        )

    connection_id = binding.get("connection_id")

    if not isinstance(connection_id, str) or not connection_id:
        raise ToolError(
            "Outlook execution requires a selected Microsoft account."
        )

    return connection_id


async def _microsoft_access_token(
    context: ToolContext,
) -> tuple[str, str]:
    connection_id = _binding_connection_id(
        context
    )

    row = await get_connection(
        context.session,
        connection_id,
    )

    if row is None:
        raise ToolError(
            "The selected Microsoft connection no longer exists."
        )

    if row.provider_id != "microsoft":
        raise ToolError(
            "The selected connection is not a Microsoft account."
        )

    if row.status != "configured":
        raise ToolError(
            "The selected Microsoft account is not currently connected."
        )

    try:
        access_token = await valid_access_token(
            context.session,
            row,
        )
    except Exception as exc:
        raise ToolError(
            f"Microsoft authorization is not usable: {exc}"
        ) from exc

    return access_token, (
        row.account_hint
        or row.label
        or "Microsoft account"
    )


def _graph_error(
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

        elif isinstance(raw_error, str):
            detail = raw_error.strip()

    detail = detail[:500]

    if response.status_code == 401:
        return ToolError(
            "Microsoft rejected the current access token. Reconnect this "
            "Microsoft account in Settings > Connections."
        )

    if response.status_code == 403:
        return ToolError(
            "Microsoft denied Outlook mail access. Confirm the Jace Entra "
            "application has delegated Mail.Read permission, then reconnect "
            "this Microsoft account and approve the new permission."
        )

    if code:
        return ToolError(
            f"{detail or fallback} ({code})"
        )

    return ToolError(
        detail or fallback
    )


async def _graph_get(
    access_token: str,
    path: str,
    *,
    params: dict[str, Any] | None = None,
    prefer_text_body: bool = False,
    consistency_level: bool = False,
) -> dict[str, Any]:
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/json",
        "User-Agent": "Jace-Desktop",
    }

    if prefer_text_body:
        headers["Prefer"] = 'outlook.body-content-type="text"'

    if consistency_level:
        headers["ConsistencyLevel"] = "eventual"

    async with httpx.AsyncClient(
        timeout=HTTP_TIMEOUT_SECONDS,
    ) as client:
        response = await client.get(
            f"{GRAPH_API}{path}",
            headers=headers,
            params=params,
        )

    if response.status_code >= 400:
        raise _graph_error(
            response,
            "Microsoft Graph mail request failed.",
        )

    try:
        payload = response.json()
    except ValueError as exc:
        raise ToolError(
            "Microsoft Graph returned an unreadable response."
        ) from exc

    if not isinstance(payload, dict):
        raise ToolError(
            "Microsoft Graph returned an unexpected response."
        )

    return payload


def _html_to_text(value: str) -> str:
    parser = _HTMLTextExtractor()

    try:
        parser.feed(value)
        parser.close()
        text = parser.text()
    except Exception:
        text = re.sub(
            r"<[^>]+>",
            " ",
            value,
        )

    return html.unescape(text)


def _address(
    recipient: object,
) -> dict[str, str | None] | None:
    if not isinstance(recipient, dict):
        return None

    email_address = recipient.get(
        "emailAddress"
    )

    if not isinstance(email_address, dict):
        return None

    name = email_address.get("name")
    address = email_address.get("address")

    if not isinstance(name, str):
        name = None

    if not isinstance(address, str):
        address = None

    if not name and not address:
        return None

    return {
        "name": name,
        "address": address,
    }


def _addresses(
    value: object,
) -> list[dict[str, str | None]]:
    if not isinstance(value, list):
        return []

    result: list[dict[str, str | None]] = []

    for item in value:
        parsed = _address(item)
        if parsed is not None:
            result.append(parsed)

    return result


def _message_body(
    message: dict[str, Any],
) -> str:
    body = message.get("body")

    if not isinstance(body, dict):
        return ""

    content = body.get("content")
    content_type = body.get("contentType")

    if not isinstance(content, str):
        return ""

    if (
        isinstance(content_type, str)
        and content_type.casefold() == "html"
    ):
        content = _html_to_text(
            content
        )

    content = "\n".join(
        line.rstrip()
        for line in content.splitlines()
    ).strip()

    return content[:MAX_BODY_CHARS]


def _message_summary(
    message: dict[str, Any],
    *,
    include_body: bool,
) -> dict[str, Any]:
    sender = _address(
        message.get("from")
    )

    result: dict[str, Any] = {
        "id": message.get("id"),
        "conversation_id": message.get(
            "conversationId"
        ),
        "internet_message_id": message.get(
            "internetMessageId"
        ),
        "from": sender,
        "to": _addresses(
            message.get("toRecipients")
        ),
        "cc": _addresses(
            message.get("ccRecipients")
        ),
        "reply_to": _addresses(
            message.get("replyTo")
        ),
        "subject": (
            message.get("subject")
            or "(no subject)"
        ),
        "received_at": message.get(
            "receivedDateTime"
        ),
        "sent_at": message.get(
            "sentDateTime"
        ),
        "snippet": message.get(
            "bodyPreview"
        ),
        "is_read": message.get(
            "isRead"
        ),
        "importance": message.get(
            "importance"
        ),
        "has_attachments": message.get(
            "hasAttachments"
        ),
        "parent_folder_id": message.get(
            "parentFolderId"
        ),
    }

    if include_body:
        result["body"] = _message_body(
            message
        )

    return result


async def _get_message(
    access_token: str,
    message_id: str,
) -> dict[str, Any]:
    return await _graph_get(
        access_token,
        f"/me/messages/{message_id}",
        params={
            "$select": FULL_MESSAGE_SELECT,
        },
        prefer_text_body=True,
    )


async def _newest_inbox_message(
    access_token: str,
) -> dict[str, Any] | None:
    payload = await _graph_get(
        access_token,
        "/me/mailFolders/inbox/messages",
        params={
            "$top": 1,
            "$orderby": (
                "receivedDateTime desc"
            ),
            "$select": FULL_MESSAGE_SELECT,
        },
        prefer_text_body=True,
    )

    values = payload.get("value")

    if not isinstance(values, list):
        return None

    for item in values:
        if isinstance(item, dict):
            return item

    return None


def _quote_search(
    query: str,
) -> str:
    """
    Graph expects the $search expression to be wrapped in double quotes.

    Preserve user/model search operators inside the expression while escaping
    literal double quotes/backslashes so they cannot break the query syntax.
    """
    cleaned = query.strip()

    if (
        len(cleaned) >= 2
        and cleaned.startswith('"')
        and cleaned.endswith('"')
    ):
        cleaned = cleaned[1:-1]

    cleaned = (
        cleaned
        .replace("\\", "\\\\")
        .replace('"', '\\"')
    )

    return f'"{cleaned}"'


async def outlook_read_email_tool(
    data: BaseModel,
    context: ToolContext,
) -> ToolExecutionResult:
    payload = data
    assert isinstance(
        payload,
        OutlookReadInput,
    )

    access_token, account = (
        await _microsoft_access_token(
            context
        )
    )

    message_id = (
        payload.message_id.strip()
        if payload.message_id
        else None
    )

    if message_id:
        message = await _get_message(
            access_token,
            message_id,
        )
    else:
        message = (
            await _newest_inbox_message(
                access_token
            )
        )

    if message is None:
        result = {
            "account": account,
            "message": None,
            "reason": (
                "No messages were found in the Outlook Inbox."
            ),
        }

        return ToolExecutionResult(
            content=json.dumps(
                result,
                ensure_ascii=False,
            ),
            display=(
                f"No Outlook Inbox messages found for {account}."
            ),
            metadata={
                "sensitive": True,
                "provider": "microsoft",
            },
        )

    summary = _message_summary(
        message,
        include_body=True,
    )

    sender = summary.get("from")
    sender_text = "unknown sender"

    if isinstance(sender, dict):
        sender_text = (
            sender.get("name")
            or sender.get("address")
            or sender_text
        )

    result = {
        "account": account,
        "message": summary,
    }

    # The full message body is available to the model for this turn, but the
    # audit preview remains metadata-only via `display`.
    display = (
        "Read Outlook message"
        f' "{summary["subject"]}"'
        f" from {sender_text}"
        f" on {account}."
    )

    return ToolExecutionResult(
        content=json.dumps(
            result,
            ensure_ascii=False,
        ),
        display=display,
        metadata={
            "sensitive": True,
            "provider": "microsoft",
            "message_id": summary.get("id"),
        },
    )


async def outlook_search_email_tool(
    data: BaseModel,
    context: ToolContext,
) -> ToolExecutionResult:
    payload = data
    assert isinstance(
        payload,
        OutlookSearchInput,
    )

    access_token, account = (
        await _microsoft_access_token(
            context
        )
    )

    listed = await _graph_get(
        access_token,
        "/me/messages",
        params={
            "$search": _quote_search(
                payload.query
            ),
            "$top": payload.limit,
            "$select": MESSAGE_SELECT,
        },
        consistency_level=True,
    )

    values = listed.get("value")

    if not isinstance(values, list):
        values = []

    messages = [
        _message_summary(
            item,
            include_body=False,
        )
        for item in values[: payload.limit]
        if isinstance(item, dict)
    ]

    # Graph generally returns message search by date; sorting again makes Jace's
    # contract deterministic if Microsoft changes ranking for a query.
    messages.sort(
        key=lambda item: (
            item.get("received_at")
            or item.get("sent_at")
            or ""
        ),
        reverse=True,
    )

    result = {
        "account": account,
        "query": payload.query,
        "messages": messages,
        "result_count": len(messages),
    }

    return ToolExecutionResult(
        content=json.dumps(
            result,
            ensure_ascii=False,
        ),
        display=(
            f"Found {len(messages)} Outlook message"
            f'{"s" if len(messages) != 1 else ""}'
            f" on {account}."
        ),
        metadata={
            "sensitive": True,
            "provider": "microsoft",
        },
    )


def register_outlook_tools() -> None:
    definitions = [
        ToolDefinition(
            name="outlook_read_email",
            label="Read Outlook email",
            description=(
                "Read one Outlook message. Leave message_id empty to read "
                "the newest message in the Inbox. This is read-only and never "
                "changes mailbox state."
            ),
            category="Email",
            risk="read",
            default_permission="allow",
            input_model=OutlookReadInput,
            handler=outlook_read_email_tool,
            provider_id="microsoft",
            capability_id="email.read",
        ),
        ToolDefinition(
            name="outlook_search_email",
            label="Search Outlook",
            description=(
                "Search the signed-in Outlook mailbox and return message IDs, "
                "sender, subject, timestamp and preview. This is read-only."
            ),
            category="Email",
            risk="read",
            default_permission="allow",
            input_model=OutlookSearchInput,
            handler=outlook_search_email_tool,
            provider_id="microsoft",
            capability_id="email.search",
        ),
    ]

    for definition in definitions:
        registry.register(
            definition,
            replace=True,
        )
