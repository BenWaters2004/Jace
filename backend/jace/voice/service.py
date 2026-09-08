from __future__ import annotations

import importlib.util
import io
import logging
import os
import tempfile
import threading
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Any


logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[3]
DATA_ROOT = PROJECT_ROOT / "data"

MIN_AUDIO_BYTES = 1_000
MAX_AUDIO_BYTES = 25 * 1024 * 1024
WELCOME_LINE = "All systems online, sir. What are we working on today?"


class VoiceRuntimeError(RuntimeError):
    """Compatibility base error for the local Jace voice runtime.

    Earlier Phase 10B modules imported VoiceRuntimeError directly.  Keep that
    public name as the root of the current voice exception hierarchy so older
    imports and exception handlers continue to work.
    """


class VoiceError(VoiceRuntimeError):
    """Base error for the local Jace voice pipeline."""


class VoiceUnavailableError(VoiceError):
    """Raised when an optional local voice dependency/model is unavailable."""


class VoiceDecodeError(VoiceError):
    """Raised when an uploaded recording is malformed or cannot be decoded."""


@dataclass(slots=True)
class TranscriptionResult:
    text: str
    language: str | None = None
    language_probability: float | None = None
    duration_seconds: float | None = None
    bytes_received: int | None = None
    filename: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "text": self.text,
            "language": self.language,
            "language_probability": self.language_probability,
            "duration_seconds": self.duration_seconds,
            "bytes_received": self.bytes_received,
            "filename": self.filename,
        }


def _package_available(name: str) -> bool:
    return importlib.util.find_spec(name) is not None


def _safe_suffix(filename: str | None, content_type: str | None) -> str:
    name_suffix = Path(filename or "").suffix.lower()
    if name_suffix in {".webm", ".ogg", ".oga", ".wav", ".mp3", ".m4a", ".mp4", ".flac", ".aac"}:
        return name_suffix

    mime = (content_type or "").lower()
    if "ogg" in mime:
        return ".ogg"
    if "wav" in mime:
        return ".wav"
    if "mpeg" in mime:
        return ".mp3"
    if "mp4" in mime or "m4a" in mime:
        return ".m4a"
    if "flac" in mime:
        return ".flac"
    if "aac" in mime:
        return ".aac"
    return ".webm"


def _validate_container_signature(data: bytes, suffix: str) -> None:
    if len(data) < MIN_AUDIO_BYTES:
        raise VoiceDecodeError(
            "The microphone recording contained too little audio data. "
            "Hold Home, speak, then release Home to send."
        )

    if len(data) > MAX_AUDIO_BYTES:
        raise VoiceDecodeError("The microphone recording is too large to transcribe.")

    if suffix == ".webm" and not data.startswith(b"\x1a\x45\xdf\xa3"):
        raise VoiceDecodeError(
            "The microphone recording was labelled as WebM but does not contain a valid WebM header. "
            "Please try the recording again."
        )

    if suffix in {".ogg", ".oga"} and not data.startswith(b"OggS"):
        raise VoiceDecodeError(
            "The microphone recording was labelled as Ogg but does not contain a valid Ogg header. "
            "Please try the recording again."
        )

    if suffix == ".wav" and not data.startswith(b"RIFF"):
        raise VoiceDecodeError(
            "The microphone recording was labelled as WAV but does not contain a valid WAV header. "
            "Please try the recording again."
        )


def _preflight_decode(path: Path) -> None:
    """Verify that PyAV can find and decode at least one audio frame.

    faster-whisper uses PyAV internally. Doing this explicitly gives the user a
    clean Jace error instead of leaking FFmpeg's Errno 1094995529.
    """

    if not _package_available("av"):
        # faster-whisper will surface its own dependency error. Do not make PyAV
        # an additional hard dependency if a different decoder is configured.
        return

    try:
        import av  # type: ignore

        decoded_frame = False
        with av.open(str(path)) as container:
            audio_streams = [stream for stream in container.streams if stream.type == "audio"]
            if not audio_streams:
                raise VoiceDecodeError("The recording contains no decodable audio stream.")

            stream = audio_streams[0]
            for packet in container.demux(stream):
                for _frame in packet.decode():
                    decoded_frame = True
                    break
                if decoded_frame:
                    break

        if not decoded_frame:
            raise VoiceDecodeError(
                "The recording contains an audio container but no usable audio frames. "
                "Hold Home for a moment before speaking and try again."
            )
    except VoiceDecodeError:
        raise
    except Exception as exc:
        message = str(exc)
        logger.warning("Voice preflight decode failed for %s: %s", path, message)
        if "1094995529" in message or "Invalid data found when processing input" in message:
            raise VoiceDecodeError(
                "The microphone recording was incomplete or corrupt and could not be decoded. "
                "Hold Home, speak, then release Home and try again."
            ) from exc
        raise VoiceDecodeError(f"The microphone recording could not be decoded: {message}") from exc


def _find_piper_model() -> Path | None:
    configured = (
        os.getenv("JACE_VOICE_PIPER_MODEL")
        or os.getenv("JACE_PIPER_MODEL")
        or ""
    ).strip()
    if configured:
        candidate = Path(configured).expanduser()
        if candidate.exists() and candidate.suffix.lower() == ".onnx":
            return candidate.resolve()

    search_roots = [
        DATA_ROOT / "voice",
        DATA_ROOT / "voice_models",
        DATA_ROOT / "models" / "voice",
        PROJECT_ROOT / "backend" / "models" / "voice",
    ]

    for root in search_roots:
        if not root.exists():
            continue
        models = sorted(root.rglob("*.onnx"))
        if models:
            return models[0].resolve()
    return None


class VoiceService:
    def __init__(self) -> None:
        self._whisper_model: Any | None = None
        self._whisper_lock = threading.Lock()
        self._piper_voice: Any | None = None
        self._piper_model_path: Path | None = None
        self._piper_lock = threading.Lock()

    @property
    def whisper_model_name(self) -> str:
        return (
            os.getenv("JACE_VOICE_STT_MODEL")
            or os.getenv("JACE_WHISPER_MODEL")
            or "base.en"
        ).strip()

    def status(self) -> dict[str, Any]:
        whisper_available = _package_available("faster_whisper")
        piper_model = _find_piper_model()
        piper_available = _package_available("piper") and piper_model is not None

        return {
            "enabled": True,
            "platform_supported": True,
            "transcription_available": whisper_available,
            "synthesis_available": piper_available,
            # Compatibility aliases used by earlier Phase 10B clients.
            "stt_available": whisper_available,
            "tts_available": piper_available,
            "whisper_model": self.whisper_model_name if whisper_available else None,
            "piper_model": str(piper_model) if piper_model else None,
            "push_to_talk_key": "Home",
            "welcome_line": WELCOME_LINE,
            "min_audio_bytes": MIN_AUDIO_BYTES,
            "max_audio_bytes": MAX_AUDIO_BYTES,
        }

    def _get_whisper_model(self) -> Any:
        if self._whisper_model is not None:
            return self._whisper_model

        if not _package_available("faster_whisper"):
            raise VoiceUnavailableError(
                "Local transcription is unavailable because faster-whisper is not installed."
            )

        with self._whisper_lock:
            if self._whisper_model is not None:
                return self._whisper_model

            from faster_whisper import WhisperModel  # type: ignore

            device = (os.getenv("JACE_VOICE_STT_DEVICE") or "auto").strip()
            compute_type = (os.getenv("JACE_VOICE_STT_COMPUTE_TYPE") or "int8").strip()

            try:
                self._whisper_model = WhisperModel(
                    self.whisper_model_name,
                    device=device,
                    compute_type=compute_type,
                )
            except Exception:
                # A CPU/int8 fallback keeps voice usable when an environment says
                # auto/CUDA but the current Windows machine cannot initialise it.
                if device == "cpu" and compute_type == "int8":
                    raise
                logger.exception(
                    "Could not initialise faster-whisper with device=%s compute_type=%s; falling back to cpu/int8",
                    device,
                    compute_type,
                )
                self._whisper_model = WhisperModel(
                    self.whisper_model_name,
                    device="cpu",
                    compute_type="int8",
                )

        return self._whisper_model

    def transcribe_bytes(
        self,
        data: bytes,
        *,
        filename: str | None = None,
        content_type: str | None = None,
    ) -> TranscriptionResult:
        suffix = _safe_suffix(filename, content_type)
        _validate_container_signature(data, suffix)

        temp_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="wb",
                delete=False,
                prefix="jace-voice-",
                suffix=suffix,
            ) as temp_file:
                temp_file.write(data)
                temp_file.flush()
                temp_path = Path(temp_file.name)

            logger.info(
                "Voice upload written: filename=%s content_type=%s bytes=%d path=%s disk_bytes=%d",
                filename,
                content_type,
                len(data),
                temp_path,
                temp_path.stat().st_size,
            )

            if temp_path.stat().st_size != len(data):
                raise VoiceDecodeError(
                    "The microphone upload was truncated while Jace wrote the temporary audio file."
                )

            _preflight_decode(temp_path)
            model = self._get_whisper_model()

            try:
                segments, info = model.transcribe(
                    str(temp_path),
                    beam_size=5,
                    vad_filter=True,
                )
                segment_list = list(segments)
            except Exception as exc:
                message = str(exc)
                logger.exception("Audio transcription failed for %s", temp_path)
                if "1094995529" in message or "Invalid data found when processing input" in message:
                    raise VoiceDecodeError(
                        "The microphone recording was incomplete or corrupt and could not be decoded. "
                        "Hold Home, speak, then release Home and try again."
                    ) from exc
                raise VoiceError(f"Audio transcription failed: {message}") from exc

            text = " ".join(
                str(segment.text).strip()
                for segment in segment_list
                if str(segment.text).strip()
            ).strip()

            if not text:
                raise VoiceDecodeError(
                    "Jace could not detect speech in that recording. Hold Home while you speak, then release it."
                )

            language = getattr(info, "language", None)
            probability = getattr(info, "language_probability", None)
            duration = getattr(info, "duration", None)

            return TranscriptionResult(
                text=text,
                language=str(language) if language else None,
                language_probability=float(probability) if probability is not None else None,
                duration_seconds=float(duration) if duration is not None else None,
                bytes_received=len(data),
                filename=filename,
            )
        finally:
            if temp_path is not None:
                try:
                    temp_path.unlink(missing_ok=True)
                except Exception:
                    logger.warning("Could not remove temporary voice file %s", temp_path, exc_info=True)

    def _get_piper_voice(self) -> Any:
        model_path = _find_piper_model()
        if model_path is None:
            raise VoiceUnavailableError(
                "Local speech synthesis is unavailable because no Piper .onnx voice model was found."
            )

        if not _package_available("piper"):
            raise VoiceUnavailableError(
                "Local speech synthesis is unavailable because Piper is not installed."
            )

        if self._piper_voice is not None and self._piper_model_path == model_path:
            return self._piper_voice

        with self._piper_lock:
            if self._piper_voice is not None and self._piper_model_path == model_path:
                return self._piper_voice

            from piper.voice import PiperVoice  # type: ignore

            config_path = model_path.with_suffix(model_path.suffix + ".json")
            if not config_path.exists():
                # Piper's normal companion file is voice.onnx.json. Some older
                # installs use voice.json; support both.
                alternate = model_path.with_suffix(".json")
                config_path = alternate if alternate.exists() else config_path

            if not config_path.exists():
                raise VoiceUnavailableError(
                    f"Piper voice configuration was not found next to {model_path.name}."
                )

            self._piper_voice = PiperVoice.load(
                str(model_path),
                config_path=str(config_path),
            )
            self._piper_model_path = model_path

        return self._piper_voice

    def synthesize_wav(self, text: str) -> bytes:
        value = text.strip()
        if not value:
            raise VoiceError("There is no text to speak.")
        if len(value) > 20_000:
            raise VoiceError("The requested speech is too long for one local voice response.")

        voice = self._get_piper_voice()
        buffer = io.BytesIO()

        try:
            with wave.open(buffer, "wb") as wav_file:
                voice.synthesize_wav(value, wav_file)
        except Exception as exc:
            logger.exception("Piper speech synthesis failed")
            raise VoiceError(f"Speech synthesis failed: {exc}") from exc

        data = buffer.getvalue()
        if not data:
            raise VoiceError("Speech synthesis returned an empty WAV file.")
        return data


voice_service = VoiceService()


# Module-level compatibility helpers for earlier Phase 10B imports.
def get_voice_status() -> dict[str, Any]:
    return voice_service.status()


def voice_status() -> dict[str, Any]:
    return voice_service.status()


def transcribe_audio(
    data: bytes,
    *,
    filename: str | None = None,
    content_type: str | None = None,
) -> TranscriptionResult:
    return voice_service.transcribe_bytes(
        data,
        filename=filename,
        content_type=content_type,
    )


def transcribe_upload(
    data: bytes,
    *,
    filename: str | None = None,
    content_type: str | None = None,
) -> TranscriptionResult:
    return transcribe_audio(data, filename=filename, content_type=content_type)


def synthesize_speech(text: str) -> bytes:
    return voice_service.synthesize_wav(text)


def synthesise_speech(text: str) -> bytes:
    return voice_service.synthesize_wav(text)
