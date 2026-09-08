"""Download the optional local faster-whisper model used by Jace Phase 7.

Run explicitly from the backend directory:
    python .\\scripts\\install_audio_model.py

The normal Jace runtime is configured with local_files_only=True and will not
silently download this model on first use.
"""
from __future__ import annotations

import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from jace.config import settings


def main() -> int:
    if not settings.audio_enabled:
        print("Audio transcription is disabled in Jace configuration.")
        return 1

    try:
        from faster_whisper import WhisperModel
    except ImportError:
        print("faster-whisper is not installed. Run: python -m pip install -r requirements.txt")
        return 1

    print(f"Downloading/preparing faster-whisper model: {settings.audio_model}")
    print("This is an explicit one-time network download into the local model cache.")
    try:
        WhisperModel(
            settings.audio_model,
            device=settings.audio_device,
            compute_type=settings.audio_compute_type,
            download_root=str(settings.audio_download_root),
            local_files_only=False,
        )
    except Exception as exc:
        print(f"Could not install the audio model: {exc}")
        return 1

    print("PASS: local Whisper model is available to Jace.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
