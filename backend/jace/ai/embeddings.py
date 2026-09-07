import httpx

from jace.config import settings


class EmbeddingUnavailableError(Exception):
    pass


class EmbeddingRequestError(Exception):
    pass


async def embed_text(text: str) -> list[float]:
    cleaned = text.strip()
    if not cleaned:
        raise ValueError("Cannot create an embedding for empty text.")

    payload = {
        "model": settings.embedding_model,
        "input": cleaned,
        "keep_alive": settings.embedding_keep_alive,
        "truncate": True,
    }
    url = f"{settings.ollama_base_url}/api/embed"
    timeout = httpx.Timeout(connect=10.0, read=120.0, write=30.0, pool=10.0)

    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(url, json=payload)
            response.raise_for_status()
    except httpx.ConnectError as exc:
        raise EmbeddingUnavailableError("Could not connect to Ollama while generating an embedding.") from exc
    except httpx.TimeoutException as exc:
        raise EmbeddingUnavailableError("The embedding model took too long to respond.") from exc
    except httpx.HTTPStatusError as exc:
        try:
            message = exc.response.json().get("error", exc.response.text)
        except Exception:
            message = exc.response.text
        raise EmbeddingRequestError(f"Embedding request failed: {message}") from exc

    data = response.json()
    embeddings = data.get("embeddings")
    if not isinstance(embeddings, list) or not embeddings or not isinstance(embeddings[0], list):
        raise EmbeddingRequestError("Ollama returned an invalid embedding response.")
    return [float(value) for value in embeddings[0]]
