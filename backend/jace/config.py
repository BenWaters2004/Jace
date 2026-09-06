from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Jace"
    app_version: str = "0.1.1"

    ollama_base_url: str = "http://127.0.0.1:11434"
    default_model: str = "qwen3.5:4b"

    request_timeout_seconds: float = 180.0


    ollama_keep_alive: str = "30m"


    ollama_think: bool = False

    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="JACE_",
        extra="ignore",
    )


settings = Settings()