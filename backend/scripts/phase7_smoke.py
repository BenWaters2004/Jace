"""Local, no-network smoke checks for Jace Phase 7."""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from PIL import Image

from jace.attachments.processors import _image_to_base64
from jace.attachments.service import AttachmentError, media_kind_for_name
from jace.config import settings
from jace.tools import ensure_tools_registered
from jace.tools.registry import registry
from jace.tools.routing import route_tool_names


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def routing_checks() -> None:
    screen_tools = route_tool_names("Look at my current screen and tell me what is wrong")
    require("capture_screen" in screen_tools, "screen requests must route capture_screen")

    attachment_tools = route_tool_names("Inspect the PDF I attached earlier")
    require("inspect_attachment" in attachment_tools, "attachment references must route inspect_attachment")

    workspace_tools = route_tool_names("Inspect the image in my approved workspace")
    require("inspect_workspace_media" in workspace_tools, "workspace media requests must route inspect_workspace_media")


def main() -> int:
    print(f"Jace version: {settings.app_version}")
    require(settings.app_version == "0.7.0", "expected Jace v0.7.0")
    require(settings.ollama_keep_alive == "-1m", "keep_alive regression: expected -1m")
    require(settings.multimodal_enabled, "multimodal support should be enabled")

    require(media_kind_for_name("photo.png") == "image", "PNG classification failed")
    require(media_kind_for_name("report.pdf") == "pdf", "PDF classification failed")
    require(media_kind_for_name("notes.docx") == "document", "DOCX classification failed")
    require(media_kind_for_name("meeting.mp3") == "audio", "audio classification failed")
    try:
        media_kind_for_name("program.exe")
    except AttachmentError:
        pass
    else:
        raise AssertionError("unsupported binary executable should be rejected")

    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "test.png"
        Image.new("RGB", (320, 180), (30, 40, 50)).save(path)
        encoded, metadata = _image_to_base64(path)
        require(bool(encoded), "image encoding returned no data")
        require(metadata["width"] == 320 and metadata["height"] == 180, "image metadata mismatch")

    ensure_tools_registered()
    names = {tool.name for tool in registry.all()}
    for required in {"inspect_attachment", "inspect_workspace_media", "capture_screen"}:
        require(required in names, f"missing registered multimodal tool: {required}")

    routing_checks()

    print(f"Registered tools: {len(names)}")
    print("Multimodal tools: capture_screen, inspect_attachment, inspect_workspace_media")
    print("PASS: Jace Phase 7 multimodal safety checks completed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
