from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


PROJECT_ROOT = Path(__file__).resolve().parents[2]

DATA_DIRECTORY = PROJECT_ROOT / "data"

DATABASE_PATH = DATA_DIRECTORY / "jace.db"


class Settings(BaseSettings):
    app_name: str = "Jace"
    app_version: str = "0.2.2"

    ollama_base_url: str = "http://127.0.0.1:11434"

    # Main conversational model.
    default_model: str = "qwen3.5:4b"

    # Dedicated semantic-memory model.
    embedding_model: str = "qwen3-embedding:0.6b"

    # Model used to decide what should be remembered.
    memory_extraction_model: str = "qwen3.5:4b"

    request_timeout_seconds: float = 180.0

    ollama_keep_alive: str = "30m"
    embedding_keep_alive: str = "30m"

    ollama_think: bool = False

    # Retrieval.
    memory_top_k: int = 6
    memory_min_similarity: float = 0.30

    # Automatic extraction.
    memory_auto_extract: bool = True
    memory_max_candidates: int = 5

    # Reject weak inferred memories.
    memory_min_importance: float = 0.55
    memory_min_confidence: float = 0.70

    # Existing-memory comparison.
    memory_reconcile_limit: int = 5
    memory_reconcile_min_similarity: float = 0.55

    # Explicit "forget that..." commands.
    memory_forget_min_similarity: float = 0.60

    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="JACE_",
        extra="ignore",
    )


settings = Settings()