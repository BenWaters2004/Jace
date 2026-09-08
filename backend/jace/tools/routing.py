import re
from urllib.parse import urlparse


ALL_TOOL_NAMES = {
    "calculator",
    "current_datetime",
    "search_memory",
    "search_conversations",
    "rename_current_conversation",
    "create_memory",
    "deactivate_memory",
    "web_search",
    "read_web_page",
    "browser_read_page",
}


def _contains_url(text: str) -> bool:
    for candidate in re.findall(r"https?://[^\s<>()]+", text, flags=re.IGNORECASE):
        parsed = urlparse(candidate.rstrip(".,;:!?)]}"))
        if parsed.scheme in {"http", "https"} and parsed.netloc:
            return True
    return False


def _looks_like_arithmetic(text: str) -> bool:
    stripped = text.strip()
    if re.fullmatch(r"[\d\s().,+\-*/%^]+", stripped) and re.search(r"\d", stripped):
        return True
    return bool(
        re.search(
            r"\b(?:calculate|calculator|work out|what is|what's)\b.{0,40}\d+\s*(?:\+|-|\*|/|%|\^)",
            text,
            flags=re.IGNORECASE,
        )
    )


def route_tool_names(message: str) -> set[str]:
    """Return only tool schemas that are plausibly useful for this request."""
    text = " ".join(message.strip().split())
    lowered = text.lower()
    selected: set[str] = set()

    if not text:
        return selected

    # Explicit escape hatch for development/debugging.
    if re.search(r"\b(?:use|show|list) all tools\b", lowered):
        return set(ALL_TOOL_NAMES)

    if _looks_like_arithmetic(text):
        selected.add("calculator")

    if re.search(
        r"\b(?:current time|what time|time is it|current date|today'?s date|what date|day is it|date and time)\b",
        lowered,
    ):
        selected.add("current_datetime")

    if re.search(
        r"\b(?:remember|recall|memory|what do you know about me|what do you remember|my saved memory|saved memories)\b",
        lowered,
    ):
        selected.add("search_memory")

    if re.search(
        r"\b(?:past conversations?|previous conversations?|last conversation|chat history|conversation history|search (?:my )?(?:past |previous )?(?:chats|conversations)|what did (?:i|we) (?:say|discuss|talk about)|what were we (?:discussing|talking about))\b",
        lowered,
    ):
        selected.add("search_conversations")

    if re.search(r"\b(?:rename|retitle)\b.{0,30}\b(?:chat|conversation|this)\b", lowered):
        selected.add("rename_current_conversation")

    # Explicit memory management via tools. The dedicated remember/forget
    # command path still handles the common natural-language forms first.
    if re.search(r"\b(?:create|add|save|store)\b.{0,25}\bmemory\b", lowered):
        selected.add("create_memory")
    if re.search(r"\b(?:deactivate|disable|remove)\b.{0,25}\bmemory\b", lowered):
        selected.update({"search_memory", "deactivate_memory"})

    has_url = _contains_url(text)
    if has_url:
        # Static reading is preferred; browser_read_page is supplied as a
        # fallback for client-rendered pages, but the model need not use it.
        selected.update({"read_web_page", "browser_read_page"})

    if re.search(
        r"\b(?:search (?:the )?web|search online|look online|look up(?: online)?|google|latest|recent news|news about|find online|internet search|current information|current info)\b",
        lowered,
    ):
        selected.update({"web_search", "read_web_page", "browser_read_page"})

    if re.search(
        r"\b(?:weather|forecast|stock price|share price|price of|current president|current prime minister|current ceo|latest version|latest release|today'?s news|recent developments)\b",
        lowered,
    ):
        selected.update({"web_search", "read_web_page", "browser_read_page"})

    # Research phrasing often needs search even without the literal word web.
    if re.search(r"\b(?:research|find sources|find articles|find documentation|latest documentation|find information about)\b", lowered):
        selected.update({"web_search", "read_web_page", "browser_read_page"})

    return selected
