"""Jace Phase 10B voice/presence release smoke checks.

This script intentionally does not require microphone hardware, Kokoro model
files or the optional Whisper model to be installed. It validates the local
voice architecture and release configuration before live Windows testing.
"""
from __future__ import annotations

import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = BACKEND_ROOT.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from jace.ai.prompts import DEFAULT_SYSTEM_PROMPT, VOICE_RESPONSE_STYLE
from jace.config import settings
from jace.db.models import Base
from jace.voice.service import _clean_for_speech, curated_voices, get_voice_runtime_status


def require(condition: bool, label: str) -> None:
    if not condition:
        raise AssertionError(label)
    print(f"PASS: {label}")


def main() -> int:
    print(f"Jace version: {settings.app_version}")
    require(settings.app_version == "0.10.0-beta.1", "version is 0.10.0-beta.1")
    require(settings.ollama_keep_alive == "-1m", "Ollama keep_alive regression remains fixed")
    require(settings.voice_enabled is True, "local voice is enabled by default")
    require(settings.voice_default_voice == "bm_lewis", "default voice is bm_lewis")
    require(settings.voice_default_language == "en-gb", "default voice language is British English")
    require(settings.voice_recording_max_bytes <= 25_000_000, "push-to-talk recording size is bounded")
    require("data" in str(settings.audio_download_root).lower() and "voice" in str(settings.audio_download_root).lower(), "Whisper model cache stays under Jace local data")
    require("voice_settings" in Base.metadata.tables, "voice_settings table is registered additively")

    voices = {item["id"] for item in curated_voices()}
    require("bm_lewis" in voices and "bf_emma" in voices, "curated British Kokoro voices are exposed")

    status = get_voice_runtime_status()
    require("stt_dependency_available" in status, "voice status reports local STT availability")
    require("tts_dependency_available" in status, "voice status reports local TTS availability")
    require("tts_model_files_available" in status, "voice status reports local TTS model files")

    cleaned = _clean_for_speech("## Result\n**Done.** See https://example.com and `engine.py`.\n```python\nprint('skip')\n```")
    require("print" not in cleaned, "fenced code is not read aloud")
    require("https://" not in cleaned, "raw URLs are not read aloud")
    require("engine.py" in cleaned, "short inline technical identifiers remain speakable")

    require("calm, capable" in DEFAULT_SYSTEM_PROMPT.lower(), "Jace personality prompt is preserved for voice")
    require("spoken response mode" in VOICE_RESPONSE_STYLE.lower(), "voice turns use a speech-oriented response style")
    require("another fictional or real assistant" in DEFAULT_SYSTEM_PROMPT.lower(), "Jace keeps his own identity")

    app_source = (PROJECT_ROOT / "apps" / "desktop" / "src" / "App.tsx").read_text(encoding="utf-8")
    controller_source = (PROJECT_ROOT / "apps" / "desktop" / "src" / "voice" / "useVoiceController.ts").read_text(encoding="utf-8")
    approval_source = (PROJECT_ROOT / "apps" / "desktop" / "src" / "voice" / "approval.ts").read_text(encoding="utf-8")
    core_source = (PROJECT_ROOT / "apps" / "desktop" / "src" / "shell" / "JaceCore.tsx").read_text(encoding="utf-8")

    require("classifySpokenApproval" in app_source, "spoken permissions use the dedicated approval classifier")
    require("allow_once" in approval_source and "deny_once" in approval_source, "verbal approval supports one-shot allow and deny")
    require("getUserMedia" in controller_source and "MediaRecorder" in controller_source, "microphone opens only through explicit browser capture")
    require("stopSpeaking();" in controller_source, "push-to-talk interrupts active speech")
    require("transcribeVoiceRecording" in controller_source, "push-to-talk uses local transcription endpoint")
    require("synthesizeVoice" in controller_source, "responses use local synthesis endpoint")
    require("--voice-level" in core_source, "real audio amplitude is passed into the Jace Core")

    # Protect the privacy boundary: no cloud speech provider endpoint or key is
    # wired into the Phase 10B desktop voice path.
    combined = (controller_source + app_source).lower()
    forbidden = ["elevenlabs", "openai.com/v1/audio", "api.deepgram", "assemblyai"]
    require(not any(item in combined for item in forbidden), "desktop voice path has no cloud speech provider")

    print("PASS: Jace Phase 10B local voice & presence checks completed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
