import asyncio

import httpx


_client: httpx.AsyncClient | None = None
_client_lock = asyncio.Lock()


async def get_ollama_client() -> httpx.AsyncClient:
    """Return one reusable HTTP client for local Ollama API traffic."""
    global _client

    if _client is not None and not _client.is_closed:
        return _client

    async with _client_lock:
        if _client is None or _client.is_closed:
            _client = httpx.AsyncClient(
                timeout=None,
                limits=httpx.Limits(
                    max_connections=10,
                    max_keepalive_connections=5,
                    keepalive_expiry=60.0,
                ),
            )

    return _client


async def close_ollama_client() -> None:
    """Close the shared Ollama client during FastAPI shutdown."""
    global _client

    async with _client_lock:
        if _client is not None and not _client.is_closed:
            await _client.aclose()
        _client = None
