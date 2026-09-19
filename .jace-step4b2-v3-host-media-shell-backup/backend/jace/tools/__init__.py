_registered = False


def ensure_tools_registered() -> None:
    global _registered

    if _registered:
        return

    from jace.tools.builtins import register_builtin_tools
    from jace.tools.webtools import register_web_tools
    from jace.tools.computer import register_computer_tools
    from jace.tools.filesystem_intelligence import register_filesystem_intelligence_tools
    from jace.tools.host_computer import register_full_computer_access_tools
    from jace.tools.multimodal import register_multimodal_tools
    from jace.tools.automation import register_automation_tools
    from jace.tools.interactive import register_interactive_tools
    from jace.tools.agent_orchestration import register_agent_orchestration_tools
    from jace.tools.gmail import register_gmail_tools

    from jace.tools.outlook import register_outlook_tools
    from jace.tools.gmail_write import register_gmail_write_tools
    from jace.tools.outlook_write import register_outlook_write_tools
    from jace.tools.google_calendar_write import register_google_calendar_write_tools
    from jace.tools.microsoft_calendar_write import register_microsoft_calendar_write_tools
    from jace.tools.calendar_intelligence import register_calendar_intelligence_tools
    from jace.tools.calendar_find_event import register_calendar_find_event_tool
    register_builtin_tools()
    register_web_tools()
    register_computer_tools()
    register_filesystem_intelligence_tools()
    register_full_computer_access_tools()
    register_multimodal_tools()
    register_automation_tools()
    register_interactive_tools()
    register_agent_orchestration_tools()
    register_gmail_tools()
    register_outlook_tools()
    register_gmail_write_tools()
    register_outlook_write_tools()
    register_google_calendar_write_tools()
    register_microsoft_calendar_write_tools()
    register_calendar_intelligence_tools()
    register_calendar_find_event_tool()

    # Extend Jace's existing smart tool router.
    from jace.tools import agent as primary_agent
    from jace.tools.agent_routing import extend_agent_tool_route

    primary_agent.route_tool_names = extend_agent_tool_route(
        primary_agent.route_tool_names
    )

    # Phase 11B.1.2:
    # Explicit background delegation must be deterministic rather than merely
    # hoping a small local model chooses the supplied tool. api.chat imported
    # stream_agent directly during module import, so patch the chat module's
    # reference as well as the source module.
    from jace.tools.agent_delegation_bridge import wrap_stream_agent

    if not getattr(
        primary_agent.stream_agent,
        "_jace_agent_delegation_bridge",
        False,
    ):
        primary_agent.stream_agent = wrap_stream_agent(
            primary_agent.stream_agent
        )

    try:
        from jace.api import chat as chat_api

        chat_api.stream_agent = primary_agent.stream_agent
    except (ImportError, AttributeError):
        # main.py normally imports chat before application lifespan startup.
        # This fallback keeps tool registration safe in isolated tests.
        pass

    _registered = True
