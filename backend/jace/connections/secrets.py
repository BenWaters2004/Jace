from __future__ import annotations

import platform
from dataclasses import dataclass

TARGET_PREFIX = "Jace/Connections"


@dataclass(frozen=True)
class SecretStoreStatus:
    available: bool
    backend: str
    reason: str | None = None


def _module():
    if platform.system() != "Windows":
        return None
    try:
        import win32cred  # type: ignore
    except Exception:
        return None
    return win32cred


def status() -> SecretStoreStatus:
    if platform.system() != "Windows":
        return SecretStoreStatus(False, "unsupported", "Windows Credential Manager is only available on Windows.")
    if _module() is None:
        return SecretStoreStatus(False, "windows_credential_manager", "pywin32/win32cred is unavailable.")
    return SecretStoreStatus(True, "windows_credential_manager")


def _target(connection_id: str, key: str) -> str:
    safe_key = "".join(ch for ch in key if ch.isalnum() or ch in {"_", "-"})
    if not safe_key:
        raise ValueError("Secret key is invalid.")
    return f"{TARGET_PREFIX}/{connection_id}/{safe_key}"


def write(connection_id: str, key: str, secret: str) -> None:
    secret = secret.strip()
    if not secret:
        raise ValueError("Secret cannot be empty.")
    win32cred = _module()
    if win32cred is None:
        raise RuntimeError(status().reason or "Secure credential storage is unavailable.")
    win32cred.CredWrite(
        {
            "Type": win32cred.CRED_TYPE_GENERIC,
            "TargetName": _target(connection_id, key),
            "UserName": "Jace",
            "CredentialBlob": secret,
            "Persist": win32cred.CRED_PERSIST_LOCAL_MACHINE,
            "Comment": "Jace connection credential",
        },
        0,
    )


def read(connection_id: str, key: str) -> str | None:
    win32cred = _module()
    if win32cred is None:
        return None
    try:
        credential = win32cred.CredRead(
            _target(connection_id, key),
            win32cred.CRED_TYPE_GENERIC,
            0,
        )
    except Exception:
        return None
    value = credential.get("CredentialBlob")
    if isinstance(value, bytes):
        try:
            return value.decode("utf-16-le").rstrip("\x00")
        except UnicodeDecodeError:
            return value.decode("utf-8", errors="replace").rstrip("\x00")
    if isinstance(value, str):
        return value
    return None


def exists(connection_id: str, key: str) -> bool:
    return read(connection_id, key) is not None


def delete(connection_id: str, key: str) -> None:
    win32cred = _module()
    if win32cred is None:
        return
    try:
        win32cred.CredDelete(
            _target(connection_id, key),
            win32cred.CRED_TYPE_GENERIC,
            0,
        )
    except Exception:
        # Deleting a missing credential is intentionally idempotent.
        return
