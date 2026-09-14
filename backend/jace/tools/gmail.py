from __future__ import annotations

# JACE_STEP4C1_GMAIL_READONLY

import base64
import html
import json
import re
from datetime import datetime, timezone
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


GMAIL_API = "https://gmail.googleapis.com/gmail/v1"
HTTP_TIMEOUT_SECONDS = 20.0
MAX_BODY_CHARS = 12_000


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


class GmailReadInput(BaseModel):
    message_id: str | None = Field(
        default=None,
        max_length=200,
        description=(
            "Exact Gmail message ID returned by gmail_search_email. "
            "Leave empty to read the newest message currently in the Inbox."
        ),
    )


class GmailSearchInput(BaseModel):
    query: str = Field(
        min_length=1,
        max_length=1_000,
        description=(
            "Gmail search query, for example 'from:alice@example.com', "
            "'subject:invoice newer_than:30d', or 'is:unread'."
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

    if binding.get("provider_id") != "google":
        raise ToolError(
            "Gmail execution requires a Google capability binding."
        )

    connection_id = binding.get("connection_id")
    if not isinstance(connection_id, str) or not connection_id:
        raise ToolError(
            "Gmail execution requires a selected Google account."
        )

    return connection_id


async def _google_access_token(
    context: ToolContext,
) -> tuple[str, str]:
    connection_id = _binding_connection_id(context)

    row = await get_connection(
        context.session,
        connection_id,
    )

    if row is None:
        raise ToolError(
            "The selected Google connection no longer exists."
        )

    if row.provider_id != "google":
        raise ToolError(
            "The selected connection is not a Google account."
        )

    if row.status != "configured":
        raise ToolError(
            "The selected Google account is not currently connected."
        )

    try:
        access_token = await valid_access_token(
            context.session,
            row,
        )
    except Exception as exc:
        raise ToolError(
            f"Google authorization is not usable: {exc}"
        ) from exc

    return access_token, (
        row.account_hint
        or row.label
        or "Google account"
    )


def _google_error(
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
            "Google denied Gmail read access. Confirm the Gmail API is "
            "enabled and reconnect this account so Jace can request "
            "gmail.readonly."
        )

    return ToolError(
        detail or fallback
    )


async def _gmail_get(
    access_token: str,
    path: str,
    *,
    params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/json",
        "User-Agent": "Jace-Desktop",
    }

    async with httpx.AsyncClient(
        timeout=HTTP_TIMEOUT_SECONDS,
    ) as client:
        response = await client.get(
            f"{GMAIL_API}{path}",
            headers=headers,
            params=params,
        )

    if response.status_code >= 400:
        raise _google_error(
            response,
            "Gmail API request failed.",
        )

    try:
        payload = response.json()
    except ValueError as exc:
        raise ToolError(
            "Gmail returned an unreadable response."
        ) from exc

    if not isinstance(payload, dict):
        raise ToolError(
            "Gmail returned an unexpected response."
        )

    return payload


def _headers(
    message: dict[str, Any],
) -> dict[str, str]:
    payload = message.get("payload")
    if not isinstance(payload, dict):
        return {}

    raw_headers = payload.get("headers")
    if not isinstance(raw_headers, list):
        return {}

    result: dict[str, str] = {}

    for item in raw_headers:
        if not isinstance(item, dict):
            continue

        name = item.get("name")
        value = item.get("value")

        if (
            isinstance(name, str)
            and isinstance(value, str)
        ):
            result[name.casefold()] = value

    return result


def _decode_base64url(
    value: object,
) -> str:
    if not isinstance(value, str) or not value:
        return ""

    try:
        padding = "=" * (
            (4 - len(value) % 4) % 4
        )
        decoded = base64.urlsafe_b64decode(
            value + padding
        )
        return decoded.decode(
            "utf-8",
            errors="replace",
        )
    except Exception:
        return ""


def _html_to_text(value: str) -> str:
    parser = _HTMLTextExtractor()

    try:
        parser.feed(value)
        parser.close()
        return html.unescape(
            parser.text()
        )
    except Exception:
        return re.sub(
            r"<[^>]+>",
            " ",
            value,
        )


def _part_body(
    part: dict[str, Any],
) -> tuple[str, str]:
    """
    Return (plain_text, html_text).

    Prefer actual text/plain content. HTML is retained only as a fallback.
    Attachments are intentionally ignored in 4C.1.
    """
    mime_type = str(
        part.get("mimeType") or ""
    ).casefold()

    body = part.get("body")
    body_data = (
        body.get("data")
        if isinstance(body, dict)
        else None
    )

    plain = ""
    rich = ""

    if mime_type == "text/plain":
        plain = _decode_base64url(
            body_data
        )
    elif mime_type == "text/html":
        rich = _decode_base64url(
            body_data
        )

    children = part.get("parts")

    if isinstance(children, list):
        child_plain: list[str] = []
        child_html: list[str] = []

        for child in children:
            if not isinstance(child, dict):
                continue

            next_plain, next_html = _part_body(
                child
            )

            if next_plain.strip():
                child_plain.append(
                    next_plain
                )

            if next_html.strip():
                child_html.append(
                    next_html
                )

        if child_plain:
            plain = "\n\n".join(
                child_plain
            )

        if child_html:
            rich = "\n\n".join(
                child_html
            )

    return plain, rich


def _message_body(
    message: dict[str, Any],
) -> str:
    payload = message.get("payload")

    if not isinstance(payload, dict):
        return ""

    plain, rich = _part_body(
        payload
    )

    body = (
        plain
        if plain.strip()
        else _html_to_text(rich)
    )

    body = "\n".join(
        line.rstrip()
        for line in body.splitlines()
    ).strip()

    return body[:MAX_BODY_CHARS]


def _internal_datetime(
    message: dict[str, Any],
) -> str | None:
    raw = message.get("internalDate")

    try:
        milliseconds = int(raw)
    except (TypeError, ValueError):
        return None

    return datetime.fromtimestamp(
        milliseconds / 1000,
        tz=timezone.utc,
    ).isoformat()


def _message_summary(
    message: dict[str, Any],
    *,
    include_body: bool,
) -> dict[str, Any]:
    headers = _headers(message)

    result: dict[str, Any] = {
        "id": message.get("id"),
        "thread_id": message.get(
            "threadId"
        ),
        "from": headers.get("from"),
        "to": headers.get("to"),
        "cc": headers.get("cc"),
        "subject": (
            headers.get("subject")
            or "(no subject)"
        ),
        "date_header": headers.get("date"),
        "received_at": _internal_datetime(
            message
        ),
        "snippet": message.get("snippet"),
        "labels": message.get(
            "labelIds",
            [],
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
    *,
    full: bool,
) -> dict[str, Any]:
    params: dict[str, Any] = {
        "format": (
            "full"
            if full
            else "metadata"
        ),
    }

    if not full:
        params["metadataHeaders"] = [
            "From",
            "To",
            "Cc",
            "Subject",
            "Date",
        ]

    return await _gmail_get(
        access_token,
        f"/users/me/messages/{message_id}",
        params=params,
    )


async def _newest_inbox_id(
    access_token: str,
) -> str | None:
    payload = await _gmail_get(
        access_token,
        "/users/me/messages",
        params={
            "labelIds": "INBOX",
            "maxResults": 1,
        },
    )

    messages = payload.get("messages")

    if not isinstance(messages, list):
        return None

    for item in messages:
        if (
            isinstance(item, dict)
            and isinstance(
                item.get("id"),
                str,
            )
        ):
            return item["id"]

    return None


async def gmail_read_email_tool(
    data: BaseModel,
    context: ToolContext,
) -> ToolExecutionResult:
    payload = data
    assert isinstance(
        payload,
        GmailReadInput,
    )

    access_token, account = (
        await _google_access_token(
            context
        )
    )

    message_id = (
        payload.message_id.strip()
        if payload.message_id
        else None
    )

    if not message_id:
        message_id = await _newest_inbox_id(
            access_token
        )

    if not message_id:
        result = {
            "account": account,
            "message": None,
            "reason": (
                "No messages were found in the Gmail Inbox."
            ),
        }

        return ToolExecutionResult(
            content=json.dumps(
                result,
                ensure_ascii=False,
            ),
            display=(
                f"No Inbox messages found for {account}."
            ),
            metadata={
                "sensitive": True,
                "provider": "google",
            },
        )

    message = await _get_message(
        access_token,
        message_id,
        full=True,
    )

    summary = _message_summary(
        message,
        include_body=True,
    )

    result = {
        "account": account,
        "message": summary,
    }

    # Keep email content out of the persistent audit preview. The full result is
    # sent only to the model for the current turn.
    display = (
        "Read Gmail message"
        f' "{summary["subject"]}"'
        f' from {summary.get("from") or "unknown sender"}'
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
            "provider": "google",
            "message_id": message_id,
        },
    )


async def gmail_search_email_tool(
    data: BaseModel,
    context: ToolContext,
) -> ToolExecutionResult:
    payload = data
    assert isinstance(
        payload,
        GmailSearchInput,
    )

    access_token, account = (
        await _google_access_token(
            context
        )
    )

    listed = await _gmail_get(
        access_token,
        "/users/me/messages",
        params={
            "q": payload.query,
            "maxResults": payload.limit,
        },
    )

    refs = listed.get("messages")

    if not isinstance(refs, list):
        refs = []

    messages: list[dict[str, Any]] = []

    for item in refs[: payload.limit]:
        if not isinstance(item, dict):
            continue

        message_id = item.get("id")

        if not isinstance(
            message_id,
            str,
        ):
            continue

        message = await _get_message(
            access_token,
            message_id,
            full=False,
        )

        messages.append(
            _message_summary(
                message,
                include_body=False,
            )
        )

    messages.sort(
        key=lambda item: (
            item.get("received_at")
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
            f"Found {len(messages)} Gmail message"
            f'{"s" if len(messages) != 1 else ""}'
            f" on {account}."
        ),
        metadata={
            "sensitive": True,
            "provider": "google",
        },
    )


def register_gmail_tools() -> None:
    definitions = [
        ToolDefinition(
            name="gmail_read_email",
            label="Read Gmail email",
            description=(
                "Read one Gmail message. Leave message_id empty to read the "
                "newest message in the Inbox. This is read-only and never "
                "changes mailbox state."
            ),
            category="Email",
            risk="read",
            default_permission="allow",
            input_model=GmailReadInput,
            handler=gmail_read_email_tool,
            provider_id="google",
            capability_id="email.read",
        ),
        ToolDefinition(
            name="gmail_search_email",
            label="Search Gmail",
            description=(
                "Search Gmail using Gmail query syntax and return message IDs, "
                "sender, subject, timestamp and snippet. This is read-only."
            ),
            category="Email",
            risk="read",
            default_permission="allow",
            input_model=GmailSearchInput,
            handler=gmail_search_email_tool,
            provider_id="google",
            capability_id="email.search",
        ),
    ]

    for definition in definitions:
        registry.register(
            definition,
            replace=True,
        )
