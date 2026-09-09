from __future__ import annotations

import importlib
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

from jace.config import settings


logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[3]
DATA_ROOT = PROJECT_ROOT / "data"
VOICE_ROOT = DATA_ROOT / "voice"
KOKORO_ROOT = VOICE_ROOT / "kokoro"

MIN_AUDIO_BYTES = 1_000
MAX_AUDIO_BYTES = 25 * 1024 * 1024
WELCOME_LINE = "All systems online, sir. What are we working on today?"

DEFAULT_KOKORO_MODEL = KOKORO_ROOT / "kokoro-v1.0.onnx"
DEFAULT_KOKORO_VOICES = KOKORO_ROOT / "voices-v1.0.bin"
DEFAULT_KOKORO_VOICE = "bm_george"
DEFAULT_KOKORO_LANGUAGE = "en-gb"
DEFAULT_KOKORO_SPEED = 1.0


class VoiceRuntimeError(RuntimeError):
    """Compatibility base error for Jace's local voice runtime."""


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
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError):
        return False


def _configured_path(*env_names: str, default: Path) -> Path:
    for env_name in env_names:
        raw = (os.getenv(env_name) or "").strip()
        if raw:
            return Path(raw).expanduser().resolve()
    return default.resolve()


def _safe_float_env(name: str, default: float, *, minimum: float, maximum: float) -> float:
    raw = (os.getenv(name) or "").strip()
    if not raw:
        return default
    try:
        value = float(raw)
    except ValueError:
        logger.warning("Ignoring invalid %s=%r; using %.2f", name, raw, default)
        return default
    if not minimum <= value <= maximum:
        logger.warning(
            "Ignoring out-of-range %s=%r; expected %.2f..%.2f; using %.2f",
            name,
            raw,
            minimum,
            maximum,
            default,
        )
        return default
    return value


def _safe_suffix(filename: str | None, content_type: str | None) -> str:
    name_suffix = Path(filename or "").suffix.lower()
    if name_suffix in {
        ".webm",
        ".ogg",
        ".oga",
        ".wav",
        ".mp3",
        ".m4a",
        ".mp4",
        ".flac",
        ".aac",
    }:
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
    """Verify PyAV can find and decode at least one audio frame.

    faster-whisper uses PyAV internally. Performing this check ourselves turns
    FFmpeg's opaque Errno 1094995529 into a useful Jace recording error.
    """

    if not _package_available("av"):
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


class VoiceService:
    def __init__(self) -> None:
        self._whisper_model: Any | None = None
        self._whisper_lock = threading.Lock()
        self._whisper_loaded_device: str | None = None
        self._whisper_loaded_compute_type: str | None = None

        self._kokoro: Any | None = None
        self._kokoro_loaded_from: tuple[Path, Path] | None = None
        self._kokoro_lock = threading.Lock()
        self._tts_inference_lock = threading.Lock()

    # ------------------------------------------------------------------
    # Configuration
    # ------------------------------------------------------------------

    @property
    def whisper_model_name(self) -> str:
        return (
            os.getenv("JACE_VOICE_STT_MODEL")
            or os.getenv("JACE_WHISPER_MODEL")
            or "base.en"
        ).strip()

    @property
    def stt_device(self) -> str:
        # Reliability first on Windows.  Faster-Whisper/CTranslate2 can create
        # an ``auto``/CUDA model successfully and only fail on the first
        # transcription when CUDA runtime DLLs such as cublas64_12.dll are not
        # on PATH.  CPU/int8 needs no CUDA installation and is fast enough for
        # Jace's short push-to-talk requests, so it is the safe default.
        value = (os.getenv("JACE_VOICE_STT_DEVICE") or "cpu").strip().lower()
        if value not in {"cpu", "cuda", "auto"}:
            logger.warning(
                "Ignoring invalid JACE_VOICE_STT_DEVICE=%r; using cpu",
                value,
            )
            return "cpu"
        return value

    @property
    def stt_compute_type(self) -> str:
        configured = (os.getenv("JACE_VOICE_STT_COMPUTE_TYPE") or "").strip()
        if configured:
            return configured
        return "float16" if self.stt_device == "cuda" else "int8"

    @property
    def kokoro_model_path(self) -> Path:
        return _configured_path(
            "JACE_VOICE_KOKORO_MODEL",
            "JACE_KOKORO_MODEL",
            default=DEFAULT_KOKORO_MODEL,
        )

    @property
    def kokoro_voices_path(self) -> Path:
        return _configured_path(
            "JACE_VOICE_KOKORO_VOICES",
            "JACE_KOKORO_VOICES",
            default=DEFAULT_KOKORO_VOICES,
        )

    @property
    def tts_voice(self) -> str:
        return (
            os.getenv("JACE_VOICE_TTS_VOICE")
            or os.getenv("JACE_KOKORO_VOICE")
            or DEFAULT_KOKORO_VOICE
        ).strip()

    @property
    def tts_language(self) -> str:
        return (
            os.getenv("JACE_VOICE_TTS_LANG")
            or os.getenv("JACE_KOKORO_LANGUAGE")
            or DEFAULT_KOKORO_LANGUAGE
        ).strip().lower()

    @property
    def tts_speed(self) -> float:
        return _safe_float_env(
            "JACE_VOICE_TTS_SPEED",
            DEFAULT_KOKORO_SPEED,
            minimum=0.5,
            maximum=2.0,
        )

    # ------------------------------------------------------------------
    # Status / diagnostics
    # ------------------------------------------------------------------

    def _tts_readiness(self) -> tuple[bool, str | None]:
        if not _package_available("kokoro_onnx"):
            return (
                False,
                "The kokoro-onnx Python package is not installed in Jace's backend environment.",
            )

        try:
            importlib.import_module("kokoro_onnx")
        except Exception as exc:
            return (
                False,
                "The kokoro-onnx package is installed but could not be imported: "
                f"{exc}",
            )

        model_path = self.kokoro_model_path
        voices_path = self.kokoro_voices_path

        if not model_path.is_file():
            return False, f"Kokoro model file is missing: {model_path}"
        if model_path.stat().st_size < 10 * 1024 * 1024:
            return False, f"Kokoro model file looks incomplete: {model_path}"

        if not voices_path.is_file():
            return False, f"Kokoro voices file is missing: {voices_path}"
        if voices_path.stat().st_size < 1 * 1024 * 1024:
            return False, f"Kokoro voices file looks incomplete: {voices_path}"

        return True, None

    def status(self) -> dict[str, Any]:
        whisper_available = _package_available("faster_whisper")
        tts_available, tts_reason = self._tts_readiness()

        return {
            "enabled": True,
            "platform_supported": True,
            "transcription_available": whisper_available,
            "synthesis_available": tts_available,
            # Compatibility aliases used by Phase 10B clients.
            "stt_available": whisper_available,
            "tts_available": tts_available,
            "whisper_model": self.whisper_model_name if whisper_available else None,
            "stt_device": self.stt_device,
            "stt_compute_type": self.stt_compute_type,
            "stt_runtime_device": self._whisper_loaded_device,
            "stt_runtime_compute_type": self._whisper_loaded_compute_type,
            "tts_engine": "kokoro-onnx",
            "kokoro_model": str(self.kokoro_model_path),
            "kokoro_voices": str(self.kokoro_voices_path),
            "kokoro_voice": self.tts_voice,
            "kokoro_language": self.tts_language,
            "kokoro_speed": self.tts_speed,
            "tts_reason": tts_reason,
            # Keep this legacy field so old UI builds do not fail while making
            # it explicit that Piper is no longer Jace's TTS engine.
            "piper_model": None,
            "push_to_talk_key": "Home",
            "welcome_line": WELCOME_LINE,
            "min_audio_bytes": MIN_AUDIO_BYTES,
            "max_audio_bytes": MAX_AUDIO_BYTES,
        }

    # ------------------------------------------------------------------
    # Speech-to-text
    # ------------------------------------------------------------------

    @staticmethod
    def _is_cuda_runtime_error(exc: BaseException) -> bool:
        message = str(exc).lower()
        markers = (
            "cublas64_12.dll",
            "cublaslt64_12.dll",
            "cudnn64_9.dll",
            "cudnn64_8.dll",
            "libcublas.so",
            "libcudnn.so",
            "cuda runtime",
            "cuda driver",
            "cuda error",
        )
        return any(marker in message for marker in markers)

    def _load_whisper_model(self, *, device: str, compute_type: str) -> Any:
        from faster_whisper import WhisperModel  # type: ignore

        logger.info(
            "Loading faster-whisper STT: model=%s device=%s compute_type=%s",
            self.whisper_model_name,
            device,
            compute_type,
        )
        model = WhisperModel(
            self.whisper_model_name,
            device=device,
            compute_type=compute_type,
        )
        self._whisper_model = model
        self._whisper_loaded_device = device
        self._whisper_loaded_compute_type = compute_type
        return model

    def _load_cpu_whisper_model(self) -> Any:
        if not _package_available("faster_whisper"):
            raise VoiceUnavailableError(
                "Local transcription is unavailable because faster-whisper is not installed."
            )

        with self._whisper_lock:
            if (
                self._whisper_model is not None
                and self._whisper_loaded_device == "cpu"
                and self._whisper_loaded_compute_type == "int8"
            ):
                return self._whisper_model

            # Drop the unusable CUDA/auto model before constructing the CPU
            # runtime.  The old object will be collected once no transcription
            # call still references it.
            self._whisper_model = None
            self._whisper_loaded_device = None
            self._whisper_loaded_compute_type = None

            return self._load_whisper_model(device="cpu", compute_type="int8")

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

            device = self.stt_device
            compute_type = self.stt_compute_type

            try:
                return self._load_whisper_model(
                    device=device,
                    compute_type=compute_type,
                )
            except Exception as exc:
                if device == "cpu" and compute_type == "int8":
                    raise VoiceUnavailableError(
                        f"Could not initialise local speech recognition on CPU: {exc}"
                    ) from exc

                logger.warning(
                    "Could not initialise faster-whisper with device=%s compute_type=%s; "
                    "falling back to cpu/int8: %s",
                    device,
                    compute_type,
                    exc,
                )

                self._whisper_model = None
                self._whisper_loaded_device = None
                self._whisper_loaded_compute_type = None
                try:
                    return self._load_whisper_model(
                        device="cpu",
                        compute_type="int8",
                    )
                except Exception as cpu_exc:
                    raise VoiceUnavailableError(
                        f"Could not initialise local speech recognition on CPU: {cpu_exc}"
                    ) from cpu_exc

    @staticmethod
    def _run_whisper_transcription(model: Any, path: Path) -> tuple[list[Any], Any]:
        # Push-to-talk clips are short, single-speaker and already noise
        # suppressed by the browser capture chain. Greedy decoding is roughly
        # twice as fast as beam_size=5 with no practical accuracy loss here,
        # and previous-text conditioning only adds work for a one-shot clip.
        transcribe_kwargs: dict[str, Any] = {
            "beam_size": max(1, int(settings.voice_stt_beam_size)),
            "condition_on_previous_text": bool(
                settings.voice_stt_condition_on_previous_text
            ),
            "without_timestamps": True,
        }

        if settings.voice_stt_vad_filter:
            transcribe_kwargs["vad_filter"] = True
            transcribe_kwargs["vad_parameters"] = {
                "min_silence_duration_ms": max(
                    100, int(settings.voice_stt_vad_min_silence_ms)
                ),
            }

        segments, info = model.transcribe(str(path), **transcribe_kwargs)
        # Faster-Whisper does most inference lazily while this generator is
        # consumed, so CUDA DLL failures can appear here rather than when the
        # WhisperModel object is constructed.
        return list(segments), info

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
                segment_list, info = self._run_whisper_transcription(model, temp_path)
            except Exception as exc:
                # ``device=auto``/CUDA can initialise successfully even when
                # the CUDA 12 runtime DLLs are absent.  CTranslate2 then fails
                # lazily while the segments generator is consumed.  Retry the
                # exact same recording once on CPU/int8 instead of surfacing a
                # cublas/cudnn DLL error to the user.
                if self._is_cuda_runtime_error(exc) and self._whisper_loaded_device != "cpu":
                    logger.warning(
                        "CUDA STT runtime is unavailable (%s). Retrying this recording on cpu/int8.",
                        exc,
                    )
                    try:
                        cpu_model = self._load_cpu_whisper_model()
                        segment_list, info = self._run_whisper_transcription(
                            cpu_model,
                            temp_path,
                        )
                    except Exception as cpu_exc:
                        message = str(cpu_exc)
                        logger.exception(
                            "CPU fallback transcription failed for %s",
                            temp_path,
                        )
                        if (
                            "1094995529" in message
                            or "Invalid data found when processing input" in message
                        ):
                            raise VoiceDecodeError(
                                "The microphone recording was incomplete or corrupt and could not be decoded. "
                                "Hold Home, speak, then release Home and try again."
                            ) from cpu_exc
                        raise VoiceError(
                            f"Audio transcription failed after CPU fallback: {message}"
                        ) from cpu_exc
                else:
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
                    "Jace could not detect speech in that recording. "
                    "Hold Home while you speak, then release it."
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
                    logger.warning(
                        "Could not remove temporary voice file %s",
                        temp_path,
                        exc_info=True,
                    )

    # ------------------------------------------------------------------
    # Text-to-speech: Kokoro ONNX
    # ------------------------------------------------------------------

    def _get_kokoro(self) -> Any:
        ready, reason = self._tts_readiness()
        if not ready:
            raise VoiceUnavailableError(reason or "Local Kokoro speech synthesis is unavailable.")

        model_path = self.kokoro_model_path
        voices_path = self.kokoro_voices_path
        source = (model_path, voices_path)

        if self._kokoro is not None and self._kokoro_loaded_from == source:
            return self._kokoro

        with self._kokoro_lock:
            if self._kokoro is not None and self._kokoro_loaded_from == source:
                return self._kokoro

            try:
                from kokoro_onnx import Kokoro  # type: ignore

                logger.info(
                    "Loading Kokoro TTS: model=%s voices=%s voice=%s language=%s",
                    model_path,
                    voices_path,
                    self.tts_voice,
                    self.tts_language,
                )
                runtime = Kokoro(str(model_path), str(voices_path))

                get_voices = getattr(runtime, "get_voices", None)
                if callable(get_voices):
                    available_voices = set(get_voices())
                    if self.tts_voice not in available_voices:
                        raise VoiceUnavailableError(
                            f"Configured Kokoro voice '{self.tts_voice}' is not present in "
                            f"{voices_path.name}."
                        )

                self._kokoro = runtime
                self._kokoro_loaded_from = source
            except VoiceUnavailableError:
                raise
            except Exception as exc:
                logger.exception("Could not initialise Kokoro ONNX")
                raise VoiceUnavailableError(
                    "Kokoro is installed and its model files exist, but the runtime could not initialise: "
                    f"{exc}"
                ) from exc

        return self._kokoro

    @staticmethod
    def _samples_to_wav(samples: Any, sample_rate: int) -> bytes:
        try:
            import numpy as np  # type: ignore
        except ImportError as exc:
            raise VoiceUnavailableError(
                "Kokoro requires NumPy, but NumPy is not installed in Jace's backend environment."
            ) from exc

        audio = np.asarray(samples, dtype=np.float32).reshape(-1)
        if audio.size == 0:
            raise VoiceError("Kokoro returned no audio samples.")

        if not np.isfinite(audio).all():
            audio = np.nan_to_num(audio, nan=0.0, posinf=1.0, neginf=-1.0)

        audio = np.clip(audio, -1.0, 1.0)
        pcm16 = (audio * 32767.0).astype("<i2", copy=False)

        buffer = io.BytesIO()
        with wave.open(buffer, "wb") as wav_file:
            wav_file.setnchannels(1)
            wav_file.setsampwidth(2)
            wav_file.setframerate(int(sample_rate))
            wav_file.writeframes(pcm16.tobytes())

        return buffer.getvalue()

    def synthesize_wav(self, text: str) -> bytes:
        value = text.strip()
        if not value:
            raise VoiceError("There is no text to speak.")
        if len(value) > 20_000:
            raise VoiceError("The requested speech is too long for one local voice response.")

        kokoro = self._get_kokoro()

        try:
            # Keep inference serial. It avoids competing local ONNX sessions when
            # a welcome line and an assistant reply arrive at nearly the same time.
            with self._tts_inference_lock:
                samples, sample_rate = kokoro.create(
                    value,
                    voice=self.tts_voice,
                    speed=self.tts_speed,
                    lang=self.tts_language,
                )
        except VoiceError:
            raise
        except Exception as exc:
            logger.exception("Kokoro speech synthesis failed")
            raise VoiceError(f"Kokoro speech synthesis failed: {exc}") from exc

        data = self._samples_to_wav(samples, int(sample_rate))
        if len(data) <= 44:
            raise VoiceError("Kokoro returned an empty WAV file.")
        return data

    # ------------------------------------------------------------------
    # Warm-up
    # ------------------------------------------------------------------

    def warm_stt(self) -> None:
        """Load the faster-whisper model. Safe to call repeatedly."""
        self._get_whisper_model()

    def warm_tts(self) -> None:
        """Load Kokoro and run one tiny synthesis.

        Constructing the ONNX session is only part of the first-call cost: the
        first `create()` also builds the phoniser state. Doing both here keeps
        the first real spoken reply from stalling for several seconds.
        """
        kokoro = self._get_kokoro()

        try:
            with self._tts_inference_lock:
                kokoro.create(
                    "Ready.",
                    voice=self.tts_voice,
                    speed=self.tts_speed,
                    lang=self.tts_language,
                )
        except Exception as exc:
            logger.warning("Kokoro warm-up synthesis did not complete: %s", exc)


voice_service = VoiceService()


# ----------------------------------------------------------------------
# Module-level compatibility helpers for earlier Phase 10B imports.
# ----------------------------------------------------------------------


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
