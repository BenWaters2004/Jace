import asyncio
from typing import Literal

from jace.config import settings
from jace.web.security import UnsafeWebAddressError, is_obviously_public_search_result, validate_public_url


class WebSearchError(RuntimeError):
    pass


Freshness = Literal["day", "week", "month", "year", "any"]
SearchKind = Literal["web", "news"]


_TIMELIMITS: dict[Freshness, str | None] = {
    "day": "d",
    "week": "w",
    "month": "m",
    "year": "y",
    "any": None,
}


def _search_sync(
    query: str,
    *,
    kind: SearchKind,
    freshness: Freshness,
    max_results: int,
) -> list[dict]:
    try:
        from ddgs import DDGS
    except ImportError as exc:
        raise WebSearchError(
            "The DDGS search dependency is not installed. Run: pip install -r requirements.txt"
        ) from exc

    engine = DDGS(timeout=int(max(3, settings.web_search_timeout_seconds)))
    common = {
        "query": query,
        "region": settings.web_search_region,
        "safesearch": settings.web_search_safesearch,
        "timelimit": _TIMELIMITS[freshness],
        "max_results": max_results,
        "backend": settings.web_search_backend,
    }

    try:
        raw = engine.news(**common) if kind == "news" else engine.text(**common)
    except Exception as exc:
        raise WebSearchError(f"Web search failed: {exc}") from exc

    results: list[dict] = []
    for item in raw or []:
        if not isinstance(item, dict):
            continue

        url = str(item.get("url") or item.get("href") or "").strip()
        if not url or not is_obviously_public_search_result(url):
            continue

        title = " ".join(str(item.get("title") or "Untitled").split())
        snippet = " ".join(str(item.get("body") or item.get("description") or "").split())
        source = str(item.get("source") or "").strip() or None
        date = str(item.get("date") or item.get("published") or "").strip() or None

        results.append(
            {
                "title": title[:500],
                "url": url,
                "snippet": snippet[:1_500],
                "source": source,
                "date": date,
            }
        )

        if len(results) >= max_results:
            break

    return results


async def web_search(
    query: str,
    *,
    kind: SearchKind = "web",
    freshness: Freshness = "any",
    max_results: int = 5,
) -> list[dict]:
    if not settings.web_enabled:
        raise WebSearchError("Internet access is disabled by Jace's backend configuration.")

    max_results = max(1, min(max_results, settings.web_search_max_results))
    query = " ".join(query.split())
    if not query:
        raise WebSearchError("Search query cannot be empty.")

    results = await asyncio.to_thread(
        _search_sync,
        query,
        kind=kind,
        freshness=freshness,
        max_results=max_results,
    )

    safe_results: list[dict] = []
    for result in results:
        try:
            result["url"] = await validate_public_url(result["url"])
        except (UnsafeWebAddressError, ValueError):
            continue
        safe_results.append(result)

    return safe_results
