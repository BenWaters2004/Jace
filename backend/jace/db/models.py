from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text
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
