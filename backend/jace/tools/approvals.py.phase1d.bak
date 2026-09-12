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


class ApprovalManager:
    def __init__(self) -> None:
        self._pending: dict[str, PendingApproval] = {}

    def create(
        self,
        *,
        conversation_id: str | None,
        tool_name: str,
        label: str,
        description: str,
        risk: str,
        arguments: dict,
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
        )
        self._pending[approval.approval_id] = approval
        return approval

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
        if approval is not None and not approval.future.done():
            approval.future.cancel()


approval_manager = ApprovalManager()
