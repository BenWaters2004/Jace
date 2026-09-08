from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from jace.config import settings as env_settings
from jace.db.models import VoiceSettings


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


async def get_or_create_voice_settings(session: AsyncSession) -> VoiceSettings:
    profile = await session.get(VoiceSettings, "default")
    if profile is not None:
        return profile

    profile = VoiceSettings(
        id="default",
        enabled=env_settings.voice_enabled,
        auto_speak=True,
        verbal_approvals=True,
        microphone_mode="push_to_talk",
        tts_voice=env_settings.voice_default_voice,
        tts_speed=env_settings.voice_default_speed,
        tts_language=env_settings.voice_default_language,
    )
    session.add(profile)
    await session.commit()
    await session.refresh(profile)
    return profile


async def update_voice_settings(
    session: AsyncSession,
    profile: VoiceSettings,
    **changes,
) -> VoiceSettings:
    for field, value in changes.items():
        if value is not None and hasattr(profile, field):
            setattr(profile, field, value)

    profile.updated_at = utc_now()
    await session.commit()
    await session.refresh(profile)
    return profile


async def reset_voice_settings(session: AsyncSession) -> VoiceSettings:
    profile = await get_or_create_voice_settings(session)
    profile.enabled = env_settings.voice_enabled
    profile.auto_speak = True
    profile.verbal_approvals = True
    profile.microphone_mode = "push_to_talk"
    profile.tts_voice = env_settings.voice_default_voice
    profile.tts_speed = env_settings.voice_default_speed
    profile.tts_language = env_settings.voice_default_language
    profile.updated_at = utc_now()
    await session.commit()
    await session.refresh(profile)
    return profile
