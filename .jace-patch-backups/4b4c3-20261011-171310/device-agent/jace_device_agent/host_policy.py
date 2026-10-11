from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable

from jace_device_agent.config import data_directory
from jace_device_agent.windows_sandbox_runner import (
    SUPPORTED_PROCESS_SHELLS,
    is_verified as windows_sandbox_verified,
)


POLICY_VERSION = 1
_ALLOWED_SHELLS = {
    "powershell",
    "cmd",
    "wsl",
    "bash",
}


def policy_path() -> Path:
    return data_directory() / "host-policy.json"


def _resolved_dir(value: str) -> Path:
    raw = str(value or "").strip()
    if not raw:
        raise ValueError("Host-policy path cannot be empty.")

    path = Path(os.path.expandvars(os.path.expanduser(raw))).resolve()
    if not path.is_dir():
        raise ValueError(f"Host-policy directory does not exist: {path}")
    return path


def _key(path: Path) -> str:
    return os.path.normcase(str(path))


def _shells(values: Iterable[str]) -> list[str]:
    result: list[str] = []
    for value in values:
        shell = str(value or "").strip().lower()
        if not shell:
            continue
        if shell not in _ALLOWED_SHELLS:
            raise ValueError(f"Unsupported host-policy shell: {shell}")
        if shell not in result:
            result.append(shell)

    if not result:
        raise ValueError("At least one allowed shell is required.")
    return result


def _within(root: Path, target: Path) -> bool:
    try:
        return os.path.commonpath([_key(root), _key(target)]) == _key(root)
    except ValueError:
        return False


@dataclass(slots=True)
class ApprovedRoot:
    path: str
    allowed_shells: list[str]
    process_enabled: bool = False
    terminal_enabled: bool = False

    def payload(self) -> dict:
        return asdict(self)


class HostPolicyRegistry:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or policy_path()

    @property
    def strong_isolation_backend(self) -> str:
        return "windows-sandbox"

    @property
    def process_isolation_ready(self) -> bool:
        return windows_sandbox_verified()

    @property
    def terminal_isolation_ready(self) -> bool:
        # Interactive ConPTY is deliberately not exposed until its own
        # isolated transport exists.
        return False

    @property
    def strong_isolation_ready(self) -> bool:
        return self.process_isolation_ready

    @property
    def isolated_process_shells(self) -> list[str]:
        if not self.process_isolation_ready:
            return []
        return sorted(SUPPORTED_PROCESS_SHELLS)

    def roots(self) -> list[ApprovedRoot]:
        if not self.path.is_file():
            return []

        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"Could not read host policy: {exc}") from exc

        if not isinstance(data, dict) or data.get("version") != POLICY_VERSION:
            raise RuntimeError("Unsupported Device Agent host-policy format.")

        raw_roots = data.get("approved_roots")
        if not isinstance(raw_roots, list):
            raise RuntimeError("approved_roots must be a list.")

        result: list[ApprovedRoot] = []
        for item in raw_roots:
            if not isinstance(item, dict):
                continue
            path = str(item.get("path") or "").strip()
            if not path:
                continue
            try:
                allowed = _shells(item.get("allowed_shells") or [])
            except ValueError:
                continue

            result.append(
                ApprovedRoot(
                    path=path,
                    allowed_shells=allowed,
                    process_enabled=bool(item.get("process_enabled", False)),
                    terminal_enabled=bool(item.get("terminal_enabled", False)),
                )
            )

        return result

    def _save(self, roots: list[ApprovedRoot]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.path.with_suffix(".tmp")
        temp.write_text(
            json.dumps(
                {
                    "version": POLICY_VERSION,
                    "approved_roots": [root.payload() for root in roots],
                },
                indent=2,
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        temp.replace(self.path)

    def approve_root(
        self,
        *,
        path: str,
        allowed_shells: Iterable[str],
        process_enabled: bool,
        terminal_enabled: bool,
    ) -> ApprovedRoot:
        resolved = _resolved_dir(path)
        approved = ApprovedRoot(
            path=str(resolved),
            allowed_shells=_shells(allowed_shells),
            process_enabled=bool(process_enabled),
            terminal_enabled=bool(terminal_enabled),
        )

        key = _key(resolved)
        roots: list[ApprovedRoot] = []
        for item in self.roots():
            try:
                if _key(_resolved_dir(item.path)) == key:
                    continue
            except ValueError:
                continue
            roots.append(item)

        roots.append(approved)
        roots.sort(key=lambda item: os.path.normcase(item.path))
        self._save(roots)
        return approved

    def revoke_root(self, path: str) -> bool:
        key = _key(_resolved_dir(path))
        before = self.roots()
        after: list[ApprovedRoot] = []

        for item in before:
            try:
                if _key(_resolved_dir(item.path)) == key:
                    continue
            except ValueError:
                continue
            after.append(item)

        if len(after) == len(before):
            return False
        self._save(after)
        return True

    def find_exact_root(self, path: str | None) -> ApprovedRoot | None:
        if not path:
            return None

        try:
            key = _key(_resolved_dir(path))
        except ValueError:
            return None

        for item in self.roots():
            try:
                if _key(_resolved_dir(item.path)) == key:
                    return item
            except ValueError:
                continue
        return None

    def find_root_for_path(self, path: str | Path) -> ApprovedRoot | None:
        target = Path(os.path.expandvars(os.path.expanduser(str(path)))).resolve()

        for item in self.roots():
            try:
                root = _resolved_dir(item.path)
            except ValueError:
                continue
            if _within(root, target):
                return item
        return None

    def authorise_path(self, path: str | Path, *, operation: str) -> ApprovedRoot:
        root = self.find_root_for_path(path)
        if root is None:
            raise PermissionError(
                f"{operation} is outside every locally approved Device Agent root."
            )
        return root

    def authorise_runtime(
        self,
        *,
        scope_root: str | None,
        shell: str,
        runtime_kind: str,
        require_strong_isolation: bool,
    ) -> ApprovedRoot:
        shell = str(shell or "").strip().lower()
        root = self.find_exact_root(scope_root)

        if root is None:
            raise PermissionError(
                "Core requested an execution root that is not locally approved."
            )
        if shell not in root.allowed_shells:
            raise PermissionError(
                f"Shell {shell!r} is not locally approved for {root.path}."
            )

        if runtime_kind == "process":
            if not root.process_enabled:
                raise PermissionError(
                    f"Remote process execution is not locally approved for {root.path}."
                )
            if require_strong_isolation:
                if not self.process_isolation_ready:
                    raise PermissionError(
                        "Windows Sandbox process isolation has not passed local verification."
                    )
                if shell not in SUPPORTED_PROCESS_SHELLS:
                    raise PermissionError(
                        f"Shell {shell!r} is not supported by the verified "
                        "Windows Sandbox process backend yet."
                    )

        elif runtime_kind == "terminal":
            if not root.terminal_enabled:
                raise PermissionError(
                    f"Remote terminal access is not locally approved for {root.path}."
                )
            if require_strong_isolation:
                raise PermissionError(
                    "Strong isolation for interactive terminals is not implemented yet."
                )
        else:
            raise PermissionError(f"Unknown runtime kind: {runtime_kind}")

        return root

    def status(self) -> dict:
        roots = self.roots()
        return {
            "version": POLICY_VERSION,
            "policy_path": str(self.path),
            "approved_root_count": len(roots),
            "approved_roots": [root.payload() for root in roots],
            "strong_isolation_backend": self.strong_isolation_backend,
            "strong_isolation_ready": self.strong_isolation_ready,
            "process_isolation_ready": self.process_isolation_ready,
            "terminal_isolation_ready": self.terminal_isolation_ready,
            "isolated_process_shells": self.isolated_process_shells,
        }


host_policy_registry = HostPolicyRegistry()
