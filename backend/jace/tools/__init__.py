_registered = False


def ensure_tools_registered() -> None:
    global _registered

    if _registered:
        return

    from jace.tools.builtins import register_builtin_tools
    from jace.tools.webtools import register_web_tools
    from jace.tools.computer import register_computer_tools
    from jace.tools.multimodal import register_multimodal_tools
    from jace.tools.automation import register_automation_tools
    from jace.tools.interactive import register_interactive_tools
    from jace.tools.agent_orchestration import register_agent_orchestration_tools

    register_builtin_tools()
    register_web_tools()
    register_computer_tools()
    register_multimodal_tools()
    register_automation_tools()
    register_interactive_tools()
    register_agent_orchestration_tools()

    # Preserve every existing smart-routing rule and layer agent routing on top.
    #
    # jace.tools.agent imports route_tool_names into its module namespace, so
    # replacing that module-global callable here extends routing without a risky
    # full replacement of routing.py.
    from jace.tools import agent as primary_agent
    from jace.tools.agent_routing import extend_agent_tool_route

    primary_agent.route_tool_names = extend_agent_tool_route(
        primary_agent.route_tool_names
    )

    _registered = True
