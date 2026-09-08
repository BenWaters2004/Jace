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


@dataclass
class ToolExecutionResult:
    content: str
    display: str | None = None
    metadata: dict[str, Any] | None = None
    images: list[str] | None = None


ToolHandler = Callable[[BaseModel, ToolContext], Awaitable[ToolExecutionResult]]


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
