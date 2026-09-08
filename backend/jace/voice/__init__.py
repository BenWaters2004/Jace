"""Public interface for Jace's local voice subsystem."""

from jace.voice.service import (
    MAX_AUDIO_BYTES,
    MIN_AUDIO_BYTES,
    WELCOME_LINE,
    TranscriptionResult,
    VoiceDecodeError,
    VoiceError,
    VoiceRuntimeError,
    VoiceService,
    VoiceUnavailableError,
    get_voice_status,
    synthesize_speech,
    synthesise_speech,
    transcribe_audio,
    transcribe_upload,
    voice_service,
    voice_status,
)

__all__ = [
    "MAX_AUDIO_BYTES",
    "MIN_AUDIO_BYTES",
    "WELCOME_LINE",
    "TranscriptionResult",
    "VoiceDecodeError",
    "VoiceError",
    "VoiceRuntimeError",
    "VoiceService",
    "VoiceUnavailableError",
    "get_voice_status",
    "synthesize_speech",
    "synthesise_speech",
    "transcribe_audio",
    "transcribe_upload",
    "voice_service",
    "voice_status",
]
