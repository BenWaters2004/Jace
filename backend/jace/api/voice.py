from __future__ import annotations

import tempfile
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import Response

from jace.attachments.audio import AudioTranscriptionError, transcribe_audio
from jace.config import settings as env_settings
from jace.database import SessionLocal
from jace.db.voice import (
    get_or_create_voice_settings,
    reset_voice_settings,
    update_voice_settings,
)
from jace.runtime import runtime_events
from jace.schemas import (
    VoiceSettingsResponse,
    VoiceSettingsUpdate,
    VoiceStateRequest,
    VoiceStatusResponse,
    VoiceSynthesisRequest,
    VoiceTranscriptionResponse,
)
from jace.voice import VoiceRuntimeError, get_voice_runtime_status, synthesize_wav


router = APIRouter(prefix="/voice", tags=["voice"])


def _voice_settings_response(profile) -> VoiceSettingsResponse:
    return VoiceSettingsResponse(
        enabled=profile.enabled,
        auto_speak=profile.auto_speak,
        verbal_approvals=profile.verbal_approvals,
        microphone_mode=profile.microphone_mode,
        tts_voice=profile.tts_voice,
        tts_speed=profile.tts_speed,
        tts_language=profile.tts_language,
        created_at=profile.created_at,
        updated_at=profile.updated_at,
    )


@router.get("/status", response_model=VoiceStatusResponse)
async def voice_status():
    status = get_voice_runtime_status()
    return VoiceStatusResponse(
        **status,
        stt_model=env_settings.audio_model,
    )


@router.get("/settings", response_model=VoiceSettingsResponse)
async def get_voice_settings():
    async with SessionLocal() as session:
        return _voice_settings_response(await get_or_create_voice_settings(session))


@router.patch("/settings", response_model=VoiceSettingsResponse)
async def patch_voice_settings(request: VoiceSettingsUpdate):
    async with SessionLocal() as session:
        profile = await get_or_create_voice_settings(session)
        profile = await update_voice_settings(
            session,
            profile,
            **request.model_dump(exclude_unset=True),
        )
        return _voice_settings_response(profile)


@router.post("/settings/reset", response_model=VoiceSettingsResponse)
async def reset_voice_profile():
    async with SessionLocal() as session:
        return _voice_settings_response(await reset_voice_settings(session))


@router.post("/listening")
async def set_listening(request: VoiceStateRequest):
    if request.active:
        await runtime_events.publish("voice.listening.started")
        await runtime_events.publish("jace.state.changed", state="listening", reason="push_to_talk")
    else:
        await runtime_events.publish("voice.listening.stopped")
        if runtime_events.state == "listening":
            await runtime_events.publish("jace.state.changed", state="transcribing", reason="push_to_talk_released")
    return {"success": True}


@router.post("/speaking")
async def set_speaking(request: VoiceStateRequest):
    if request.active:
        await runtime_events.publish("speech.started")
        await runtime_events.publish("jace.state.changed", state="speaking", reason="voice_playback")
    else:
        await runtime_events.publish("speech.complete")
        if runtime_events.state == "speaking":
            await runtime_events.publish("jace.state.changed", state="idle", reason="voice_playback_complete")
    return {"success": True}


@router.post("/transcribe", response_model=VoiceTranscriptionResponse)
async def transcribe_voice(file: UploadFile = File(...)):
    if not env_settings.voice_enabled:
        raise HTTPException(status_code=403, detail="Voice is disabled in Jace configuration.")

    raw = await file.read(env_settings.voice_recording_max_bytes + 1)
    await file.close()
    if not raw:
        raise HTTPException(status_code=400, detail="The microphone recording was empty.")
    if len(raw) > env_settings.voice_recording_max_bytes:
        raise HTTPException(status_code=413, detail="The microphone recording is too large.")

    suffix = Path(file.filename or "voice.webm").suffix or ".webm"
    await runtime_events.publish("voice.transcription.started")
    await runtime_events.publish("jace.state.changed", state="transcribing", reason="local_whisper")

    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(prefix="jace-voice-", suffix=suffix, delete=False) as handle:
            handle.write(raw)
            temp_path = Path(handle.name)

        text, metadata = await transcribe_audio(temp_path)
        await runtime_events.publish(
            "voice.transcription.complete",
            transcript_chars=len(text),
            language=metadata.get("language"),
        )
        return VoiceTranscriptionResponse(
            text=text,
            language=metadata.get("language"),
            language_probability=metadata.get("language_probability"),
            duration=metadata.get("duration"),
        )
    except AudioTranscriptionError as exc:
        await runtime_events.publish("voice.transcription.failed", error=str(exc))
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    finally:
        if temp_path is not None:
            try:
                temp_path.unlink(missing_ok=True)
            except OSError:
                pass
        if runtime_events.state == "transcribing":
            await runtime_events.publish("jace.state.changed", state="idle", reason="transcription_finished")


@router.post("/synthesize")
async def synthesize_voice(request: VoiceSynthesisRequest):
    if not env_settings.voice_enabled:
        raise HTTPException(status_code=403, detail="Voice is disabled in Jace configuration.")

    async with SessionLocal() as session:
        profile = await get_or_create_voice_settings(session)
        if not profile.enabled:
            raise HTTPException(status_code=403, detail="Voice is disabled in Jace settings.")
        voice = request.voice or profile.tts_voice
        speed = request.speed if request.speed is not None else profile.tts_speed
        language = request.language or profile.tts_language

    try:
        wav = await synthesize_wav(
            request.text,
            voice=voice,
            speed=speed,
            language=language,
        )
    except VoiceRuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    return Response(
        wav,
        media_type="audio/wav",
        headers={"Cache-Control": "no-store"},
    )
