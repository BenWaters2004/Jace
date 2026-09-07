import html
import re
from dataclasses import dataclass
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup

from jace.config import settings
from jace.web.security import UnsafeWebAddressError, validate_public_url


class WebFetchError(RuntimeError):
    pass


@dataclass
class FetchedPage:
    url: str
    title: str
    description: str
    text: str
    links: list[dict[str, str]]
    content_type: str
    status_code: int


def _clean_text(value: str) -> str:
    value = html.unescape(value)
    value = value.replace("\r", "\n")
    value = re.sub(r"[ \t]+", " ", value)
    value = re.sub(r"\n[ \t]+", "\n", value)
    value = re.sub(r"\n{3,}", "\n\n", value)
    return value.strip()


def _extract_html(body: bytes, base_url: str, max_chars: int, max_links: int) -> tuple[str, str, str, list[dict[str, str]]]:
    soup = BeautifulSoup(body, "html.parser")

    for tag in soup(["script", "style", "noscript", "template", "svg", "canvas"]):
        tag.decompose()

    title = _clean_text(soup.title.get_text(" ", strip=True)) if soup.title else ""

    description = ""
    meta = soup.find("meta", attrs={"name": re.compile(r"^description$", re.I)})
    if meta and meta.get("content"):
        description = _clean_text(str(meta.get("content")))[:1_000]

    main = soup.find("main") or soup.find("article") or soup.body or soup
    text = _clean_text(main.get_text("\n", strip=True))[:max_chars]

    links: list[dict[str, str]] = []
    seen: set[str] = set()
    for anchor in soup.find_all("a", href=True):
        raw_href = str(anchor.get("href") or "").strip()
        absolute = urljoin(base_url, raw_href)
        if not absolute.startswith(("http://", "https://")):
            continue
        if absolute in seen:
            continue
        seen.add(absolute)
        label = _clean_text(anchor.get_text(" ", strip=True)) or absolute
        links.append({"text": label[:300], "url": absolute})
        if len(links) >= max_links:
            break

    return title, description, text, links


async def fetch_web_page(url: str, *, max_chars: int | None = None) -> FetchedPage:
    if not settings.web_enabled:
        raise WebFetchError("Internet access is disabled by Jace's backend configuration.")

    max_chars = max(1_000, min(max_chars or settings.web_page_max_chars, settings.web_page_max_chars))
    current_url = await validate_public_url(url)
    timeout = httpx.Timeout(
        connect=min(10.0, settings.web_request_timeout_seconds),
        read=settings.web_request_timeout_seconds,
        write=10.0,
        pool=10.0,
    )

    headers = {
        "User-Agent": settings.web_user_agent,
        "Accept": "text/html,application/xhtml+xml,text/plain,application/json;q=0.8,*/*;q=0.2",
        "Accept-Language": "en-GB,en;q=0.8",
    }

    final_url = current_url
    status_code = 0
    response_headers: dict[str, str] = {}
    raw = b""

    async with httpx.AsyncClient(timeout=timeout, follow_redirects=False, headers=headers, trust_env=False) as client:
        for redirect_index in range(settings.web_max_redirects + 1):
            current_url = await validate_public_url(current_url)

            try:
                async with client.stream("GET", current_url) as response:
                    status_code = response.status_code
                    response_headers = dict(response.headers)
                    final_url = await validate_public_url(str(response.url))

                    if response.status_code in {301, 302, 303, 307, 308}:
                        location = response.headers.get("location")
                        if not location:
                            raise WebFetchError("The web page returned an invalid redirect.")
                        if redirect_index >= settings.web_max_redirects:
                            raise WebFetchError("The web page redirected too many times.")
                        current_url = urljoin(current_url, location)
                        continue

                    chunks: list[bytes] = []
                    total = 0
                    async for chunk in response.aiter_bytes():
                        total += len(chunk)
                        if total > settings.web_max_download_bytes:
                            raise WebFetchError(
                                f"The page is larger than Jace's {settings.web_max_download_bytes:,}-byte read limit."
                            )
                        chunks.append(chunk)
                    raw = b"".join(chunks)
                    break

            except httpx.TimeoutException as exc:
                raise WebFetchError("The web page request timed out.") from exc
            except WebFetchError:
                raise
            except httpx.HTTPError as exc:
                raise WebFetchError(f"Web page request failed: {exc}") from exc
        else:
            raise WebFetchError("The web page redirected too many times.")

    if status_code >= 400:
        raise WebFetchError(f"The web page returned HTTP {status_code}.")

    content_type = response_headers.get("content-type", "").split(";", 1)[0].strip().lower()

    if content_type in {"text/html", "application/xhtml+xml", ""}:
        title, description, text, links = _extract_html(
            raw,
            final_url,
            max_chars,
            settings.web_max_links,
        )
    elif content_type.startswith("text/") or content_type in {"application/json", "application/ld+json"}:
        charset = "utf-8"
        type_header = response_headers.get("content-type", "")
        match = re.search(r"charset=([^;\s]+)", type_header, flags=re.I)
        if match:
            charset = match.group(1).strip('"\'')
        try:
            decoded = raw.decode(charset, errors="replace")
        except LookupError:
            decoded = raw.decode("utf-8", errors="replace")
        title = ""
        description = ""
        text = _clean_text(decoded)[:max_chars]
        links = []
    else:
        raise WebFetchError(
            f"Unsupported content type: {content_type or 'unknown'}. Phase 5 reads HTML, text and JSON pages."
        )

    if not text:
        raise WebFetchError("No readable text was found on the page.")

    return FetchedPage(
        url=final_url,
        title=title,
        description=description,
        text=text,
        links=links,
        content_type=content_type or "text/html",
        status_code=status_code,
    )
