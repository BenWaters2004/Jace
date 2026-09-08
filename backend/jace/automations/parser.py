from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from jace.ai.engine import structured_chat
from jace.database import SessionLocal
from jace.db.settings import get_or_create_assistant_settings
from jace.schemas import AutomationDraftResponse
from jace.tools import ensure_tools_registered
from jace.tools.registry import registry


AUTOMATION_PARSE_SYSTEM_PROMPT = """
You convert a user's natural-language automation request into a Jace automation draft.
Return only the requested structured data.

Rules:
- Do not invent a schedule if the user did not specify enough scheduling information. Prefer a reasonable interpretation only when the wording is clear (for example 'every morning' means daily around 08:00).
- Monday=0, Tuesday=1, Wednesday=2, Thursday=3, Friday=4, Saturday=5, Sunday=6.
- Use schedule_type once, interval, daily, weekly, or cron.
- Use an ISO-8601 timezone-aware datetime for a one-time run_at.
- A watcher is a recurring check that should notify only when a condition is true or changes. Put the check/work in instruction and the notification condition in watcher_condition.
- A normal task executes and returns a result each time.
- suggested_tools must contain only tool names provided in the AVAILABLE TOOLS section.
- Prefer the minimum capabilities necessary. Never suggest write/execute/screen tools unless the user's request clearly needs them.
- A plain reminder normally needs no tools.
- Keep the generated name short and descriptive.
"""


async def parse_automation_draft(text: str, timezone_name: str) -> AutomationDraftResponse:
    try:
        zone = ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError as exc:
        raise ValueError(f"Unknown timezone: {timezone_name}") from exc

    ensure_tools_registered()
    tool_lines = [
        f"- {definition.name}: {definition.description} (risk={definition.risk})"
        for definition in registry.all()
    ]
    now = datetime.now(zone)

    async with SessionLocal() as session:
        profile = await get_or_create_assistant_settings(session)
        model = profile.default_model

    prompt = f"""
Current local datetime: {now.isoformat()}
Default timezone: {timezone_name}

AVAILABLE TOOLS
{chr(10).join(tool_lines)}
END AVAILABLE TOOLS

USER REQUEST
{text.strip()}
END USER REQUEST
"""

    draft = await structured_chat(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        system_prompt=AUTOMATION_PARSE_SYSTEM_PROMPT,
        response_model=AutomationDraftResponse,
    )

    valid_names = {definition.name for definition in registry.all()}
    draft.suggested_tools = sorted(set(name for name in draft.suggested_tools if name in valid_names))
    if not draft.schedule.timezone:
        draft.schedule.timezone = timezone_name
    return draft
