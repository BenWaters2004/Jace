from jace.tools.agent_routing import (
    build_forced_director_call,
    parse_director_request,
    parse_explicit_delegation,
)


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def main() -> None:
    open_ended = "Jace, investigate this and fix whatever you find."
    plan = parse_director_request(open_ended)
    require(plan is not None, "Open-ended investigate+fix should route to Agent Director.")

    forced = build_forced_director_call(
        open_ended,
        reasoning_mode="balanced",
        available_tool_names={"delegate_agent_director"},
    )
    require(forced is not None, "Director forced call should be built.")
    require(
        forced["function"]["name"] == "delegate_agent_director",
        "Wrong Director tool name.",
    )

    named = "Jace, have the Analyst Agent explain DNS caching in the background."
    require(
        parse_director_request(named) is None,
        "Explicit named-worker delegation must not be stolen by Director.",
    )
    require(
        parse_explicit_delegation(named) is not None,
        "Existing explicit named-worker delegation should still work.",
    )

    simple = "What is DNS caching?"
    require(
        parse_director_request(simple) is None,
        "Simple normal questions must remain in foreground Jace.",
    )

    explicit_director = "Use whatever agents you need to diagnose this and give me the best solution."
    require(
        parse_director_request(explicit_director) is not None,
        "Explicit agent-team/autonomy request should route to Director.",
    )

    print("PASS: 11B.4 Agent Director routing checks passed.")


if __name__ == "__main__":
    main()
