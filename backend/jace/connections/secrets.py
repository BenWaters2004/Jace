from __future__ import annotations

import hashlib
import json
import platform
import secrets as secure_random
from dataclasses import dataclass
from typing import Any


TARGET_PREFIX = "Jace/Connections"

# Windows Credential Manager:
# CRED_MAX_CREDENTIAL_BLOB_SIZE == 5 * 512 bytes.
#
# pywin32 accepts CredentialBlob as a Python Unicode string and writes it
# as UTF-16, so we must calculate the actual UTF-16 byte size rather than
# simply using len(value).
MAX_CREDENTIAL_BLOB_BYTES = 5 * 512

# New storage formats.
DIRECT_PREFIX = "JACE_SECRET_V1:"
CHUNKED_PREFIX = "JACE_CHUNKED_V1:"

# Leave some space below the Windows maximum for safety.
CHUNK_PAYLOAD_BYTES = 2200


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
        return SecretStoreStatus(
            False,
            "unsupported",
            "Windows Credential Manager is only available on Windows.",
        )

    if _module() is None:
        return SecretStoreStatus(
            False,
            "windows_credential_manager",
            "pywin32/win32cred is unavailable.",
        )

    return SecretStoreStatus(
        True,
        "windows_credential_manager",
    )


def _target(connection_id: str, key: str) -> str:
    safe_id = "".join(
        ch
        for ch in connection_id
        if ch.isalnum() or ch in {"_", "-", "."}
    )

    safe_key = "".join(
        ch
        for ch in key
        if ch.isalnum() or ch in {"_", "-"}
    )

    if not safe_id or not safe_key:
        raise ValueError("Credential target is invalid.")

    return f"{TARGET_PREFIX}/{safe_id}/{safe_key}"


def _chunk_target(
    connection_id: str,
    key: str,
    generation: str,
    index: int,
) -> str:
    return _target(
        connection_id,
        f"{key}_chunk_{generation}_{index:04d}",
    )


def _blob_size(value: str) -> int:
    """
    Return the actual number of bytes pywin32 will use for CredentialBlob.
    """

    return len(value.encode("utf-16-le"))


def _write_target(
    target: str,
    value: str,
) -> None:
    size = _blob_size(value)

    if size > MAX_CREDENTIAL_BLOB_BYTES:
        raise ValueError(
            "Credential value exceeds the Windows Credential Manager "
            f"{MAX_CREDENTIAL_BLOB_BYTES}-byte limit."
        )

    win32cred = _module()

    if win32cred is None:
        raise RuntimeError(
            status().reason
            or "Secure credential storage is unavailable."
        )

    win32cred.CredWrite(
        {
            "Type": win32cred.CRED_TYPE_GENERIC,
            "TargetName": target,
            "UserName": "Jace",
            "CredentialBlob": value,
            "Persist": win32cred.CRED_PERSIST_LOCAL_MACHINE,
            "Comment": "Jace connection credential",
        },
        0,
    )


def _read_target(target: str) -> str | None:
    win32cred = _module()

    if win32cred is None:
        return None

    try:
        credential = win32cred.CredRead(
            target,
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
            return value.decode(
                "utf-8",
                errors="replace",
            ).rstrip("\x00")

    if isinstance(value, str):
        return value

    return None


def _delete_target(target: str) -> None:
    win32cred = _module()

    if win32cred is None:
        return

    try:
        win32cred.CredDelete(
            target,
            win32cred.CRED_TYPE_GENERIC,
            0,
        )
    except Exception:
        return


def _split_secret(secret: str) -> list[str]:
    """
    Split a secret into chunks that remain safely below the Windows
    CredentialBlob byte limit after UTF-16 encoding.
    """

    if not secret:
        return []

    chunks: list[str] = []

    current: list[str] = []
    current_bytes = 0

    for character in secret:
        character_bytes = len(
            character.encode("utf-16-le")
        )

        if (
            current
            and current_bytes + character_bytes
            > CHUNK_PAYLOAD_BYTES
        ):
            chunks.append(
                "".join(current)
            )

            current = []
            current_bytes = 0

        if character_bytes > CHUNK_PAYLOAD_BYTES:
            raise ValueError(
                "Secret contains a character too large to store."
            )

        current.append(character)
        current_bytes += character_bytes

    if current:
        chunks.append(
            "".join(current)
        )

    return chunks


def _parse_chunk_manifest(
    value: str | None,
) -> dict[str, Any] | None:
    if (
        not value
        or not value.startswith(CHUNKED_PREFIX)
    ):
        return None

    try:
        payload = json.loads(
            value[len(CHUNKED_PREFIX):]
        )
    except (json.JSONDecodeError, TypeError):
        return None

    if not isinstance(payload, dict):
        return None

    generation = payload.get("generation")
    parts = payload.get("parts")
    digest = payload.get("sha256")

    if (
        not isinstance(generation, str)
        or not generation
    ):
        return None

    if not all(
        character in "0123456789abcdef"
        for character in generation
    ):
        return None

    if (
        not isinstance(parts, int)
        or parts < 1
        or parts > 10000
    ):
        return None

    if (
        not isinstance(digest, str)
        or len(digest) != 64
    ):
        return None

    return payload


def _delete_manifest_chunks(
    connection_id: str,
    key: str,
    manifest: dict[str, Any] | None,
) -> None:
    if not manifest:
        return

    generation = manifest["generation"]
    parts = manifest["parts"]

    for index in range(parts):
        _delete_target(
            _chunk_target(
                connection_id,
                key,
                generation,
                index,
            )
        )


def write(
    connection_id: str,
    key: str,
    secret: str,
) -> None:
    if (
        not isinstance(secret, str)
        or not secret
    ):
        raise ValueError(
            "Secret cannot be empty."
        )

    if _module() is None:
        raise RuntimeError(
            status().reason
            or "Secure credential storage is unavailable."
        )

    main_target = _target(
        connection_id,
        key,
    )

    previous_value = _read_target(
        main_target
    )

    previous_manifest = _parse_chunk_manifest(
        previous_value
    )

    # Small values remain in a single Credential Manager entry.
    direct_value = (
        f"{DIRECT_PREFIX}{secret}"
    )

    if (
        _blob_size(direct_value)
        <= MAX_CREDENTIAL_BLOB_BYTES
    ):
        _write_target(
            main_target,
            direct_value,
        )

        # If the previous version was chunked, clean up its chunks only
        # after the new value has been written successfully.
        _delete_manifest_chunks(
            connection_id,
            key,
            previous_manifest,
        )

        return

    # Large secret: store chunks under a unique generation.
    #
    # A generation ID allows us to write the replacement completely
    # before switching the manifest to it.
    generation = secure_random.token_hex(8)

    chunks = _split_secret(secret)

    written_targets: list[str] = []

    try:
        for index, chunk in enumerate(chunks):
            target = _chunk_target(
                connection_id,
                key,
                generation,
                index,
            )

            _write_target(
                target,
                chunk,
            )

            written_targets.append(target)

        manifest_payload = {
            "generation": generation,
            "parts": len(chunks),
            "sha256": hashlib.sha256(
                secret.encode("utf-8")
            ).hexdigest(),
        }

        manifest = (
            CHUNKED_PREFIX
            + json.dumps(
                manifest_payload,
                separators=(",", ":"),
            )
        )

        # Commit the new value by switching the main entry to its
        # manifest only after every chunk exists.
        _write_target(
            main_target,
            manifest,
        )

    except Exception:
        # Don't leave incomplete chunks behind if anything failed.
        for target in written_targets:
            _delete_target(target)

        raise

    # New value is now committed. Remove old chunks afterwards.
    _delete_manifest_chunks(
        connection_id,
        key,
        previous_manifest,
    )


def read(
    connection_id: str,
    key: str,
) -> str | None:
    main_target = _target(
        connection_id,
        key,
    )

    value = _read_target(
        main_target
    )

    if value is None:
        return None

    # Current small-value format.
    if value.startswith(DIRECT_PREFIX):
        return value[len(DIRECT_PREFIX):]

    # Current large-value format.
    manifest = _parse_chunk_manifest(
        value
    )

    if manifest is None:
        # Legacy compatibility.
        #
        # Credentials stored before chunking was introduced contained
        # the secret directly. This keeps the existing Google account
        # working without requiring the user to reconnect.
        return value

    generation = manifest["generation"]
    parts = manifest["parts"]

    chunks: list[str] = []

    for index in range(parts):
        chunk = _read_target(
            _chunk_target(
                connection_id,
                key,
                generation,
                index,
            )
        )

        if chunk is None:
            return None

        chunks.append(chunk)

    secret = "".join(chunks)

    actual_digest = hashlib.sha256(
        secret.encode("utf-8")
    ).hexdigest()

    if actual_digest != manifest["sha256"]:
        return None

    return secret


def exists(
    connection_id: str,
    key: str,
) -> bool:
    return (
        read(connection_id, key)
        is not None
    )


def delete(
    connection_id: str,
    key: str,
) -> None:
    main_target = _target(
        connection_id,
        key,
    )

    value = _read_target(
        main_target
    )

    manifest = _parse_chunk_manifest(
        value
    )

    _delete_manifest_chunks(
        connection_id,
        key,
        manifest,
    )

    _delete_target(
        main_target
    )