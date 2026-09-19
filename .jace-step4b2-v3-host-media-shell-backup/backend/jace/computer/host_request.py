from __future__ import annotations

# JACE_STEP4B2_V2_HOST_REQUEST_RESOLUTION

import re
from typing import Any


HOST_TOOL_NAMES = {
    "computer_locations",
    "list_host_directory",
    "read_host_file",
    "host_file_info",
    "search_host_files",
    "write_host_file",
    "replace_host_text",
    "move_host_path",
    "delete_host_path",
    "run_shell_command",
}

SAFE_AUTO_HOST_TOOLS = {
    "computer_locations",
    "list_host_directory",
    "read_host_file",
    "host_file_info",
}


_QUOTED_WINDOWS_PATH_RE = re.compile(
    r"[\"'](?P<path>[A-Za-z]:[\\/][^\"']+)[\"']"
)

_QUOTED_UNC_PATH_RE = re.compile(
    r"[\"'](?P<path>\\\\[^\"']+)[\"']"
)

# Deliberately conservative: this fallback only captures a bare Windows/UNC
# path when it occupies the tail of the request. That is enough for common
# requests such as "Show me what's in C:\\Users\\Ben\\Downloads." without
# guessing where a path with spaces ends in more complex prose.
_TAIL_WINDOWS_PATH_RE = re.compile(
    r"(?P<path>[A-Za-z]:[\\/].+?)"
    r"(?P<punct>[.!?;,]*)\s*$"
)

_TAIL_UNC_PATH_RE = re.compile(
    r"(?P<path>\\\\[^\\/\s]+[\\/].+?)"
    r"(?P<punct>[.!?;,]*)\s*$"
)


def extract_explicit_host_path(
    message: str,
) -> str | None:
    text = (
        message
        or ""
    ).strip()

    if not text:
        return None

    for pattern in (
        _QUOTED_WINDOWS_PATH_RE,
        _QUOTED_UNC_PATH_RE,
    ):
        match = pattern.search(
            text
        )

        if match:
            return match.group(
                "path"
            ).strip()

    for pattern in (
        _TAIL_WINDOWS_PATH_RE,
        _TAIL_UNC_PATH_RE,
    ):
        match = pattern.search(
            text
        )

        if match:
            return match.group(
                "path"
            ).strip()

    common_folders = {
        "desktop": "~/Desktop",
        "documents": "~/Documents",
        "downloads": "~/Downloads",
        "pictures": "~/Pictures",
        "videos": "~/Videos",
        "music": "~/Music",
    }

    lowered = text.casefold()

    for name, path in common_folders.items():
        if re.search(
            rf"\b(?:my\s+)?{re.escape(name)}\b",
            lowered,
        ):
            return path

    return None


def host_auto_tool_call(
    selected_tool_names: list[str] | set[str] | tuple[str, ...],
    user_message: str,
) -> dict[str, Any] | None:
    """
    Build only deterministic, read-only host calls.

    Search/write/move/delete/shell operations are intentionally excluded because
    they require arguments or generated commands that must come from the model.
    """
    candidates = sorted(
        set(
            selected_tool_names
        )
        & SAFE_AUTO_HOST_TOOLS
    )

    if len(
        candidates
    ) != 1:
        return None

    name = candidates[
        0
    ]

    if name == "computer_locations":
        arguments: dict[str, Any] = {}
    else:
        path = extract_explicit_host_path(
            user_message
        )

        if not path:
            return None

        arguments = {
            "path":
                path,
        }

    return {
        "type":
            "function",
        "function": {
            "name":
                name,
            "arguments":
                arguments,
        },
    }
