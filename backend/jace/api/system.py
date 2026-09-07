from fastapi import APIRouter, HTTPException

from jace.ai.engine import OllamaRequestError, OllamaUnavailableError, get_models
from jace.config import DATABASE_PATH, settings
from jace.schemas import HealthResponse, ModelsResponse


router = APIRouter(tags=["system"])


@router.get("/")
async def root():
    return {"name": settings.app_name, "version": settings.app_version, "status": "running"}


@router.get("/health", response_model=HealthResponse)
async def health():
    try:
        models = await get_models()
        return HealthResponse(
            status="ok",
            ollama_connected=True,
            app_version=settings.app_version,
            default_model=settings.default_model,
            embedding_model=settings.embedding_model,
            installed_models=len(models),
            database_path=str(DATABASE_PATH),
        )
    except (OllamaUnavailableError, OllamaRequestError):
        return HealthResponse(
            status="degraded",
            ollama_connected=False,
            app_version=settings.app_version,
            default_model=settings.default_model,
            embedding_model=settings.embedding_model,
            installed_models=0,
            database_path=str(DATABASE_PATH),
        )


@router.get("/models", response_model=ModelsResponse)
async def models():
    try:
        return ModelsResponse(models=await get_models())
    except OllamaUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except OllamaRequestError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
