#!/usr/bin/env python3
"""Local-only, metadata-only triage for Gitleaks results from Jace's Git index.

Does not scan Jace's working directory or history and never prints secret content.
It reconstructs only currently staged Git blobs in a disposable temporary folder.
If a file is not safely eligible for the scan, it aborts rather than calling it clean.

Usage: python tools/jace_secret_review.py --repo-root .
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import sys
import tempfile

if __package__:
    from .jace_secret_scan import _git, _possibly_private, _valid_path, MAX_BLOB_BYTES, MAX_TOTAL_BYTES
else:
    from jace_secret_scan import _git, _possibly_private, _valid_path, MAX_BLOB_BYTES, MAX_TOTAL_BYTES


def index_snapshot(repo: Path, target: Path) -> set[str]:
    index = _git(repo, "ls-files", "--stage", "-z")
    if index.returncode != 0:
        raise RuntimeError("Could not read Git index")
    records = index.stdout.split(b"\0")
    if not records or not any(records):
        raise RuntimeError("No Git index entries")
    valid: set[str] = set()
    volume = 0
    staged: list[tuple[str, str]] = []
    for raw in records:
        if not raw:
            continue
        try:
            head, raw_name = raw.split(b"\t", 1)
            mode, sha, stage = head.decode("ascii").split(" ")
            name = raw_name.decode("utf-8", "surrogateescape")
        except (ValueError, UnicodeError) as exc:
            raise RuntimeError("Unrecognised Git index metadata") from exc
        if (not _valid_path(name) or mode not in ("100644", "100755") or stage != "0"
                or not re.fullmatch(r"[a-f0-9]{40,64}", sha) or name in valid):
            raise RuntimeError("Unsupported index entry; cannot safely scan")
        if _possibly_private(name):
            raise RuntimeError("Tracked private/generated files remain; untrack before reviewing")
        valid.add(name)
        staged.append((name, sha))
    for name, sha in staged:
        size = _git(repo, "cat-file", "-s", sha)
        if size.returncode != 0:
            raise RuntimeError("Cannot determine Git blob size")
        try:
            length = int(size.stdout.strip())
        except ValueError as exc:
            raise RuntimeError("Unrecognised blob size") from exc
        volume += length
        if length < 0 or length > MAX_BLOB_BYTES or volume > MAX_TOTAL_BYTES:
            raise RuntimeError("Git-index blob size exceeds scan limits")
        blob = _git(repo, "cat-file", "blob", sha)
        if blob.returncode != 0 or len(blob.stdout) != length:
            raise RuntimeError("Failed to retrieve staged blob")
        out = target.joinpath(*PurePosixPath(name).parts)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(blob.stdout)
    return valid


def safe_metadata(findings: object, staged_paths: set[str]) -> list[tuple[str, str, str]]:
    """Return only whitelisted relative paths, line numbers and rule IDs.

    Never return Match, Secret, Entropy, Description, raw report data, or excerpts.
    """
    if not isinstance(findings, list):
        raise ValueError("Invalid Gitleaks report format")
    sorted_paths = sorted(staged_paths, key=len, reverse=True)
    sanitized = []
    for entry in findings:
        if not isinstance(entry, dict):
            raise ValueError("Invalid Gitleaks finding")
        # Use only paths we ourselves extracted from the Git index.
        raw_file = str(entry.get("File", "")).replace("\\", "/").lower()
        filepath = "[unresolved tracked path]"
        for known in sorted_paths:
            k = known.lower()
            if raw_file == k or raw_file.endswith("/" + k):
                filepath = known
                break
        raw_line = entry.get("StartLine")
        lineno = str(raw_line) if type(raw_line) is int and 1 <= raw_line <= 999999999 else "?"
        rule = entry.get("RuleID")
        rule = rule if isinstance(rule, str) and re.fullmatch(r"[a-zA-Z0-9_.-]{1,80}", rule) else "unknown-rule"
        sanitized.append((filepath, lineno, rule))
    return sanitized


def review(repo: Path, binary: str) -> int:
    try:
        with tempfile.TemporaryDirectory(prefix="jace_phase0b_review_") as directory:
            folder = Path(directory)
            snapshot = folder / "staged"
            snapshot.mkdir()
            staged = index_snapshot(repo, snapshot)
            report = folder / "findings.json"
            result = subprocess.run(
                [binary, "dir", "--no-banner", "--redact", "--report-format", "json",
                 "--report-path", str(report), str(snapshot)],
                cwd=repo, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                timeout=300, check=False,
            )
            if result.returncode == 0:
                print(f"Gitleaks: no findings in {len(staged)} staged tracked files. Git history was NOT scanned.")
                return 0
            if result.returncode != 1:
                raise RuntimeError("Gitleaks exited unexpectedly; review is incomplete")
            findings = json.loads(report.read_text(encoding="utf-8"))
            summary = safe_metadata(findings, staged)
            if not summary:
                raise RuntimeError("Gitleaks returned findings but report metadata is missing")
            print(f"Gitleaks detected {len(summary)} potential secret(s) in staged tracked files:")
            for i, (path, line, rule) in enumerate(summary, 1):
                print(f"  {i}. {path}:{line} (rule: {rule})")
            print("Secret values and source excerpts were intentionally NOT shown or saved by this helper.")
            print("Inspect matches locally. Rotate any exposed credentials; do not post secret values.")
            return 1
    except (OSError, subprocess.TimeoutExpired, UnicodeError, ValueError, RuntimeError) as error:
        # Only class name: paths or original scanner output might contain private details.
        print(f"Review BLOCKED ({type(error).__name__}); no clean result can be claimed.", file=sys.stderr)
        return 2


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[1])
    arguments = parser.parse_args(argv)
    binary = shutil.which("gitleaks")
    if binary is None:
        print("Review BLOCKED: gitleaks not found on PATH.", file=sys.stderr)
        return 2
    return review(arguments.repo_root.resolve(), binary)


if __name__ == "__main__":
    raise SystemExit(main())
