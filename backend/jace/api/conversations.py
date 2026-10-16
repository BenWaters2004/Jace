from fastapi import APIRouter, Depends, HTTPException

from jace.api.helpers import conversation_detail_response
from jace.attachments.service import cleanup_conversation_files
from jace.database import SessionLocal
from jace.auth.actor_context import ActorContext, require_actor
from jace.auth.resource_ownership import (
    claim_resource,
    filter_or_claim_local,
    release_resource,
    require_or_claim_local,
)
from jace.db.conversations import (
    create_conversation,
    delete_conversation,
    get_conversation,
    list_conversations,
    update_conversation,
)
from jace.db.settings import get_or_create_assistant_settings
from jace.config import settings as env_settings
from jace.model_gateway.cutover import (
    ChatCutoverConfigurationError, choose_chat_model,
)
from jace.schemas import (
    ConversationCreate,
    ConversationDetail,
    ConversationListResponse,
    ConversationSummary,
    ConversationUpdate,
)


router = APIRouter(prefix="/conversations", tags=["conversations"])

# JACE_4B4A2_CONVERSATION_OWNERSHIP

async def _owned_conversation(session, conversation_id: str, actor: ActorContext):
    conversation = await get_conversation(session, conversation_id)
    if conversation is None:
        return None
    await require_or_claim_local(
        session,
        resource_kind="conversation",
        resource_id=conversation.id,
        actor_id=actor.actor_id,
        client_id=actor.client_id,
        server_mode=actor.server_mode,
    )
    return conversation



@router.post("", response_model=ConversationDetail)
async def create_new_conversation(request: ConversationCreate, actor: ActorContext = Depends(require_actor)):
    async with SessionLocal() as session:
        profile = await get_or_create_assistant_settings(session)
        try:
            chosen_model = choose_chat_model(
                request.model or profile.default_model,
                cutover_enabled=env_settings.cloud_chat_cutover,
                fast_route=env_settings.model_route_conversation_fast,
                auto_enabled=env_settings.smart_routing_enabled,
            )
        except ChatCutoverConfigurationError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        conversation = await create_conversation(
            session,
            model=chosen_model,
            system_prompt=request.system_prompt if request.system_prompt is not None else profile.system_prompt,
        )
        conversation = await get_conversation(session, conversation.id)
        if conversation is not None:
            await claim_resource(
                session,
                resource_kind="conversation",
                resource_id=conversation.id,
                actor_id=actor.actor_id,
                client_id=actor.client_id,
            )
        if conversation is None:
            raise HTTPException(status_code=500, detail="Conversation could not be created.")
        return conversation_detail_response(conversation)


@router.get("", response_model=ConversationListResponse)
async def conversations(actor: ActorContext = Depends(require_actor)):
    async with SessionLocal() as session:
        rows = await list_conversations(session)
        visible = await filter_or_claim_local(
            session,
            resource_kind="conversation",
            actor_id=actor.actor_id,
            client_id=actor.client_id,
            server_mode=actor.server_mode,
            rows=[conversation for conversation, _count in rows],
        )
        visible_ids = {item.id for item in visible}
        rows = [(conversation, count) for conversation, count in rows if conversation.id in visible_ids]
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
async def conversation(conversation_id: str, actor: ActorContext = Depends(require_actor)):
    async with SessionLocal() as session:
        result = await _owned_conversation(session, conversation_id, actor)
        if result is None:
            raise HTTPException(status_code=404, detail="Conversation not found.")
        return conversation_detail_response(result)


@router.patch("/{conversation_id}", response_model=ConversationDetail)
async def patch_conversation(conversation_id: str, request: ConversationUpdate, actor: ActorContext = Depends(require_actor)):
    async with SessionLocal() as session:
        conversation = await _owned_conversation(session, conversation_id, actor)
        if conversation is None:
            raise HTTPException(status_code=404, detail="Conversation not found.")
        await update_conversation(
            session,
            conversation,
            title=request.title,
            model=request.model,
            system_prompt=request.system_prompt,
        )
        updated = await _owned_conversation(session, conversation_id, actor)
        if updated is None:
            raise HTTPException(status_code=404, detail="Conversation not found.")
        return conversation_detail_response(updated)


@router.delete("/{conversation_id}")
async def remove_conversation(conversation_id: str, actor: ActorContext = Depends(require_actor)):
    async with SessionLocal() as session:
        existing = await _owned_conversation(session, conversation_id, actor)
        if existing is None:
            raise HTTPException(status_code=404, detail="Conversation not found.")
        if not await delete_conversation(session, conversation_id):
            raise HTTPException(status_code=404, detail="Conversation not found.")
        await release_resource(
            session,
            resource_kind="conversation",
            resource_id=conversation_id,
            actor_id=actor.actor_id,
        )
        cleanup_conversation_files(conversation_id)
        return {"success": True}
