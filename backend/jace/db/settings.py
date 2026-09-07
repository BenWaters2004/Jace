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


def build_profile_prompt(profile: AssistantSettings, conversation_prompt: str | None = None) -> str:
    base = (conversation_prompt or profile.system_prompt or DEFAULT_SYSTEM_PROMPT).strip()
    identity = (
        f"\n\nASSISTANT PROFILE\n"
        f"Your name is {profile.assistant_name}.\n"
        f"The user's display name is {profile.user_name}.\n"
        f"{style_instruction(profile.response_style)}\n"
        "END ASSISTANT PROFILE"
    )
    return base + identity
