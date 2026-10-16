import asyncio

from fastapi import APIRouter, HTTPException

from jace.ai.engine import OllamaRequestError, OllamaUnavailableError, get_models
from jace.config import DATABASE_PATH, settings
from jace.schemas import HealthResponse, ModelInfo, ModelsResponse
from jace.model_gateway.cutover import configured_cloud_models


router = APIRouter(tags=["system"])


@router.get("/status")
async def root():
    """
    Basic Jace backend identity/status endpoint.

    The root path "/" is deliberately reserved for desktop OAuth
    loopback callbacks (Google/Microsoft).
    """
    return {
        "name": settings.app_name,
        "version": settings.app_version,
        "status": "running",
    }


@router.get("/health", response_model=HealthResponse)
async def health():
    try:
        models = (await asyncio.wait_for(get_models(), timeout=2.0)
                  if settings.cloud_chat_cutover else await get_models())
        return HealthResponse(
            status="ok",
            ollama_connected=True,
            app_version=settings.app_version,
            default_model=settings.default_model,
            embedding_model=settings.embedding_model,
            installed_models=len(models),
            database_path=(
                str(DATABASE_PATH)
                if settings.database_backend == "sqlite"
                else settings.database_backend
            ),
        )
    except (OllamaUnavailableError, OllamaRequestError, TimeoutError):
        return HealthResponse(
            status="degraded",
            ollama_connected=False,
            app_version=settings.app_version,
            default_model=settings.default_model,
            embedding_model=settings.embedding_model,
            installed_models=0,
            database_path=(
                str(DATABASE_PATH)
                if settings.database_backend == "sqlite"
                else settings.database_backend
            ),
        )


def _configured_cloud_catalog() -> list[str]:
    if not settings.cloud_chat_cutover:
        return []
    return configured_cloud_models(
        [
            settings.model_route_conversation_fast,
            settings.model_route_conversation_balanced,
            settings.model_route_reasoning_high,
            settings.model_route_coding_high,
            settings.model_route_research_high,
        ],
        cloud_egress=settings.privacy_cloud_egress_enabled,
        openai_enabled=bool(settings.openai_api_key.strip()),
        anthropic_enabled=bool(settings.anthropic_api_key.strip()),
    )


@router.get("/models", response_model=ModelsResponse)
async def models():
    cloud = _configured_cloud_catalog()
    local = []
    try:
        local = await asyncio.wait_for(get_models(), timeout=2.0) if cloud else await get_models()
    except (OllamaUnavailableError, OllamaRequestError, TimeoutError) as exc:
        if not cloud:
            # Preserve the original error semantics when no cloud models exist.
            status = 503 if isinstance(exc, (OllamaUnavailableError, TimeoutError)) else 502
            raise HTTPException(status_code=status, detail=str(exc)) from exc
    if settings.cloud_chat_cutover:
        # Keep explicit local override available even as legacy bare model
        # names are automatically routed to the configured cloud provider.
        local = [ModelInfo(name=f"ollama:{item.name}", size=item.size,
                           parameter_size=item.parameter_size,
                           quantization_level=item.quantization_level)
                 for item in local]
    auto = [ModelInfo(name="auto")] if settings.cloud_chat_cutover and settings.smart_routing_enabled and cloud else []
    return ModelsResponse(models=auto + [ModelInfo(name=route) for route in cloud] + local)

# JACE_4BS2_RUNTIME_INFO
@router.get("/runtime-info")
async def runtime_info():
    return {
        "name": settings.app_name,
        "server_name": settings.server_name,
        "version": settings.app_version,
        "status": "running",
        "mode": settings.mode,
        "public_url": settings.public_url or None,
        "database_backend": settings.database_backend,
    }

