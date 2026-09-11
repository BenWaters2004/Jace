from __future__ import annotations

import py_compile
import shutil
from pathlib import Path

MARKER = "# 11B.4.13 workspace-search hygiene"

HELPERS = r'''

# 11B.4.13 workspace-search hygiene
#
# Root-level workspace searches should spend their bounded scan budget on the
# user's project rather than dependency caches, generated build outputs, or
# obvious binary assets. These names are ecosystem conventions rather than
# assumptions about any one project layout. If a user explicitly searches with
# path set to one of these directories, files at that selected root are still
# searchable; the pruning only affects recursive child traversal.
_SEARCH_PRUNED_DIR_NAMES = {
    "node_modules",
    "bower_components",
    "jspm_packages",
    "__pycache__",
    ".venv",
    "venv",
    "env",
    ".tox",
    ".nox",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".cache",
    ".next",
    ".nuxt",
    ".turbo",
    "dist",
    "build",
    "coverage",
    "target",
    "out",
    "pods",
    "deriveddata",
}

_SEARCH_SKIPPED_FILE_SUFFIXES = {
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".ico", ".tif", ".tiff",
    ".mp3", ".wav", ".ogg", ".flac", ".m4a", ".aac",
    ".mp4", ".mov", ".avi", ".mkv", ".webm",
    ".woff", ".woff2", ".ttf", ".otf", ".eot",
    ".zip", ".7z", ".rar", ".tar", ".gz", ".bz2", ".xz",
    ".pdf", ".exe", ".dll", ".so", ".dylib", ".pdb",
    ".db", ".sqlite", ".sqlite3", ".onnx", ".bin", ".class", ".jar",
}


def _search_should_prune_dir(name: str) -> bool:
    value = str(name or "").strip()
    if not value:
        return True
    return value.startswith(".") or value.casefold() in _SEARCH_PRUNED_DIR_NAMES


def _search_should_skip_file(name: str) -> bool:
    value = str(name or "").strip()
    if not value:
        return True
    return Path(value).suffix.casefold() in _SEARCH_SKIPPED_FILE_SUFFIXES


def _prune_search_directories(dir_names: list[str]) -> int:
    """Prune noisy recursive trees in-place and return how many were removed."""
    before = len(dir_names)
    dir_names[:] = sorted(
        (name for name in dir_names if not _search_should_prune_dir(name)),
        key=str.casefold,
    )
    return before - len(dir_names)
'''

NEW_FUNCTION = r'''async def search_workspace_files_tool(data: BaseModel, context: ToolContext) -> ToolExecutionResult:
    payload = data
    assert isinstance(payload, SearchWorkspaceFilesInput)
    workspace = await _workspace_for_tool(context, payload.workspace_id)
    root, base = _resolve(workspace, payload.path, must_exist=True)
    if not base.is_dir():
        raise ToolError("Search path must be a directory.")

    query = payload.query.casefold()
    results = []
    scanned = 0
    files_skipped = 0
    directories_pruned = 0

    for current_root, dir_names, file_names in os.walk(base):
        # Keep bounded searches focused on project-owned text/source instead of
        # exhausting the scan limit inside package managers, virtualenvs,
        # generated builds, caches, or similar recursive trees.
        directories_pruned += _prune_search_directories(dir_names)

        for name in sorted(file_names, key=str.casefold):
            if _search_should_skip_file(name):
                files_skipped += 1
                continue
            if scanned >= settings.computer_search_max_files:
                break

            scanned += 1
            candidate = Path(current_root) / name
            try:
                _, candidate = resolve_workspace_path(
                    workspace.root_path,
                    relative_display(root, candidate),
                    must_exist=True,
                )
            except ComputerPathError:
                continue

            relative = relative_display(root, candidate)
            path_match = query in relative.casefold()
            content_match = None
            line_number = None

            if payload.include_content:
                try:
                    if candidate.stat().st_size <= settings.computer_max_read_bytes:
                        text = _read_text(candidate)
                        for index, line in enumerate(text.splitlines(), start=1):
                            if query in line.casefold():
                                line_number = index
                                content_match = line.strip()[:500]
                                break
                except (ToolError, OSError):
                    pass

            if path_match or content_match is not None:
                results.append(
                    {
                        "path": relative,
                        "path_match": path_match,
                        "line": line_number,
                        "snippet": content_match,
                    }
                )
                if len(results) >= min(payload.max_results, settings.computer_search_max_results):
                    break

        if scanned >= settings.computer_search_max_files or len(results) >= payload.max_results:
            break

    scan_limit_reached = scanned >= settings.computer_search_max_files
    return ToolExecutionResult(
        content=json.dumps(
            {
                "workspace": workspace.label,
                "query": payload.query,
                "results": results,
                "files_scanned": scanned,
                "files_skipped": files_skipped,
                "directories_pruned": directories_pruned,
                "scan_limit_reached": scan_limit_reached,
            },
            ensure_ascii=False,
        ),
        display=(
            f"Found {len(results)} matching file result{'s' if len(results) != 1 else ''} in {workspace.label}. "
            f"Scanned {scanned} searchable file{'s' if scanned != 1 else ''}; "
            f"pruned {directories_pruned} generated/dependency director{'ies' if directories_pruned != 1 else 'y'}."
        ),
    )

'''


def apply() -> None:
    backend = Path(__file__).resolve().parents[1]
    target = backend / "jace" / "tools" / "computer.py"
    if not target.exists():
        raise SystemExit(f"Could not find {target}")

    text = target.read_text(encoding="utf-8")
    original = text

    if MARKER not in text:
        anchor = '_TEXT_ENCODINGS = ("utf-8-sig", "utf-8", "cp1252")'
        pos = text.find(anchor)
        if pos < 0:
            raise SystemExit("Could not find _TEXT_ENCODINGS anchor in computer.py; no changes made.")
        insert_at = pos + len(anchor)
        text = text[:insert_at] + HELPERS + text[insert_at:]

    start = text.find("async def search_workspace_files_tool(")
    end = text.find("class CreateWorkspaceDirectoryInput", start)
    if start < 0 or end < 0:
        raise SystemExit("Could not locate search_workspace_files_tool boundaries; no changes made.")

    text = text[:start] + NEW_FUNCTION + text[end:]

    if text == original:
        print("11B.4.13 workspace-search hygiene is already installed.")
    else:
        backup = target.with_suffix(target.suffix + ".11B.4.13.bak")
        if not backup.exists():
            shutil.copy2(target, backup)
        target.write_text(text, encoding="utf-8")
        print(f"Updated {target}")
        print(f"Backup: {backup}")

    py_compile.compile(str(target), doraise=True)
    print("PASS: computer.py compiles after 11B.4.13 workspace-search hygiene patch.")


if __name__ == "__main__":
    apply()
