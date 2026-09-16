from __future__ import annotations

import asyncio
import sys

from jace.capabilities.registry import snapshot
from jace.connections.service import (
    _loads_object,
    list_provider_connections,
)
from jace.database import SessionLocal
from jace.tools import ensure_tools_registered
from jace.tools.email_common import (
    EmailComposeInput,
    EmailSendInput,
)
from jace.tools.registry import registry


GOOGLE_REQUIRED = {
    "https://www.googleapis.com/auth/gmail.compose",
    "https://www.googleapis.com/auth/gmail.send",
}

MICROSOFT_REQUIRED = {
    "mail.readwrite",
    "mail.send",
}


def _scopes(
    config: dict,
) -> set[str]:
    raw = config.get(
        "scopes",
        [],
    )

    if not isinstance(raw, list):
        return set()

    return {
        str(value).casefold()
        for value in raw
        if isinstance(value, str)
    }


async def main() -> int:
    print()
    print("Jace Step 4C.3 email draft/send test")
    print("====================================")
    print()

    ensure_tools_registered()

    expected = {
        "gmail_create_draft": (
            "google",
            "email.draft",
        ),
        "gmail_send_email": (
            "google",
            "email.send",
        ),
        "outlook_create_draft": (
            "microsoft",
            "email.draft",
        ),
        "outlook_send_email": (
            "microsoft",
            "email.send",
        ),
    }

    for tool_name, (
        provider_id,
        capability_id,
    ) in expected.items():
        definition = registry.get(
            tool_name
        )

        if definition is None:
            raise RuntimeError(
                f"{tool_name} is not registered."
            )

        if (
            definition.provider_id
            != provider_id
            or definition.capability_id
            != capability_id
            or definition.risk
            != "write"
            or definition.default_permission
            != "ask"
        ):
            raise RuntimeError(
                f"{tool_name} has unsafe or incorrect registration metadata."
            )

    print(
        "Write-tool registration + Ask defaults: PASS"
    )

    sample = EmailComposeInput(
        to=[
            "recipient@example.com",
        ],
        cc=[],
        bcc=[],
        subject="Jace 4C.3 test",
        body="This is a validation-only message.",
    )

    if sample.to != [
        "recipient@example.com"
    ]:
        raise RuntimeError(
            "Email recipient validation failed."
        )

    draft_send = EmailSendInput(
        draft_id="provider-draft-id",
    )

    if (
        draft_send.draft_id
        != "provider-draft-id"
    ):
        raise RuntimeError(
            "Existing-draft send mode failed validation."
        )

    print(
        "Email payload validation: PASS"
    )

    async with SessionLocal() as session:
        for provider_id, required in (
            (
                "google",
                {
                    value.casefold()
                    for value in GOOGLE_REQUIRED
                },
            ),
            (
                "microsoft",
                MICROSOFT_REQUIRED,
            ),
        ):
            rows = await list_provider_connections(
                session,
                provider_id,
            )

            configured = [
                row
                for row in rows
                if row.status == "configured"
            ]

            if not configured:
                raise RuntimeError(
                    f"No connected {provider_id} account was found."
                )

            row = configured[0]
            config = _loads_object(
                row.config_json
            )
            granted = _scopes(
                config
            )

            missing = (
                required
                - granted
            )

            if missing:
                raise RuntimeError(
                    f"{provider_id} still needs OAuth scope(s): "
                    + ", ".join(
                        sorted(missing)
                    )
                    + ". Reconnect that account in Settings > Connections."
                )

        capability_snapshot = await snapshot(
            session
        )

    write_rows = [
        row
        for row in capability_snapshot.get(
            "capabilities",
            [],
        )
        if row.get(
            "provider_capability_id"
        )
        in {
            "email.draft",
            "email.send",
        }
        and row.get("provider_id")
        in {
            "google",
            "microsoft",
        }
        and row.get("source")
        == "connection"
    ]

    if len(write_rows) < 4:
        raise RuntimeError(
            "Expected Google and Microsoft draft/send capability bindings."
        )

    not_ready = [
        row
        for row in write_rows
        if row.get("state")
        != "ready"
    ]

    if not_ready:
        details = "; ".join(
            (
                f'{row.get("provider_id")}:'
                f'{row.get("provider_capability_id")}='
                f'{row.get("state")}/'
                f'{row.get("availability_reason")}'
            )
            for row in not_ready
        )

        raise RuntimeError(
            "One or more write capabilities are not ready: "
            + details
        )

    print(
        "Google + Microsoft draft/send scopes: PASS"
    )
    print(
        "Provider capability bindings ready: PASS"
    )

    print()
    print(
        "PASS - Step 4C.3 email draft/send is configured."
    )
    print()
    print(
        "No email was drafted or sent by this automated test."
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
