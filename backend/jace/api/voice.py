from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field

from jace.voice.service import (
    MAX_AUDIO_BYTES,
    VoiceDecodeError,
    VoiceError,
    VoiceUnavailableError,
    voice_service,
)


logger = logging.getLogger(__name__)
router = APIRouter(prefix="/voice", tags=["voice"])


class SpeechRequest(BaseModel):
    text: str = Field(min_length=1, max_length=20_000)


_stt_warmup_task: asyncio.Task | None = None


async def _warm_stt_runtime() -> None:
    """Load Faster-Whisper off the request path.

    The desktop asks for /voice/status during startup. That is a good moment to
    begin loading the local STT model in a worker thread, so the first actual
    push-to-talk request does not also pay the model-loading cost.

    _get_whisper_model is currently the service's internal loader; using it
    here is intentional until VoiceService exposes a public warm-up method.
    """

    try:
        await asyncio.to_thread(voice_service._get_whisper_model)  # noqa: SLF001
        logger.info("Jace STT runtime warmed successfully.")
    except Exception as exc:
        # Warm-up is best effort. The normal transcription endpoint will still
        # return the authoritative error if STT is unavailable when requested.
        logger.warning("Jace STT warm-up did not complete: %s", exc)


def _ensure_stt_warmup() -> None:
    global _stt_warmup_task

    if _stt_warmup_task is None or _stt_warmup_task.done():
        _stt_warmup_task = asyncio.create_task(_warm_stt_runtime())


@router.get("/status")
async def get_status():
    _ensure_stt_warmup()
    return voice_service.status()


# Compatibility route used by the Phase 10B desktop client during startup.
# Voice settings currently come from the same local runtime configuration as
# the status payload, so expose that payload here rather than maintaining a
# second source of truth.
@router.get("/settings")
async def get_settings():
    _ensure_stt_warmup()
    return voice_service.status()


@router.post("/transcribe")
async def transcribe_voice(file: UploadFile = File(...)):
    try:
        audio_bytes = await file.read(MAX_AUDIO_BYTES + 1)
    finally:
        await file.close()

    logger.info(
        "Voice upload received: filename=%s content_type=%s bytes=%d",
        file.filename,
        file.content_type,
        len(audio_bytes),
    )

    if not audio_bytes:
        raise HTTPException(status_code=422, detail="The microphone upload was empty.")

    if len(audio_bytes) > MAX_AUDIO_BYTES:
        raise HTTPException(
            status_code=413,
            detail="The microphone recording is too large to transcribe.",
        )

    try:
        result = await asyncio.to_thread(
            voice_service.transcribe_bytes,
            audio_bytes,
            filename=file.filename,
            content_type=file.content_type,
        )
        return result.as_dict()
    except VoiceDecodeError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except VoiceUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except VoiceError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Unexpected local voice transcription failure")
        message = str(exc)
        if "1094995529" in message or "Invalid data found when processing input" in message:
            raise HTTPException(
                status_code=422,
                detail=(
                    "The microphone recording was incomplete or corrupt and could not be decoded. "
                    "Hold Home, speak, then release Home and try again."
                ),
            ) from exc
        raise HTTPException(
            status_code=500,
            detail=f"Audio transcription failed: {message}",
        ) from exc


@router.post("/synthesize")
async def synthesize_voice(request: SpeechRequest):
    try:
        wav_bytes = await asyncio.to_thread(
            voice_service.synthesize_wav,
            request.text,
        )
        return Response(
            content=wav_bytes,
            media_type="audio/wav",
            headers={"Cache-Control": "no-store"},
        )
    except VoiceUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except VoiceError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Unexpected local voice synthesis failure")
        raise HTTPException(
            status_code=500,
            detail=f"Speech synthesis failed: {exc}",
        ) from exc


# British-spelling compatibility route for any early Phase 10B client builds.
@router.post("/synthesise")
async def synthesise_voice(request: SpeechRequest):
    return await synthesize_voice(request)
