from datetime import datetime
from typing import Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
)


class ChatMessage(BaseModel):
    role: Literal[
        "user",
        "assistant",
    ]

    content: str = Field(
        min_length=1
    )


class ModelInfo(BaseModel):
    name: str

    size: int | None = None

    parameter_size: str | None = None

    quantization_level: str | None = None


class ModelsResponse(BaseModel):
    models: list[ModelInfo]


class HealthResponse(BaseModel):
    status: str

    ollama_connected: bool

    app_version: str

    default_model: str

    installed_models: int


class ConversationCreate(BaseModel):
    model: str

    system_prompt: str = ""


class ConversationUpdate(BaseModel):
    title: str | None = None

    model: str | None = None

    system_prompt: str | None = None


class GenerationStatsResponse(BaseModel):
    time_to_first_token_ms: float | None = None

    total_duration_ms: float | None = None

    load_duration_ms: float | None = None

    prompt_eval_count: int | None = None

    prompt_eval_cached_count: int | None = None

    prompt_eval_duration_ms: float | None = None

    eval_count: int | None = None

    eval_duration_ms: float | None = None

    tokens_per_second: float | None = None


class MessageResponse(BaseModel):
    model_config = ConfigDict(
        from_attributes=True
    )

    id: str

    conversation_id: str

    role: str

    content: str

    status: str

    model: str | None = None

    created_at: datetime

    stats: GenerationStatsResponse | None = None


class ConversationSummary(BaseModel):
    id: str

    title: str

    model: str

    created_at: datetime

    updated_at: datetime

    message_count: int


class ConversationDetail(BaseModel):
    id: str

    title: str

    model: str

    system_prompt: str

    created_at: datetime

    updated_at: datetime

    messages: list[MessageResponse]


class ConversationListResponse(BaseModel):
    conversations: list[
        ConversationSummary
    ]


class PersistentChatRequest(BaseModel):
    conversation_id: str

    message: str = Field(
        min_length=1,
        max_length=100_000,
    )

    model: str

    system_prompt: str


class MemoryCreate(BaseModel):
    memory_type: Literal[
        "fact",
        "preference",
        "project",
        "decision",
        "goal",
        "temporary",
        "other",
    ] = "fact"

    subject: str = Field(
        min_length=1,
        max_length=200,
    )

    content: str = Field(
        min_length=1,
        max_length=10_000,
    )

    importance: float = Field(
        default=0.5,
        ge=0.0,
        le=1.0,
    )

    confidence: float = Field(
        default=1.0,
        ge=0.0,
        le=1.0,
    )

    is_pinned: bool = False


class MemoryUpdate(BaseModel):
    memory_type: Literal[
        "fact",
        "preference",
        "project",
        "decision",
        "goal",
        "temporary",
        "other",
    ] | None = None

    subject: str | None = Field(
        default=None,
        min_length=1,
        max_length=200,
    )

    content: str | None = Field(
        default=None,
        min_length=1,
        max_length=10_000,
    )

    importance: float | None = Field(
        default=None,
        ge=0.0,
        le=1.0,
    )

    confidence: float | None = Field(
        default=None,
        ge=0.0,
        le=1.0,
    )

    is_pinned: bool | None = None

    is_active: bool | None = None


class MemoryResponse(BaseModel):
    id: str

    memory_type: str

    subject: str

    content: str

    importance: float

    confidence: float

    source_type: str

    source_conversation_id: str | None

    source_message_id: str | None

    embedding_model: str

    is_pinned: bool

    is_active: bool

    created_at: datetime

    updated_at: datetime

    last_accessed_at: datetime | None

    access_count: int


class MemoryListResponse(BaseModel):
    memories: list[
        MemoryResponse
    ]


class MemorySearchRequest(BaseModel):
    query: str = Field(
        min_length=1,
        max_length=10_000,
    )

    limit: int = Field(
        default=6,
        ge=1,
        le=50,
    )

    min_similarity: float = Field(
        default=0.30,
        ge=-1.0,
        le=1.0,
    )


class MemorySearchResult(BaseModel):
    memory: MemoryResponse

    similarity: float

    score: float


class MemorySearchResponse(BaseModel):
    results: list[
        MemorySearchResult
    ]


class ExtractedMemoryCandidate(BaseModel):
    memory_type: Literal[
        "fact",
        "preference",
        "project",
        "decision",
        "goal",
        "temporary",
        "other",
    ]

    subject: str = Field(
        min_length=1,
        max_length=200,
    )

    content: str = Field(
        min_length=1,
        max_length=2000,
    )

    importance: float = Field(
        ge=0.0,
        le=1.0,
    )

    confidence: float = Field(
        ge=0.0,
        le=1.0,
    )


class MemoryExtractionResult(BaseModel):
    memories: list[
        ExtractedMemoryCandidate
    ] = Field(
        default_factory=list,
        max_length=5,
    )


class MemoryReconciliationResult(BaseModel):
    action: Literal[
        "create",
        "duplicate",
        "merge",
        "supersede",
        "ignore",
    ]

    target_memory_id: str | None = None

    memory_type: Literal[
        "fact",
        "preference",
        "project",
        "decision",
        "goal",
        "temporary",
        "other",
    ]

    subject: str = Field(
        min_length=1,
        max_length=200,
    )

    content: str = Field(
        min_length=1,
        max_length=2000,
    )

    importance: float = Field(
        ge=0.0,
        le=1.0,
    )

    confidence: float = Field(
        ge=0.0,
        le=1.0,
    )

    reason: str = Field(
        min_length=1,
        max_length=500,
    )