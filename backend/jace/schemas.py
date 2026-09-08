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
    voice_mode: bool = False


class VoiceSettingsResponse(BaseModel):
    enabled: bool
    auto_speak: bool
    verbal_approvals: bool
    microphone_mode: Literal["push_to_talk"]
    tts_voice: str
    tts_speed: float
    tts_language: str
    created_at: datetime
    updated_at: datetime


class VoiceSettingsUpdate(BaseModel):
    enabled: bool | None = None
    auto_speak: bool | None = None
    verbal_approvals: bool | None = None
    microphone_mode: Literal["push_to_talk"] | None = None
    tts_voice: str | None = Field(default=None, min_length=1, max_length=120)
    tts_speed: float | None = Field(default=None, ge=0.70, le=1.45)
    tts_language: str | None = Field(default=None, min_length=2, max_length=30)


class VoiceStatusResponse(BaseModel):
    enabled: bool
    stt_dependency_available: bool
    tts_dependency_available: bool
    tts_model_files_available: bool
    stt_model: str
    tts_model_path: str
    tts_voices_path: str
    voices: list[dict[str, str]]


class VoiceTranscriptionResponse(BaseModel):
    text: str
    language: str | None = None
    language_probability: float | None = None
    duration: float | None = None


class VoiceSynthesisRequest(BaseModel):
    text: str = Field(min_length=1, max_length=900)
    voice: str | None = Field(default=None, min_length=1, max_length=120)
    speed: float | None = Field(default=None, ge=0.70, le=1.45)
    language: str | None = Field(default=None, min_length=2, max_length=30)


class VoiceStateRequest(BaseModel):
    active: bool


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

# -----------------------------
# Phase 8 automation
# -----------------------------

AutomationType = Literal["task", "watcher"]
AutomationScheduleType = Literal["once", "interval", "daily", "weekly", "cron"]
AutomationRunStatus = Literal[
    "running", "success", "failed", "condition_not_met", "missed", "disabled"
]


class AutomationSchedule(BaseModel):
    schedule_type: AutomationScheduleType
    timezone: str = Field(default="Europe/London", min_length=1, max_length=100)
    run_at: datetime | None = None
    interval_minutes: int | None = Field(default=None, ge=1, le=525_600)
    time_of_day: str | None = Field(default=None, pattern=r"^(?:[01]\d|2[0-3]):[0-5]\d$")
    days_of_week: list[int] = Field(default_factory=list, max_length=7)
    cron_expression: str | None = Field(default=None, min_length=5, max_length=200)


class AutomationCreate(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    instruction: str = Field(min_length=1, max_length=20_000)
    automation_type: AutomationType = "task"
    schedule: AutomationSchedule
    watcher_condition: str | None = Field(default=None, max_length=5_000)
    allowed_tools: list[str] = Field(default_factory=list, max_length=40)
    enabled: bool = True
    notify_on_success: bool = True
    notify_on_failure: bool = True
    notify_on_condition: bool = True
    timeout_seconds: int = Field(default=300, ge=30, le=1800)
    model: str | None = Field(default=None, max_length=200)
    reasoning_mode: ReasoningMode = "fast"


class AutomationUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=160)
    instruction: str | None = Field(default=None, min_length=1, max_length=20_000)
    automation_type: AutomationType | None = None
    schedule: AutomationSchedule | None = None
    watcher_condition: str | None = Field(default=None, max_length=5_000)
    allowed_tools: list[str] | None = Field(default=None, max_length=40)
    enabled: bool | None = None
    notify_on_success: bool | None = None
    notify_on_failure: bool | None = None
    notify_on_condition: bool | None = None
    timeout_seconds: int | None = Field(default=None, ge=30, le=1800)
    model: str | None = Field(default=None, max_length=200)
    reasoning_mode: ReasoningMode | None = None


class AutomationToolScopeResponse(BaseModel):
    tool_name: str
    allowed: bool


class AutomationResponse(BaseModel):
    id: str
    name: str
    instruction: str
    automation_type: str
    schedule: AutomationSchedule
    watcher_condition: str | None
    allowed_tools: list[str]
    enabled: bool
    notify_on_success: bool
    notify_on_failure: bool
    notify_on_condition: bool
    timeout_seconds: int
    model: str | None
    reasoning_mode: str
    created_at: datetime
    updated_at: datetime
    next_run_at: datetime | None
    last_run_at: datetime | None
    last_status: str | None
    last_result: str | None


class AutomationListResponse(BaseModel):
    enabled: bool
    automations: list[AutomationResponse]


class AutomationRunResponse(BaseModel):
    id: str
    automation_id: str
    trigger_type: str
    status: str
    started_at: datetime
    completed_at: datetime | None
    result: str | None
    error: str | None
    condition_met: bool | None
    tool_names: list[str]
    model: str | None


class AutomationRunListResponse(BaseModel):
    runs: list[AutomationRunResponse]


class AutomationNotificationResponse(BaseModel):
    id: str
    automation_id: str
    run_id: str | None
    title: str
    body: str
    level: str
    created_at: datetime
    read_at: datetime | None


class AutomationNotificationListResponse(BaseModel):
    notifications: list[AutomationNotificationResponse]


class AutomationStatusResponse(BaseModel):
    enabled: bool
    scheduler_running: bool
    automation_count: int
    enabled_count: int
    watcher_count: int
    unread_notifications: int
    timezone: str


class AutomationDraftRequest(BaseModel):
    instruction: str = Field(min_length=1, max_length=10_000)
    timezone: str = Field(default="Europe/London", min_length=1, max_length=100)


class AutomationDraftResponse(BaseModel):
    name: str
    instruction: str
    automation_type: AutomationType
    schedule: AutomationSchedule
    watcher_condition: str | None = None
    suggested_tools: list[str] = Field(default_factory=list)
    notify_on_success: bool = True
    notify_on_failure: bool = True
    notify_on_condition: bool = True
    reasoning: str = ""


class AutomationWatcherEvaluation(BaseModel):
    condition_met: bool
    summary: str = Field(min_length=1, max_length=3_000)
    state: str = Field(default="", max_length=8_000)


# Phase 9 interactive desktop control
class ControlWindowResponse(BaseModel):
    handle: int
    title: str
    process_name: str
    process_id: int
    left: int
    top: int
    right: int
    bottom: int
    width: int
    height: int
    is_active: bool
    blocked: bool
    sensitive: bool
    policy_id: str | None = None
    policy_label: str | None = None
    observe_allowed: bool
    interact_allowed: bool
    sensitive_allowed: bool


class ControlWindowListResponse(BaseModel):
    windows: list[ControlWindowResponse]


class ControlAppPolicyCreate(BaseModel):
    label: str = Field(min_length=1, max_length=140)
    process_pattern: str = Field(min_length=1, max_length=260)
    title_pattern: str = Field(default="*", min_length=1, max_length=500)
    observe_enabled: bool = True
    interact_enabled: bool = False
    sensitive_enabled: bool = False


class ControlAppPolicyUpdate(BaseModel):
    label: str | None = Field(default=None, min_length=1, max_length=140)
    process_pattern: str | None = Field(default=None, min_length=1, max_length=260)
    title_pattern: str | None = Field(default=None, min_length=1, max_length=500)
    observe_enabled: bool | None = None
    interact_enabled: bool | None = None
    sensitive_enabled: bool | None = None
    is_active: bool | None = None


class ControlAppPolicyResponse(BaseModel):
    id: str
    label: str
    process_pattern: str
    title_pattern: str
    observe_enabled: bool
    interact_enabled: bool
    sensitive_enabled: bool
    is_active: bool
    created_at: datetime
    updated_at: datetime


class ControlAppPolicyListResponse(BaseModel):
    policies: list[ControlAppPolicyResponse]


class ControlSessionCreate(BaseModel):
    conversation_id: str | None = Field(default=None, min_length=36, max_length=36)
    max_steps: int = Field(default=30, ge=1, le=80)
    store_screenshots: bool = False


class ControlSessionResponse(BaseModel):
    id: str
    conversation_id: str | None
    status: str
    step_count: int
    max_steps: int
    remaining_steps: int
    store_screenshots: bool
    sensitive_authorized_once: bool
    started_at: datetime
    updated_at: datetime
    ended_at: datetime | None
    stop_reason: str | None


class ControlSessionListResponse(BaseModel):
    sessions: list[ControlSessionResponse]


class ControlActionResponse(BaseModel):
    id: str
    session_id: str
    conversation_id: str | None
    action_type: str
    window_handle: str | None
    process_name: str | None
    window_title: str | None
    arguments: dict[str, Any]
    status: str
    result_preview: str | None
    screenshot_attachment_id: str | None
    created_at: datetime
    completed_at: datetime | None


class ControlActionListResponse(BaseModel):
    actions: list[ControlActionResponse]


class ControlStatusResponse(BaseModel):
    enabled: bool
    platform_supported: bool
    active_session: ControlSessionResponse | None
    policy_count: int
    active_policy_count: int
    visible_window_count: int
    physical_failsafe: str
