from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIRECTORY = PROJECT_ROOT / "data"
DATABASE_PATH = DATA_DIRECTORY / "jace.db"
ATTACHMENTS_DIRECTORY = DATA_DIRECTORY / "attachments"
VOICE_DIRECTORY = DATA_DIRECTORY / "voice"
VOICE_KOKORO_DIRECTORY = VOICE_DIRECTORY / "kokoro"
VOICE_WHISPER_DIRECTORY = VOICE_DIRECTORY / "whisper"


class Settings(BaseSettings):
    app_name: str = "Jace"
    app_version: str = "0.10.0-beta.1"

    ollama_base_url: str = "http://127.0.0.1:11434"
    default_model: str = "qwen3.5:4b"
    embedding_model: str = "qwen3-embedding:0.6b"
    memory_extraction_model: str = "qwen3.5:4b"

    request_timeout_seconds: float = 180.0

    # Performance: keep the main chat model resident for the lifetime of a
    # normal Jace session. The embedding model can still expire sooner.
    ollama_keep_alive: str = "-1m"
    embedding_keep_alive: str = "20m"
    preload_default_model: bool = True
    preload_timeout_seconds: float = 120.0

    # 4096 was too tight once the personality, tool policy, memory context and
    # 20 messages of history were all in the prompt: Ollama silently truncated,
    # and the personality was among the first things to go. 8192 leaves real
    # headroom on a 4B model. Lower it again if VRAM becomes a problem.
    ollama_num_ctx: int = 8192

    # Bound prompt growth. Full history remains persisted in SQLite.
    history_max_messages: int = 20
    history_max_chars: int = 10_000

    memory_smart_retrieval: bool = True
    memory_extraction_idle_seconds: float = 4.0
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
    tool_result_max_chars: int = 8_000
    tool_audit_preview_chars: int = 1_500

    # How much assistant text is held back on a tool-enabled turn while we wait
    # to see whether the model is calling a tool instead of answering. Ollama
    # emits tool_calls at the very start of a turn, so a small window is enough
    # to keep planning narration hidden while still streaming answers live.
    #   0  -> never hold back (fastest, tiny risk of showing planning text)
    #  -1  -> hold the entire turn (previous behaviour)
    tool_stream_buffer_chars: int = 160

    # Phase 5 internet access.
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
        "Chrome/131.0 Safari/537.36 Jace/0.9.0"
    )
    browser_enabled: bool = True
    browser_timeout_seconds: float = 25.0
    browser_wait_after_load_ms: int = 350
    browser_max_page_chars: int = 7_000
    browser_max_links: int = 25

    # Phase 6 controlled local-computer access.
    computer_enabled: bool = True
    computer_allow_sensitive_files: bool = False
    computer_max_read_bytes: int = 1_000_000
    computer_max_write_chars: int = 200_000
    computer_search_max_files: int = 1_500
    computer_search_max_results: int = 50
    computer_command_output_chars: int = 12_000
    computer_command_inherit_environment: bool = False
    computer_command_max_timeout_seconds: int = 900

    # Phase 7 multimodal attachments.
    multimodal_enabled: bool = True
    attachment_max_count: int = 6
    attachment_image_max_bytes: int = 12_000_000
    attachment_document_max_bytes: int = 25_000_000
    attachment_audio_max_bytes: int = 75_000_000
    attachment_text_max_chars: int = 14_000
    attachment_model_image_max_edge: int = 1600
    attachment_pdf_render_pages: int = 3
    attachment_pdf_render_scale: float = 1.35

    # Qwen3.5:4b is already multimodal in current Ollama builds. This optional
    # override lets a future specialist vision model be selected without a code
    # change; leave blank to use the active conversation model.
    vision_model: str = ""

    # Local audio transcription. Runtime is intentionally local-only: Jace will
    # not silently download a Whisper model. Use scripts/install_audio_model.py
    # once if audio transcription is wanted.
    audio_enabled: bool = True
    audio_model: str = "base"
    audio_device: str = "cpu"
    audio_compute_type: str = "int8"
    audio_beam_size: int = 3
    audio_local_files_only: bool = True
    audio_download_root: Path = VOICE_WHISPER_DIRECTORY

    # Permissioned screen capture.
    screen_capture_enabled: bool = True
    screen_capture_max_edge: int = 1920

    # Phase 8 automation and scheduled tasks.
    automation_enabled: bool = True
    automation_scheduler_timezone: str = "Europe/London"
    automation_misfire_grace_seconds: int = 3600
    automation_max_parallel_runs: int = 2
    automation_default_timeout_seconds: int = 300
    automation_max_timeout_seconds: int = 1800
    automation_max_tool_steps: int = 6
    automation_run_history_limit: int = 200
    automation_notification_poll_seconds: int = 10
    automation_max_result_chars: int = 20_000
    automation_watcher_state_chars: int = 10_000


    # Phase 10B local voice / presence. Push-to-talk is intentionally the
    # default: the microphone is opened only while the user is actively
    # holding the control in the desktop UI. STT uses the existing local
    # faster-whisper model; TTS uses local Kokoro ONNX model files.
    voice_enabled: bool = True
    voice_default_voice: str = "bm_lewis"
    voice_default_speed: float = 1.06
    voice_default_language: str = "en-gb"
    voice_tts_max_chars: int = 900
    voice_recording_max_bytes: int = 20_000_000
    voice_kokoro_model_path: Path = VOICE_KOKORO_DIRECTORY / "kokoro-v1.0.onnx"
    voice_kokoro_voices_path: Path = VOICE_KOKORO_DIRECTORY / "voices-v1.0.bin"

    # Push-to-talk transcription latency. beam_size=5 roughly doubles decode time
    # for no meaningful accuracy gain on short clean utterances, and per-segment
    # conditioning is pointless for a single push-to-talk clip.
    voice_stt_beam_size: int = 1
    voice_stt_vad_filter: bool = True
    voice_stt_vad_min_silence_ms: int = 300
    voice_stt_condition_on_previous_text: bool = False
    # Warm Kokoro at startup so the first spoken reply does not pay model load.
    voice_warm_tts_on_status: bool = True

    # Phase 9 interactive GUI control. This is intentionally Windows-first.
    interactive_control_enabled: bool = True
    interactive_default_max_steps: int = 30
    interactive_max_steps: int = 80
    interactive_session_timeout_seconds: int = 1800
    interactive_action_pause_ms: int = 220
    interactive_type_interval_ms: int = 18
    interactive_auto_capture_after_action: bool = True
    interactive_capture_max_edge: int = 1600
    interactive_store_screenshots_default: bool = False
    interactive_max_text_chars: int = 4_000
    interactive_max_hotkey_keys: int = 5

    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="JACE_",
        extra="ignore",
    )


settings = Settings()
