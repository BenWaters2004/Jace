from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable

from jace_device_agent.config import data_directory

POLICY_VERSION = 1
_ALLOWED_SHELLS = {"powershell", "cmd", "wsl", "bash"}


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
    out: list[str] = []
    for value in values:
        shell = str(value or "").strip().lower()
        if not shell:
            continue
        if shell not in _ALLOWED_SHELLS:
            raise ValueError(f"Unsupported host-policy shell: {shell}")
        if shell not in out:
            out.append(shell)
    if not out:
        raise ValueError("At least one allowed shell is required.")
    return out


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
    """Local Device Agent authority for host access.

    4B.4C.1 intentionally keeps strong isolation unavailable. The real
    Windows isolated runner is added in 4B.4C.2.
    """

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or policy_path()

    @property
    def strong_isolation_backend(self) -> str:
        return "not-installed"

    @property
    def strong_isolation_ready(self) -> bool:
        # Deliberately code-defined rather than editable in policy JSON.
        return False

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
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(
            json.dumps(
                {
                    "version": POLICY_VERSION,
                    "approved_roots": [r.payload() for r in roots],
                },
                indent=2,
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        tmp.replace(self.path)

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
        target = Path(
            os.path.expandvars(os.path.expanduser(str(path)))
        ).resolve()
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
        if runtime_kind == "process" and not root.process_enabled:
            raise PermissionError(
                f"Remote process execution is not locally approved for {root.path}."
            )
        if runtime_kind == "terminal" and not root.terminal_enabled:
            raise PermissionError(
                f"Remote terminal access is not locally approved for {root.path}."
            )
        if runtime_kind not in {"process", "terminal"}:
            raise PermissionError(f"Unknown runtime kind: {runtime_kind}")
        if require_strong_isolation and not self.strong_isolation_ready:
            raise PermissionError(
                "Strong host isolation is required but the isolated execution "
                "runner is not installed. Complete 4B.4C.2 first."
            )
        return root

    def status(self) -> dict:
        roots = self.roots()
        return {
            "version": POLICY_VERSION,
            "policy_path": str(self.path),
            "approved_root_count": len(roots),
            "approved_roots": [r.payload() for r in roots],
            "strong_isolation_backend": self.strong_isolation_backend,
            "strong_isolation_ready": self.strong_isolation_ready,
        }


host_policy_registry = HostPolicyRegistry()
