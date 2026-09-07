from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


PROJECT_ROOT = Path(__file__).resolve().parents[2]

DATA_DIRECTORY = PROJECT_ROOT / "data"

DATABASE_PATH = DATA_DIRECTORY / "jace.db"


class Settings(BaseSettings):
    app_name: str = "Jace"
    app_version: str = "0.2.1"

    ollama_base_url: str = "http://127.0.0.1:11434"

    # Main conversational model.
    default_model: str = "qwen3.5:4b"

    # Dedicated semantic-memory model.
    embedding_model: str = "qwen3-embedding:0.6b"

    request_timeout_seconds: float = 180.0

    # Keep both models loaded for a while after use.
    ollama_keep_alive: str = "30m"
    embedding_keep_alive: str = "30m"

    ollama_think: bool = False

    # Long-term memory retrieval.
    memory_top_k: int = 6
    memory_min_similarity: float = 0.30

    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="JACE_",
        extra="ignore",
    )


settings = Settings()