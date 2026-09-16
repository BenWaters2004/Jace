from __future__ import annotations

import asyncio
import json
import sys

import httpx

from jace.connections.oauth import valid_access_token
from jace.capabilities.registry import _scope_satisfied
from jace.connections.service import (
    _loads_object,
    list_provider_connections,
)
from jace.database import SessionLocal
from jace.tools import ensure_tools_registered
from jace.tools.registry import registry


GRAPH_API = "https://graph.microsoft.com/v1.0"
MAIL_READ = "Mail.Read"


def _scope_names(config: dict) -> set[str]:
    raw = config.get("scopes")

    if not isinstance(raw, list):
        return set()

    return {
        str(value).casefold()
        for value in raw
        if isinstance(value, str)
    }


async def main() -> int:
    print()
    print("Jace Step 4C.2 Outlook read-only test")
    print("=====================================")
    print()

    ensure_tools_registered()

    read_tool = registry.get(
        "outlook_read_email"
    )
    search_tool = registry.get(
        "outlook_search_email"
    )

    if (
        read_tool is None
        or read_tool.provider_id != "microsoft"
        or read_tool.capability_id != "email.read"
    ):
        raise RuntimeError(
            "outlook_read_email is not correctly registered."
        )

    if (
        search_tool is None
        or search_tool.provider_id != "microsoft"
        or search_tool.capability_id != "email.search"
    ):
        raise RuntimeError(
            "outlook_search_email is not correctly registered."
        )

    print("Outlook tool registration: PASS")

    if not _scope_satisfied(
        "microsoft",
        "Mail.Read",
        (
            "https://graph.microsoft.com/Mail.Read",
        ),
    ):
        raise RuntimeError(
            "Microsoft resource-qualified scope normalization failed."
        )

    print("Microsoft scope normalization: PASS")

    async with SessionLocal() as session:
        rows = await list_provider_connections(
            session,
            "microsoft",
        )

        configured = [
            row
            for row in rows
            if row.status == "configured"
        ]

        if not configured:
            raise RuntimeError(
                "No connected Microsoft account was found."
            )

        row = configured[0]
        config = _loads_object(
            row.config_json
        )
        scopes = _scope_names(
            config
        )

        if MAIL_READ.casefold() not in scopes:
            raise RuntimeError(
                "The connected Microsoft account does not yet record Mail.Read. "
                "Reconnect Microsoft in Settings > Connections after installing 4C.2."
            )

        print("Recorded Mail.Read scope: PASS")

        access_token = await valid_access_token(
            session,
            row,
        )

        headers = {
            "Authorization": (
                f"Bearer {access_token}"
            ),
            "Accept": "application/json",
            "Prefer": 'outlook.body-content-type="text"',
            "User-Agent": "Jace-Desktop",
        }

        async with httpx.AsyncClient(
            timeout=20.0,
        ) as client:
            response = await client.get(
                (
                    f"{GRAPH_API}"
                    "/me/mailFolders/inbox/messages"
                ),
                headers=headers,
                params={
                    "$top": 1,
                    "$orderby": (
                        "receivedDateTime desc"
                    ),
                    "$select": (
                        "id,subject,from,"
                        "receivedDateTime,bodyPreview"
                    ),
                },
            )

            if response.status_code >= 400:
                try:
                    detail = response.json()
                except ValueError:
                    detail = response.text

                raise RuntimeError(
                    "Graph Inbox query failed: "
                    + json.dumps(
                        detail,
                        ensure_ascii=False,
                    )[:1_000]
                    if not isinstance(detail, str)
                    else (
                        "Graph Inbox query failed: "
                        + detail[:1_000]
                    )
                )

            payload = response.json()

    messages = payload.get(
        "value",
        [],
    )

    if not messages:
        print(
            "Live Outlook Inbox access: PASS "
            "(Inbox currently has no messages)"
        )
        print()
        print(
            "PASS - Step 4C.2 Outlook read-only is operational."
        )
        print()
        return 0

    message = messages[0]

    sender = (
        message.get("from", {})
        .get("emailAddress", {})
    )

    sender_text = (
        sender.get("name")
        or sender.get("address")
        or "(unknown)"
    )

    print("Live Outlook Inbox access: PASS")
    print()
    print("Newest message:")
    print(
        "  From:    "
        + str(sender_text)
    )
    print(
        "  Subject: "
        + str(
            message.get("subject")
            or "(no subject)"
        )
    )
    print(
        "  Date:    "
        + str(
            message.get("receivedDateTime")
            or "(unknown)"
        )
    )
    print()
    print(
        "PASS - Step 4C.2 Outlook read-only is operational."
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
