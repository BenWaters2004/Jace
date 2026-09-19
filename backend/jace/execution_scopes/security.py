from __future__ import annotations

from pathlib import (
    PurePosixPath,
    PureWindowsPath,
)

from jace.tools.base import ToolError


def _looks_windows(
    value: str,
) -> bool:
    path = PureWindowsPath(
        value
    )

    return bool(
        path.drive
        or value.startswith("\\\\")
    )


def validate_relative_cwd(
    value: str | None,
) -> str:
    raw = str(
        value
        or "."
    ).strip()

    if not raw:
        raw = "."

    windows = PureWindowsPath(
        raw
    )
    posix = PurePosixPath(
        raw
    )

    if (
        windows.is_absolute()
        or posix.is_absolute()
        or windows.drive
    ):
        raise ToolError(
            "Execution working directory must be relative to the "
            "approved execution scope."
        )

    parts = (
        windows.parts
        if "\\" in raw
        else posix.parts
    )

    if any(
        part == ".."
        for part in parts
    ):
        raise ToolError(
            "Execution working directory cannot escape its approved scope."
        )

    return raw


def device_scoped_path(
    root_path: str,
    relative_cwd: str | None,
) -> str:
    relative = validate_relative_cwd(
        relative_cwd
    )

    if _looks_windows(
        root_path
    ):
        root = PureWindowsPath(
            root_path
        )
        target = (
            root
            if relative == "."
            else root
            / PureWindowsPath(
                relative
            )
        )
    else:
        root = PurePosixPath(
            root_path
        )
        target = (
            root
            if relative == "."
            else root
            / PurePosixPath(
                relative
            )
        )

    return str(
        target
    )
