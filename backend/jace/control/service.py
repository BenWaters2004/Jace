from __future__ import annotations

import asyncio
import base64
import io
import json
from datetime import datetime, timedelta, timezone
from fnmatch import fnmatch
from typing import Any

from PIL import Image
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from jace.attachments.service import create_attachment_from_bytes
from jace.config import settings
from jace.control.runtime import activate_emergency_stop, clear_emergency_stop, emergency_stop_active
from jace.control.security import (
    intent_is_sensitive,
    key_sequence_is_sensitive,
    process_is_absolutely_blocked,
    process_pattern_is_too_broad,
    text_contains_high_risk_secret,
    window_is_sensitive,
)
from jace.control.windows import WindowInfo, active_window, get_window, list_windows, matches_pattern, window_at_point
from jace.db.models import ControlActionAudit, ControlAppPolicy, ControlSession


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class ControlError(ValueError):
    pass


class ControlSensitiveAuthorizationRequired(ControlError):
    pass


async def list_policies(session: AsyncSession, *, active_only: bool = False) -> list[ControlAppPolicy]:
    statement = select(ControlAppPolicy)
    if active_only:
        statement = statement.where(ControlAppPolicy.is_active.is_(True))
    statement = statement.order_by(ControlAppPolicy.is_active.desc(), ControlAppPolicy.label.asc())
    result = await session.execute(statement)
    return list(result.scalars().all())


async def get_policy(session: AsyncSession, policy_id: str) -> ControlAppPolicy | None:
    return await session.get(ControlAppPolicy, policy_id)


async def create_policy(
    session: AsyncSession,
    *,
    label: str,
    process_pattern: str,
    title_pattern: str,
    observe_enabled: bool,
    interact_enabled: bool,
    sensitive_enabled: bool,
) -> ControlAppPolicy:
    label = label.strip()
    process_pattern = process_pattern.strip()
    title_pattern = title_pattern.strip() or "*"
    if not label or not process_pattern:
        raise ValueError("Policy label and process pattern are required.")
    if process_pattern_is_too_broad(process_pattern):
        raise ValueError("Process patterns must identify a specific application; machine-wide wildcards such as *.exe are not allowed.")
    if sensitive_enabled and not interact_enabled:
        raise ValueError("Sensitive interaction can only be enabled when normal interaction is enabled.")
    row = ControlAppPolicy(
        label=label,
        process_pattern=process_pattern,
        title_pattern=title_pattern,
        observe_enabled=observe_enabled,
        interact_enabled=interact_enabled,
        sensitive_enabled=sensitive_enabled,
    )
    session.add(row)
    await session.commit()
    await session.refresh(row)
    return row


async def update_policy(
    session: AsyncSession,
    row: ControlAppPolicy,
    *,
    label: str | None = None,
    process_pattern: str | None = None,
    title_pattern: str | None = None,
    observe_enabled: bool | None = None,
    interact_enabled: bool | None = None,
    sensitive_enabled: bool | None = None,
    is_active: bool | None = None,
) -> ControlAppPolicy:
    if label is not None:
        row.label = label.strip()
    if process_pattern is not None:
        row.process_pattern = process_pattern.strip()
    if title_pattern is not None:
        row.title_pattern = title_pattern.strip() or "*"
    if not row.label or not row.process_pattern:
        raise ValueError("Policy label and process pattern are required.")
    if process_pattern_is_too_broad(row.process_pattern):
        raise ValueError("Process patterns must identify a specific application; machine-wide wildcards such as *.exe are not allowed.")
    if observe_enabled is not None:
        row.observe_enabled = observe_enabled
    if interact_enabled is not None:
        row.interact_enabled = interact_enabled
    if sensitive_enabled is not None:
        row.sensitive_enabled = sensitive_enabled
    if is_active is not None:
        row.is_active = is_active
    if row.sensitive_enabled and not row.interact_enabled:
        raise ValueError("Sensitive interaction can only be enabled when normal interaction is enabled.")
    row.updated_at = utc_now()
    await session.commit()
    await session.refresh(row)
    return row


async def delete_policy(session: AsyncSession, row: ControlAppPolicy) -> None:
    await session.delete(row)
    await session.commit()


async def matching_policy(session: AsyncSession, window: WindowInfo | None) -> ControlAppPolicy | None:
    if window is None:
        return None
    policies = await list_policies(session, active_only=True)
    for policy in policies:
        if process_pattern_is_too_broad(policy.process_pattern):
            continue
        if not matches_pattern(window.process_name, policy.process_pattern):
            continue
        if not matches_pattern(window.title, policy.title_pattern or "*"):
            continue
        return policy
    return None


async def window_policy_summary(session: AsyncSession, window: WindowInfo) -> dict[str, Any]:
    policy = await matching_policy(session, window)
    blocked = process_is_absolutely_blocked(window.process_name)
    return {
        **window.to_dict(),
        "blocked": blocked,
        "sensitive": window_is_sensitive(window),
        "policy_id": policy.id if policy else None,
        "policy_label": policy.label if policy else None,
        "observe_allowed": bool(policy and policy.observe_enabled and not blocked),
        "interact_allowed": bool(policy and policy.interact_enabled and not blocked),
        "sensitive_allowed": bool(policy and policy.sensitive_enabled and not blocked),
    }


async def list_windows_with_policy(session: AsyncSession) -> list[dict[str, Any]]:
    return [await window_policy_summary(session, item) for item in await asyncio.to_thread(list_windows)]


async def start_session(
    session: AsyncSession,
    *,
    conversation_id: str | None,
    max_steps: int | None = None,
    store_screenshots: bool | None = None,
) -> ControlSession:
    if not settings.interactive_control_enabled:
        raise ControlError("Interactive computer control is disabled.")

    # A new explicit session is the only thing that clears a prior process-local
    # emergency kill switch.
    clear_emergency_stop()

    # Desktop input is a machine-global resource. Keep exactly one live control
    # session regardless of which conversation or management screen started it.
    result = await session.execute(
        select(ControlSession).where(ControlSession.status == "active")
    )
    for old in result.scalars().all():
        old.status = "stopped"
        old.ended_at = utc_now()
        old.updated_at = utc_now()
        old.sensitive_authorized_once = False
        old.stop_reason = "Superseded by a newer global control session."

    requested_steps = max_steps or settings.interactive_default_max_steps
    row = ControlSession(
        conversation_id=conversation_id,
        max_steps=max(1, min(int(requested_steps), settings.interactive_max_steps)),
        store_screenshots=(
            settings.interactive_store_screenshots_default
            if store_screenshots is None
            else bool(store_screenshots)
        ),
    )
    session.add(row)
    await session.commit()
    await session.refresh(row)
    return row


async def get_session(session: AsyncSession, session_id: str) -> ControlSession | None:
    return await session.get(ControlSession, session_id)


async def list_sessions(session: AsyncSession, *, limit: int = 50) -> list[ControlSession]:
    result = await session.execute(
        select(ControlSession)
        .order_by(ControlSession.started_at.desc())
        .limit(max(1, min(limit, 200)))
    )
    return list(result.scalars().all())


async def active_session(session: AsyncSession) -> ControlSession | None:
    result = await session.execute(
        select(ControlSession)
        .where(ControlSession.status == "active")
        .order_by(ControlSession.started_at.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def assert_session_active(session: AsyncSession, session_id: str) -> ControlSession:
    row = await get_session(session, session_id)
    if row is None:
        raise ControlError("Unknown control session.")
    if row.status != "active":
        raise ControlError(f"Control session is {row.status}, not active.")
    if utc_now() - _aware(row.started_at) > timedelta(seconds=settings.interactive_session_timeout_seconds):
        row.status = "expired"
        row.ended_at = utc_now()
        row.stop_reason = "Interactive session timeout reached."
        await session.commit()
        raise ControlError("The control session expired. Start a new session.")
    if row.step_count >= row.max_steps:
        row.status = "step_limit"
        row.ended_at = utc_now()
        row.stop_reason = "Maximum interactive step count reached."
        await session.commit()
        raise ControlError("The control session reached its maximum step count.")
    return row


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


async def increment_step(session: AsyncSession, row: ControlSession) -> None:
    row.step_count += 1
    row.updated_at = utc_now()
    if row.step_count >= row.max_steps:
        # Keep this step valid; the following step will be rejected.
        row.stop_reason = "Maximum interactive step count will stop the next action."
    await session.commit()


async def stop_session(session: AsyncSession, session_id: str, *, reason: str = "Stopped by user.") -> ControlSession:
    row = await get_session(session, session_id)
    if row is None:
        raise ControlError("Unknown control session.")
    if row.status == "active":
        row.status = "stopped"
        row.ended_at = utc_now()
        row.updated_at = utc_now()
        row.stop_reason = reason[:500]
        row.sensitive_authorized_once = False
        await session.commit()
        await session.refresh(row)
    return row


async def emergency_stop_all(session: AsyncSession) -> int:
    # Signal worker-thread input primitives first, then persist the stopped state.
    activate_emergency_stop()
    result = await session.execute(select(ControlSession).where(ControlSession.status == "active"))
    rows = list(result.scalars().all())
    now = utc_now()
    for row in rows:
        row.status = "emergency_stopped"
        row.ended_at = now
        row.updated_at = now
        row.stop_reason = "Emergency stop activated."
        row.sensitive_authorized_once = False
    await session.commit()
    return len(rows)


async def authorize_sensitive_once(session: AsyncSession, session_id: str) -> ControlSession:
    row = await assert_session_active(session, session_id)
    row.sensitive_authorized_once = True
    row.updated_at = utc_now()
    await session.commit()
    await session.refresh(row)
    return row


async def require_window_observation(
    session: AsyncSession,
    control_session: ControlSession,
    window: WindowInfo | None,
) -> ControlAppPolicy:
    if window is None:
        raise ControlError("Jace could not identify the target application window.")
    if process_is_absolutely_blocked(window.process_name):
        raise ControlError(
            f"Observation of {window.process_name} is blocked because it may expose credentials or secure-desktop data."
        )

    policy = await matching_policy(session, window)
    if policy is None or not policy.observe_enabled:
        raise ControlError(
            f'Observation of "{window.process_name} — {window.title}" is not allowed. '
            "Add an observation policy from the Control screen first."
        )

    if window_is_sensitive(window):
        if not policy.sensitive_enabled:
            raise ControlError(
                "This looks like a sensitive window, but the matching app policy does not permit sensitive interaction/observation."
            )
        if not control_session.sensitive_authorized_once:
            raise ControlSensitiveAuthorizationRequired(
                "Sensitive observation blocked. Use the Control screen to authorize the next sensitive action, then retry."
            )
        control_session.sensitive_authorized_once = False
        control_session.updated_at = utc_now()
        await session.commit()

    return policy


async def require_window_interaction(
    session: AsyncSession,
    control_session: ControlSession,
    window: WindowInfo | None,
    *,
    intent: str,
    typed_text: str | None = None,
    keys: list[str] | None = None,
) -> ControlAppPolicy:
    if window is None:
        raise ControlError("Jace could not identify the target application window.")
    if process_is_absolutely_blocked(window.process_name):
        raise ControlError(
            f"Interaction with {window.process_name} is blocked because it may expose credentials or secure-desktop data."
        )

    policy = await matching_policy(session, window)
    if policy is None or not policy.interact_enabled:
        raise ControlError(
            f'Interaction with "{window.process_name} — {window.title}" is not allowed. '
            "Add an interactive app policy from the Control screen first."
        )

    if typed_text and text_contains_high_risk_secret(typed_text):
        raise ControlError(
            "Jace will not type detected passwords, API keys, private keys, payment-card numbers, or similar secrets. Enter that value manually."
        )

    sensitive = window_is_sensitive(window) or intent_is_sensitive(intent)
    if keys and key_sequence_is_sensitive(keys):
        sensitive = True

    if sensitive:
        if not policy.sensitive_enabled:
            raise ControlError(
                "This looks like a sensitive screen or action, but the matching app policy does not permit sensitive interaction."
            )
        if not control_session.sensitive_authorized_once:
            raise ControlSensitiveAuthorizationRequired(
                "Sensitive action blocked. Use the Control screen to authorize the next sensitive action, then retry."
            )
        # One-shot authorization is consumed regardless of whether the caller
        # performs click/type/key after this check.
        control_session.sensitive_authorized_once = False
        control_session.updated_at = utc_now()
        await session.commit()

    return policy


async def create_action_audit(
    session: AsyncSession,
    *,
    control_session: ControlSession,
    action_type: str,
    window: WindowInfo | None,
    arguments: dict[str, Any],
) -> ControlActionAudit:
    row = ControlActionAudit(
        session_id=control_session.id,
        conversation_id=control_session.conversation_id,
        action_type=action_type,
        window_handle=str(window.handle) if window else None,
        process_name=window.process_name if window else None,
        window_title=window.title if window else None,
        arguments_json=json.dumps(arguments, ensure_ascii=False, separators=(",", ":")),
        status="requested",
    )
    session.add(row)
    await session.commit()
    await session.refresh(row)
    return row


async def complete_action_audit(
    session: AsyncSession,
    row: ControlActionAudit,
    *,
    status: str,
    result_preview: str | None = None,
    screenshot_attachment_id: str | None = None,
) -> None:
    row.status = status
    row.result_preview = (result_preview or "")[:1500] or None
    row.screenshot_attachment_id = screenshot_attachment_id
    row.completed_at = utc_now()
    await session.commit()


async def list_action_audit(
    session: AsyncSession,
    *,
    session_id: str | None = None,
    limit: int = 100,
) -> list[ControlActionAudit]:
    statement = select(ControlActionAudit)
    if session_id:
        statement = statement.where(ControlActionAudit.session_id == session_id)
    statement = statement.order_by(ControlActionAudit.created_at.desc()).limit(max(1, min(limit, 500)))
    result = await session.execute(statement)
    return list(result.scalars().all())


def assert_physical_failsafe() -> None:
    """Block input after the UI emergency stop or physical top-left fail-safe."""
    if emergency_stop_active():
        raise ControlError("Emergency stop is active. Start a new control session before continuing.")
    try:
        import win32api
        x, y = win32api.GetCursorPos()
        if int(x) <= 1 and int(y) <= 1:
            raise ControlError(
                "Physical fail-safe is active because the mouse is in the top-left corner. Move it away before continuing."
            )
    except ImportError:
        return


async def capture_desktop_png(*, window: WindowInfo | None = None) -> bytes:
    try:
        import mss
        import mss.tools
    except ImportError as exc:
        raise ControlError("Screen capture dependency is not installed.") from exc

    def capture() -> bytes:
        with mss.mss() as sct:
            if window is None:
                monitor = sct.monitors[0]
            else:
                monitor = {
                    "left": window.left,
                    "top": window.top,
                    "width": window.width,
                    "height": window.height,
                }
            shot = sct.grab(monitor)
            raw = mss.tools.to_png(shot.rgb, shot.size)

        # Keep model images bounded even on 4K/multi-monitor desktops.
        with Image.open(io.BytesIO(raw)) as image:
            image = image.convert("RGB")
            if max(image.size) > settings.interactive_capture_max_edge:
                image.thumbnail(
                    (settings.interactive_capture_max_edge, settings.interactive_capture_max_edge),
                    Image.Resampling.LANCZOS,
                )
            output = io.BytesIO()
            image.save(output, format="PNG", optimize=True)
            return output.getvalue()

    return await asyncio.to_thread(capture)


async def screenshot_result(
    session: AsyncSession,
    control_session: ControlSession,
    *,
    window: WindowInfo | None = None,
    name: str = "control-screen.png",
) -> tuple[str, str | None]:
    png = await capture_desktop_png(window=window)
    encoded = base64.b64encode(png).decode("ascii")
    attachment_id: str | None = None
    if control_session.store_screenshots and control_session.conversation_id:
        attachment = await create_attachment_from_bytes(
            session,
            conversation_id=control_session.conversation_id,
            original_name=name,
            data=png,
            mime_type="image/png",
            source_type="control_session",
            source_path=f"control:{control_session.id}",
        )
        attachment_id = attachment.id
    return encoded, attachment_id
