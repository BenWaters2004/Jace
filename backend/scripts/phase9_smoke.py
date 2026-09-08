"""Local no-network safety/routing smoke checks for Jace Phase 9 interactive control."""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from jace.config import settings  # noqa: E402
from jace.control import windows as control_windows  # noqa: E402
from jace.control.runtime import (  # noqa: E402
    activate_emergency_stop,
    clear_emergency_stop,
    emergency_stop_active,
)
from jace.control.security import (  # noqa: E402
    intent_is_sensitive,
    key_sequence_is_sensitive,
    process_is_absolutely_blocked,
    process_pattern_is_too_broad,
    text_contains_high_risk_secret,
    window_is_sensitive,
)
from jace.tools.interactive import register_interactive_tools  # noqa: E402
from jace.tools.registry import registry  # noqa: E402
from jace.tools.routing import route_tool_names  # noqa: E402


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)
    print(f"PASS: {message}")


def expect_value_error(fn, message: str) -> None:
    try:
        fn()
    except ValueError:
        print(f"PASS: {message}")
    else:
        raise AssertionError(message)


def main() -> int:
    print(f"Jace version: {settings.app_version}")
    require(settings.app_version == "0.10.0-alpha.2", "version is 0.10.0-alpha.2")
    require(settings.ollama_keep_alive == "-1m", "Ollama keep_alive regression remains fixed")
    require(settings.interactive_control_enabled, "interactive control is enabled by default")
    require(settings.interactive_default_max_steps > 0, "default control step limit is configured")
    require(settings.interactive_default_max_steps <= settings.interactive_max_steps, "default step limit is within hard maximum")
    require(settings.interactive_session_timeout_seconds > 0, "control-session timeout is configured")

    # Credential and secure-desktop apps are absolute blocks regardless of policy.
    for process in [
        "Bitwarden.exe",
        "1Password.exe",
        "KeePassXC.exe",
        "CredentialUIBroker.exe",
        "LogonUI.exe",
        "consent.exe",
    ]:
        require(process_is_absolutely_blocked(process), f"absolutely blocked process: {process}")
    require(not process_is_absolutely_blocked("Code.exe"), "ordinary editor process is not absolutely blocked")

    require(process_pattern_is_too_broad("*.exe"), "machine-wide *.exe app policy is rejected")
    require(process_pattern_is_too_broad("*"), "machine-wide wildcard app policy is rejected")
    require(not process_pattern_is_too_broad("msedge*.exe"), "specific browser process wildcard is allowed")

    fake_sensitive = SimpleNamespace(process_name="msedge.exe", title="Account sign in - Browser")
    fake_normal = SimpleNamespace(process_name="Code.exe", title="Jace - Visual Studio Code")
    require(window_is_sensitive(fake_sensitive), "login-like window title is sensitive")
    require(not window_is_sensitive(fake_normal), "ordinary editor window is not marked sensitive")

    for intent in ["send this email", "submit the form", "delete the file", "pay at checkout", "sign in to the account"]:
        require(intent_is_sensitive(intent), f"sensitive intent detected: {intent}")
    require(not intent_is_sensitive("scroll through the documentation"), "ordinary navigation intent is not sensitive")

    require(text_contains_high_risk_secret("api_key=sk-abcdefghijklmnopqrstuvwxyz123456"), "API-key-like text is rejected")
    require(text_contains_high_risk_secret("-----BEGIN PRIVATE KEY-----"), "private-key material is rejected")
    require(text_contains_high_risk_secret("4242 4242 4242 4242"), "payment-card-like Luhn value is rejected")
    require(not text_contains_high_risk_secret("hello from Jace"), "ordinary text is allowed")

    require(key_sequence_is_sensitive(["enter"]), "Enter is treated as potentially submitting")
    require(key_sequence_is_sensitive(["alt", "f4"]), "Alt+F4 is treated as sensitive")
    require(not key_sequence_is_sensitive(["ctrl", "c"]), "Ctrl+C is not intrinsically sensitive")

    # Window-relative coordinates may never escape the window the model saw.
    original_get_window = control_windows.get_window
    control_windows.get_window = lambda _handle: SimpleNamespace(left=100, top=200, width=800, height=600)
    try:
        require(
            control_windows.absolute_point(x=20, y=30, coordinate_space="window", window_handle=1) == (120, 230),
            "window-relative coordinates convert inside the approved window",
        )
        expect_value_error(
            lambda: control_windows.absolute_point(x=900, y=20, coordinate_space="window", window_handle=1),
            "window-relative coordinates cannot escape the target window",
        )
        expect_value_error(
            lambda: control_windows.absolute_point(x=-1, y=20, coordinate_space="window", window_handle=1),
            "negative window-relative coordinates are rejected",
        )
    finally:
        control_windows.get_window = original_get_window

    clear_emergency_stop()
    require(not emergency_stop_active(), "emergency kill switch starts clear")
    activate_emergency_stop()
    require(emergency_stop_active(), "emergency kill switch can interrupt live input")
    clear_emergency_stop()

    routed = route_tool_names("Open my browser and click the documentation link")
    expected_family = {
        "start_control_session",
        "control_status",
        "list_control_windows",
        "focus_control_window",
        "capture_control_screen",
        "move_control_pointer",
        "click_control",
        "scroll_control",
        "type_control_text",
        "press_control_keys",
        "stop_control_session",
    }
    require(expected_family <= routed, "interactive GUI request exposes the Phase 9 control family")
    stopped = route_tool_names("Emergency stop computer control")
    require("stop_control_session" in stopped, "control-stop phrasing exposes the stop tool")

    # Register just the Phase 9 family so this smoke test remains no-network and
    # does not require APScheduler to import the older automation tool family.
    register_interactive_tools()
    registered = {item.name for item in registry.all()}
    require(expected_family <= registered, "all 11 Phase 9 tools register")

    print("Interactive tools: " + ", ".join(sorted(expected_family)))
    print("PASS: Jace Phase 9 interactive-control safety checks completed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
