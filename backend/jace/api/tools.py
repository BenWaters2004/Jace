import json

from fastapi import APIRouter, HTTPException, Query

from jace.config import settings
from jace.database import SessionLocal
from jace.schemas import (
    PendingToolApprovalResponse,
    PendingToolApprovalsResponse,
    ToolApprovalDecisionRequest,
    ToolApprovalDecisionResponse,
    ToolAuditListResponse,
    ToolAuditResponse,
    ToolListResponse,
    ToolPermissionUpdate,
    ToolResponse,
)
from jace.tools import ensure_tools_registered
from jace.tools.approvals import approval_manager
from jace.tools.permissions import (
    clear_tool_audit,
    ensure_tool_permissions,
    list_tool_audit,
    permission_map,
    set_tool_permission,
)
from jace.tools.registry import registry


router = APIRouter(prefix="/tools", tags=["tools"])


def _arguments(value: str) -> dict:
    try:
        parsed = json.loads(value)
        return parsed if isinstance(parsed, dict) else {}
    except json.JSONDecodeError:
        return {}


@router.get("", response_model=ToolListResponse)
async def list_tools():
    ensure_tools_registered()

    async with SessionLocal() as session:
        await ensure_tool_permissions(session)
        permissions = await permission_map(session)

    return ToolListResponse(
        enabled=settings.tools_enabled,
        tools=[
            ToolResponse(
                name=definition.name,
                label=definition.label,
                description=definition.description,
                category=definition.category,
                risk=definition.risk,
                permission=permissions.get(
                    definition.name,
                    definition.default_permission,
                ),
                default_permission=definition.default_permission,
                parameters=definition.input_model.model_json_schema(),
            )
            for definition in registry.all()
        ],
    )


@router.patch("/{tool_name}/permission", response_model=ToolResponse)
async def patch_tool_permission(tool_name: str, request: ToolPermissionUpdate):
    ensure_tools_registered()
    definition = registry.get(tool_name)

    if definition is None:
        raise HTTPException(status_code=404, detail="Tool not found.")

    async with SessionLocal() as session:
        try:
            row = await set_tool_permission(
                session,
                tool_name,
                request.permission,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    return ToolResponse(
        name=definition.name,
        label=definition.label,
        description=definition.description,
        category=definition.category,
        risk=definition.risk,
        permission=row.permission,
        default_permission=definition.default_permission,
        parameters=definition.input_model.model_json_schema(),
    )


@router.get("/audit", response_model=ToolAuditListResponse)
async def tool_audit(
    limit: int = Query(default=100, ge=1, le=500),
    tool_name: str | None = None,
):
    async with SessionLocal() as session:
        entries = await list_tool_audit(
            session,
            limit=limit,
            tool_name=tool_name,
        )

    return ToolAuditListResponse(
        entries=[
            ToolAuditResponse(
                id=entry.id,
                conversation_id=entry.conversation_id,
                tool_name=entry.tool_name,
                permission_mode=entry.permission_mode,
                status=entry.status,
                arguments=_arguments(entry.arguments_json),
                result_preview=entry.result_preview,
                error=entry.error,
                approval_id=entry.approval_id,
                created_at=entry.created_at,
                completed_at=entry.completed_at,
            )
            for entry in entries
        ]
    )


@router.delete("/audit")
async def clear_audit():
    async with SessionLocal() as session:
        count = await clear_tool_audit(session)
    return {"success": True, "deleted": count}


@router.get("/approvals", response_model=PendingToolApprovalsResponse)
async def pending_approvals():
    return PendingToolApprovalsResponse(
        approvals=[
            PendingToolApprovalResponse(
                approval_id=approval.approval_id,
                conversation_id=approval.conversation_id,
                tool_name=approval.tool_name,
                label=approval.label,
                description=approval.description,
                risk=approval.risk,
                arguments=approval.arguments,
                created_at=approval.created_at,
            )
            for approval in approval_manager.list()
        ]
    )


@router.post(
    "/approvals/{approval_id}",
    response_model=ToolApprovalDecisionResponse,
)
async def resolve_approval(
    approval_id: str,
    request: ToolApprovalDecisionRequest,
):
    approval = approval_manager.get(approval_id)
    if approval is None:
        raise HTTPException(
            status_code=404,
            detail="This tool approval is no longer pending.",
        )

    approved = request.decision in {"allow_once", "allow_always"}

    if request.decision in {"allow_always", "deny_always"}:
        new_permission = "allow" if request.decision == "allow_always" else "deny"
        async with SessionLocal() as session:
            await set_tool_permission(
                session,
                approval.tool_name,
                new_permission,
            )

    resolved = approval_manager.resolve(
        approval_id,
        approved,
    )

    return ToolApprovalDecisionResponse(
        approval_id=approval_id,
        resolved=resolved is not None,
        decision=request.decision,
        tool_name=approval.tool_name,
    )
