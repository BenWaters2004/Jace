from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def new_id() -> str:
    return str(uuid4())


class Base(DeclarativeBase):
    pass


class Conversation(Base):
    __tablename__ = "conversations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    title: Mapped[str] = mapped_column(String(200), nullable=False, default="New conversation")
    model: Mapped[str] = mapped_column(String(200), nullable=False)
    system_prompt: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)

    messages: Mapped[list["Message"]] = relationship(
        back_populates="conversation",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="Message.created_at",
    )
    attachments: Mapped[list["Attachment"]] = relationship(
        back_populates="conversation",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="Attachment.created_at",
    )


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    conversation_id: Mapped[str] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="complete")
    model: Mapped[str | None] = mapped_column(String(200), nullable=True)
    time_to_first_token_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    total_duration_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    load_duration_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    prompt_eval_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    prompt_eval_cached_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    prompt_eval_duration_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    eval_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    eval_duration_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    tokens_per_second: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)

    conversation: Mapped["Conversation"] = relationship(back_populates="messages")
    attachments: Mapped[list["Attachment"]] = relationship(
        back_populates="message",
        passive_deletes=True,
        order_by="Attachment.created_at",
    )


class Attachment(Base):
    """User-provided or tool-created multimodal material stored locally."""

    __tablename__ = "attachments"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    conversation_id: Mapped[str] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    message_id: Mapped[str | None] = mapped_column(
        ForeignKey("messages.id", ondelete="SET NULL"), nullable=True, index=True
    )
    original_name: Mapped[str] = mapped_column(String(500), nullable=False)
    stored_name: Mapped[str] = mapped_column(String(500), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(160), nullable=False)
    media_kind: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    source_type: Mapped[str] = mapped_column(String(40), nullable=False, default="upload")
    source_path: Mapped[str | None] = mapped_column(String(1400), nullable=True)
    extracted_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)

    conversation: Mapped["Conversation"] = relationship(back_populates="attachments")
    message: Mapped["Message | None"] = relationship(back_populates="attachments")


class Memory(Base):
    __tablename__ = "memories"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    memory_type: Mapped[str] = mapped_column(String(30), nullable=False, default="fact", index=True)
    subject: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    importance: Mapped[float] = mapped_column(Float, nullable=False, default=0.5)
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    source_type: Mapped[str] = mapped_column(String(30), nullable=False, default="manual")
    source_conversation_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    source_message_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    embedding_model: Mapped[str] = mapped_column(String(200), nullable=False)
    embedding_json: Mapped[str] = mapped_column(Text, nullable=False)
    is_pinned: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    last_accessed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    access_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class AssistantSettings(Base):
    """Single-row persistent configuration for the local Jace assistant."""

    __tablename__ = "assistant_settings"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default="default")
    assistant_name: Mapped[str] = mapped_column(String(80), nullable=False, default="Jace")
    user_name: Mapped[str] = mapped_column(String(80), nullable=False, default="You")
    system_prompt: Mapped[str] = mapped_column(Text, nullable=False, default="")
    default_model: Mapped[str] = mapped_column(String(200), nullable=False)
    reasoning_mode: Mapped[str] = mapped_column(String(20), nullable=False, default="fast")
    response_style: Mapped[str] = mapped_column(String(20), nullable=False, default="balanced")
    temperature: Mapped[float] = mapped_column(Float, nullable=False, default=0.4)
    memory_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    memory_auto_extract: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    memory_top_k: Mapped[int] = mapped_column(Integer, nullable=False, default=6)
    memory_min_similarity: Mapped[float] = mapped_column(Float, nullable=False, default=0.50)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)


class VoiceSettings(Base):
    """Single-row local voice configuration for Phase 10B."""

    __tablename__ = "voice_settings"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default="default")
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    auto_speak: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    verbal_approvals: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    microphone_mode: Mapped[str] = mapped_column(String(30), nullable=False, default="push_to_talk")
    tts_voice: Mapped[str] = mapped_column(String(120), nullable=False, default="bm_lewis")
    tts_speed: Mapped[float] = mapped_column(Float, nullable=False, default=1.06)
    tts_language: Mapped[str] = mapped_column(String(30), nullable=False, default="en-gb")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)


class ToolPermission(Base):
    """Persistent user policy for a registered tool."""

    __tablename__ = "tool_permissions"

    tool_name: Mapped[str] = mapped_column(String(120), primary_key=True)
    permission: Mapped[str] = mapped_column(String(20), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)


class ToolAuditLog(Base):
    """Append-only record of tool requests and outcomes."""

    __tablename__ = "tool_audit_log"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    conversation_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    tool_name: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    permission_mode: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    arguments_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    result_preview: Mapped[str | None] = mapped_column(Text, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    approval_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ComputerWorkspace(Base):
    """User-approved local directory boundary for Phase 6 computer tools."""

    __tablename__ = "computer_workspaces"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    label: Mapped[str] = mapped_column(String(120), nullable=False)
    root_path: Mapped[str] = mapped_column(String(1200), nullable=False, unique=True)
    read_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    write_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)

    commands: Mapped[list["ComputerCommandPreset"]] = relationship(
        back_populates="workspace",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="ComputerCommandPreset.label",
    )


class ComputerCommandPreset(Base):
    """Exact, user-created command that Jace may request to run in one workspace."""

    __tablename__ = "computer_command_presets"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    workspace_id: Mapped[str] = mapped_column(
        ForeignKey("computer_workspaces.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    label: Mapped[str] = mapped_column(String(120), nullable=False)
    executable: Mapped[str] = mapped_column(String(800), nullable=False)
    arguments_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    relative_cwd: Mapped[str] = mapped_column(String(800), nullable=False, default=".")
    timeout_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=120)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)

    workspace: Mapped["ComputerWorkspace"] = relationship(back_populates="commands")


class Automation(Base):
    """Persistent scheduled task or condition watcher."""

    __tablename__ = "automations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    instruction: Mapped[str] = mapped_column(Text, nullable=False)
    automation_type: Mapped[str] = mapped_column(String(20), nullable=False, default="task", index=True)
    schedule_type: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    schedule_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    timezone: Mapped[str] = mapped_column(String(100), nullable=False, default="Europe/London")
    watcher_condition: Mapped[str | None] = mapped_column(Text, nullable=True)
    watcher_state_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, index=True)
    notify_on_success: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    notify_on_failure: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    notify_on_condition: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    timeout_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=300)
    model: Mapped[str | None] = mapped_column(String(200), nullable=True)
    reasoning_mode: Mapped[str] = mapped_column(String(20), nullable=False, default="fast")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    next_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_status: Mapped[str | None] = mapped_column(String(30), nullable=True)
    last_result: Mapped[str | None] = mapped_column(Text, nullable=True)

    tool_permissions: Mapped[list["AutomationToolPermission"]] = relationship(
        back_populates="automation",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="AutomationToolPermission.tool_name",
    )
    runs: Mapped[list["AutomationRun"]] = relationship(
        back_populates="automation",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="AutomationRun.started_at.desc()",
    )
    notifications: Mapped[list["AutomationNotification"]] = relationship(
        back_populates="automation",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="AutomationNotification.created_at.desc()",
    )


class AutomationToolPermission(Base):
    """Per-automation capability allow-list."""

    __tablename__ = "automation_tool_permissions"
    __table_args__ = (
        UniqueConstraint("automation_id", "tool_name", name="uq_automation_tool_permission"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    automation_id: Mapped[str] = mapped_column(
        ForeignKey("automations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    tool_name: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    allowed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)

    automation: Mapped["Automation"] = relationship(back_populates="tool_permissions")


class AutomationRun(Base):
    """Execution history for scheduled/manual automation runs."""

    __tablename__ = "automation_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    automation_id: Mapped[str] = mapped_column(
        ForeignKey("automations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    trigger_type: Mapped[str] = mapped_column(String(30), nullable=False, default="scheduled")
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="running", index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    result: Mapped[str | None] = mapped_column(Text, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    condition_met: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    tool_names_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    model: Mapped[str | None] = mapped_column(String(200), nullable=True)

    automation: Mapped["Automation"] = relationship(back_populates="runs")
    notifications: Mapped[list["AutomationNotification"]] = relationship(
        back_populates="run",
        passive_deletes=True,
        order_by="AutomationNotification.created_at.desc()",
    )


class AutomationNotification(Base):
    """Queued notification surfaced to the desktop application."""

    __tablename__ = "automation_notifications"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    automation_id: Mapped[str] = mapped_column(
        ForeignKey("automations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    run_id: Mapped[str | None] = mapped_column(
        ForeignKey("automation_runs.id", ondelete="SET NULL"), nullable=True, index=True
    )
    title: Mapped[str] = mapped_column(String(240), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    level: Mapped[str] = mapped_column(String(20), nullable=False, default="info")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now, index=True)
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)

    automation: Mapped["Automation"] = relationship(back_populates="notifications")
    run: Mapped["AutomationRun | None"] = relationship(back_populates="notifications")


class ControlAppPolicy(Base):
    """Persistent per-application observation / interaction boundary for Phase 9."""

    __tablename__ = "control_app_policies"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    label: Mapped[str] = mapped_column(String(140), nullable=False)
    process_pattern: Mapped[str] = mapped_column(String(260), nullable=False)
    title_pattern: Mapped[str] = mapped_column(String(500), nullable=False, default="*")
    observe_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    interact_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    sensitive_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)


class ControlSession(Base):
    """Short-lived, explicitly authorised GUI-control session."""

    __tablename__ = "control_sessions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    conversation_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="active", index=True)
    step_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_steps: Mapped[int] = mapped_column(Integer, nullable=False, default=30)
    store_screenshots: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    sensitive_authorized_once: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    stop_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)


class ControlActionAudit(Base):
    """Append-only Phase 9 action history separate from the generic tool audit."""

    __tablename__ = "control_action_audit"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    session_id: Mapped[str] = mapped_column(
        ForeignKey("control_sessions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    conversation_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    action_type: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    window_handle: Mapped[str | None] = mapped_column(String(40), nullable=True)
    process_name: Mapped[str | None] = mapped_column(String(260), nullable=True)
    window_title: Mapped[str | None] = mapped_column(String(700), nullable=True)
    arguments_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="requested", index=True)
    result_preview: Mapped[str | None] = mapped_column(Text, nullable=True)
    screenshot_attachment_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
