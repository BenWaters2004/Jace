"""Phase 0B.4: narrowly correct sample model routes in one Jace documentation file.

Dry-run is the default. --apply edits one documentation file while preserving all
other bytes. No Git commands, runtime configuration, or secret-scanner exclusions.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import os
from pathlib import Path
import shutil
import tempfile

DOC = Path("docs/operations/evidence-review-c4b.md")
REPLACEMENTS = (
    (b"JACE_COLLABORATION_DRAFTER_ROUTE=openai:<real-API-model-ID>",
     b"JACE_COLLABORATION_DRAFTER_ROUTE=openai:demo"),
    (b"JACE_COLLABORATION_REVIEWER_ROUTE=anthropic:<real-API-model-ID>",
     b"JACE_COLLABORATION_REVIEWER_ROUTE=anthropic:demo"),
)


class UnsafeDocumentError(ValueError):
    """The target cannot be safely changed by this narrow installer."""


def patched(content: bytes) -> tuple[bytes, bool]:
    """Return new bytes and changed flag, or fail for drift/partial changes."""
    old = [content.count(before) for before, _ in REPLACEMENTS]
    new = [content.count(after) for _, after in REPLACEMENTS]
    if old == [0, 0] and new == [1, 1]:
        return content, False
    if old != [1, 1] or any(new):
        raise UnsafeDocumentError(
            "Documentation sample differs from expected version; no changes applied."
        )
    result = content
    for before, after in REPLACEMENTS:
        result = result.replace(before, after, 1)
    return result, True


def backup_directory() -> Path:
    base = os.environ.get("LOCALAPPDATA")
    if base:
        return Path(base) / "Jace" / "patch-backups" / "phase0b4"
    return Path.home() / ".jace-patch-backups" / "phase0b4"


def apply_to_repo(root: Path, *, apply: bool = False, backups: Path | None = None) -> str:
    root = root.resolve(strict=True)
    if not (root / "backend" / "jace").is_dir() or not (root / ".git").exists():
        raise UnsafeDocumentError("Repo root is not an expected Jace Git checkout.")
    target = root / DOC
    if not target.is_file() or target.is_symlink():
        raise UnsafeDocumentError(f"Missing or linked documentation file: {DOC}")
    original = target.read_bytes()
    updated, changed = patched(original)
    if not changed:
        return "ALREADY_FIXED: expected demonstration routes are present."
    if not apply:
        return "DRY_RUN: would replace two demo-only model route values; no files changed."

    backup_root = (backups or backup_directory()).resolve()
    if backup_root == root or root in backup_root.parents:
        raise UnsafeDocumentError("Backup directory must be outside the Git checkout.")
    backup_root.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    backup_path = backup_root / ("evidence-review-c4b.md." + timestamp + ".bak")
    with backup_path.open("xb") as backup:
        backup.write(original)
    if backup_path.read_bytes() != original:
        raise UnsafeDocumentError("Backup verification failed. Target was not changed.")

    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(prefix=".jace-0b4-", dir=target.parent,
                                         suffix=".tmp", delete=False) as tmp:
            temporary = Path(tmp.name)
            tmp.write(updated)
        if target.read_bytes() != original:
            raise UnsafeDocumentError("Target changed since backup; refusing overwrite.")
        shutil.copymode(target, temporary)
        os.replace(temporary, target)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return f"APPLIED: documentation example updated. Backup: {backup_path}"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--apply", action="store_true", help="Apply the checked patch; default is dry-run")
    args = parser.parse_args()
    try:
        print(apply_to_repo(args.repo_root, apply=args.apply))
    except (OSError, UnsafeDocumentError) as error:
        print(f"BLOCKED: {error}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
