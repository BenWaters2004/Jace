from __future__ import annotations

import argparse
import os
import sys
import tempfile
import urllib.error
import urllib.request
from pathlib import Path


BACKEND_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = BACKEND_ROOT.parent
KOKORO_DIR = PROJECT_ROOT / "data" / "voice" / "kokoro"

MODEL_URL = (
    "https://github.com/thewh1teagle/kokoro-onnx/releases/download/"
    "model-files-v1.1/kokoro-v1.0.onnx"
)
VOICES_URL = (
    "https://github.com/thewh1teagle/kokoro-onnx/releases/download/"
    "model-files-v1.1/voices-v1.0.bin"
)

MODEL_PATH = KOKORO_DIR / "kokoro-v1.0.onnx"
VOICES_PATH = KOKORO_DIR / "voices-v1.0.bin"

MIN_MODEL_BYTES = 10 * 1024 * 1024
MIN_VOICES_BYTES = 1 * 1024 * 1024


def _human_size(size: int) -> str:
    value = float(size)
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            return f"{value:.1f} {unit}"
        value /= 1024
    return f"{size} B"


def _valid_existing(path: Path, minimum: int) -> bool:
    return path.is_file() and path.stat().st_size >= minimum


def _download(url: str, destination: Path, minimum: int, *, force: bool) -> None:
    if not force and _valid_existing(destination, minimum):
        print(f"[OK] {destination.name} already exists ({_human_size(destination.stat().st_size)}).")
        return

    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(
        prefix=f".{destination.name}.",
        suffix=".part",
        dir=destination.parent,
    )
    os.close(fd)
    temp_path = Path(temp_name)

    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Jace-Voice-Installer/10B",
            "Accept": "application/octet-stream",
        },
    )

    try:
        print(f"[DOWNLOAD] {destination.name}")
        print(f"           {url}")
        with urllib.request.urlopen(request, timeout=60) as response, temp_path.open("wb") as output:
            total_header = response.headers.get("Content-Length")
            total = int(total_header) if total_header and total_header.isdigit() else None
            copied = 0
            last_percent = -1

            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                output.write(chunk)
                copied += len(chunk)

                if total:
                    percent = int((copied / total) * 100)
                    if percent >= last_percent + 5 or percent == 100:
                        print(
                            f"           {percent:3d}%  "
                            f"{_human_size(copied)} / {_human_size(total)}"
                        )
                        last_percent = percent
                elif copied % (25 * 1024 * 1024) < len(chunk):
                    print(f"           {_human_size(copied)}")

        size = temp_path.stat().st_size
        if size < minimum:
            raise RuntimeError(
                f"Downloaded {destination.name} is unexpectedly small "
                f"({_human_size(size)}; expected at least {_human_size(minimum)})."
            )

        temp_path.replace(destination)
        print(f"[OK] {destination} ({_human_size(size)})")
    except (urllib.error.URLError, TimeoutError, OSError, RuntimeError) as exc:
        raise RuntimeError(f"Could not download {destination.name}: {exc}") from exc
    finally:
        temp_path.unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Install the local Kokoro ONNX model files used by Jace voice synthesis."
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-download model files even when valid files already exist.",
    )
    args = parser.parse_args()

    print("Jace Kokoro voice model installer")
    print(f"Project: {PROJECT_ROOT}")
    print(f"Target : {KOKORO_DIR}")
    print()

    try:
        _download(MODEL_URL, MODEL_PATH, MIN_MODEL_BYTES, force=args.force)
        _download(VOICES_URL, VOICES_PATH, MIN_VOICES_BYTES, force=args.force)
    except RuntimeError as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 1

    print()
    print("Kokoro model files are ready:")
    print(f"  model : {MODEL_PATH}")
    print(f"  voices: {VOICES_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
