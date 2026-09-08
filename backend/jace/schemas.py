from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


MemoryType = Literal["fact", "preference", "project", "decision", "goal", "temporary", "other"]
ReasoningMode = Literal["fast", "balanced", "deep"]
ResponseStyle = Literal["concise", "balanced", "detailed"]
ToolPermissionMode = Literal["allow", "ask", "deny"]
ToolRisk = Literal["read", "write", "execute"]


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
    embedding_model: str
    installed_models: int
    database_path: str


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


class AttachmentResponse(BaseModel):
    id: str
    conversation_id: str
    message_id: str | None
    original_name: str
    mime_type: str
    media_kind: str
    size_bytes: int
    sha256: str
    source_type: str
    source_path: str | None
    created_at: datetime


class AttachmentStatusResponse(BaseModel):
    enabled: bool
    image_max_bytes: int
    document_max_bytes: int
    audio_max_bytes: int
    max_count: int
    audio_enabled: bool
    audio_model: str
    screen_capture_enabled: bool


class MessageResponse(BaseModel):
    id: str
    conversation_id: str
    role: str
    content: str
    status: str
    model: str | None = None
    created_at: datetime
    stats: GenerationStatsResponse | None = None
    attachments: list[AttachmentResponse] = Field(default_factory=list)


class ConversationCreate(BaseModel):
    model: str | None = None
    system_prompt: str | None = None


class ConversationUpdate(BaseModel):
    title: str | None = None
    model: str | None = None
    system_prompt: str | None = None


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
    conversations: list[ConversationSummary]


class PersistentChatRequest(BaseModel):
    conversation_id: str
    message: str = Field(default="", max_length=100_000)
    attachment_ids: list[str] = Field(default_factory=list, max_length=6)
    model: str | None = None
    system_prompt: str | None = None
    reasoning_mode: ReasoningMode | None = None
    temperature: float | None = Field(default=None, ge=0.0, le=2.0)


class MemoryCreate(BaseModel):
    memory_type: MemoryType = "fact"
    subject: str = Field(min_length=1, max_length=200)
    content: str = Field(min_length=1, max_length=10_000)
    importance: float = Field(default=0.5, ge=0.0, le=1.0)
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    is_pinned: bool = False


class MemoryUpdate(BaseModel):
    memory_type: MemoryType | None = None
    subject: str | None = Field(default=None, min_length=1, max_length=200)
    content: str | None = Field(default=None, min_length=1, max_length=10_000)
    importance: float | None = Field(default=None, ge=0.0, le=1.0)
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
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
    memories: list[MemoryResponse]


class MemorySearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=10_000)
    limit: int = Field(default=6, ge=1, le=50)
    min_similarity: float = Field(default=0.50, ge=-1.0, le=1.0)


class MemorySearchResult(BaseModel):
    memory: MemoryResponse
    similarity: float
    score: float


class MemorySearchResponse(BaseModel):
    results: list[MemorySearchResult]


class ExtractedMemoryCandidate(BaseModel):
    memory_type: MemoryType
    subject: str = Field(min_length=1, max_length=200)
    content: str = Field(min_length=1, max_length=2000)
    importance: float = Field(ge=0.0, le=1.0)
    confidence: float = Field(ge=0.0, le=1.0)


class MemoryExtractionResult(BaseModel):
    memories: list[ExtractedMemoryCandidate] = Field(default_factory=list, max_length=5)


class MemoryReconciliationResult(BaseModel):
    action: Literal["create", "duplicate", "merge", "supersede", "ignore"]
    target_memory_id: str | None = None
    memory_type: MemoryType
    subject: str = Field(min_length=1, max_length=200)
    content: str = Field(min_length=1, max_length=2000)
    importance: float = Field(ge=0.0, le=1.0)
    confidence: float = Field(ge=0.0, le=1.0)
    reason: str = Field(min_length=1, max_length=500)


class AssistantSettingsResponse(BaseModel):
    assistant_name: str
    user_name: str
    system_prompt: str
    default_model: str
    reasoning_mode: ReasoningMode
    response_style: ResponseStyle
    temperature: float
    memory_enabled: bool
    memory_auto_extract: bool
    memory_top_k: int
    memory_min_similarity: float
    created_at: datetime
    updated_at: datetime


class AssistantSettingsUpdate(BaseModel):
    assistant_name: str | None = Field(default=None, min_length=1, max_length=80)
    user_name: str | None = Field(default=None, min_length=1, max_length=80)
    system_prompt: str | None = Field(default=None, min_length=1, max_length=30_000)
    default_model: str | None = Field(default=None, min_length=1, max_length=200)
    reasoning_mode: ReasoningMode | None = None
    response_style: ResponseStyle | None = None
    temperature: float | None = Field(default=None, ge=0.0, le=2.0)
    memory_enabled: bool | None = None
    memory_auto_extract: bool | None = None
    memory_top_k: int | None = Field(default=None, ge=1, le=20)
    memory_min_similarity: float | None = Field(default=None, ge=0.0, le=1.0)


# -----------------------------
# Phase 4 tools
# -----------------------------


class ToolResponse(BaseModel):
    name: str
    label: str
    description: str
    category: str
    risk: ToolRisk
    permission: ToolPermissionMode
    default_permission: ToolPermissionMode
    parameters: dict[str, Any]


class ToolListResponse(BaseModel):
    enabled: bool
    tools: list[ToolResponse]


class ToolPermissionUpdate(BaseModel):
    permission: ToolPermissionMode


class ToolAuditResponse(BaseModel):
    id: str
    conversation_id: str | None
    tool_name: str
    permission_mode: str
    status: str
    arguments: dict[str, Any]
    result_preview: str | None
    error: str | None
    approval_id: str | None
    created_at: datetime
    completed_at: datetime | None


class ToolAuditListResponse(BaseModel):
    entries: list[ToolAuditResponse]


class ToolApprovalDecisionRequest(BaseModel):
    decision: Literal["allow_once", "allow_always", "deny_once", "deny_always"]


class ToolApprovalDecisionResponse(BaseModel):
    approval_id: str
    resolved: bool
    decision: str
    tool_name: str


class PendingToolApprovalResponse(BaseModel):
    approval_id: str
    conversation_id: str | None
    tool_name: str
    label: str
    description: str
    risk: ToolRisk
    arguments: dict[str, Any]
    created_at: datetime


class PendingToolApprovalsResponse(BaseModel):
    approvals: list[PendingToolApprovalResponse]


# -----------------------------
# Phase 6 computer/workspaces
# -----------------------------


class ComputerCommandPresetResponse(BaseModel):
    id: str
    workspace_id: str
    label: str
    executable: str
    arguments: list[str]
    relative_cwd: str
    timeout_seconds: int
    is_active: bool
    created_at: datetime
    updated_at: datetime


class ComputerCommandPresetCreate(BaseModel):
    label: str = Field(min_length=1, max_length=120)
    executable: str = Field(min_length=1, max_length=800)
    arguments: list[str] = Field(default_factory=list, max_length=40)
    relative_cwd: str = Field(default=".", min_length=1, max_length=800)
    timeout_seconds: int = Field(default=120, ge=1, le=900)


class ComputerCommandPresetUpdate(BaseModel):
    label: str | None = Field(default=None, min_length=1, max_length=120)
    executable: str | None = Field(default=None, min_length=1, max_length=800)
    arguments: list[str] | None = Field(default=None, max_length=40)
    relative_cwd: str | None = Field(default=None, min_length=1, max_length=800)
    timeout_seconds: int | None = Field(default=None, ge=1, le=900)
    is_active: bool | None = None


class ComputerWorkspaceResponse(BaseModel):
    id: str
    label: str
    root_path: str
    read_enabled: bool
    write_enabled: bool
    is_active: bool
    created_at: datetime
    updated_at: datetime
    commands: list[ComputerCommandPresetResponse]


class ComputerWorkspaceListResponse(BaseModel):
    enabled: bool
    workspaces: list[ComputerWorkspaceResponse]


class ComputerWorkspaceCreate(BaseModel):
    label: str = Field(min_length=1, max_length=120)
    root_path: str = Field(min_length=1, max_length=1200)
    read_enabled: bool = True
    write_enabled: bool = False


class ComputerWorkspaceUpdate(BaseModel):
    label: str | None = Field(default=None, min_length=1, max_length=120)
    root_path: str | None = Field(default=None, min_length=1, max_length=1200)
    read_enabled: bool | None = None
    write_enabled: bool | None = None
    is_active: bool | None = None


class ComputerStatusResponse(BaseModel):
    enabled: bool
    workspace_count: int
    active_workspace_count: int
    command_preset_count: int
    sensitive_files_allowed: bool
