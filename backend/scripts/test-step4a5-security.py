from __future__ import annotations

import asyncio
import json

from sqlalchemy import delete

from jace.database import SessionLocal, engine, init_database
from jace.db.models import ToolAuditLog
from jace.tools.approvals import approval_manager
from jace.tools.permissions import create_tool_audit


TEST_TOOL = "__step4a5_test__"


async def main() -> None:
    print()
    print("Jace Step 4A.5 permissions/audit security test")
    print("==============================================")
    print()

    await init_database()

    async with engine.begin() as connection:
        result = await connection.exec_driver_sql(
            "PRAGMA table_info(tool_audit_log)"
        )
        columns = {
            str(row[1])
            for row in result.fetchall()
        }

    required = {
        "provider_id",
        "connection_id",
        "capability_id",
        "account_hint",
    }

    missing = required - columns

    if missing:
        raise RuntimeError(
            f"Tool audit migration is missing columns: {sorted(missing)}"
        )

    print("Audit schema migration: PASS")

    async with SessionLocal() as session:
        entry = await create_tool_audit(
            session,
            conversation_id=None,
            tool_name=TEST_TOOL,
            permission_mode="ask",
            arguments={
                "query": "safe value",
                "access_token": "SECRET_VALUE",
                "nested": {
                    "client_secret": "SECRET_VALUE",
                },
            },
            provider_id="google",
            connection_id="step4a5-connection",
            capability_id="email.search",
            account_hint="tester@example.com",
        )

        stored = json.loads(entry.arguments_json)

        if "SECRET_VALUE" in entry.arguments_json:
            raise RuntimeError(
                "A secret value was persisted in tool audit arguments."
            )

        if (
            stored.get("access_token") != "<redacted>"
            or stored.get("nested", {}).get("client_secret") != "<redacted>"
        ):
            raise RuntimeError(
                "Secret-shaped audit fields were not redacted."
            )

        if (
            entry.provider_id != "google"
            or entry.connection_id != "step4a5-connection"
            or entry.capability_id != "email.search"
            or entry.account_hint != "tester@example.com"
        ):
            raise RuntimeError(
                "External capability audit identity was not stored correctly."
            )

        await session.execute(
            delete(ToolAuditLog).where(
                ToolAuditLog.tool_name == TEST_TOOL
            )
        )
        await session.commit()

    print("Connection-aware audit + secret redaction: PASS")

    approval = approval_manager.create(
        conversation_id=None,
        tool_name=TEST_TOOL,
        label="Test external tool",
        description="Step 4A.5 approval metadata test.",
        risk="write",
        arguments={"subject": "test"},
        provider_id="microsoft",
        connection_id="approval-connection",
        capability_id="email.send",
        account_hint="tester@example.com",
    )

    if (
        approval.provider_id != "microsoft"
        or approval.connection_id != "approval-connection"
        or approval.capability_id != "email.send"
        or approval.account_hint != "tester@example.com"
    ):
        raise RuntimeError(
            "External approval metadata was not retained."
        )

    approval_manager.cancel(approval.approval_id)

    print("Connection-aware approval metadata: PASS")
    print()
    print("PASS - Step 4A.5 permission and audit hardening is installed.")
    print()


if __name__ == "__main__":
    asyncio.run(main())
