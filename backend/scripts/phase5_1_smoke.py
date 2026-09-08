"""Local smoke tests for the Jace v0.5.1 performance pass."""

import sys
from pathlib import Path
from types import SimpleNamespace

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from jace.config import settings  # noqa: E402
from jace.db.conversations import model_history  # noqa: E402
from jace.memory.gating import should_retrieve_memory  # noqa: E402
from jace.tools.routing import route_tool_names  # noqa: E402


def check(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)
    print(f"PASS: {message}")


def fake_message(role: str, content: str, status: str = "complete"):
    return SimpleNamespace(role=role, content=content, status=status)


def main() -> None:
    print(f"Jace version: {settings.app_version}")

    check(settings.app_version == "0.5.1", "version is 0.5.1")
    check(not should_retrieve_memory("Hello"), "greeting skips pre-chat memory embedding")
    check(not should_retrieve_memory("Explain recursion in Python"), "generic knowledge skips memory embedding")
    check(
        should_retrieve_memory("What database did we choose for Project Atlas?"),
        "project/history request enables memory retrieval",
    )

    check(route_tool_names("Hello") == set(), "normal chat exposes no tool schemas")
    check(route_tool_names("What is 812 * 57?") == {"calculator"}, "arithmetic routes only calculator")
    check(
        route_tool_names("What time is it in London?") == {"current_datetime"},
        "time request routes only date/time tool",
    )
    check(
        route_tool_names("Search the web for the latest Ollama release")
        == {"web_search", "read_web_page", "browser_read_page"},
        "web research routes only the web tool family",
    )
    check(
        route_tool_names("Read https://docs.ollama.com/faq")
        == {"read_web_page", "browser_read_page"},
        "direct URL routes only page-reading tools",
    )
    check(
        route_tool_names("What did we discuss in our last conversation?") == {"search_conversations"},
        "conversation-history phrasing routes history search",
    )
    check(
        route_tool_names("Look up the current Ollama documentation")
        == {"web_search", "read_web_page", "browser_read_page"},
        "look-up phrasing routes web research",
    )

    messages = []
    for index in range(40):
        role = "user" if index % 2 == 0 else "assistant"
        messages.append(fake_message(role, f"message-{index}-" + ("x" * 600)))
    conversation = SimpleNamespace(messages=messages)
    history = model_history(conversation, max_messages=20, max_chars=10_000)
    check(len(history) <= 20, "history is capped by message count")
    check(sum(len(item["content"]) for item in history) <= 10_000, "history is capped by character budget")
    check(history[-1]["content"].startswith("message-39-"), "newest history is preserved")

    check(settings.web_page_max_chars <= 8_000, "static web payload budget is reduced")
    check(settings.browser_max_page_chars <= 9_000, "browser payload budget is reduced")
    check(settings.tool_result_max_chars <= 8_000, "tool result prompt budget is reduced")

    print("\nPASS: Jace v0.5.1 performance smoke tests completed.")


if __name__ == "__main__":
    main()
