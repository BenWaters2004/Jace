from __future__ import annotations

import fnmatch
import os
from pathlib import Path

from jace.config import settings


class ComputerPathError(ValueError):
    pass


_SENSITIVE_NAMES = {
    ".env",
    ".npmrc",
    ".pypirc",
    "credentials.json",
    "secrets.json",
    "secrets.yaml",
    "secrets.yml",
    "id_rsa",
    "id_ed25519",
    "known_hosts",
    "authorized_keys",
}

_SENSITIVE_PATTERNS = (
    ".env.*",
    "*.pem",
    "*.key",
    "*.p12",
    "*.pfx",
    "*.kdbx",
    "*.ovpn",
    "*.rdp",
)

_SENSITIVE_DIRS = {
    ".ssh",
    ".aws",
    ".azure",
    ".gnupg",
}


def _casefold_parts(path: Path) -> list[str]:
    return [part.casefold() for part in path.parts]


def is_sensitive_relative_path(relative: Path) -> bool:
    if settings.computer_allow_sensitive_files:
        return False

    parts = _casefold_parts(relative)
    if any(part in _SENSITIVE_DIRS for part in parts[:-1]):
        return True

    if not parts:
        return False

    name = parts[-1]
    if name in _SENSITIVE_NAMES:
        return True

    return any(fnmatch.fnmatch(name, pattern.casefold()) for pattern in _SENSITIVE_PATTERNS)


def validate_workspace_root(root_path: str) -> Path:
    raw = root_path.strip().strip('"')
    if not raw:
        raise ComputerPathError("Workspace path cannot be empty.")

    path = Path(raw).expanduser()
    if not path.is_absolute():
        raise ComputerPathError("Workspace path must be an absolute path.")

    try:
        resolved = path.resolve(strict=True)
    except (FileNotFoundError, OSError) as exc:
        raise ComputerPathError("Workspace path does not exist or cannot be accessed.") from exc

    if not resolved.is_dir():
        raise ComputerPathError("Workspace path must point to a directory.")

    return resolved


def _normalise_relative_path(relative_path: str) -> Path:
    text = (relative_path or ".").strip()
    if not text:
        text = "."

    # Reject obvious alternate roots before Path normalisation. This matters on
    # Windows where drive letters and UNC paths can otherwise escape a root.
    if os.path.isabs(text) or text.startswith(("\\\\", "//")):
        raise ComputerPathError("Use a path relative to the configured workspace.")
    if len(text) >= 2 and text[1] == ":":
        raise ComputerPathError("Drive-qualified paths are not allowed inside a workspace tool call.")
    if "\x00" in text:
        raise ComputerPathError("Path contains an invalid null character.")

    relative = Path(text)
    if any(part == ".." for part in relative.parts):
        raise ComputerPathError("Parent-directory traversal is not allowed.")

    return relative


def resolve_workspace_path(
    root_path: str,
    relative_path: str,
    *,
    must_exist: bool = False,
    allow_sensitive: bool = False,
) -> tuple[Path, Path]:
    root = validate_workspace_root(root_path)
    relative = _normalise_relative_path(relative_path)

    if not allow_sensitive and is_sensitive_relative_path(relative):
        raise ComputerPathError("That path is protected as a potentially sensitive credential/configuration file.")

    candidate = root / relative

    try:
        resolved = candidate.resolve(strict=must_exist)
    except (FileNotFoundError, OSError) as exc:
        raise ComputerPathError("The requested workspace path does not exist or cannot be accessed.") from exc

    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise ComputerPathError("The requested path resolves outside the configured workspace.") from exc

    # Re-check the fully resolved relative path. Existing symlinks can otherwise
    # turn a harmless-looking relative path into a sensitive target.
    resolved_relative = resolved.relative_to(root)
    if not allow_sensitive and is_sensitive_relative_path(resolved_relative):
        raise ComputerPathError("That resolved path is protected as sensitive.")

    return root, resolved


def relative_display(root: Path, path: Path) -> str:
    try:
        relative = path.relative_to(root)
    except ValueError:
        return str(path)
    text = str(relative)
    return "." if text in {"", "."} else text
