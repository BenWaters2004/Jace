"""Safe, best-effort Gitleaks scan of CURRENT TRACKED GIT INDEX, not working files/history.

- No private local data or Git history is scanned automatically.
- Builds an isolated ephemeral snapshot from staged Git blob IDs.
- Suppresses stdout/stderr and discards redacted finding metadata.
- Always fails closed if any tracked blob is not inspected.
- A clean result does NOT attest that repository history or untracked files are clean.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path, PurePosixPath
import json
import shutil
import subprocess
import tempfile

# The repository tracks a legitimate ~6.35 MB thinking-audio asset.
# Keep a per-blob limit but allow existing media to be included in scans.
MAX_BLOB_BYTES = 8 * 1024 * 1024
MAX_TOTAL_BYTES = 80 * 1024 * 1024
EXCLUDED_PREFIXES = ("backend/.venv/", "device-agent/.venv/", ".jace-patch-backups/", "data/")
EXCLUDED_SUFFIXES = (".db", ".db-shm", ".db-wal", ".sqlite", ".sqlite3", ".key", ".p12", ".pfx", ".pem")


def _possibly_private(path: str) -> bool:
    low = path.lower()
    # Empty data/.gitkeep is deliberately tracked so a clean checkout retains
    # the data directory. This is metadata, not private data. All other data/
    # entries remain fail-closed, including DB, voice and generated reports.
    if low == "data/.gitkeep":
        return False
    leaf = PurePosixPath(low).name
    return (low.startswith(EXCLUDED_PREFIXES) or low.endswith(EXCLUDED_SUFFIXES)
            or (leaf.startswith(".env") and leaf != ".env.example"))


@dataclass(frozen=True)
class ScanVerdict:
    status: str
    detail: str
    repair: str = ""


def _git(repo: Path, *args: str, timeout: int = 40) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=repo, stdout=subprocess.PIPE,
                          stderr=subprocess.DEVNULL, check=False, timeout=timeout)


def _valid_path(value: str) -> bool:
    path = PurePosixPath(value)
    return (bool(value) and not path.is_absolute() and not value.startswith(("/", "\\"))
            and "\\" not in value and ":" not in value and all(p not in ("", ".", "..") for p in path.parts))


def scan_index_snapshot(repo: Path, *, executable: str | None = None) -> ScanVerdict:
    binary = executable or shutil.which("gitleaks")
    if not binary:
        return ScanVerdict("NOT_CONFIGURED", "Gitleaks not found on PATH; no scan executed.",
                           "Install Gitleaks, reopen PowerShell and rerun the security profile.")
    try:
        tracked = _git(repo, "ls-files", "--stage", "-z")
    except (OSError, subprocess.TimeoutExpired):
        return ScanVerdict("BLOCKED", "Could not safely enumerate Git index.")
    if tracked.returncode != 0:
        return ScanVerdict("BLOCKED", "Git index enumeration failed.")
    entries = []
    excluded = []
    for record in tracked.stdout.split(b"\0"):
        if not record:
            continue
        try:
            meta, name_bytes = record.split(b"\t", 1)
            mode, sha, stage = meta.decode("ascii").split(" ")
            name = name_bytes.decode("utf-8", "surrogateescape")
        except (ValueError, UnicodeError):
            return ScanVerdict("BLOCKED", "Unrecognised Git index record.")
        if not _valid_path(name) or mode not in ("100644", "100755") or stage != "0":
            return ScanVerdict("BLOCKED", "Unsupported tracked path or index stage; scan incomplete.")
        if _possibly_private(name):
            excluded.append(name)
            continue
        entries.append((name, sha))
    if excluded:
        # Even if some source is scanned, private/generated entries must not be silently called PASS.
        return ScanVerdict("BLOCKED", f"{len(excluded)} tracked private/generated paths still require untracking; secret scan not run.",
                           "Run Phase 0B untracking, commit cleanup, then retry.")
    if not entries:
        return ScanVerdict("BLOCKED", "No eligible Git index entries were found.")

    copied = 0
    volume = 0
    try:
        with tempfile.TemporaryDirectory(prefix="jace_phase0b_scan_") as tmp:
            base = Path(tmp)
            snapshot = base / "tracked"
            snapshot.mkdir()
            for name, sha in entries:
                size = _git(repo, "cat-file", "-s", sha)
                if size.returncode != 0:
                    return ScanVerdict("BLOCKED", "Unable to size a tracked blob; scan incomplete.")
                try:
                    length = int(size.stdout.strip())
                except ValueError:
                    return ScanVerdict("BLOCKED", "Invalid Git blob size; scan incomplete.")
                volume += length
                if length > MAX_BLOB_BYTES or volume > MAX_TOTAL_BYTES:
                    return ScanVerdict("BLOCKED", "Tracked source exceeds safe scan size limits; scan incomplete.",
                                       "Review oversized files locally and establish a dedicated scanning policy.")
                data = _git(repo, "cat-file", "blob", sha)
                if data.returncode != 0 or len(data.stdout) != length:
                    return ScanVerdict("BLOCKED", "Unable to materialize tracked blob; scan incomplete.")
                target = snapshot.joinpath(*PurePosixPath(name).parts)
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(data.stdout)
                copied += 1
            report = base / "findings.json"
            cmd = [str(binary), "dir", "--no-banner", "--redact", "--report-format", "json",
                   "--report-path", str(report), str(snapshot)]
            proc = subprocess.run(cmd, cwd=repo, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                  check=False, timeout=300)
            if proc.returncode == 0:
                return ScanVerdict("PASS", f"Gitleaks completed on {copied} staged tracked files; no findings. History and untracked files not scanned.")
            if proc.returncode == 1:
                count = None
                try:
                    content = json.loads(report.read_text(encoding="utf-8"))
                    if isinstance(content, list):
                        count = len(content)
                except (ValueError, OSError):
                    pass
                return ScanVerdict("FAIL", f"Gitleaks detected {count if count is not None else 'one or more'} potential secret(s) in current tracked files. Findings intentionally not persisted.",
                                   "Investigate privately, rotate confirmed leaked credentials, then rescan. Separately audit Git history.")
            return ScanVerdict("FAIL", "Gitleaks returned an unexpected failure; output withheld.",
                               "Check Gitleaks installation and run its help command locally.")
    except (OSError, subprocess.TimeoutExpired, UnicodeError):
        return ScanVerdict("BLOCKED", "Gitleaks scan could not complete; no sensitive scanner output retained.")
