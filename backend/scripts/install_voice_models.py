"""Explicitly install the local Kokoro model files used by Jace Phase 10B.

Run from C:\\Users\\Ben\\jace\\backend:
    python .\\scripts\\install_voice_models.py

This script performs an explicit network download into Jace's local data folder.
The normal Jace runtime never silently downloads TTS model files.
"""
from __future__ import annotations

import hashlib
import sys
import urllib.request
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from jace.config import settings

MODEL_URL = "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/kokoro-v1.0.onnx"
VOICES_URL = "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/voices-v1.0.bin"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def download(url: str, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists() and destination.stat().st_size > 1_000_000:
        print(f"Already present: {destination}")
        return

    partial = destination.with_suffix(destination.suffix + ".part")
    partial.unlink(missing_ok=True)
    print(f"Downloading {destination.name} ...")
    with urllib.request.urlopen(url, timeout=60) as response, partial.open("wb") as output:
        total = int(response.headers.get("Content-Length") or 0)
        downloaded = 0
        while True:
            chunk = response.read(1024 * 1024)
            if not chunk:
                break
            output.write(chunk)
            downloaded += len(chunk)
            if total:
                print(f"  {downloaded / total * 100:5.1f}%", end="\r")
    print(" " * 20, end="\r")
    partial.replace(destination)
    print(f"Saved {destination} ({destination.stat().st_size / 1024 / 1024:.1f} MB)")
    print(f"SHA-256: {sha256(destination)}")


def main() -> int:
    print("Jace Phase 10B local voice model installer")
    print("These files stay local under data\\voice\\kokoro.")
    try:
        download(MODEL_URL, settings.voice_kokoro_model_path)
        download(VOICES_URL, settings.voice_kokoro_voices_path)
    except Exception as exc:
        print(f"Could not download Kokoro model files: {exc}")
        return 1

    print("PASS: Kokoro model and voice files are installed locally.")
    print("If TTS reports an eSpeak error on Windows, install eSpeak NG with:")
    print("  winget install --id eSpeak-NG.eSpeak-NG -e")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
