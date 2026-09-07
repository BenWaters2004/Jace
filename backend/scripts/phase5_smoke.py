import asyncio
import sys
from pathlib import Path


BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from jace.config import settings  # noqa: E402
from jace.tools import ensure_tools_registered  # noqa: E402
from jace.tools.registry import registry  # noqa: E402
from jace.web.security import UnsafeWebAddressError, validate_public_url  # noqa: E402


async def main() -> int:
    ensure_tools_registered()

    names = {tool.name for tool in registry.all()}
    required = {"web_search", "read_web_page", "browser_read_page"}
    missing = sorted(required - names)

    print(f"Jace version: {settings.app_version}")
    print(f"Registered tools: {len(names)}")
    print("Web tools:", ", ".join(sorted(required & names)) or "none")

    if missing:
        print("FAIL: missing web tools:", ", ".join(missing))
        return 1

    blocked_targets = [
        "http://127.0.0.1/",
        "http://169.254.169.254/",
        "https://10.0.0.1/",
        "https://[::1]/",
    ]

    for target in blocked_targets:
        try:
            await validate_public_url(target)
        except UnsafeWebAddressError:
            print(f"PASS blocked: {target}")
        else:
            print(f"FAIL allowed private target: {target}")
            return 1

    print("PASS: Phase 5 local safety checks completed.")
    print("Live web search/page tests require internet access and are intentionally not run here.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
