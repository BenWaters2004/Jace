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
    "list_computer_workspaces",
    "list_workspace_files",
    "read_workspace_file",
    "search_workspace_files",
    "workspace_file_info",
    "create_workspace_directory",
    "write_workspace_file",
    "replace_workspace_text",
    "move_workspace_path",
    "delete_workspace_file",
    "run_workspace_command",
    "inspect_attachment",
    "inspect_workspace_media",
    "capture_screen",
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

    if re.search(r"\b(?:create|add|save|store)\b.{0,25}\bmemory\b", lowered):
        selected.add("create_memory")
    if re.search(r"\b(?:deactivate|disable|remove)\b.{0,25}\bmemory\b", lowered):
        selected.update({"search_memory", "deactivate_memory"})

    has_url = _contains_url(text)
    if has_url:
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

    if re.search(
        r"\b(?:research|find sources|find articles|find documentation|latest documentation|find information about)\b",
        lowered,
    ):
        selected.update({"web_search", "read_web_page", "browser_read_page"})

    computer_hint = re.search(
        r"\b(?:my (?:file|files|folder|folders|directory|directories|project|repo|repository|codebase)|"
        r"local (?:file|files|folder|folders|project|repo|repository)|workspace|working tree|source file|code file)\b",
        lowered,
    )

    if computer_hint or re.search(
        r"\b(?:list|show|find|search|read|open|inspect)\b.{0,30}\b(?:files?|folders?|directories|repo|repository|codebase)\b",
        lowered,
    ):
        selected.add("list_computer_workspaces")

    if re.search(r"\b(?:list|show|browse|what(?:'s| is) in)\b.{0,35}\b(?:files?|folders?|directories|workspace|repo|repository)\b", lowered):
        selected.update({"list_computer_workspaces", "list_workspace_files"})

    if re.search(r"\b(?:read|open|inspect|show|view|look at)\b.{0,40}\b(?:file|source|code|readme|config|configuration)\b", lowered):
        selected.update({"list_computer_workspaces", "read_workspace_file", "workspace_file_info"})

    if re.search(r"\b(?:find|search|locate|grep)\b.{0,35}\b(?:file|files|text|code|project|repo|repository|workspace)\b", lowered):
        selected.update({"list_computer_workspaces", "search_workspace_files", "read_workspace_file"})

    if re.search(r"\b(?:edit|modify|change|update|fix|refactor|replace|write|create)\b.{0,45}\b(?:file|code|source|component|module|class|function|config|configuration)\b", lowered):
        selected.update({
            "list_computer_workspaces",
            "search_workspace_files",
            "read_workspace_file",
            "workspace_file_info",
            "write_workspace_file",
            "replace_workspace_text",
        })

    if re.search(r"\b(?:create|make|add)\b.{0,30}\b(?:folder|directory)\b", lowered):
        selected.update({"list_computer_workspaces", "create_workspace_directory"})

    if re.search(r"\b(?:rename|move)\b.{0,30}\b(?:file|folder|directory|path)\b", lowered):
        selected.update({"list_computer_workspaces", "workspace_file_info", "move_workspace_path"})

    if re.search(r"\b(?:delete|remove)\b.{0,30}\b(?:file)\b", lowered):
        selected.update({"list_computer_workspaces", "workspace_file_info", "delete_workspace_file"})

    if re.search(r"\b(?:run|execute|build|test|tests|lint|format|git status|check the project)\b", lowered) and (
        computer_hint or re.search(r"\b(?:project|repo|repository|workspace|code|build|tests?|lint|git)\b", lowered)
    ):
        selected.update({"list_computer_workspaces", "run_workspace_command"})

    # Phase 7 multimodal. User-attached media is injected directly in the
    # current turn. These schemas are for later references, workspace media,
    # and permissioned live screen capture.
    if re.search(
        r"\b(?:attachment|attached|image|photo|picture|screenshot|pdf|document|audio|voice note|recording)\b",
        lowered,
    ):
        selected.add("inspect_attachment")

    if re.search(
        r"\b(?:look at|inspect|analyse|analyze|read|open|view|transcribe)\b.{0,45}"
        r"\b(?:image|photo|picture|pdf|document|audio|recording|voice note)\b",
        lowered,
    ) and computer_hint:
        selected.update({"list_computer_workspaces", "inspect_workspace_media"})

    if re.search(
        r"\b(?:look at|inspect|see|capture|take (?:a )?screenshot of|what(?:'s| is) on)\b.{0,35}"
        r"\b(?:my |the |current )?(?:screen|display|monitor|desktop)\b",
        lowered,
    ):
        selected.add("capture_screen")

    return selected
