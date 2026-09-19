import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from jace.agents import start_agent_manager, stop_agent_manager
from jace.ai.client import close_ollama_client
from jace.ai.engine import OllamaRequestError, OllamaUnavailableError, warm_model
from jace.automations.scheduler import start_automation_scheduler, stop_automation_scheduler
from jace.auth.middleware import AuthMiddleware
from jace.api.agents import router as agents_router
from jace.api.auth import router as auth_router
from jace.api.attachments import router as attachments_router
from jace.api.automations import router as automations_router
from jace.api.calendar import router as calendar_router
from jace.api.chat import router as chat_router
# JACE_STEP4A1_CONNECTIONS_FOUNDATION
from jace.api.capabilities import router as capabilities_router
from jace.api.connections import callback_router as connections_callback_router, router as connections_router
from jace.api.computer import router as computer_router
from jace.api.control import router as control_router
from jace.api.conversations import router as conversations_router
from jace.api.devices import router as devices_router
from jace.api.memories import router as memories_router
from jace.api.runtime import router as runtime_router
from jace.api.runtime_stream import router as runtime_stream_router
from jace.api.settings import router as settings_router
from jace.api.security import router as security_router
from jace.api.system import router as system_router
from jace.api.model_gateway import router as model_gateway_router
from jace.api.privacy import router as privacy_router
from jace.api.tools import router as tools_router
from jace.api.voice import router as voice_router
from jace.calendar.service import ensure_default_jace_calendar
from jace.config import settings
from jace.database import SessionLocal, close_database, init_database
from jace.db.settings import get_or_create_assistant_settings
from jace.runtime import runtime_events
from jace.tools import ensure_tools_registered
from jace.tools.permissions import ensure_tool_permissions


logger = logging.getLogger("uvicorn.error")


@asynccontextmanager
async def lifespan(app: FastAPI):
    del app


    # JACE_4BS2_STARTUP_MODE
    logger.info(
        "Starting %s in %s mode",
        settings.server_name,
        settings.mode,
    )

    ensure_tools_registered()

    # Importing the agents API above loads the Phase 11A SQLAlchemy models before
    # create_all() runs, so the new local agent tables are created automatically.
    await init_database()
    await runtime_events.initialize()

    preload_model_name = settings.default_model

    async with SessionLocal() as session:
        await ensure_tool_permissions(session)
        # JACE_STEP4C4A_UNIFIED_CALENDAR_CORE
        await ensure_default_jace_calendar(session)
        profile = await get_or_create_assistant_settings(session)
        await session.commit()
        if profile.default_model:
            preload_model_name = profile.default_model

    if settings.preload_default_model:
        try:
            logger.info("Preloading Jace model %s...", preload_model_name)
            await warm_model(preload_model_name)
            logger.info("Jace model preload complete: %s", preload_model_name)
        except (OllamaUnavailableError, OllamaRequestError) as exc:
            # Jace should still start if Ollama is temporarily unavailable.
            logger.warning("Jace model preload skipped: %s", exc)

    await start_automation_scheduler()
    await start_agent_manager()

    await runtime_events.publish(
        "jace.state.changed",
        state="idle",
        reason="backend_ready",
    )

    yield

    await runtime_events.publish(
        "jace.state.changed",
        state="offline",
        reason="backend_stopping",
    )

    await stop_agent_manager()
    await stop_automation_scheduler()
    await close_ollama_client()
    await close_database()


app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description="Jace Core backend for the Jace AI assistant.",
    lifespan=lifespan,
)

# JACE_4BS3_AUTH_MIDDLEWARE
app.add_middleware(AuthMiddleware)

# JACE_4BS2_MODE_AWARE_CORS
#
# Local mode keeps localhost/Tauri development working.
# Server mode deliberately has no wildcard fallback.
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.configured_cors_origins,
    allow_origin_regex=(
        (
            r"^(http://localhost(:\d+)?|"
            r"http://127\.0\.0\.1(:\d+)?|"
            r"http://tauri\.localhost|"
            r"https://tauri\.localhost|"
            r"tauri://localhost)$"
        )
        if settings.mode == "local"
        else None
    ),
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=[
        "Authorization",
        "Content-Type",
        "X-Jace-Client-ID",
        "X-Jace-Request-ID",
    ],
)

app.include_router(system_router)
app.include_router(model_gateway_router)
app.include_router(privacy_router)
app.include_router(auth_router)
app.include_router(voice_router)
app.include_router(attachments_router)
app.include_router(automations_router)
app.include_router(calendar_router)
app.include_router(agents_router)
app.include_router(settings_router)
app.include_router(security_router)
app.include_router(connections_router)
app.include_router(connections_callback_router)
app.include_router(capabilities_router)
app.include_router(memories_router)
app.include_router(runtime_router)
app.include_router(runtime_stream_router)
app.include_router(computer_router)
app.include_router(control_router)
app.include_router(tools_router)
app.include_router(conversations_router)
app.include_router(devices_router)
app.include_router(chat_router)
