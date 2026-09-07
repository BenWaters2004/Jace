import asyncio
from dataclasses import dataclass
from urllib.parse import urljoin, urlsplit

from jace.config import settings
from jace.web.fetch import _clean_text
from jace.web.security import UnsafeWebAddressError, validate_public_url


class BrowserReadError(RuntimeError):
    pass


@dataclass
class BrowserPage:
    url: str
    title: str
    text: str
    links: list[dict[str, str]]


async def read_browser_page(
    url: str,
    *,
    wait_ms: int | None = None,
    max_chars: int | None = None,
) -> BrowserPage:
    if not settings.web_enabled:
        raise BrowserReadError("Internet access is disabled by Jace's backend configuration.")
    if not settings.browser_enabled:
        raise BrowserReadError("The JavaScript browser is disabled by Jace's backend configuration.")

    try:
        from playwright.async_api import Error as PlaywrightError
        from playwright.async_api import TimeoutError as PlaywrightTimeoutError
        from playwright.async_api import async_playwright
    except ImportError as exc:
        raise BrowserReadError(
            "Playwright is not installed. Run: pip install -r requirements.txt"
        ) from exc

    target = await validate_public_url(url)
    wait_ms = max(0, min(wait_ms if wait_ms is not None else settings.browser_wait_after_load_ms, 3_000))
    max_chars = max(1_000, min(max_chars or settings.browser_max_page_chars, settings.browser_max_page_chars))

    host_cache: dict[tuple[str, int], bool] = {}

    async def network_allowed(candidate: str) -> bool:
        parsed = urlsplit(candidate)
        if parsed.scheme in {"data", "blob", "about"}:
            return True
        if parsed.scheme not in {"http", "https"}:
            return False

        host = parsed.hostname
        if not host:
            return False
        try:
            port = parsed.port or (443 if parsed.scheme == "https" else 80)
        except ValueError:
            return False
        key = (host.lower(), port)
        if key in host_cache:
            return host_cache[key]

        try:
            await validate_public_url(candidate)
        except (UnsafeWebAddressError, ValueError):
            host_cache[key] = False
        else:
            host_cache[key] = True
        return host_cache[key]

    timeout_ms = int(settings.browser_timeout_seconds * 1_000)

    try:
        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(headless=True)
            context = await browser.new_context(
                user_agent=settings.web_user_agent,
                locale="en-GB",
                accept_downloads=False,
                service_workers="block",
                java_script_enabled=True,
            )
            async def route_handler(route):
                if await network_allowed(route.request.url):
                    await route.continue_()
                else:
                    await route.abort("blockedbyclient")

            async def websocket_handler(web_socket_route):
                # Browser read is intentionally document-oriented. Blocking WebSockets
                # prevents a rendered page from opening a second uncontrolled network channel.
                await web_socket_route.close(code=1000, reason="Blocked by Jace read-only browser")

            await context.route("**/*", route_handler)
            await context.route_web_socket("**/*", websocket_handler)

            page = await context.new_page()
            await page.goto(target, wait_until="domcontentloaded", timeout=timeout_ms)

            if wait_ms:
                await page.wait_for_timeout(wait_ms)

            final_url = await validate_public_url(page.url)
            title = _clean_text(await page.title())
            body = page.locator("body")
            text = _clean_text(await body.inner_text(timeout=5_000))[:max_chars]

            raw_links = await page.locator("a[href]").evaluate_all(
                "els => els.slice(0, 100).map(a => ({text: (a.innerText || a.textContent || '').trim(), href: a.href}))"
            )

            links: list[dict[str, str]] = []
            seen: set[str] = set()
            for item in raw_links:
                if not isinstance(item, dict):
                    continue
                href = str(item.get("href") or "").strip()
                if not href:
                    continue
                absolute = urljoin(final_url, href)
                if not absolute.startswith(("http://", "https://")) or absolute in seen:
                    continue
                seen.add(absolute)
                links.append(
                    {
                        "text": _clean_text(str(item.get("text") or ""))[:300] or absolute,
                        "url": absolute,
                    }
                )
                if len(links) >= settings.browser_max_links:
                    break

            await context.close()
            await browser.close()

    except PlaywrightTimeoutError as exc:
        raise BrowserReadError("The browser timed out while loading the page.") from exc
    except PlaywrightError as exc:
        message = str(exc)
        if "Executable doesn't exist" in message or "browserType.launch" in message:
            raise BrowserReadError(
                "Chromium for Playwright is not installed. Run: python -m playwright install chromium"
            ) from exc
        raise BrowserReadError(f"Browser page read failed: {message}") from exc
    except asyncio.CancelledError:
        raise
    except UnsafeWebAddressError as exc:
        raise BrowserReadError(str(exc)) from exc

    if not text:
        raise BrowserReadError("No readable page text was found after rendering.")

    return BrowserPage(url=final_url, title=title, text=text, links=links)
