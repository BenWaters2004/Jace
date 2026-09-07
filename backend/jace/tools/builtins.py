import ast
import json
import math
import operator
from datetime import datetime
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from jace.db.conversations import get_conversation, update_conversation
from jace.db.models import Conversation
from jace.memory.service import create_memory, get_memory, search_memories, update_memory
from jace.tools.base import ToolContext, ToolDefinition, ToolError, ToolExecutionResult
from jace.tools.registry import registry


# -----------------------------
# Calculator
# -----------------------------


class CalculatorInput(BaseModel):
    expression: str = Field(
        min_length=1,
        max_length=500,
        description="Arithmetic expression using numbers, parentheses and + - * / // % **.",
    )


_BINARY_OPERATORS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}

_UNARY_OPERATORS = {
    ast.UAdd: operator.pos,
    ast.USub: operator.neg,
}


def _safe_number(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ToolError("Calculator only supports real numeric values.")
    if isinstance(value, float) and not math.isfinite(value):
        raise ToolError("Calculator result was not finite.")
    if abs(value) > 1e100:
        raise ToolError("Calculator result is too large.")
    return value


def _evaluate_node(node: ast.AST, depth: int = 0):
    if depth > 25:
        raise ToolError("Calculator expression is too deeply nested.")

    if isinstance(node, ast.Expression):
        return _evaluate_node(node.body, depth + 1)

    if isinstance(node, ast.Constant):
        return _safe_number(node.value)

    if isinstance(node, ast.UnaryOp) and type(node.op) in _UNARY_OPERATORS:
        value = _evaluate_node(node.operand, depth + 1)
        return _safe_number(_UNARY_OPERATORS[type(node.op)](value))

    if isinstance(node, ast.BinOp) and type(node.op) in _BINARY_OPERATORS:
        left = _evaluate_node(node.left, depth + 1)
        right = _evaluate_node(node.right, depth + 1)

        if isinstance(node.op, ast.Pow):
            if abs(right) > 20:
                raise ToolError("Exponent is too large.")
            if abs(left) > 1e20:
                raise ToolError("Power base is too large.")

        try:
            return _safe_number(_BINARY_OPERATORS[type(node.op)](left, right))
        except ZeroDivisionError as exc:
            raise ToolError("Division by zero.") from exc

    raise ToolError("Unsupported calculator expression.")


async def calculator_tool(data: BaseModel, context: ToolContext) -> ToolExecutionResult:
    del context
    payload = data
    assert isinstance(payload, CalculatorInput)
    try:
        tree = ast.parse(payload.expression, mode="eval")
    except SyntaxError as exc:
        raise ToolError("Invalid arithmetic expression.") from exc

    result = _evaluate_node(tree)
    text = f"{payload.expression} = {result}"
    return ToolExecutionResult(
        content=json.dumps({"expression": payload.expression, "result": result}),
        display=text,
    )


# -----------------------------
# Current date/time
# -----------------------------


class CurrentDateTimeInput(BaseModel):
    timezone: str | None = Field(
        default=None,
        max_length=100,
        description=(
            "Optional IANA timezone such as Europe/London or America/New_York. "
            "Omit it to use this computer's local timezone."
        ),
    )


async def current_datetime_tool(data: BaseModel, context: ToolContext) -> ToolExecutionResult:
    del context
    payload = data
    assert isinstance(payload, CurrentDateTimeInput)

    if payload.timezone:
        try:
            zone = ZoneInfo(payload.timezone)
        except ZoneInfoNotFoundError as exc:
            raise ToolError(f"Unknown timezone: {payload.timezone}") from exc
        now = datetime.now(zone)
        timezone_name = payload.timezone
    else:
        now = datetime.now().astimezone()
        timezone_name = str(now.tzinfo)

    result = {
        "iso": now.isoformat(),
        "date": now.strftime("%Y-%m-%d"),
        "time": now.strftime("%H:%M:%S"),
        "weekday": now.strftime("%A"),
        "timezone": timezone_name,
    }

    return ToolExecutionResult(
        content=json.dumps(result),
        display=f"{result['weekday']} {result['date']} {result['time']} ({timezone_name})",
    )


# -----------------------------
# Memory search
# -----------------------------


class SearchMemoryInput(BaseModel):
    query: str = Field(min_length=1, max_length=2_000)
    limit: int = Field(default=5, ge=1, le=10)


async def search_memory_tool(data: BaseModel, context: ToolContext) -> ToolExecutionResult:
    payload = data
    assert isinstance(payload, SearchMemoryInput)

    hits = await search_memories(
        context.session,
        payload.query,
        limit=payload.limit,
        min_similarity=0.45,
        update_access=False,
    )

    memories = [
        {
            "id": hit.memory.id,
            "type": hit.memory.memory_type,
            "subject": hit.memory.subject,
            "content": hit.memory.content,
            "confidence": round(hit.memory.confidence, 3),
            "relevance": round(hit.similarity, 3),
        }
        for hit in hits
    ]

    return ToolExecutionResult(
        content=json.dumps({"memories": memories}, ensure_ascii=False),
        display=(
            f"Found {len(memories)} relevant memor{'y' if len(memories) == 1 else 'ies'}."
            if memories
            else "No relevant memories found."
        ),
    )


# -----------------------------
# Conversation search
# -----------------------------


class SearchConversationsInput(BaseModel):
    query: str = Field(
        default="",
        max_length=2_000,
        description="Search text. Leave empty to list recent conversations.",
    )
    limit: int = Field(default=5, ge=1, le=10)


async def search_conversations_tool(data: BaseModel, context: ToolContext) -> ToolExecutionResult:
    payload = data
    assert isinstance(payload, SearchConversationsInput)

    result = await context.session.execute(
        select(Conversation)
        .options(selectinload(Conversation.messages))
        .order_by(Conversation.updated_at.desc())
        .limit(100)
    )
    conversations = list(result.scalars().all())

    query = payload.query.strip().lower()
    matches: list[dict] = []

    for conversation in conversations:
        searchable = " ".join(
            [
                conversation.title,
                *[
                    message.content
                    for message in conversation.messages
                    if message.role in {"user", "assistant"}
                ],
            ]
        ).lower()

        if query and query not in searchable:
            continue

        excerpt = ""
        if query:
            for message in reversed(conversation.messages):
                if query in message.content.lower():
                    excerpt = " ".join(message.content.split())[:500]
                    break

        if not excerpt and conversation.messages:
            excerpt = " ".join(conversation.messages[-1].content.split())[:500]

        matches.append(
            {
                "id": conversation.id,
                "title": conversation.title,
                "updated_at": conversation.updated_at.isoformat(),
                "message_count": len(conversation.messages),
                "excerpt": excerpt,
            }
        )

        if len(matches) >= payload.limit:
            break

    return ToolExecutionResult(
        content=json.dumps({"conversations": matches}, ensure_ascii=False),
        display=f"Found {len(matches)} conversation{'s' if len(matches) != 1 else ''}.",
    )


# -----------------------------
# Rename current conversation
# -----------------------------


class RenameConversationInput(BaseModel):
    title: str = Field(min_length=1, max_length=200)


async def rename_conversation_tool(data: BaseModel, context: ToolContext) -> ToolExecutionResult:
    payload = data
    assert isinstance(payload, RenameConversationInput)

    if not context.conversation_id:
        raise ToolError("There is no active conversation to rename.")

    conversation = await get_conversation(context.session, context.conversation_id)
    if conversation is None:
        raise ToolError("The active conversation could not be found.")

    updated = await update_conversation(
        context.session,
        conversation,
        title=payload.title,
    )

    return ToolExecutionResult(
        content=json.dumps({"conversation_id": updated.id, "title": updated.title}),
        display=f'Renamed this conversation to "{updated.title}".',
    )


# -----------------------------
# Create memory
# -----------------------------


class CreateMemoryInput(BaseModel):
    memory_type: Literal[
        "fact",
        "preference",
        "project",
        "decision",
        "goal",
        "temporary",
        "other",
    ] = "fact"
    subject: str = Field(min_length=1, max_length=200)
    content: str = Field(min_length=1, max_length=2_000)
    importance: float = Field(default=0.7, ge=0.0, le=1.0)
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)


async def create_memory_tool(data: BaseModel, context: ToolContext) -> ToolExecutionResult:
    payload = data
    assert isinstance(payload, CreateMemoryInput)

    memory = await create_memory(
        context.session,
        memory_type=payload.memory_type,
        subject=payload.subject,
        content=payload.content,
        importance=payload.importance,
        confidence=payload.confidence,
        source_type="tool",
        source_conversation_id=context.conversation_id,
    )

    return ToolExecutionResult(
        content=json.dumps(
            {
                "memory_id": memory.id,
                "type": memory.memory_type,
                "subject": memory.subject,
                "content": memory.content,
            },
            ensure_ascii=False,
        ),
        display=f'Saved memory "{memory.subject}".',
    )


# -----------------------------
# Deactivate memory
# -----------------------------


class DeactivateMemoryInput(BaseModel):
    memory_id: str = Field(
        min_length=36,
        max_length=36,
        description=(
            "Exact memory ID returned by the search_memory tool. "
            "Search memory first; do not guess this value."
        ),
    )
    subject: str = Field(
        min_length=1,
        max_length=200,
        description=(
            "Human-readable subject returned with the memory ID. "
            "This is checked before the memory is changed."
        ),
    )


async def deactivate_memory_tool(data: BaseModel, context: ToolContext) -> ToolExecutionResult:
    payload = data
    assert isinstance(payload, DeactivateMemoryInput)

    memory = await get_memory(
        context.session,
        payload.memory_id,
    )

    if memory is None or not memory.is_active:
        raise ToolError("The requested active memory could not be found.")

    if memory.subject.strip().casefold() != payload.subject.strip().casefold():
        raise ToolError(
            "The supplied memory subject does not match that memory ID. "
            "Search memory again before trying to deactivate it."
        )

    memory = await update_memory(
        context.session,
        memory,
        is_active=False,
    )

    result = {
        "id": memory.id,
        "subject": memory.subject,
        "content": memory.content,
    }

    return ToolExecutionResult(
        content=json.dumps({"deactivated": result}, ensure_ascii=False),
        display=f'Deactivated memory "{memory.subject}".',
    )


def register_builtin_tools() -> None:
    definitions = [
        ToolDefinition(
            name="calculator",
            label="Calculator",
            description=(
                "Safely evaluate arithmetic expressions. Use this for non-trivial "
                "calculations instead of relying on mental arithmetic."
            ),
            category="Utility",
            risk="read",
            default_permission="allow",
            input_model=CalculatorInput,
            handler=calculator_tool,
        ),
        ToolDefinition(
            name="current_datetime",
            label="Current date & time",
            description=(
                "Get the current date and time from this computer, optionally in an "
                "IANA timezone."
            ),
            category="Utility",
            risk="read",
            default_permission="allow",
            input_model=CurrentDateTimeInput,
            handler=current_datetime_tool,
        ),
        ToolDefinition(
            name="search_memory",
            label="Search memory",
            description=(
                "Semantically search Jace's active long-term memories when stored "
                "context needs to be recovered explicitly."
            ),
            category="Memory",
            risk="read",
            default_permission="allow",
            input_model=SearchMemoryInput,
            handler=search_memory_tool,
        ),
        ToolDefinition(
            name="search_conversations",
            label="Search conversations",
            description=(
                "Search locally stored conversation titles and message history, or "
                "list recent conversations."
            ),
            category="History",
            risk="read",
            default_permission="allow",
            input_model=SearchConversationsInput,
            handler=search_conversations_tool,
        ),
        ToolDefinition(
            name="rename_current_conversation",
            label="Rename conversation",
            description="Rename the currently active Jace conversation.",
            category="Conversation",
            risk="write",
            default_permission="ask",
            input_model=RenameConversationInput,
            handler=rename_conversation_tool,
        ),
        ToolDefinition(
            name="create_memory",
            label="Create memory",
            description=(
                "Create a durable long-term memory. This changes Jace's persistent "
                "memory and therefore normally requires user approval."
            ),
            category="Memory",
            risk="write",
            default_permission="ask",
            input_model=CreateMemoryInput,
            handler=create_memory_tool,
        ),
        ToolDefinition(
            name="deactivate_memory",
            label="Deactivate memory",
            description=(
                "Deactivate one exact long-term memory by ID without permanently "
                "deleting it. Use search_memory first to obtain the ID and subject."
            ),
            category="Memory",
            risk="write",
            default_permission="ask",
            input_model=DeactivateMemoryInput,
            handler=deactivate_memory_tool,
        ),
    ]

    for definition in definitions:
        registry.register(definition, replace=True)
