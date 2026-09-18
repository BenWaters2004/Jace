from __future__ import annotations

# JACE_STEP4B1_FILESYSTEM_INTELLIGENCE_CORE

from dataclasses import dataclass
from datetime import datetime, timezone
import fnmatch
import json
from pathlib import Path
from typing import Any, Iterable

from jace.computer.security import (
    is_sensitive_relative_path,
    relative_display,
)


# Dependency/build/cache trees are intentionally excluded from "project-owned"
# intelligence. The low-level Phase 6 file tools can still access them by
# explicit path when the workspace security policy allows it.
DEFAULT_PRUNED_DIRECTORIES = {
    ".git",
    ".hg",
    ".svn",
    ".idea",
    ".vscode",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".tox",
    ".nox",
    ".next",
    ".nuxt",
    ".svelte-kit",
    ".turbo",
    ".cache",
    "__pycache__",
    "node_modules",
    "bower_components",
    "vendor",
    "venv",
    ".venv",
    "env",
    ".envdir",
    "dist",
    "build",
    "out",
    "target",
    "coverage",
    ".coverage",
    "bin",
    "obj",
}

DEFAULT_SKIPPED_FILES = {
    ".ds_store",
    "thumbs.db",
    "desktop.ini",
}

BINARY_OR_ARCHIVE_EXTENSIONS = {
    ".7z",
    ".a",
    ".avi",
    ".bin",
    ".bmp",
    ".class",
    ".dll",
    ".dmg",
    ".doc",
    ".docx",
    ".exe",
    ".flac",
    ".gif",
    ".gz",
    ".ico",
    ".iso",
    ".jar",
    ".jpeg",
    ".jpg",
    ".lockb",
    ".mov",
    ".mp3",
    ".mp4",
    ".o",
    ".obj",
    ".onnx",
    ".pdf",
    ".png",
    ".ppt",
    ".pptx",
    ".pyc",
    ".rar",
    ".so",
    ".tar",
    ".tiff",
    ".ttf",
    ".wav",
    ".webm",
    ".webp",
    ".woff",
    ".woff2",
    ".xls",
    ".xlsx",
    ".xz",
    ".zip",
}

LANGUAGE_BY_EXTENSION = {
    ".astro": "Astro",
    ".bash": "Shell",
    ".c": "C",
    ".cc": "C++",
    ".cpp": "C++",
    ".cs": "C#",
    ".css": "CSS",
    ".dart": "Dart",
    ".go": "Go",
    ".h": "C/C++ Header",
    ".hpp": "C++ Header",
    ".html": "HTML",
    ".java": "Java",
    ".js": "JavaScript",
    ".jsx": "JavaScript React",
    ".json": "JSON",
    ".kt": "Kotlin",
    ".kts": "Kotlin",
    ".lua": "Lua",
    ".md": "Markdown",
    ".php": "PHP",
    ".ps1": "PowerShell",
    ".py": "Python",
    ".rb": "Ruby",
    ".rs": "Rust",
    ".scss": "SCSS",
    ".sh": "Shell",
    ".sql": "SQL",
    ".svelte": "Svelte",
    ".swift": "Swift",
    ".toml": "TOML",
    ".ts": "TypeScript",
    ".tsx": "TypeScript React",
    ".vue": "Vue",
    ".xml": "XML",
    ".yaml": "YAML",
    ".yml": "YAML",
}

PROJECT_MARKERS = [
    ("package.json", "Node / JavaScript"),
    ("vite.config.js", "Vite"),
    ("vite.config.ts", "Vite"),
    ("next.config.js", "Next.js"),
    ("next.config.mjs", "Next.js"),
    ("next.config.ts", "Next.js"),
    ("pyproject.toml", "Python"),
    ("requirements.txt", "Python"),
    ("Pipfile", "Python"),
    ("poetry.lock", "Python"),
    ("uv.lock", "Python"),
    ("composer.json", "PHP / Composer"),
    ("artisan", "Laravel"),
    ("Cargo.toml", "Rust"),
    ("go.mod", "Go"),
    ("pom.xml", "Java / Maven"),
    ("build.gradle", "Java / Gradle"),
    ("build.gradle.kts", "Kotlin / Gradle"),
    ("Gemfile", "Ruby"),
    ("pubspec.yaml", "Dart / Flutter"),
]

PACKAGE_MANAGER_MARKERS = {
    "package-lock.json": "npm",
    "npm-shrinkwrap.json": "npm",
    "pnpm-lock.yaml": "pnpm",
    "yarn.lock": "Yarn",
    "bun.lock": "Bun",
    "bun.lockb": "Bun",
    "Pipfile.lock": "Pipenv",
    "poetry.lock": "Poetry",
    "uv.lock": "uv",
    "composer.lock": "Composer",
    "Cargo.lock": "Cargo",
    "go.sum": "Go modules",
    "Gemfile.lock": "Bundler",
}


@dataclass(slots=True)
class WorkspaceScan:
    files: list[Path]
    directories: list[Path]
    files_scanned: int
    directories_pruned: int
    scan_limit_reached: bool


def utc_iso_from_timestamp(value: float) -> str:
    return datetime.fromtimestamp(
        value,
        tz=timezone.utc,
    ).isoformat()


def language_for_path(path: Path) -> str | None:
    return LANGUAGE_BY_EXTENSION.get(
        path.suffix.casefold()
    )


def is_probably_binary(path: Path) -> bool:
    return (
        path.suffix.casefold()
        in BINARY_OR_ARCHIVE_EXTENSIONS
    )


def should_skip_relative(
    relative: Path,
) -> bool:
    if is_sensitive_relative_path(relative):
        return True

    if relative.name.casefold() in DEFAULT_SKIPPED_FILES:
        return True

    return False


def should_prune_directory_name(
    name: str,
) -> bool:
    return name.casefold() in {
        value.casefold()
        for value in DEFAULT_PRUNED_DIRECTORIES
    }


def scan_workspace(
    root: Path,
    *,
    base: Path | None = None,
    max_files: int = 5000,
    max_depth: int | None = None,
    include_hidden: bool = False,
) -> WorkspaceScan:
    start = base or root
    files: list[Path] = []
    directories: list[Path] = []
    files_scanned = 0
    directories_pruned = 0
    scan_limit_reached = False

    pending: list[tuple[Path, int]] = [
        (
            start,
            0,
        )
    ]

    while pending:
        current, depth = pending.pop()

        try:
            children = sorted(
                current.iterdir(),
                key=lambda item: (
                    not item.is_dir(),
                    item.name.casefold(),
                ),
            )
        except OSError:
            continue

        for child in children:
            try:
                relative = child.relative_to(
                    root
                )
            except ValueError:
                continue

            try:
                if child.is_symlink():
                    directories_pruned += 1
                    continue
            except OSError:
                continue

            if (
                not include_hidden
                and any(
                    part.startswith(".")
                    and part not in {".", ".."}
                    for part in relative.parts
                )
            ):
                if child.is_dir():
                    directories_pruned += 1
                continue

            if should_skip_relative(
                relative
            ):
                if child.is_dir():
                    directories_pruned += 1
                continue

            try:
                is_dir = child.is_dir()
            except OSError:
                continue

            if is_dir:
                if should_prune_directory_name(
                    child.name
                ):
                    directories_pruned += 1
                    continue

                directories.append(
                    child
                )

                if (
                    max_depth is None
                    or depth + 1 < max_depth
                ):
                    pending.append(
                        (
                            child,
                            depth + 1,
                        )
                    )
                continue

            files_scanned += 1

            if files_scanned > max_files:
                scan_limit_reached = True
                return WorkspaceScan(
                    files=files,
                    directories=directories,
                    files_scanned=max_files,
                    directories_pruned=directories_pruned,
                    scan_limit_reached=True,
                )

            files.append(
                child
            )

    return WorkspaceScan(
        files=files,
        directories=directories,
        files_scanned=files_scanned,
        directories_pruned=directories_pruned,
        scan_limit_reached=scan_limit_reached,
    )


def detect_project_markers(
    root: Path,
) -> dict[str, Any]:
    detected_types: list[str] = []
    manifests: list[str] = []

    for name, project_type in PROJECT_MARKERS:
        path = root / name

        if path.exists():
            manifests.append(
                name
            )
            if (
                project_type
                not in detected_types
            ):
                detected_types.append(
                    project_type
                )

    # Detect common .NET project/solution markers without a full recursive scan.
    try:
        top_files = list(
            root.iterdir()
        )
    except OSError:
        top_files = []

    if any(
        item.is_file()
        and item.suffix.casefold()
        in {".sln", ".csproj"}
        for item in top_files
    ):
        detected_types.append(
            ".NET"
        )
        manifests.extend(
            sorted(
                item.name
                for item in top_files
                if item.is_file()
                and item.suffix.casefold()
                in {".sln", ".csproj"}
            )
        )

    package_managers = [
        label
        for marker, label
        in PACKAGE_MANAGER_MARKERS.items()
        if (
            root
            / marker
        ).exists()
    ]

    return {
        "project_types":
            detected_types,
        "manifests":
            sorted(
                set(
                    manifests
                )
            ),
        "package_managers":
            sorted(
                set(
                    package_managers
                )
            ),
    }


def git_summary(
    root: Path,
) -> dict[str, Any]:
    git_entry = root / ".git"

    if not git_entry.exists():
        return {
            "is_git_repository":
                False,
            "branch":
                None,
        }

    if git_entry.is_symlink():
        return {
            "is_git_repository":
                True,
            "branch":
                None,
        }

    git_dir = git_entry

    if git_entry.is_file():
        try:
            line = git_entry.read_text(
                encoding="utf-8",
                errors="replace",
            ).strip()
        except OSError:
            line = ""

        prefix = "gitdir:"

        if line.casefold().startswith(
            prefix
        ):
            raw = line[
                len(
                    prefix
                ):
            ].strip()
            candidate = Path(
                raw
            )

            if not candidate.is_absolute():
                candidate = (
                    root
                    / candidate
                )

            try:
                resolved_candidate = candidate.resolve(
                    strict=True
                )
                resolved_candidate.relative_to(
                    root.resolve(
                        strict=True
                    )
                )
                git_dir = resolved_candidate
            except (
                OSError,
                ValueError,
            ):
                # Worktree metadata may live outside the approved workspace.
                # Do not cross that boundary merely to discover a branch.
                return {
                    "is_git_repository":
                        True,
                    "branch":
                        None,
                }

    head = git_dir / "HEAD"

    try:
        value = head.read_text(
            encoding="utf-8",
            errors="replace",
        ).strip()
    except OSError:
        return {
            "is_git_repository":
                True,
            "branch":
                None,
        }

    if value.startswith(
        "ref: refs/heads/"
    ):
        branch = value[
            len(
                "ref: refs/heads/"
            ):
        ]
    elif value:
        branch = (
            "detached"
        )
    else:
        branch = None

    return {
        "is_git_repository":
            True,
        "branch":
            branch,
    }


def language_statistics(
    files: Iterable[Path],
) -> list[dict[str, Any]]:
    counts: dict[
        str,
        dict[str, int],
    ] = {}

    for path in files:
        language = language_for_path(
            path
        )

        if language is None:
            continue

        row = counts.setdefault(
            language,
            {
                "files":
                    0,
                "bytes":
                    0,
            },
        )
        row[
            "files"
        ] += 1

        try:
            row[
                "bytes"
            ] += path.stat().st_size
        except OSError:
            pass

    result = [
        {
            "language":
                language,
            "files":
                row[
                    "files"
                ],
            "bytes":
                row[
                    "bytes"
                ],
        }
        for language, row
        in counts.items()
    ]

    return sorted(
        result,
        key=lambda item: (
            -item[
                "files"
            ],
            item[
                "language"
            ].casefold(),
        ),
    )


def tree_entries(
    root: Path,
    base: Path,
    *,
    max_depth: int,
    max_entries: int,
    include_hidden: bool,
    files_only: bool = False,
) -> tuple[
    list[dict[str, Any]],
    bool,
    int,
]:
    result: list[
        dict[str, Any]
    ] = []
    pruned = 0
    pending: list[
        tuple[
            Path,
            int,
        ]
    ] = [
        (
            base,
            0,
        )
    ]

    while pending:
        current, depth = pending.pop()

        if depth >= max_depth:
            continue

        try:
            children = sorted(
                current.iterdir(),
                key=lambda item: (
                    not item.is_dir(),
                    item.name.casefold(),
                ),
                reverse=True,
            )
        except OSError:
            continue

        for child in children:
            try:
                relative = child.relative_to(
                    root
                )
            except ValueError:
                continue

            try:
                if child.is_symlink():
                    pruned += 1
                    continue
            except OSError:
                continue

            if (
                not include_hidden
                and any(
                    part.startswith(".")
                    for part in relative.parts
                )
            ):
                if child.is_dir():
                    pruned += 1
                continue

            if should_skip_relative(
                relative
            ):
                if child.is_dir():
                    pruned += 1
                continue

            try:
                is_dir = child.is_dir()
            except OSError:
                continue

            if (
                is_dir
                and should_prune_directory_name(
                    child.name
                )
            ):
                pruned += 1
                continue

            if (
                not files_only
                or not is_dir
            ):
                item: dict[str, Any] = {
                    "path":
                        str(
                            relative
                        ),
                    "type":
                        (
                            "directory"
                            if is_dir
                            else "file"
                        ),
                    "depth":
                        len(
                            relative.parts
                        )
                        - len(
                            base.relative_to(
                                root
                            ).parts
                        ),
                }

                if not is_dir:
                    try:
                        stat = child.stat()
                        item[
                            "size"
                        ] = stat.st_size
                        item[
                            "modified"
                        ] = utc_iso_from_timestamp(
                            stat.st_mtime
                        )
                    except OSError:
                        pass

                    language = language_for_path(
                        child
                    )

                    if language:
                        item[
                            "language"
                        ] = language

                result.append(
                    item
                )

                if len(
                    result
                ) >= max_entries:
                    return (
                        result,
                        True,
                        pruned,
                    )

            if is_dir:
                pending.append(
                    (
                        child,
                        depth + 1,
                    )
                )

    return (
        result,
        False,
        pruned,
    )


def matches_path_filters(
    relative: str,
    *,
    pattern: str | None,
    extension: str | None,
    language: str | None,
) -> bool:
    normalised = relative.replace(
        "\\",
        "/",
    )

    if (
        pattern
        and not fnmatch.fnmatch(
            normalised.casefold(),
            pattern.casefold(),
        )
        and not fnmatch.fnmatch(
            Path(
                normalised
            ).name.casefold(),
            pattern.casefold(),
        )
    ):
        return False

    if extension:
        wanted = extension.casefold()

        if not wanted.startswith(
            "."
        ):
            wanted = (
                "."
                + wanted
            )

        if (
            Path(
                relative
            ).suffix.casefold()
            != wanted
        ):
            return False

    if language:
        detected = language_for_path(
            Path(
                relative
            )
        )

        if (
            detected is None
            or detected.casefold()
            != language.casefold()
        ):
            return False

    return True
