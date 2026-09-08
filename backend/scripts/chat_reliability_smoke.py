from jace.ai.prompts import build_tool_agent_system_prompt
from jace.tools.agent import _looks_incomplete_response


def check(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)
    print(f"PASS: {message}")


def main() -> None:
    check(
        _looks_incomplete_response(
            "There is no",
            done_reason="stop",
            user_message="summarize b-waters.com",
            tool_calls_used=1,
        ),
        "detects the reported incomplete fragment",
    )
    check(
        not _looks_incomplete_response(
            "PostgreSQL",
            done_reason="stop",
            user_message="Which database did we choose?",
            tool_calls_used=0,
        ),
        "does not reject a legitimate short answer",
    )
    check(
        not _looks_incomplete_response(
            "The site is currently offline.",
            done_reason="stop",
            user_message="Is the site online?",
            tool_calls_used=1,
        ),
        "does not reject a complete short tool answer",
    )
    web_prompt = build_tool_agent_system_prompt(
        ["web_search", "read_web_page", "browser_read_page"]
    )
    check("call read_web_page DIRECTLY first" in web_prompt, "exact-domain direct-read rule is present")
    check("Interactive-control rules" not in web_prompt, "irrelevant GUI-control rules are excluded from web turns")
    check(len(web_prompt) < 2500, "web tool policy remains compact")
    print("PASS: Jace chat reliability hotfix smoke checks completed.")


if __name__ == "__main__":
    main()
