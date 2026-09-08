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

    register_builtin_tools()
    register_web_tools()
    register_computer_tools()
    register_multimodal_tools()
    register_automation_tools()
    _registered = True
