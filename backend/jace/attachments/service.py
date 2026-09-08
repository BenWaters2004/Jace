from __future__ import annotations

import hashlib
import json
import mimetypes
import re
from pathlib import Path
from uuid import uuid4

from fastapi import UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from jace.config import ATTACHMENTS_DIRECTORY, settings
from jace.db.models import Attachment


IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"}
PDF_EXTENSIONS = {".pdf"}
AUDIO_EXTENSIONS = {".wav", ".mp3", ".m4a", ".flac", ".ogg", ".oga", ".webm", ".aac", ".wma"}
DOCUMENT_EXTENSIONS = {
    ".txt", ".md", ".markdown", ".csv", ".json", ".xml", ".html", ".htm",
    ".log", ".ini", ".cfg", ".conf", ".yaml", ".yml", ".toml", ".py", ".php",
    ".js", ".jsx", ".ts", ".tsx", ".css", ".scss", ".sql", ".sh", ".ps1",
    ".bat", ".cmd", ".java", ".c", ".h", ".cpp", ".hpp", ".cs", ".go", ".rs",
    ".rb", ".swift", ".kt", ".docx",
}


class AttachmentError(ValueError):
    pass


def safe_filename(value: str) -> str:
    name = Path(value or "attachment").name
    name = re.sub(r"[^A-Za-z0-9._ -]+", "_", name).strip(" .")
    return (name or "attachment")[:240]


def media_kind_for_name(name: str, mime_type: str | None = None) -> str:
    suffix = Path(name).suffix.lower()
    mime = (mime_type or "").lower()
    if suffix in IMAGE_EXTENSIONS or mime.startswith("image/"):
        return "image"
    if suffix in PDF_EXTENSIONS or mime == "application/pdf":
        return "pdf"
    if suffix in AUDIO_EXTENSIONS or mime.startswith("audio/"):
        return "audio"
    if suffix in DOCUMENT_EXTENSIONS or mime.startswith("text/"):
        return "document"
    raise AttachmentError(f"Unsupported attachment type: {suffix or mime or 'unknown'}")


def max_bytes_for_kind(kind: str) -> int:
    if kind == "image":
        return settings.attachment_image_max_bytes
    if kind == "audio":
        return settings.attachment_audio_max_bytes
    return settings.attachment_document_max_bytes


def attachment_directory(conversation_id: str) -> Path:
    path = ATTACHMENTS_DIRECTORY / conversation_id
    path.mkdir(parents=True, exist_ok=True)
    return path


def attachment_path(attachment: Attachment) -> Path:
    root = (ATTACHMENTS_DIRECTORY / attachment.conversation_id).resolve()
    path = (root / attachment.stored_name).resolve()
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise AttachmentError("Attachment storage path escaped its conversation directory.") from exc
    return path


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _mime_for(name: str, supplied: str | None) -> str:
    if supplied and supplied != "application/octet-stream":
        return supplied[:160]
    guessed, _ = mimetypes.guess_type(name)
    return guessed or "application/octet-stream"


async def create_attachment_from_bytes(
    session: AsyncSession,
    *,
    conversation_id: str,
    original_name: str,
    data: bytes,
    mime_type: str | None = None,
    source_type: str = "upload",
    source_path: str | None = None,
) -> Attachment:
    if not settings.multimodal_enabled:
        raise AttachmentError("Multimodal attachments are disabled.")

    clean_name = safe_filename(original_name)
    mime = _mime_for(clean_name, mime_type)
    kind = media_kind_for_name(clean_name, mime)
    limit = max_bytes_for_kind(kind)
    if not data:
        raise AttachmentError("Attachment was empty.")
    if len(data) > limit:
        raise AttachmentError(
            f"{kind.title()} attachment is too large ({len(data):,} bytes; limit {limit:,})."
        )

    suffix = Path(clean_name).suffix.lower() or {
        "image": ".png",
        "pdf": ".pdf",
        "audio": ".bin",
        "document": ".txt",
    }[kind]
    stored_name = f"{uuid4()}{suffix}"
    destination = attachment_directory(conversation_id) / stored_name
    destination.write_bytes(data)

    attachment = Attachment(
        conversation_id=conversation_id,
        original_name=clean_name,
        stored_name=stored_name,
        mime_type=mime,
        media_kind=kind,
        size_bytes=len(data),
        sha256=_sha256(data),
        source_type=source_type,
        source_path=source_path,
        metadata_json="{}",
    )
    session.add(attachment)
    await session.commit()
    await session.refresh(attachment)
    return attachment


async def create_attachment_from_upload(
    session: AsyncSession,
    *,
    conversation_id: str,
    upload: UploadFile,
) -> Attachment:
    name = upload.filename or "attachment"
    mime = upload.content_type
    kind = media_kind_for_name(name, mime)
    limit = max_bytes_for_kind(kind)

    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = await upload.read(1024 * 1024)
        if not chunk:
            break
        total += len(chunk)
        if total > limit:
            raise AttachmentError(
                f"{kind.title()} attachment exceeds the {limit:,}-byte limit."
            )
        chunks.append(chunk)

    return await create_attachment_from_bytes(
        session,
        conversation_id=conversation_id,
        original_name=name,
        data=b"".join(chunks),
        mime_type=mime,
        source_type="upload",
    )


async def get_attachment(session: AsyncSession, attachment_id: str) -> Attachment | None:
    result = await session.execute(select(Attachment).where(Attachment.id == attachment_id))
    return result.scalar_one_or_none()


async def get_attachments(
    session: AsyncSession,
    attachment_ids: list[str],
    *,
    conversation_id: str | None = None,
) -> list[Attachment]:
    if not attachment_ids:
        return []
    unique = list(dict.fromkeys(attachment_ids))
    statement = select(Attachment).where(Attachment.id.in_(unique))
    if conversation_id is not None:
        statement = statement.where(Attachment.conversation_id == conversation_id)
    result = await session.execute(statement)
    by_id = {item.id: item for item in result.scalars().all()}
    return [by_id[item_id] for item_id in unique if item_id in by_id]


async def latest_conversation_attachment(
    session: AsyncSession,
    conversation_id: str,
) -> Attachment | None:
    result = await session.execute(
        select(Attachment)
        .where(Attachment.conversation_id == conversation_id)
        .order_by(Attachment.created_at.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def assign_attachments_to_message(
    session: AsyncSession,
    attachments: list[Attachment],
    message_id: str,
) -> None:
    for attachment in attachments:
        attachment.message_id = message_id
    await session.commit()


async def update_attachment_processing(
    session: AsyncSession,
    attachment: Attachment,
    *,
    extracted_text: str | None = None,
    metadata: dict | None = None,
) -> Attachment:
    if extracted_text is not None:
        attachment.extracted_text = extracted_text
    if metadata is not None:
        current: dict = {}
        try:
            current = json.loads(attachment.metadata_json or "{}")
        except json.JSONDecodeError:
            current = {}
        current.update(metadata)
        attachment.metadata_json = json.dumps(current, ensure_ascii=False)
    await session.commit()
    await session.refresh(attachment)
    return attachment


async def delete_attachment(session: AsyncSession, attachment: Attachment) -> None:
    path = attachment_path(attachment)
    await session.delete(attachment)
    await session.commit()
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass


def cleanup_conversation_files(conversation_id: str) -> None:
    root = ATTACHMENTS_DIRECTORY / conversation_id
    if not root.exists():
        return
    for path in sorted(root.rglob("*"), reverse=True):
        try:
            if path.is_file() or path.is_symlink():
                path.unlink()
            elif path.is_dir():
                path.rmdir()
        except OSError:
            pass
    try:
        root.rmdir()
    except OSError:
        pass
