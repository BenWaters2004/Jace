from __future__ import annotations

import asyncio
from pathlib import Path

from jace.config import settings


class AudioTranscriptionError(RuntimeError):
    pass


_model = None
_model_lock = asyncio.Lock()


async def _get_model():
    global _model
    if _model is not None:
        return _model

    async with _model_lock:
        if _model is not None:
            return _model
        try:
            from faster_whisper import WhisperModel
        except ImportError as exc:
            raise AudioTranscriptionError(
                "Audio transcription dependency is not installed. Run pip install -r requirements.txt."
            ) from exc

        def load():
            return WhisperModel(
                settings.audio_model,
                device=settings.audio_device,
                compute_type=settings.audio_compute_type,
                download_root=str(settings.audio_download_root),
                local_files_only=settings.audio_local_files_only,
            )

        try:
            _model = await asyncio.to_thread(load)
        except Exception as exc:
            if settings.audio_local_files_only:
                raise AudioTranscriptionError(
                    "The configured local Whisper model is not installed. Run "
                    "python .\\scripts\\install_audio_model.py once, then retry."
                ) from exc
            raise AudioTranscriptionError(f"Could not load the audio model: {exc}") from exc
    return _model


async def transcribe_audio(path: Path) -> tuple[str, dict]:
    if not settings.audio_enabled:
        raise AudioTranscriptionError("Audio transcription is disabled.")

    model = await _get_model()

    def transcribe():
        segments, info = model.transcribe(
            str(path),
            beam_size=settings.audio_beam_size,
            vad_filter=True,
            word_timestamps=False,
        )
        pieces = []
        segment_count = 0
        for segment in segments:
            segment_count += 1
            text = (segment.text or "").strip()
            if text:
                pieces.append(text)
        return " ".join(pieces).strip(), {
            "language": getattr(info, "language", None),
            "language_probability": getattr(info, "language_probability", None),
            "duration": getattr(info, "duration", None),
            "segments": segment_count,
        }

    try:
        text, metadata = await asyncio.to_thread(transcribe)
    except AudioTranscriptionError:
        raise
    except Exception as exc:
        raise AudioTranscriptionError(f"Audio transcription failed: {exc}") from exc

    if not text:
        raise AudioTranscriptionError("No speech could be transcribed from the audio file.")
    return text, metadata
