from fastapi import APIRouter

from jace.api.helpers import assistant_settings_response
from jace.database import SessionLocal
from jace.db.settings import get_or_create_assistant_settings, reset_assistant_settings, update_assistant_settings
from jace.schemas import AssistantSettingsResponse, AssistantSettingsUpdate


router = APIRouter(prefix="/settings", tags=["settings"])


@router.get("", response_model=AssistantSettingsResponse)
async def get_settings():
    async with SessionLocal() as session:
        profile = await get_or_create_assistant_settings(session)
        return assistant_settings_response(profile)


@router.patch("", response_model=AssistantSettingsResponse)
async def patch_settings(request: AssistantSettingsUpdate):
    async with SessionLocal() as session:
        profile = await get_or_create_assistant_settings(session)
        changes = request.model_dump(exclude_unset=True)
        profile = await update_assistant_settings(session, profile, **changes)
        return assistant_settings_response(profile)


@router.post("/reset", response_model=AssistantSettingsResponse)
async def reset_settings():
    async with SessionLocal() as session:
        return assistant_settings_response(await reset_assistant_settings(session))
