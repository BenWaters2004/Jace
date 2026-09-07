from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from jace.api.chat import router as chat_router
from jace.api.conversations import router as conversations_router
from jace.api.memories import router as memories_router
from jace.api.settings import router as settings_router
from jace.api.system import router as system_router
from jace.config import settings
from jace.database import close_database, init_database


@asynccontextmanager
async def lifespan(app: FastAPI):
    del app
    await init_database()
    yield
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
app.include_router(conversations_router)
app.include_router(chat_router)
