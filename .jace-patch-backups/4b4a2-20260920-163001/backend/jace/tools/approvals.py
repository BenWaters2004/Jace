import asyncio
import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import uuid4

from jace.config import settings


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class PendingApproval:
    approval_id: str
    conversation_id: str | None
    tool_name: str
    label: str
    description: str
    risk: str
    arguments: dict
    created_at: datetime
    future: asyncio.Future[bool]
    source: str = "chat"
    task_id: str | None = None
    agent_id: str | None = None
    configured_permission: str | None = None
    provider_id: str | None = None
    connection_id: str | None = None
    capability_id: str | None = None
    account_hint: str | None = None


# JACE_4B3D_EXACT_SESSION_GRANT_V2
def approval_arguments_fingerprint(
    arguments: dict,
) -> str:
    encoded = json.dumps(
        arguments,
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
        default=str,
    ).encode(
        "utf-8",
        errors="replace",
    )

    return hashlib.sha256(
        encoded
    ).hexdigest()


class ApprovalManager:
    def __init__(self) -> None:
        self._pending: dict[str, PendingApproval] = {}
        # JACE_4B3D_SESSION_APPROVAL_GRANTS
        self._approval_grant_keys: dict[str, tuple[str, str]] = {}
        self._session_grants: set[
            tuple[str, str, str, str]
        ] = set()

    def create(
        self,
        *,
        conversation_id: str | None,
        tool_name: str,
        label: str,
        description: str,
        risk: str,
        arguments: dict,
        source: str = "chat",
        task_id: str | None = None,
        agent_id: str | None = None,
        provider_id: str | None = None,
        connection_id: str | None = None,
        capability_id: str | None = None,
        account_hint: str | None = None,
        configured_permission: str | None = None,
    ) -> PendingApproval:
        loop = asyncio.get_running_loop()
        approval = PendingApproval(
            approval_id=str(uuid4()),
            conversation_id=conversation_id,
            tool_name=tool_name,
            label=label,
            description=description,
            risk=risk,
            arguments=arguments,
            created_at=utc_now(),
            future=loop.create_future(),
            source=source,
            task_id=task_id,
            agent_id=agent_id,
            configured_permission=configured_permission,
            provider_id=provider_id,
            connection_id=connection_id,
            capability_id=capability_id,
            account_hint=account_hint,
        )
        self._pending[approval.approval_id] = approval
        return approval

    def bind_session_grant(
        self,
        approval_id: str,
        grant_key: str | None,
        arguments: dict | None = None,
    ) -> None:
        value = str(
            grant_key
            or ""
        ).strip()

        if not value:
            return

        approval = self._pending.get(
            approval_id
        )

        grant_arguments = (
            arguments
            if arguments is not None
            else (
                approval.arguments
                if approval is not None
                else {}
            )
        )

        self._approval_grant_keys[
            approval_id
        ] = (
            value,
            approval_arguments_fingerprint(
                grant_arguments
            ),
        )

    def grant_key(
        self,
        approval_id: str,
    ) -> str | None:
        record = self._approval_grant_keys.get(
            approval_id
        )

        return (
            record[0]
            if record is not None
            else None
        )

    def grant_arguments_fingerprint(
        self,
        approval_id: str,
    ) -> str | None:
        record = self._approval_grant_keys.get(
            approval_id
        )

        return (
            record[1]
            if record is not None
            else None
        )

    def is_session_granted(
        self,
        conversation_id: str | None,
        tool_name: str,
        grant_key: str | None,
        arguments: dict | None = None,
    ) -> bool:
        if (
            not conversation_id
            or not grant_key
            or arguments is None
        ):
            return False

        return (
            conversation_id,
            tool_name,
            grant_key,
            approval_arguments_fingerprint(
                arguments
            ),
        ) in self._session_grants

    def grant_session_from_approval(
        self,
        approval_id: str,
    ) -> bool:
        approval = self._pending.get(
            approval_id
        )
        record = self._approval_grant_keys.get(
            approval_id
        )

        if (
            approval is None
            or record is None
            or not approval.conversation_id
        ):
            return False

        grant_key, arguments_fingerprint = record

        # Re-check that the approval has not been mutated after the grant
        # fingerprint was bound.
        if (
            approval_arguments_fingerprint(
                approval.arguments
            )
            != arguments_fingerprint
        ):
            return False

        self._session_grants.add(
            (
                approval.conversation_id,
                approval.tool_name,
                grant_key,
                arguments_fingerprint,
            )
        )

        return True

    def clear_conversation_grants(
        self,
        conversation_id: str,
    ) -> int:
        matches = {
            item
            for item in self._session_grants
            if item[0]
            == conversation_id
        }

        self._session_grants.difference_update(
            matches
        )

        return len(
            matches
        )

    def get(self, approval_id: str) -> PendingApproval | None:
        return self._pending.get(approval_id)

    def list(self) -> list[PendingApproval]:
        return sorted(
            self._pending.values(),
            key=lambda approval: approval.created_at,
        )

    async def wait(self, approval_id: str) -> bool:
        approval = self._pending.get(approval_id)
        if approval is None:
            raise LookupError("Tool approval no longer exists.")

        try:
            return await asyncio.wait_for(
                asyncio.shield(approval.future),
                timeout=settings.tool_approval_timeout_seconds,
            )
        finally:
            current = self._pending.pop(approval_id, None)
            self._approval_grant_keys.pop(approval_id, None)
            if current and not current.future.done():
                current.future.cancel()

    def resolve(self, approval_id: str, approved: bool) -> PendingApproval | None:
        approval = self._pending.get(approval_id)
        if approval is None:
            return None

        if not approval.future.done():
            approval.future.set_result(approved)

        return approval

    def cancel(self, approval_id: str) -> None:
        approval = self._pending.pop(approval_id, None)
        self._approval_grant_keys.pop(approval_id, None)
        if approval is not None and not approval.future.done():
            approval.future.cancel()


approval_manager = ApprovalManager()
