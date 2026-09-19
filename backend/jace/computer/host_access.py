from __future__ import annotations

# JACE_STEP4B2_FULL_HOST_ACCESS_CORE

import os
import string
from pathlib import Path


class HostPathError(ValueError):
    pass


def expand_host_path(value: str, *, must_exist: bool = False) -> Path:
    text = (value or "").strip().strip('"')
    if "\x00" in text:
        raise HostPathError("Path contains an invalid null character.")

    if not text:
        path = Path.home()
    else:
        expanded = os.path.expandvars(text)
        path = Path(expanded).expanduser()

        if not path.is_absolute():
            path = Path.home() / path

    try:
        resolved = path.resolve(strict=must_exist)
    except (FileNotFoundError, OSError) as exc:
        raise HostPathError(
            "The requested path does not exist or cannot be accessed."
        ) from exc

    return resolved


def available_locations() -> dict:
    home = Path.home()
    result = {
        "home": str(home),
        "cwd": str(Path.cwd().resolve()),
        "desktop": str(home / "Desktop"),
        "documents": str(home / "Documents"),
        "downloads": str(home / "Downloads"),
        "pictures": str(home / "Pictures"),
        "videos": str(home / "Videos"),
        "music": str(home / "Music"),
        "drives": [],
    }

    if os.name == "nt":
        drives = []
        for letter in string.ascii_uppercase:
            candidate = Path(f"{letter}:\\")
            try:
                if candidate.exists():
                    drives.append(str(candidate))
            except OSError:
                continue
        result["drives"] = drives
    else:
        result["drives"] = ["/"]

    return result
