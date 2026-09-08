from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import FileResponse

from jace.api.helpers import attachment_response
from jace.attachments.service import (
    AttachmentError,
    attachment_path,
    create_attachment_from_upload,
    delete_attachment,
    get_attachment,
)
from jace.config import settings
from jace.database import SessionLocal
from jace.db.conversations import get_conversation
from jace.schemas import AttachmentResponse, AttachmentStatusResponse


router = APIRouter(prefix="/attachments", tags=["attachments"])


@router.get("/status", response_model=AttachmentStatusResponse)
async def attachment_status():
    return AttachmentStatusResponse(
        enabled=settings.multimodal_enabled,
        image_max_bytes=settings.attachment_image_max_bytes,
        document_max_bytes=settings.attachment_document_max_bytes,
        audio_max_bytes=settings.attachment_audio_max_bytes,
        max_count=settings.attachment_max_count,
        audio_enabled=settings.audio_enabled,
        audio_model=settings.audio_model,
        screen_capture_enabled=settings.screen_capture_enabled,
    )


@router.post("", response_model=AttachmentResponse)
async def upload_attachment(
    conversation_id: str,
    file: UploadFile = File(...),
):
    async with SessionLocal() as session:
        conversation = await get_conversation(session, conversation_id)
        if conversation is None:
            raise HTTPException(status_code=404, detail="Conversation not found.")
        try:
            attachment = await create_attachment_from_upload(
                session,
                conversation_id=conversation_id,
                upload=file,
            )
        except AttachmentError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        finally:
            await file.close()
        return attachment_response(attachment)


@router.get("/{attachment_id}", response_model=AttachmentResponse)
async def attachment_details(attachment_id: str):
    async with SessionLocal() as session:
        attachment = await get_attachment(session, attachment_id)
        if attachment is None:
            raise HTTPException(status_code=404, detail="Attachment not found.")
        return attachment_response(attachment)


@router.get("/{attachment_id}/content")
async def attachment_content(attachment_id: str):
    async with SessionLocal() as session:
        attachment = await get_attachment(session, attachment_id)
        if attachment is None:
            raise HTTPException(status_code=404, detail="Attachment not found.")
        path = attachment_path(attachment)
        if not path.exists():
            raise HTTPException(status_code=404, detail="Attachment file is missing.")
        return FileResponse(
            path,
            media_type=attachment.mime_type,
            filename=attachment.original_name,
            content_disposition_type="inline",
        )


@router.delete("/{attachment_id}")
async def remove_attachment(attachment_id: str):
    async with SessionLocal() as session:
        attachment = await get_attachment(session, attachment_id)
        if attachment is None:
            raise HTTPException(status_code=404, detail="Attachment not found.")
        if attachment.message_id is not None:
            raise HTTPException(
                status_code=409,
                detail="Attachments already sent in a conversation cannot be removed independently.",
            )
        await delete_attachment(session, attachment)
        return {"success": True}
