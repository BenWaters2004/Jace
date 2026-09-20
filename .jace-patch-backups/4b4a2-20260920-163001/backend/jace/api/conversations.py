from fastapi import APIRouter, HTTPException

from jace.api.helpers import conversation_detail_response
from jace.attachments.service import cleanup_conversation_files
from jace.database import SessionLocal
from jace.db.conversations import (
    create_conversation,
    delete_conversation,
    get_conversation,
    list_conversations,
    update_conversation,
)
from jace.db.settings import get_or_create_assistant_settings
from jace.schemas import (
    ConversationCreate,
    ConversationDetail,
    ConversationListResponse,
    ConversationSummary,
    ConversationUpdate,
)


router = APIRouter(prefix="/conversations", tags=["conversations"])


@router.post("", response_model=ConversationDetail)
async def create_new_conversation(request: ConversationCreate):
    async with SessionLocal() as session:
        profile = await get_or_create_assistant_settings(session)
        conversation = await create_conversation(
            session,
            model=request.model or profile.default_model,
            system_prompt=request.system_prompt if request.system_prompt is not None else profile.system_prompt,
        )
        conversation = await get_conversation(session, conversation.id)
        if conversation is None:
            raise HTTPException(status_code=500, detail="Conversation could not be created.")
        return conversation_detail_response(conversation)


@router.get("", response_model=ConversationListResponse)
async def conversations():
    async with SessionLocal() as session:
        rows = await list_conversations(session)
        return ConversationListResponse(
            conversations=[
                ConversationSummary(
                    id=conversation.id,
                    title=conversation.title,
                    model=conversation.model,
                    created_at=conversation.created_at,
                    updated_at=conversation.updated_at,
                    message_count=message_count,
                )
                for conversation, message_count in rows
            ]
        )


@router.get("/{conversation_id}", response_model=ConversationDetail)
async def conversation(conversation_id: str):
    async with SessionLocal() as session:
        result = await get_conversation(session, conversation_id)
        if result is None:
            raise HTTPException(status_code=404, detail="Conversation not found.")
        return conversation_detail_response(result)


@router.patch("/{conversation_id}", response_model=ConversationDetail)
async def patch_conversation(conversation_id: str, request: ConversationUpdate):
    async with SessionLocal() as session:
        conversation = await get_conversation(session, conversation_id)
        if conversation is None:
            raise HTTPException(status_code=404, detail="Conversation not found.")
        await update_conversation(
            session,
            conversation,
            title=request.title,
            model=request.model,
            system_prompt=request.system_prompt,
        )
        updated = await get_conversation(session, conversation_id)
        if updated is None:
            raise HTTPException(status_code=404, detail="Conversation not found.")
        return conversation_detail_response(updated)


@router.delete("/{conversation_id}")
async def remove_conversation(conversation_id: str):
    async with SessionLocal() as session:
        if not await delete_conversation(session, conversation_id):
            raise HTTPException(status_code=404, detail="Conversation not found.")
        cleanup_conversation_files(conversation_id)
        return {"success": True}
