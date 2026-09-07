import asyncio
import json
import time
from collections.abc import (
    AsyncIterator,
)
from contextlib import (
    asynccontextmanager,
)
from typing import Any

from fastapi import (
    FastAPI,
    HTTPException,
)
from fastapi.middleware.cors import (
    CORSMiddleware,
)
from fastapi.responses import (
    StreamingResponse,
)

from jace.ai.engine import (
    OllamaRequestError,
    OllamaUnavailableError,
    get_models,
    stream_chat,
)
from jace.config import settings
from jace.database import (
    SessionLocal,
    close_database,
    init_database,
)
from jace.db.conversations import (
    add_message,
    create_conversation,
    delete_conversation,
    get_conversation,
    list_conversations,
    model_history,
    store_user_message,
    update_conversation,
)
from jace.schemas import (
    ConversationCreate,
    ConversationDetail,
    ConversationListResponse,
    ConversationSummary,
    ConversationUpdate,
    GenerationStatsResponse,
    HealthResponse,
    MessageResponse,
    ModelsResponse,
    PersistentChatRequest,
    MemoryCreate,
    MemoryListResponse,
    MemoryResponse,
    MemorySearchRequest,
    MemorySearchResponse,
    MemorySearchResult,
    MemoryUpdate,
)
from jace.memory.service import (
    build_memory_context,
    create_memory,
    delete_memory,
    get_memory,
    list_memories,
    search_memories,
    update_memory,
)
from jace.memory.extractor import (
    detect_memory_command,
    process_explicit_command,
    schedule_memory_extraction,
)

@asynccontextmanager
async def lifespan(
    app: FastAPI,
):
    del app

    await init_database()

    yield

    await close_database()


app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description=(
        "Local backend for the "
        "Jace AI assistant."
    ),
    lifespan=lifespan,
)


app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=(
        r"^(http://localhost(:\d+)?|"
        r"http://127\.0\.0\.1(:\d+)?|"
        r"http://tauri\.localhost|"
        r"https://tauri\.localhost|"
        r"tauri://localhost)$"
    ),
    allow_credentials=False,
    allow_methods=[
        "GET",
        "POST",
        "PATCH",
        "DELETE",
        "OPTIONS",
    ],
    allow_headers=[
        "Content-Type",
    ],
)


def ndjson_event(
    data: dict[str, Any],
) -> str:
    return (
        json.dumps(
            data,
            ensure_ascii=False,
            separators=(",", ":"),
        )
        + "\n"
    )


def nanoseconds_to_ms(
    nanoseconds: int | None,
) -> float | None:
    if nanoseconds is None:
        return None

    return round(
        nanoseconds / 1_000_000,
        2,
    )


def calculate_tokens_per_second(
    token_count: int | None,
    duration_nanoseconds: int | None,
) -> float | None:
    if (
        not token_count
        or not duration_nanoseconds
        or duration_nanoseconds <= 0
    ):
        return None

    seconds = (
        duration_nanoseconds
        / 1_000_000_000
    )

    if seconds <= 0:
        return None

    return round(
        token_count / seconds,
        2,
    )


def message_response(
    message,
) -> MessageResponse:
    has_stats = any(
        value is not None
        for value in [
            message.time_to_first_token_ms,
            message.total_duration_ms,
            message.load_duration_ms,
            message.prompt_eval_count,
            message.prompt_eval_cached_count,
            message.prompt_eval_duration_ms,
            message.eval_count,
            message.eval_duration_ms,
            message.tokens_per_second,
        ]
    )

    stats = None

    if has_stats:
        stats = GenerationStatsResponse(
            time_to_first_token_ms=(
                message.time_to_first_token_ms
            ),
            total_duration_ms=(
                message.total_duration_ms
            ),
            load_duration_ms=(
                message.load_duration_ms
            ),
            prompt_eval_count=(
                message.prompt_eval_count
            ),
            prompt_eval_cached_count=(
                message.prompt_eval_cached_count
            ),
            prompt_eval_duration_ms=(
                message.prompt_eval_duration_ms
            ),
            eval_count=(
                message.eval_count
            ),
            eval_duration_ms=(
                message.eval_duration_ms
            ),
            tokens_per_second=(
                message.tokens_per_second
            ),
        )

    return MessageResponse(
        id=message.id,
        conversation_id=(
            message.conversation_id
        ),
        role=message.role,
        content=message.content,
        status=message.status,
        model=message.model,
        created_at=message.created_at,
        stats=stats,
    )

def memory_response(
    memory,
) -> MemoryResponse:
    return MemoryResponse(
        id=memory.id,

        memory_type=(
            memory.memory_type
        ),

        subject=memory.subject,

        content=memory.content,

        importance=(
            memory.importance
        ),

        confidence=(
            memory.confidence
        ),

        source_type=(
            memory.source_type
        ),

        source_conversation_id=(
            memory.source_conversation_id
        ),

        source_message_id=(
            memory.source_message_id
        ),

        embedding_model=(
            memory.embedding_model
        ),

        is_pinned=(
            memory.is_pinned
        ),

        is_active=(
            memory.is_active
        ),

        created_at=(
            memory.created_at
        ),

        updated_at=(
            memory.updated_at
        ),

        last_accessed_at=(
            memory.last_accessed_at
        ),

        access_count=(
            memory.access_count
        ),
    )


def conversation_detail_response(
    conversation,
) -> ConversationDetail:
    return ConversationDetail(
        id=conversation.id,
        title=conversation.title,
        model=conversation.model,
        system_prompt=(
            conversation.system_prompt
        ),
        created_at=conversation.created_at,
        updated_at=conversation.updated_at,
        messages=[
            message_response(message)
            for message
            in conversation.messages
        ],
    )


@app.get("/")
async def root():
    return {
        "name": settings.app_name,
        "version": settings.app_version,
        "status": "running",
    }


@app.get(
    "/health",
    response_model=HealthResponse,
)
async def health():
    try:
        models = await get_models()

        return HealthResponse(
            status="ok",
            ollama_connected=True,
            app_version=settings.app_version,
            default_model=settings.default_model,
            installed_models=len(models),
        )

    except (
        OllamaUnavailableError,
        OllamaRequestError,
    ):
        return HealthResponse(
            status="degraded",
            ollama_connected=False,
            app_version=settings.app_version,
            default_model=settings.default_model,
            installed_models=0,
        )


@app.get(
    "/models",
    response_model=ModelsResponse,
)
async def models():
    try:
        installed_models = (
            await get_models()
        )

        return ModelsResponse(
            models=installed_models,
        )

    except OllamaUnavailableError as exc:
        raise HTTPException(
            status_code=503,
            detail=str(exc),
        ) from exc

    except OllamaRequestError as exc:
        raise HTTPException(
            status_code=502,
            detail=str(exc),
        ) from exc

# ----------------------------------
# Long-term Memory
# ----------------------------------


@app.post(
    "/memories",
    response_model=MemoryResponse,
)
async def create_new_memory(
    request: MemoryCreate,
):
    async with SessionLocal() as session:
        try:
            memory = await create_memory(
                session,

                memory_type=(
                    request.memory_type
                ),

                subject=(
                    request.subject
                ),

                content=(
                    request.content
                ),

                importance=(
                    request.importance
                ),

                confidence=(
                    request.confidence
                ),

                is_pinned=(
                    request.is_pinned
                ),
            )

        except ValueError as exc:
            raise HTTPException(
                status_code=400,
                detail=str(exc),
            ) from exc

        return memory_response(
            memory
        )


@app.get(
    "/memories",
    response_model=MemoryListResponse,
)
async def memories(
    query: str | None = None,
    memory_type: str | None = None,
    active_only: bool = True,
):
    async with SessionLocal() as session:
        results = await list_memories(
            session,

            query=query,

            memory_type=(
                memory_type
            ),

            active_only=(
                active_only
            ),
        )

        return MemoryListResponse(
            memories=[
                memory_response(
                    memory
                )
                for memory
                in results
            ]
        )


@app.get(
    "/memories/{memory_id}",
    response_model=MemoryResponse,
)
async def memory(
    memory_id: str,
):
    async with SessionLocal() as session:
        result = await get_memory(
            session,
            memory_id,
        )

        if result is None:
            raise HTTPException(
                status_code=404,
                detail="Memory not found.",
            )

        return memory_response(
            result
        )


@app.patch(
    "/memories/{memory_id}",
    response_model=MemoryResponse,
)
async def patch_memory(
    memory_id: str,
    request: MemoryUpdate,
):
    async with SessionLocal() as session:
        memory = await get_memory(
            session,
            memory_id,
        )

        if memory is None:
            raise HTTPException(
                status_code=404,
                detail="Memory not found.",
            )

        try:
            memory = await update_memory(
                session,
                memory,

                memory_type=(
                    request.memory_type
                ),

                subject=(
                    request.subject
                ),

                content=(
                    request.content
                ),

                importance=(
                    request.importance
                ),

                confidence=(
                    request.confidence
                ),

                is_pinned=(
                    request.is_pinned
                ),

                is_active=(
                    request.is_active
                ),
            )

        except ValueError as exc:
            raise HTTPException(
                status_code=400,
                detail=str(exc),
            ) from exc

        return memory_response(
            memory
        )


@app.delete(
    "/memories/{memory_id}",
)
async def remove_memory(
    memory_id: str,
):
    async with SessionLocal() as session:
        memory = await get_memory(
            session,
            memory_id,
        )

        if memory is None:
            raise HTTPException(
                status_code=404,
                detail="Memory not found.",
            )

        await delete_memory(
            session,
            memory,
        )

        return {
            "success": True
        }


@app.post(
    "/memories/search",
    response_model=MemorySearchResponse,
)
async def semantic_memory_search(
    request: MemorySearchRequest,
):
    async with SessionLocal() as session:
        hits = await search_memories(
            session,

            request.query,

            limit=request.limit,

            min_similarity=(
                request.min_similarity
            ),

            update_access=False,
        )

        return MemorySearchResponse(
            results=[
                MemorySearchResult(
                    memory=memory_response(
                        hit.memory
                    ),

                    similarity=round(
                        hit.similarity,
                        4,
                    ),

                    score=round(
                        hit.score,
                        4,
                    ),
                )
                for hit
                in hits
            ]
        )

# ----------------------------------
# Conversations
# ----------------------------------


@app.post(
    "/conversations",
    response_model=ConversationDetail,
)
async def create_new_conversation(
    request: ConversationCreate,
):
    async with SessionLocal() as session:
        conversation = (
            await create_conversation(
                session,
                model=request.model,
                system_prompt=(
                    request.system_prompt
                ),
            )
        )

        conversation = (
            await get_conversation(
                session,
                conversation.id,
            )
        )

        if conversation is None:
            raise HTTPException(
                status_code=500,
                detail=(
                    "Conversation could "
                    "not be created."
                ),
            )

        return (
            conversation_detail_response(
                conversation
            )
        )


@app.get(
    "/conversations",
    response_model=ConversationListResponse,
)
async def conversations():
    async with SessionLocal() as session:
        rows = await list_conversations(
            session
        )

        return ConversationListResponse(
            conversations=[
                ConversationSummary(
                    id=conversation.id,
                    title=conversation.title,
                    model=conversation.model,
                    created_at=(
                        conversation.created_at
                    ),
                    updated_at=(
                        conversation.updated_at
                    ),
                    message_count=message_count,
                )
                for (
                    conversation,
                    message_count,
                ) in rows
            ]
        )


@app.get(
    "/conversations/{conversation_id}",
    response_model=ConversationDetail,
)
async def conversation(
    conversation_id: str,
):
    async with SessionLocal() as session:
        result = await get_conversation(
            session,
            conversation_id,
        )

        if result is None:
            raise HTTPException(
                status_code=404,
                detail=(
                    "Conversation not found."
                ),
            )

        return (
            conversation_detail_response(
                result
            )
        )


@app.patch(
    "/conversations/{conversation_id}",
    response_model=ConversationDetail,
)
async def patch_conversation(
    conversation_id: str,
    request: ConversationUpdate,
):
    async with SessionLocal() as session:
        conversation = (
            await get_conversation(
                session,
                conversation_id,
            )
        )

        if conversation is None:
            raise HTTPException(
                status_code=404,
                detail=(
                    "Conversation not found."
                ),
            )

        await update_conversation(
            session,
            conversation,
            title=request.title,
            model=request.model,
            system_prompt=(
                request.system_prompt
            ),
        )

        conversation = (
            await get_conversation(
                session,
                conversation_id,
            )
        )

        return (
            conversation_detail_response(
                conversation
            )
        )


@app.delete(
    "/conversations/{conversation_id}",
)
async def remove_conversation(
    conversation_id: str,
):
    async with SessionLocal() as session:
        deleted = (
            await delete_conversation(
                session,
                conversation_id,
            )
        )

        if not deleted:
            raise HTTPException(
                status_code=404,
                detail=(
                    "Conversation not found."
                ),
            )

        return {
            "success": True
        }


# ----------------------------------
# Streaming Chat
# ----------------------------------


@app.post("/chat/stream")
async def send_streaming_chat(
    request: PersistentChatRequest,
):
    # Prepare the conversation and
    # persist the user's message first.
    async with SessionLocal() as session:
        conversation = (
            await get_conversation(
                session,
                request.conversation_id,
            )
        )

        if conversation is None:
            raise HTTPException(
                status_code=404,
                detail=(
                    "Conversation not found."
                ),
            )

        await update_conversation(
            session,
            conversation,
            model=request.model,
            system_prompt=(
                request.system_prompt
            ),
        )

        user_message = (
            await store_user_message(
                session,
                conversation,
                request.message,
            )
        )

        user_message_id = (
            user_message.id
        )

        memory_command = (
            detect_memory_command(
                request.message
            )
        )

        memory_command_handled = (
            memory_command
            is not None
        )

        memory_action_context = ""


        if memory_command is not None:
            try:
                result = (
                    await process_explicit_command(
                        session,

                        command=(
                            memory_command
                        ),

                        conversation_id=(
                            conversation.id
                        ),

                        source_message_id=(
                            user_message_id
                        ),
                    )
                )

                memory_action_context = f"""


        MEMORY SYSTEM ACTION

        The Jace application has already processed
        the user's explicit memory instruction.

        Result:
        {result}

        This is an actual completed application action.
        You may accurately acknowledge the result.
        Do not claim that you lack persistent memory.

        END MEMORY SYSTEM ACTION
        """

            except (
                OllamaUnavailableError,
                OllamaRequestError,
            ) as exc:

                memory_action_context = f"""


        MEMORY SYSTEM ACTION

        The user's explicit memory instruction
        could not be completed.

        Reason:
        {str(exc)}

        Do not claim that the action succeeded.

        END MEMORY SYSTEM ACTION
        """

        conversation = (
            await get_conversation(
                session,
                conversation.id,
            )
        )

        if conversation is None:
            raise HTTPException(
                status_code=500,
                detail=(
                    "Conversation could "
                    "not be reloaded."
                ),
            )

        history = model_history(
            conversation
        )

        conversation_id = (
            conversation.id
        )

        conversation_model = (
            conversation.model
        )

        conversation_system_prompt = (
            conversation.system_prompt
        )


    async def persist_assistant(
        content: str,
        status: str,
        metrics: dict | None = None,
    ) -> str | None:
        
        if not content.strip():
          return None

        async with SessionLocal() as session:
            conversation = (
                await get_conversation(
                    session,
                    conversation_id,
                )
            )

            if conversation is None:
                return None

            message = await add_message(
                session,
                conversation=conversation,
                role="assistant",
                content=content,
                status=status,
                model=conversation_model,
                metrics=metrics,
            )

            return message.id


    async def generate() -> AsyncIterator[str]:
        response_parts: list[str] = []

        started_at = (
            time.perf_counter()
        )

        # Search long-term memory before
        # asking the conversational model.
        async with SessionLocal() as session:
            memory_hits = (
                await search_memories(
                    session,

                    request.message,

                    limit=(
                        settings.memory_top_k
                    ),

                    min_similarity=(
                        settings.memory_min_similarity
                    ),

                    update_access=True,
                )
            )

        memory_context = (
            build_memory_context(
                memory_hits
            )
        )

        effective_system_prompt = (
            conversation_system_prompt
            + memory_context
            + memory_action_context
        )

        first_token_at: (
            float | None
        ) = None

        saved = False

        try:
            async for chunk in stream_chat(
                model=conversation_model,
                messages=history,
                system_prompt=(
                    effective_system_prompt
                ),
            ):
                message = (
                    chunk.get("message")
                    or {}
                )

                content = (
                    message.get("content")
                    or ""
                )

                if content:
                    if first_token_at is None:
                        first_token_at = (
                            time.perf_counter()
                        )

                    response_parts.append(
                        content
                    )

                    yield ndjson_event(
                        {
                            "type": "token",
                            "content": content,
                        }
                    )


                if chunk.get("done"):
                    eval_count = (
                        chunk.get(
                            "eval_count"
                        )
                    )

                    eval_duration = (
                        chunk.get(
                            "eval_duration"
                        )
                    )

                    time_to_first_token_ms = (
                        round(
                            (
                                first_token_at
                                - started_at
                            )
                            * 1000,
                            2,
                        )
                        if first_token_at
                        is not None
                        else None
                    )

                    metrics = {
                        "time_to_first_token_ms":
                            time_to_first_token_ms,

                        "total_duration_ms":
                            nanoseconds_to_ms(
                                chunk.get(
                                    "total_duration"
                                )
                            ),

                        "load_duration_ms":
                            nanoseconds_to_ms(
                                chunk.get(
                                    "load_duration"
                                )
                            ),

                        "prompt_eval_count":
                            chunk.get(
                                "prompt_eval_count"
                            ),

                        "prompt_eval_cached_count":
                            chunk.get(
                                "prompt_eval_cached_count"
                            ),

                        "prompt_eval_duration_ms":
                            nanoseconds_to_ms(
                                chunk.get(
                                    "prompt_eval_duration"
                                )
                            ),

                        "eval_count":
                            eval_count,

                        "eval_duration_ms":
                            nanoseconds_to_ms(
                                eval_duration
                            ),

                        "tokens_per_second":
                            calculate_tokens_per_second(
                                eval_count,
                                eval_duration,
                            ),
                    }

                    full_response = (
                        "".join(
                            response_parts
                        )
                    )

                    assistant_message_id = (
                        await persist_assistant(
                            full_response,
                            "complete",
                            metrics,
                        )
                    )

                    saved = True


                    # Explicit Remember/Forget commands
                    # were already handled synchronously.
                    #
                    # Everything else can be examined
                    # automatically after the response.
                    if (
                        not memory_command_handled
                        and assistant_message_id
                    ):
                        schedule_memory_extraction(
                            conversation_id=(
                                conversation_id
                            ),

                            source_message_id=(
                                user_message_id
                            ),

                            user_message=(
                                request.message
                            ),

                            assistant_message=(
                                full_response
                            ),
                        )

                    yield ndjson_event(
                        {
                            "type": "done",

                            "model": (
                                chunk.get(
                                    "model",
                                    conversation_model,
                                )
                            ),

                            "done_reason": (
                                chunk.get(
                                    "done_reason"
                                )
                            ),

                            "metrics": metrics,
                        }
                    )


        except asyncio.CancelledError:
            if (
                response_parts
                and not saved
            ):
                partial_response = (
                    "".join(
                        response_parts
                    )
                )

                # Shield the database write
                # from request cancellation.
                await asyncio.shield(
                    persist_assistant(
                        partial_response,
                        "stopped",
                    )
                )

            raise


        except OllamaUnavailableError as exc:
            if (
                response_parts
                and not saved
            ):
                await persist_assistant(
                    "".join(
                        response_parts
                    ),
                    "error",
                )

                saved = True

            yield ndjson_event(
                {
                    "type": "error",
                    "message": str(exc),
                }
            )


        except OllamaRequestError as exc:
            if (
                response_parts
                and not saved
            ):
                await persist_assistant(
                    "".join(
                        response_parts
                    ),
                    "error",
                )

                saved = True

            yield ndjson_event(
                {
                    "type": "error",
                    "message": str(exc),
                }
            )


    return StreamingResponse(
        generate(),
        media_type=(
            "application/x-ndjson"
        ),
        headers={
            "Cache-Control":
                "no-cache",

            "X-Accel-Buffering":
                "no",
        },
    )