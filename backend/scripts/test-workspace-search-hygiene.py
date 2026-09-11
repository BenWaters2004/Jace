from __future__ import annotations

import sys
from pathlib import Path

# Running this file directly from backend/scripts places that directory on
# sys.path, not the backend project root. Add backend explicitly so `jace`
# imports exactly as it does when the application runs.
BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from jace.tools import computer


def assert_true(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def _get_search_pruned_dirs() -> set[str]:
    value = getattr(computer, "_SEARCH_PRUNED_DIR_NAMES", None)
    if value is None:
        raise AssertionError(
            "computer.py does not expose _SEARCH_PRUNED_DIR_NAMES. "
            "The 11B.4.13 search-hygiene patch may not be installed."
        )
    return {str(item).casefold() for item in value}


def _get_search_skipped_suffixes() -> set[str]:
    # 11B.4.13 uses _SEARCH_SKIPPED_FILE_SUFFIXES. Keep the fallback so this
    # regression test remains useful if an earlier internal name is present.
    value = getattr(computer, "_SEARCH_SKIPPED_FILE_SUFFIXES", None)
    if value is None:
        value = getattr(computer, "_SEARCH_SKIPPED_SUFFIXES", None)

    if value is None:
        raise AssertionError(
            "computer.py does not expose _SEARCH_SKIPPED_FILE_SUFFIXES. "
            "The 11B.4.13 search-hygiene patch may not be installed."
        )

    return {str(item).casefold() for item in value}


def main() -> None:
    pruned = _get_search_pruned_dirs()
    skipped_suffixes = _get_search_skipped_suffixes()

    # Common generated/dependency trees should be pruned during normal
    # recursive workspace searches.
    for name in {
        "node_modules",
        ".venv",
        "venv",
        "__pycache__",
        ".next",
        ".nuxt",
        ".turbo",
        "dist",
        "build",
        "coverage",
        "target",
        "out",
        "bower_components",
        "jspm_packages",
    }:
        assert_true(
            name.casefold() in pruned,
            f"Expected generated/dependency directory to be pruned: {name}",
        )

    # Ambiguous / ordinary first-party directory names must remain searchable.
    for name in {
        "vendor",
        "src",
        "backend",
        "frontend",
        "app",
        "apps",
        "lib",
        "packages",
    }:
        assert_true(
            name.casefold() not in pruned,
            f"Ordinary/ambiguous project directory was incorrectly pruned: {name}",
        )

    # Obvious binary/media/model/archive files should not consume the bounded
    # workspace text-search scan budget.
    for suffix in {
        ".png",
        ".jpg",
        ".jpeg",
        ".gif",
        ".webp",
        ".ico",
        ".mp3",
        ".wav",
        ".mp4",
        ".woff",
        ".woff2",
        ".ttf",
        ".zip",
        ".7z",
        ".exe",
        ".dll",
        ".sqlite",
        ".db",
        ".onnx",
    }:
        assert_true(
            suffix.casefold() in skipped_suffixes,
            f"Expected binary suffix to be skipped by workspace text search: {suffix}",
        )

    # Normal source/config/document file types must remain searchable.
    for suffix in {
        ".py",
        ".ts",
        ".tsx",
        ".js",
        ".jsx",
        ".php",
        ".rs",
        ".java",
        ".cs",
        ".go",
        ".html",
        ".css",
        ".json",
        ".yaml",
        ".yml",
        ".toml",
        ".md",
        ".sql",
    }:
        assert_true(
            suffix.casefold() not in skipped_suffixes,
            f"Searchable project file type was incorrectly excluded: {suffix}",
        )

    print(
        "PASS: 11B.4.13 workspace search prunes dependency/generated trees, "
        "skips obvious binary assets, and keeps ordinary project directories searchable."
    )


if __name__ == "__main__":
    main()
