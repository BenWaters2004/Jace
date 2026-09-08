from __future__ import annotations

import asyncio
import importlib.util
import io
import re
from pathlib import Path
from typing import Any

from jace.config import settings


class VoiceRuntimeError(RuntimeError):
    pass


# Curated rather than exhaustive. These are the voices we expose in the Jace UI
# first; advanced users can still type another installed Kokoro voice name.
_CURATED_VOICES: list[dict[str, str]] = [
    {"id": "bm_lewis", "label": "Lewis · British male · calm / butler", "language": "en-gb"},
    {"id": "bm_george", "label": "George · British male · clear", "language": "en-gb"},
    {"id": "bm_daniel", "label": "Daniel · British male · warm", "language": "en-gb"},
    {"id": "bm_fable", "label": "Fable · British male · expressive", "language": "en-gb"},
    {"id": "bf_emma", "label": "Emma · British female · natural", "language": "en-gb"},
    {"id": "bf_alice", "label": "Alice · British female · clear", "language": "en-gb"},
    {"id": "am_michael", "label": "Michael · American male · steady", "language": "en-us"},
    {"id": "am_adam", "label": "Adam · American male · direct", "language": "en-us"},
    {"id": "af_heart", "label": "Heart · American female · warm", "language": "en-us"},
    {"id": "af_sarah", "label": "Sarah · American female · natural", "language": "en-us"},
]

_tts_engine: Any | None = None
_tts_lock = asyncio.Lock()


def curated_voices() -> list[dict[str, str]]:
    return list(_CURATED_VOICES)


def _model_path() -> Path:
    return settings.voice_kokoro_model_path


def _voices_path() -> Path:
    return settings.voice_kokoro_voices_path


def _dependency_available(name: str) -> bool:
    return importlib.util.find_spec(name) is not None


def _tts_files_available() -> bool:
    return _model_path().is_file() and _voices_path().is_file()


def get_voice_runtime_status() -> dict[str, Any]:
    return {
        "enabled": settings.voice_enabled,
        "stt_dependency_available": _dependency_available("faster_whisper"),
        "tts_dependency_available": _dependency_available("kokoro_onnx") and _dependency_available("soundfile"),
        "tts_model_files_available": _tts_files_available(),
        "tts_model_path": str(_model_path()),
        "tts_voices_path": str(_voices_path()),
        "voices": curated_voices(),
    }


def _clean_for_speech(text: str) -> str:
    value = text.strip()
    if not value:
        return ""

    # Do not read fenced source code aloud. Inline code is retained as words,
    # which is much more useful for short identifiers in spoken answers.
    value = re.sub(r"```[\s\S]*?```", " ", value)
    value = re.sub(r"`([^`]+)`", r"\1", value)
    value = re.sub(r"!\[[^\]]*\]\([^)]*\)", " ", value)
    value = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r"\1", value)
    value = re.sub(r"https?://\S+", "the linked page", value)
    value = re.sub(r"^\s{0,3}#{1,6}\s+", "", value, flags=re.MULTILINE)
    value = re.sub(r"^\s*[-*+]\s+", "", value, flags=re.MULTILINE)
    value = re.sub(r"^\s*\d+[.)]\s+", "", value, flags=re.MULTILINE)
    value = value.replace("**", "").replace("__", "").replace("~~", "")
    value = re.sub(r"\s+", " ", value).strip()
    return value


async def _get_tts_engine():
    global _tts_engine
    if _tts_engine is not None:
        return _tts_engine

    async with _tts_lock:
        if _tts_engine is not None:
            return _tts_engine

        if not settings.voice_enabled:
            raise VoiceRuntimeError("Voice is disabled in Jace configuration.")
        if not _tts_files_available():
            raise VoiceRuntimeError(
                "Kokoro voice model files are not installed. Run "
                "python .\\scripts\\install_voice_models.py first."
            )

        try:
            from kokoro_onnx import Kokoro
        except ImportError as exc:
            raise VoiceRuntimeError(
                "kokoro-onnx is not installed. Run python -m pip install -r requirements.txt."
            ) from exc

        def load():
            # kokoro-onnx uses ONNX Runtime and keeps the model in process after
            # the first load. This deliberately leaves the RTX available to
            # Ollama; normal ONNX CPU execution is fast enough for this 82M model.
            return Kokoro(str(_model_path()), str(_voices_path()))

        try:
            _tts_engine = await asyncio.to_thread(load)
        except Exception as exc:
            raise VoiceRuntimeError(f"Could not load the local Kokoro voice model: {exc}") from exc

    return _tts_engine


async def synthesize_wav(
    text: str,
    *,
    voice: str,
    speed: float,
    language: str,
) -> bytes:
    cleaned = _clean_for_speech(text)
    if not cleaned:
        raise VoiceRuntimeError("There is no speakable text in this segment.")
    if len(cleaned) > settings.voice_tts_max_chars:
        raise VoiceRuntimeError(
            f"One speech segment may contain at most {settings.voice_tts_max_chars} characters."
        )

    engine = await _get_tts_engine()

    def generate() -> bytes:
        try:
            import soundfile as sf
        except ImportError as exc:
            raise VoiceRuntimeError("soundfile is not installed.") from exc

        try:
            samples, sample_rate = engine.create(
                cleaned,
                voice=voice,
                speed=max(0.70, min(1.45, float(speed))),
                lang=language,
            )
            buffer = io.BytesIO()
            sf.write(buffer, samples, sample_rate, format="WAV", subtype="PCM_16")
            return buffer.getvalue()
        except VoiceRuntimeError:
            raise
        except Exception as exc:
            raise VoiceRuntimeError(f"Local speech synthesis failed: {exc}") from exc

    return await asyncio.to_thread(generate)
