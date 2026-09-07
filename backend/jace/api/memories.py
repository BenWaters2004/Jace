from fastapi import APIRouter, HTTPException

from jace.api.helpers import memory_response
from jace.database import SessionLocal
from jace.memory.service import create_memory, delete_memory, get_memory, list_memories, search_memories, update_memory
from jace.schemas import (
    MemoryCreate,
    MemoryListResponse,
    MemoryResponse,
    MemorySearchRequest,
    MemorySearchResponse,
    MemorySearchResult,
    MemoryUpdate,
)


router = APIRouter(prefix="/memories", tags=["memory"])


@router.post("", response_model=MemoryResponse)
async def create_new_memory(request: MemoryCreate):
    async with SessionLocal() as session:
        try:
            memory = await create_memory(
                session,
                memory_type=request.memory_type,
                subject=request.subject,
                content=request.content,
                importance=request.importance,
                confidence=request.confidence,
                is_pinned=request.is_pinned,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return memory_response(memory)


@router.get("", response_model=MemoryListResponse)
async def memories(query: str | None = None, memory_type: str | None = None, active_only: bool = True):
    async with SessionLocal() as session:
        results = await list_memories(session, query=query, memory_type=memory_type, active_only=active_only)
        return MemoryListResponse(memories=[memory_response(memory) for memory in results])


@router.post("/search", response_model=MemorySearchResponse)
async def semantic_memory_search(request: MemorySearchRequest):
    async with SessionLocal() as session:
        hits = await search_memories(
            session,
            request.query,
            limit=request.limit,
            min_similarity=request.min_similarity,
            update_access=False,
        )
        return MemorySearchResponse(
            results=[
                MemorySearchResult(
                    memory=memory_response(hit.memory),
                    similarity=round(hit.similarity, 4),
                    score=round(hit.score, 4),
                )
                for hit in hits
            ]
        )


@router.get("/{memory_id}", response_model=MemoryResponse)
async def memory(memory_id: str):
    async with SessionLocal() as session:
        result = await get_memory(session, memory_id)
        if result is None:
            raise HTTPException(status_code=404, detail="Memory not found.")
        return memory_response(result)


@router.patch("/{memory_id}", response_model=MemoryResponse)
async def patch_memory(memory_id: str, request: MemoryUpdate):
    async with SessionLocal() as session:
        memory = await get_memory(session, memory_id)
        if memory is None:
            raise HTTPException(status_code=404, detail="Memory not found.")
        try:
            updated = await update_memory(
                session,
                memory,
                memory_type=request.memory_type,
                subject=request.subject,
                content=request.content,
                importance=request.importance,
                confidence=request.confidence,
                is_pinned=request.is_pinned,
                is_active=request.is_active,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return memory_response(updated)


@router.delete("/{memory_id}")
async def remove_memory(memory_id: str):
    async with SessionLocal() as session:
        memory = await get_memory(session, memory_id)
        if memory is None:
            raise HTTPException(status_code=404, detail="Memory not found.")
        await delete_memory(session, memory)
        return {"success": True}
