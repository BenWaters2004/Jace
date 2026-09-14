from __future__ import annotations

import asyncio
import json
import sys

import httpx

from jace.connections.oauth import valid_access_token
from jace.connections.service import (
    _loads_object,
    list_provider_connections,
)
from jace.database import SessionLocal
from jace.tools import ensure_tools_registered
from jace.tools.registry import registry


GMAIL_SCOPE = (
    "https://www.googleapis.com/auth/gmail.readonly"
)
GMAIL_API = (
    "https://gmail.googleapis.com/gmail/v1"
)


async def main() -> int:
    print()
    print("Jace Step 4C.1 Gmail read-only test")
    print("===================================")
    print()

    ensure_tools_registered()

    read_tool = registry.get(
        "gmail_read_email"
    )
    search_tool = registry.get(
        "gmail_search_email"
    )

    if (
        read_tool is None
        or read_tool.provider_id != "google"
        or read_tool.capability_id != "email.read"
    ):
        raise RuntimeError(
            "gmail_read_email is not correctly registered."
        )

    if (
        search_tool is None
        or search_tool.provider_id != "google"
        or search_tool.capability_id != "email.search"
    ):
        raise RuntimeError(
            "gmail_search_email is not correctly registered."
        )

    print("Gmail tool registration: PASS")

    async with SessionLocal() as session:
        rows = await list_provider_connections(
            session,
            "google",
        )

        configured = [
            row
            for row in rows
            if row.status == "configured"
        ]

        if not configured:
            raise RuntimeError(
                "No connected Google account was found."
            )

        row = configured[0]
        config = _loads_object(
            row.config_json
        )

        scopes = {
            str(item)
            for item in config.get(
                "scopes",
                [],
            )
        }

        if GMAIL_SCOPE not in scopes:
            raise RuntimeError(
                "The connected Google account does not yet record "
                "gmail.readonly. Reconnect Google in "
                "Settings > Connections after installing 4C.1."
            )

        print(
            "Recorded gmail.readonly scope: PASS"
        )

        access_token = await valid_access_token(
            session,
            row,
        )

        headers = {
            "Authorization": (
                f"Bearer {access_token}"
            ),
            "Accept": "application/json",
            "User-Agent": "Jace-Desktop",
        }

        async with httpx.AsyncClient(
            timeout=20.0,
        ) as client:
            response = await client.get(
                f"{GMAIL_API}/users/me/messages",
                headers=headers,
                params={
                    "labelIds": "INBOX",
                    "maxResults": 1,
                },
            )

            if response.status_code >= 400:
                try:
                    detail = response.json()
                except ValueError:
                    detail = response.text

                raise RuntimeError(
                    "Gmail messages.list failed: "
                    + str(detail)[:800]
                )

            payload = response.json()

            messages = payload.get(
                "messages",
                [],
            )

            if not messages:
                print(
                    "Live Gmail Inbox access: PASS "
                    "(Inbox currently has no messages)"
                )
                return 0

            message_id = messages[0].get(
                "id"
            )

            response = await client.get(
                (
                    f"{GMAIL_API}/users/me/messages/"
                    f"{message_id}"
                ),
                headers=headers,
                params={
                    "format": "metadata",
                    "metadataHeaders": [
                        "From",
                        "Subject",
                        "Date",
                    ],
                },
            )

            if response.status_code >= 400:
                raise RuntimeError(
                    "Gmail messages.get failed."
                )

            message = response.json()

    raw_headers = (
        message.get("payload", {})
        .get("headers", [])
    )

    header_map = {
        str(item.get("name", "")).casefold():
            str(item.get("value", ""))
        for item in raw_headers
        if isinstance(item, dict)
    }

    print("Live Gmail Inbox access: PASS")
    print()
    print(
        "Newest message:"
    )
    print(
        "  From:    "
        + (
            header_map.get("from")
            or "(unknown)"
        )
    )
    print(
        "  Subject: "
        + (
            header_map.get("subject")
            or "(no subject)"
        )
    )
    print(
        "  Date:    "
        + (
            header_map.get("date")
            or "(unknown)"
        )
    )
    print()
    print(
        "PASS - Step 4C.1 Gmail read-only is operational."
    )
    print()

    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(
            asyncio.run(main())
        )
    except Exception as exc:
        print()
        print(
            f"FAIL - {exc}",
            file=sys.stderr,
        )
        print()
        raise
