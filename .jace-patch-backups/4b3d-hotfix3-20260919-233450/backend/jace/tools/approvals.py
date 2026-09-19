import asyncio
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
    provider_id: str | None = None
    connection_id: str | None = None
    capability_id: str | None = None
    account_hint: str | None = None


class ApprovalManager:
    def __init__(self) -> None:
        self._pending: dict[str, PendingApproval] = {}
        # JACE_4B3D_SESSION_APPROVAL_GRANTS
        self._approval_grant_keys: dict[str, str] = {}
        self._session_grants: set[tuple[str, str, str]] = set()

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
    ) -> None:
        value = str(
            grant_key
            or ""
        ).strip()

        if value:
            self._approval_grant_keys[
                approval_id
            ] = value

    def grant_key(
        self,
        approval_id: str,
    ) -> str | None:
        return self._approval_grant_keys.get(
            approval_id
        )

    def is_session_granted(
        self,
        conversation_id: str | None,
        tool_name: str,
        grant_key: str | None,
    ) -> bool:
        if (
            not conversation_id
            or not grant_key
        ):
            return False

        return (
            conversation_id,
            tool_name,
            grant_key,
        ) in self._session_grants

    def grant_session(
        self,
        conversation_id: str | None,
        tool_name: str,
        grant_key: str | None,
    ) -> bool:
        if (
            not conversation_id
            or not grant_key
        ):
            return False

        self._session_grants.add(
            (
                conversation_id,
                tool_name,
                grant_key,
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
            if item[0] == conversation_id
        }

        self._session_grants.difference_update(
            matches
        )
        return len(matches)

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
