import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from jace.ai.client import close_ollama_client
from jace.ai.engine import OllamaRequestError, OllamaUnavailableError, warm_model
from jace.api.chat import router as chat_router
from jace.api.computer import router as computer_router
from jace.api.conversations import router as conversations_router
from jace.api.memories import router as memories_router
from jace.api.settings import router as settings_router
from jace.api.system import router as system_router
from jace.api.tools import router as tools_router
from jace.config import settings
from jace.database import SessionLocal, close_database, init_database
from jace.db.settings import get_or_create_assistant_settings
from jace.tools import ensure_tools_registered
from jace.tools.permissions import ensure_tool_permissions


logger = logging.getLogger("uvicorn.error")


@asynccontextmanager
async def lifespan(app: FastAPI):
    del app

    ensure_tools_registered()
    await init_database()

    preload_model_name = settings.default_model
    async with SessionLocal() as session:
        await ensure_tool_permissions(session)
        profile = await get_or_create_assistant_settings(session)
        if profile.default_model:
            preload_model_name = profile.default_model

    if settings.preload_default_model:
        try:
            logger.info("Preloading Jace model %s...", preload_model_name)
            await warm_model(preload_model_name)
            logger.info("Jace model preload complete: %s", preload_model_name)
        except (OllamaUnavailableError, OllamaRequestError) as exc:
            # The app should still start if Ollama is temporarily unavailable.
            logger.warning("Jace model preload skipped: %s", exc)

    yield

    await close_ollama_client()
    await close_database()


app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description="Local backend for the Jace AI assistant.",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=(
        r"^(http://localhost(:\d+)?|"
        r"http://127\.0\.0\.1(:\d+)?|"
        r"http://tauri\.localhost|"
        r"https://tauri\.localhost|"
        r"tauri://localhost)$"
    ),
    allow_credentials=False,
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type"],
)

app.include_router(system_router)
app.include_router(settings_router)
app.include_router(memories_router)
app.include_router(computer_router)
app.include_router(tools_router)
app.include_router(conversations_router)
app.include_router(chat_router)
