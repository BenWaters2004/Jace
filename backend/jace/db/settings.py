from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from jace.ai.prompts import DEFAULT_SYSTEM_PROMPT
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


def build_profile_prompt(
    profile: AssistantSettings,
    conversation_prompt: str | None = None,
) -> str:
    """Build the authoritative system prompt for every Jace turn.

    DEFAULT_SYSTEM_PROMPT is deliberately always present. Previously the
    personality in prompts.py was only copied into SQLite when the profile was
    first created/reset. Existing profiles and conversations could therefore
    keep an older prompt forever, making later personality edits appear to do
    nothing.

    A stored profile/conversation prompt is now treated as an optional
    customization layer rather than a replacement for Jace's core identity.
    The canonical personality from prompts.py is appended after custom text so
    stale or generic stored prompts cannot silently replace Jace's identity.
    """

    stored_prompt = (conversation_prompt or profile.system_prompt or "").strip()
    canonical_prompt = DEFAULT_SYSTEM_PROMPT.strip()

    sections: list[str] = []

    if stored_prompt and stored_prompt != canonical_prompt:
        sections.append(
            "JACE CUSTOM INSTRUCTIONS\n"
            "These are additional user-configured instructions. They may refine "
            "behaviour, but they do not replace the core Jace personality, safety, "
            "permission, or operating rules that follow.\n"
            f"{stored_prompt}\n"
            "END JACE CUSTOM INSTRUCTIONS"
        )

    # Keep the canonical prompt late in the system message so it remains the
    # authoritative identity even when an old database prompt still exists.
    sections.append(canonical_prompt)

    sections.append(
        "ASSISTANT PROFILE\n"
        f"Your name is {profile.assistant_name}.\n"
        f"The user's display name is {profile.user_name}.\n"
        f"{style_instruction(profile.response_style)}\n"
        "The JACE — PERSONALITY section above is your persistent identity and "
        "tone for both typed and spoken responses. Do not drop into a generic "
        "assistant persona merely because the request is factual or simple.\n"
        "END ASSISTANT PROFILE"
    )

    return "\n\n".join(section for section in sections if section.strip())
