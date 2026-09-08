"""Local safety/routing smoke tests for Jace Phase 6."""

import sys
import tempfile
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from jace.computer.security import ComputerPathError, resolve_workspace_path  # noqa: E402
from jace.computer.service import validate_command_executable  # noqa: E402
from jace.config import settings  # noqa: E402
from jace.tools.routing import route_tool_names  # noqa: E402


def check(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)
    print(f"PASS: {message}")


def main() -> None:
    print(f"Jace version: {settings.app_version}")
    check(settings.app_version == "0.7.0", "version is 0.7.0")
    check(settings.ollama_keep_alive == "-1m", "Ollama keep_alive uses a valid duration string")
    check(settings.computer_enabled, "computer capability is enabled")
    check(not settings.computer_allow_sensitive_files, "sensitive local files are blocked by default")

    routed = route_tool_names("Read the README file in my local project")
    check("list_computer_workspaces" in routed, "computer request exposes workspace discovery")
    check("read_workspace_file" in routed, "file read request exposes the file reader")

    routed = route_tool_names("Run the tests in my project workspace")
    check("run_workspace_command" in routed, "project test request exposes command presets")

    try:
        validate_command_executable("powershell.exe")
    except ValueError:
        print("PASS: arbitrary PowerShell shell preset is blocked")
    else:
        raise AssertionError("PowerShell shell host was not blocked")

    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        (root / "src").mkdir()
        (root / "src" / "hello.txt").write_text("hello", encoding="utf-8")
        (root / ".env").write_text("SECRET=test", encoding="utf-8")

        _, safe = resolve_workspace_path(str(root), "src/hello.txt", must_exist=True)
        check(safe.read_text(encoding="utf-8") == "hello", "normal workspace file resolves")

        try:
            resolve_workspace_path(str(root), "../outside.txt")
        except ComputerPathError:
            print("PASS: parent-directory traversal is blocked")
        else:
            raise AssertionError("Path traversal was not blocked")

        try:
            resolve_workspace_path(str(root), ".env", must_exist=True)
        except ComputerPathError:
            print("PASS: sensitive .env file is blocked")
        else:
            raise AssertionError("Sensitive file was not blocked")

    print("\nPASS: Jace Phase 6 local computer safety checks completed.")


if __name__ == "__main__":
    main()
