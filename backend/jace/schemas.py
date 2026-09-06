from typing import Literal

from pydantic import BaseModel, Field


class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(
        min_length=1
    )


class ChatRequest(BaseModel):
    model: str
    messages: list[ChatMessage]
    system_prompt: str = ""


class ModelInfo(BaseModel):
    name: str
    size: int | None = None
    parameter_size: str | None = None
    quantization_level: str | None = None


class ModelsResponse(BaseModel):
    models: list[ModelInfo]


class HealthResponse(BaseModel):
    status: str
    ollama_connected: bool
    app_version: str
    default_model: str
    installed_models: int