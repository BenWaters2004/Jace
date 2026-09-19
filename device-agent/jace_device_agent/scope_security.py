from __future__ import annotations

import os
from pathlib import Path


def resolve_scoped_cwd(
    cwd: str | None,
    scope_root: str | None,
) -> str | None:
    if scope_root is None:
        if cwd is None:
            return None

        target = Path(
            os.path.expandvars(
                os.path.expanduser(
                    cwd
                )
            )
        ).resolve()

        if not target.is_dir():
            raise ValueError(
                f"Working directory does not exist: {target}"
            )

        return str(
            target
        )

    root = Path(
        os.path.expandvars(
            os.path.expanduser(
                scope_root
            )
        )
    ).resolve()

    if not root.is_dir():
        raise ValueError(
            f"Execution scope root does not exist: {root}"
        )

    target = (
        root
        if cwd is None
        else Path(
            os.path.expandvars(
                os.path.expanduser(
                    cwd
                )
            )
        ).resolve()
    )

    if not target.is_dir():
        raise ValueError(
            f"Working directory does not exist: {target}"
        )

    try:
        common = os.path.commonpath(
            [
                os.path.normcase(
                    str(
                        root
                    )
                ),
                os.path.normcase(
                    str(
                        target
                    )
                ),
            ]
        )
    except ValueError as exc:
        raise ValueError(
            "Working directory is outside the approved execution scope."
        ) from exc

    if os.path.normcase(
        common
    ) != os.path.normcase(
        str(
            root
        )
    ):
        raise ValueError(
            "Working directory resolved outside the approved execution scope."
        )

    return str(
        target
    )
