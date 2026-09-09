from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from jace.ai.prompts import DEFAULT_SYSTEM_PROMPT, PERSONALITY_ANCHOR
from jace.config import settings as env_settings
from jace.db.models import AssistantSettings


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


async def get_or_create_assistant_settings(session: AsyncSession) -> AssistantSettings:
    profile = await session.get(AssistantSettings, "default")
    if profile is not None:
        return profile

    profile = AssistantSettings(
        id="default",
        assistant_name="Jace",
        user_name="You",
        system_prompt=DEFAULT_SYSTEM_PROMPT,
        default_model=env_settings.default_model,
        reasoning_mode="fast",
        response_style="balanced",
        temperature=0.4,
        memory_enabled=env_settings.memory_enabled,
        memory_auto_extract=env_settings.memory_auto_extract,
        memory_top_k=env_settings.memory_top_k,
        memory_min_similarity=env_settings.memory_min_similarity,
    )
    session.add(profile)
    await session.commit()
    await session.refresh(profile)
    return profile


async def update_assistant_settings(
    session: AsyncSession,
    profile: AssistantSettings,
    **changes,
) -> AssistantSettings:
    for field, value in changes.items():
        if value is not None and hasattr(profile, field):
            setattr(profile, field, value)

    profile.updated_at = utc_now()
    await session.commit()
    await session.refresh(profile)
    return profile


async def reset_assistant_settings(session: AsyncSession) -> AssistantSettings:
    profile = await get_or_create_assistant_settings(session)
    profile.assistant_name = "Jace"
    profile.user_name = "You"
    profile.system_prompt = DEFAULT_SYSTEM_PROMPT
    profile.default_model = env_settings.default_model
    profile.reasoning_mode = "fast"
    profile.response_style = "balanced"
    profile.temperature = 0.4
    profile.memory_enabled = env_settings.memory_enabled
    profile.memory_auto_extract = env_settings.memory_auto_extract
    profile.memory_top_k = env_settings.memory_top_k
    profile.memory_min_similarity = env_settings.memory_min_similarity
    profile.updated_at = utc_now()
    await session.commit()
    await session.refresh(profile)
    return profile


def style_instruction(response_style: str) -> str:
    return {
        "concise": "Keep responses concise and focused unless the user explicitly asks for detail.",
        "balanced": "Use a balanced level of detail: enough explanation to be useful without unnecessary length.",
        "detailed": "Provide thorough explanations, useful context and implementation detail when relevant.",
    }.get(response_style, "Use a balanced level of detail.")


# A stored prompt that is really just an older copy of the personality file must
# not be re-injected as "custom instructions" — that is how a superseded persona
# keeps overriding the current one. These markers identify any generation of the
# Jace personality prompt.
_PERSONALITY_MARKERS = (
    "JACE — PERSONALITY",
    "JACE - PERSONALITY",
    "JACE PERSONALITY",
)


def _is_legacy_personality_copy(stored_prompt: str) -> bool:
    """True when a stored prompt is a (possibly stale) copy of the persona file."""
    upper = stored_prompt.upper()
    return any(marker in upper for marker in _PERSONALITY_MARKERS)


def build_profile_prompt(
    profile: AssistantSettings,
    conversation_prompt: str | None = None,
    *,
    include_anchor: bool = True,
) -> str:
    """Build the identity portion of the system prompt for a Jace turn.

    prompts.py is the single source of truth for who Jace is. Anything stored in
    SQLite is treated as an optional refinement layer, and a stored prompt that
    is merely an older snapshot of the personality file is dropped entirely
    rather than replayed ahead of the current one.

    Ordering matters for small local models: the canonical personality comes
    first, and ``PERSONALITY_ANCHOR`` is repeated at the very end of the finished
    system message. ``include_anchor=False`` lets a caller append other context
    (tool policy, memory, voice style) and add the anchor itself afterwards, so
    the anchor stays last.
    """

    stored_prompt = (conversation_prompt or profile.system_prompt or "").strip()
    canonical_prompt = DEFAULT_SYSTEM_PROMPT.strip()

    sections: list[str] = [canonical_prompt]

    is_custom = bool(
        stored_prompt
        and stored_prompt != canonical_prompt
        and not _is_legacy_personality_copy(stored_prompt)
    )

    if is_custom:
        sections.append(
            "JACE CUSTOM INSTRUCTIONS\n"
            "User-configured refinements for this conversation. They adjust priorities "
            "and subject-matter behaviour. They never replace the personality, tone, "
            "safety, permission or operating rules defined above.\n"
            f"{stored_prompt}\n"
            "END JACE CUSTOM INSTRUCTIONS"
        )

    sections.append(
        "ASSISTANT PROFILE\n"
        f"Your name is {profile.assistant_name}.\n"
        f"The user's display name is {profile.user_name}.\n"
        f"{style_instruction(profile.response_style)}\n"
        "END ASSISTANT PROFILE"
    )

    if include_anchor:
        sections.append(PERSONALITY_ANCHOR)

    return "\n\n".join(section for section in sections if section.strip())
