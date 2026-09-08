"""Local no-network smoke checks for Jace Phase 8 automation."""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from jace.automations.scheduler import build_trigger  # noqa: E402
from jace.automations.service import (  # noqa: E402
    BACKGROUND_FORBIDDEN_TOOLS,
    validate_schedule,
    validate_tool_names,
)
from jace.config import settings  # noqa: E402
from jace.schemas import AutomationSchedule  # noqa: E402
from jace.tools import ensure_tools_registered  # noqa: E402
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
    require(settings.automation_enabled, "automation scheduler is enabled by default")
    require(settings.automation_max_parallel_runs >= 1, "automation concurrency limit is configured")
    require(settings.automation_max_tool_steps >= 1, "automation tool-step safety limit is configured")

    ensure_tools_registered()
    names = {definition.name for definition in registry.all()}
    required_tools = {
        "list_automations",
        "create_automation",
        "set_automation_enabled",
        "run_automation_now",
    }
    require(required_tools <= names, "all Phase 8 automation tools are registered")
    require(len(names) >= 39, "Phase 9 retains Phase 8 tools and registers at least 39 tools total")

    routed = route_tool_names("Remind me tomorrow at 9am to call John")
    require("create_automation" in routed, "reminder requests expose automation creation")
    require("current_datetime" in routed, "relative reminder requests expose current time")

    routed = route_tool_names("Show my automations")
    require("list_automations" in routed, "automation list requests expose list_automations")

    future = AutomationSchedule(
        schedule_type="once",
        timezone="Europe/London",
        run_at=datetime.now(timezone.utc) + timedelta(hours=1),
    )
    validate_schedule(future)
    require(True, "future one-time schedules validate")

    past = AutomationSchedule(
        schedule_type="once",
        timezone="Europe/London",
        run_at=datetime.now(timezone.utc) - timedelta(minutes=1),
    )
    expect_value_error(lambda: validate_schedule(past), "new one-time schedules in the past are rejected")

    daily = AutomationSchedule(
        schedule_type="daily",
        timezone="Europe/London",
        time_of_day="08:00",
    )
    validate_schedule(daily)
    require(build_trigger(type("Row", (), {
        "schedule_type": "daily",
        "schedule_json": '{"run_at":null,"interval_minutes":null,"time_of_day":"08:00","days_of_week":[],"cron_expression":null}',
        "timezone": "Europe/London",
    })()) is not None, "daily schedules build an APScheduler trigger")

    cron = AutomationSchedule(
        schedule_type="cron",
        timezone="Europe/London",
        cron_expression="0 8 * * 1-5",
    )
    validate_schedule(cron)
    require(True, "valid five-field cron schedules validate")

    bad_cron = AutomationSchedule(
        schedule_type="cron",
        timezone="Europe/London",
        cron_expression="99 99 * * *",
    )
    expect_value_error(lambda: validate_schedule(bad_cron), "invalid cron ranges are rejected before persistence")

    require("create_automation" in BACKGROUND_FORBIDDEN_TOOLS, "automation creation cannot be delegated to background jobs")
    require("click_control" in BACKGROUND_FORBIDDEN_TOOLS, "background automations cannot receive Phase 9 GUI-control tools")
    expect_value_error(
        lambda: validate_tool_names(["create_automation"], background_scope=True),
        "background scopes cannot grant automation-management tools",
    )

    print(f"Registered tools: {len(names)}")
    print("PASS: Jace Phase 8 automation safety checks completed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
