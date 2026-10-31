"""C5B.1: minimal, metadata-only, durable model provider invocation receipts.

One row is written per actual provider adapter attempt (including retries), not
per final answer. No prompts, responses, tool arguments, embeddings or exception
messages are stored. DB errors do not mask the inference result.

A receipt represents Jace's observed call to an adapter, not external billing
confirmation. Token figures are only used when a terminal stream supplied them.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import math
import time
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from datetime import datetime, timezone
from typing import Any, TypeVar

from sqlalchemy import DateTime, Float, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from jace.config import settings
from jace.db.models import Base


log = logging.getLogger("uvicorn.error")
T = TypeVar("T")


class ModelInvocationReceipt(Base):
    __tablename__ = "model_invocation_receipts"
    __table_args__ = (
        Index("ix_model_receipts_created", "created_at"),
        Index("ix_model_receipts_provider_created", "provider_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    provider_id: Mapped[str] = mapped_column(String(80), nullable=False)
    model: Mapped[str] = mapped_column(String(300), nullable=False)
    capability: Mapped[str] = mapped_column(String(80), nullable=False)
    operation: Mapped[str] = mapped_column(String(40), nullable=False)
    requested_route: Mapped[str] = mapped_column(String(400), nullable=False)
    effective_route: Mapped[str] = mapped_column(String(400), nullable=False)
    route_changed: Mapped[bool] = mapped_column(nullable=False, default=False)
    privacy_classification: Mapped[str | None] = mapped_column(String(80))
    privacy_mode: Mapped[str | None] = mapped_column(String(80))
    privacy_action: Mapped[str | None] = mapped_column(String(80))
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    error_category: Mapped[str | None] = mapped_column(String(70))
    latency_ms: Mapped[float] = mapped_column(Float, nullable=False)
    input_tokens: Mapped[int | None] = mapped_column(Integer)
    output_tokens: Mapped[int | None] = mapped_column(Integer)
    usage_source: Mapped[str] = mapped_column(String(30), nullable=False)
    estimated_cost_usd: Mapped[float | None] = mapped_column(Float)
    pricing_sha256: Mapped[str | None] = mapped_column(String(64))
    provider_request_id: Mapped[str | None] = mapped_column(String(180))


def _short(value: Any, limit: int) -> str | None:
    if value is None:
        return None
    s = str(value).strip()
    return s[:limit] or None


def _token(value: Any) -> int | None:
    # bool, floats and negative/implausible token figures are not counts.
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value if 0 <= value <= 2_000_000_000 else None


def _priced_usage(route_id: str, inp: int | None, out: int | None):
    if inp is None or out is None:
        return None, None
    raw = str(getattr(settings, "cloud_pricing_json", "{}"))
    try:
        schedule = json.loads(raw)
        rate = schedule.get(route_id) if isinstance(schedule, dict) else None
        if not isinstance(rate, dict):
            return None, None
        first = float(rate["input_per_million"])
        second = float(rate["output_per_million"])
        if not all(math.isfinite(v) and v >= 0 for v in (first, second)):
            return None, None
        # A zero rate is an explicitly configured price, not a guessed price.
        cost = (inp * first + out * second) / 1_000_000
        # Hash version identifies a pricing schedule, not a provider invoice.
        digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
        return round(cost, 10), digest
    except (ValueError, TypeError, KeyError, OverflowError):
        return None, None


async def persist_receipt(receipt: ModelInvocationReceipt) -> bool:
    """Best-effort DB insert; never logs raw DB exception or prompt contents."""
    try:
        from jace.database import SessionLocal  # import lazily to avoid DB cycles
        async with SessionLocal() as session:
            session.add(receipt)
            await session.commit()
        return True
    except Exception as exc:
        log.warning("C5B receipt persistence unavailable (%s)", type(exc).__name__)
        return False


class Invocation:
    def __init__(self, *, route: Any, capability: str, operation: str,
                 privacy: Any, requested_route: str | None = None) -> None:
        self.route = route
        self.capability = capability
        self.operation = operation
        self.privacy = privacy
        self.requested_route = requested_route or route.route_id
        self.started_clock = time.monotonic()
        self.created_at = datetime.now(timezone.utc)
        self.terminal: dict[str, Any] | None = None
        self.completed = False

    async def finish(self, *, status: str, error_category: str | None = None) -> None:
        if self.completed:
            return
        self.completed = True
        terminal = self.terminal or {}
        input_tokens = _token(terminal.get("prompt_eval_count"))
        output_tokens = _token(terminal.get("eval_count"))
        if input_tokens is None or output_tokens is None:
            input_tokens = output_tokens = None
        if input_tokens == 0 and output_tokens == 0:
            # The adapters default to 0 when an API did not report usage.
            input_tokens = output_tokens = None
        cost, pricing_sha = _priced_usage(self.route.route_id, input_tokens, output_tokens)
        # Do not trust arbitrary model output as a provider-issued request ID.
        receipt = ModelInvocationReceipt(
            id=str(uuid.uuid4()), created_at=self.created_at,
            finished_at=datetime.now(timezone.utc),
            provider_id=_short(self.route.provider, 80) or "unknown",
            model=_short(self.route.model, 300) or "unknown",
            capability=_short(self.capability, 80) or "unknown",
            operation=_short(self.operation, 40) or "unknown",
            requested_route=_short(self.requested_route, 400) or "unknown",
            effective_route=_short(self.route.route_id, 400) or "unknown",
            route_changed=(self.requested_route != self.route.route_id),
            privacy_classification=_short(getattr(self.privacy, "classification", None), 80),
            privacy_mode=_short(getattr(self.privacy, "mode", None), 80),
            privacy_action=_short(getattr(self.privacy, "action", None), 80),
            status=status, error_category=_short(error_category, 70),
            latency_ms=round((time.monotonic() - self.started_clock) * 1000, 2),
            input_tokens=input_tokens, output_tokens=output_tokens,
            usage_source="provider_terminal" if input_tokens is not None else "unavailable",
            estimated_cost_usd=cost, pricing_sha256=pricing_sha,
            provider_request_id=None,
        )
        await persist_receipt(receipt)


async def traced_stream(
    *, route: Any, capability: str, operation: str, privacy: Any,
    requested_route: str | None, stream: AsyncIterator[dict[str, Any]],
) -> AsyncIterator[dict[str, Any]]:
    invocation = Invocation(route=route, capability=capability, operation=operation,
                            privacy=privacy, requested_route=requested_route)
    status = "incomplete"
    reason: str | None = None
    try:
        async for chunk in stream:
            if isinstance(chunk, dict) and chunk.get("done") is True:
                # Only a *provider terminal event* supplies billable token usage.
                invocation.terminal = chunk
                status = "success"
            yield chunk
    except (asyncio.CancelledError, GeneratorExit):
        status = "cancelled" if status != "success" else status
        raise
    except Exception as exc:
        status = "error"
        reason = _short(type(exc).__name__, 70)
        raise
    finally:
        await invocation.finish(status=status, error_category=reason)


async def traced_call(
    *, route: Any, capability: str, operation: str, privacy: Any,
    requested_route: str | None, invoke: Callable[[], Awaitable[T]],
) -> T:
    invocation = Invocation(route=route, capability=capability, operation=operation,
                            privacy=privacy, requested_route=requested_route)
    status = "error"
    reason: str | None = None
    try:
        value = await invoke()
        status = "success"
        return value
    except asyncio.CancelledError:
        status = "cancelled"
        raise
    except Exception as exc:
        reason = _short(type(exc).__name__, 70)
        raise
    finally:
        await invocation.finish(status=status, error_category=reason)
