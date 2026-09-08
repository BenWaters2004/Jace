from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIRECTORY = PROJECT_ROOT / "data"
DATABASE_PATH = DATA_DIRECTORY / "jace.db"


class Settings(BaseSettings):
    app_name: str = "Jace"
    app_version: str = "0.5.1"

    ollama_base_url: str = "http://127.0.0.1:11434"
    default_model: str = "qwen3.5:4b"
    embedding_model: str = "qwen3-embedding:0.6b"
    memory_extraction_model: str = "qwen3.5:4b"

    request_timeout_seconds: float = 180.0

    # Performance: keep the main chat model resident for the lifetime of a
    # normal Jace session. The embedding model can still expire sooner.
    ollama_keep_alive: int | str = -1
    embedding_keep_alive: str = "20m"
    preload_default_model: bool = True
    preload_timeout_seconds: float = 120.0
    ollama_num_ctx: int = 4096

    # Bound prompt growth. This keeps recent context without allowing a long
    # chat to grow indefinitely and slow prompt evaluation every turn.
    history_max_messages: int = 20
    history_max_chars: int = 10_000

    # Smart memory retrieval avoids loading/running the embedding model for
    # greetings and generic requests that do not need personal/project context.
    memory_smart_retrieval: bool = True

    # Automatic memory work yields to interactive chat traffic.
    memory_extraction_idle_seconds: float = 4.0

    # Environment-level feature switches. Persistent user settings can be
    # more restrictive, but they cannot enable a feature disabled here.
    memory_enabled: bool = True
    memory_auto_extract: bool = True
    memory_top_k: int = 6
    memory_min_similarity: float = 0.50
    memory_max_candidates: int = 5
    memory_min_importance: float = 0.55
    memory_min_confidence: float = 0.70
    memory_reconcile_limit: int = 5
    memory_reconcile_min_similarity: float = 0.55
    memory_forget_min_similarity: float = 0.60

    # Agent/tool settings.
    tools_enabled: bool = True
    smart_tool_routing: bool = True
    max_tool_steps: int = 7
    tool_approval_timeout_seconds: float = 300.0

    # Smaller result budgets keep tool follow-up turns inside the 4K-ish local
    # context budget and reduce prompt-evaluation latency.
    tool_result_max_chars: int = 8_000
    tool_audit_preview_chars: int = 1_500

    # Phase 5 internet access. These are read-only network capabilities.
    web_enabled: bool = True
    web_search_region: str = "uk-en"
    web_search_safesearch: str = "moderate"
    web_search_backend: str = "auto"
    web_search_timeout_seconds: float = 12.0
    web_search_max_results: int = 6

    web_request_timeout_seconds: float = 20.0
    web_max_redirects: int = 5
    web_max_download_bytes: int = 2_000_000
    web_page_max_chars: int = 6_500
    web_max_links: int = 20
    web_user_agent: str = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0 Safari/537.36 Jace/0.5.1"
    )

    # JavaScript-rendered read-only browser.
    browser_enabled: bool = True
    browser_timeout_seconds: float = 25.0
    browser_wait_after_load_ms: int = 350
    browser_max_page_chars: int = 7_000
    browser_max_links: int = 25

    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="JACE_",
        extra="ignore",
    )


settings = Settings()
