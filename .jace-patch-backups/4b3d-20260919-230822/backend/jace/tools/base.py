from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel, ValidationError
from sqlalchemy.ext.asyncio import AsyncSession


ToolPermissionMode = Literal["allow", "ask", "deny"]
ToolRisk = Literal["read", "write", "execute"]


class ToolError(Exception):
    pass


class ToolValidationError(ToolError):
    pass


@dataclass
class ToolContext:
    session: AsyncSession
    conversation_id: str | None
    user_message: str
    capability_binding: dict[str, Any] | None = None


@dataclass
class ToolExecutionResult:
    content: str
    display: str | None = None
    metadata: dict[str, Any] | None = None
    images: list[str] | None = None


ToolHandler = Callable[[BaseModel, ToolContext], Awaitable[ToolExecutionResult]]


# JACE_4B3C_DYNAMIC_TOOL_POLICY
@dataclass(frozen=True)
class ToolPolicyDecision:
    minimum_permission: ToolPermissionMode = "allow"
    classification: str = "standard"
    reason: str | None = None
    risk: ToolRisk | None = None


ToolPolicyResolver = Callable[
    [dict[str, Any]],
    ToolPolicyDecision,
]


@dataclass(frozen=True)
class ToolDefinition:
    name: str
    label: str
    description: str
    category: str
    risk: ToolRisk
    default_permission: ToolPermissionMode
    input_model: type[BaseModel]
    handler: ToolHandler
    provider_id: str | None = None
    capability_id: str | None = None
    policy_resolver: ToolPolicyResolver | None = None

    def resolve_policy(
        self,
        arguments: dict[str, Any],
    ) -> ToolPolicyDecision:
        if self.policy_resolver is None:
            return ToolPolicyDecision(
                minimum_permission="allow",
                classification="standard",
                risk=self.risk,
            )

        try:
            decision = self.policy_resolver(arguments)
        except Exception as exc:
            return ToolPolicyDecision(
                minimum_permission="ask",
                classification="policy_error",
                risk=self.risk,
                reason=(
                    "Dynamic tool policy evaluation failed closed: "
                    f"{exc}"
                ),
            )

        if decision.minimum_permission not in {"allow", "ask", "deny"}:
            return ToolPolicyDecision(
                minimum_permission="ask",
                classification="policy_error",
                risk=self.risk,
                reason=(
                    "Dynamic tool policy returned an invalid permission "
                    "and was escalated to ask."
                ),
            )

        return decision

    def ollama_schema(self) -> dict[str, Any]:
        schema = self.input_model.model_json_schema()
        schema.pop("title", None)
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": schema,
            },
        }

    async def execute(
        self,
        arguments: dict[str, Any],
        context: ToolContext,
    ) -> ToolExecutionResult:
        try:
            validated = self.input_model.model_validate(arguments)
        except ValidationError as exc:
            raise ToolValidationError(
                f"Invalid arguments for {self.name}: {exc.errors(include_url=False)}"
            ) from exc

        return await self.handler(validated, context)
