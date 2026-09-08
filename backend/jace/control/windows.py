from __future__ import annotations

import fnmatch
import platform
from dataclasses import dataclass, asdict


class DesktopControlUnavailable(RuntimeError):
    pass


@dataclass(frozen=True)
class WindowInfo:
    handle: int
    title: str
    process_name: str
    process_id: int
    left: int
    top: int
    right: int
    bottom: int
    is_active: bool = False

    @property
    def width(self) -> int:
        return max(0, self.right - self.left)

    @property
    def height(self) -> int:
        return max(0, self.bottom - self.top)

    def to_dict(self) -> dict:
        data = asdict(self)
        data["width"] = self.width
        data["height"] = self.height
        return data


def _require_windows():
    if platform.system() != "Windows":
        raise DesktopControlUnavailable(
            "Interactive desktop control is currently supported on Windows only."
        )
    try:
        import psutil  # noqa: F401
        import win32api  # noqa: F401
        import win32con  # noqa: F401
        import win32gui  # noqa: F401
        import win32process  # noqa: F401
    except ImportError as exc:
        raise DesktopControlUnavailable(
            "Phase 9 Windows-control dependencies are not installed. Run pip install -r requirements.txt."
        ) from exc


def _process_name(pid: int) -> str:
    try:
        import psutil
        return psutil.Process(pid).name()
    except Exception:
        return "unknown"


def _window_info(hwnd: int, *, active_handle: int | None = None) -> WindowInfo | None:
    _require_windows()
    import win32gui
    import win32process

    try:
        if not win32gui.IsWindow(hwnd) or not win32gui.IsWindowVisible(hwnd):
            return None
        title = (win32gui.GetWindowText(hwnd) or "").strip()
        if not title:
            return None
        left, top, right, bottom = win32gui.GetWindowRect(hwnd)
        _, pid = win32process.GetWindowThreadProcessId(hwnd)
        return WindowInfo(
            handle=int(hwnd),
            title=title[:700],
            process_name=_process_name(int(pid))[:260],
            process_id=int(pid),
            left=int(left),
            top=int(top),
            right=int(right),
            bottom=int(bottom),
            is_active=active_handle == hwnd,
        )
    except Exception:
        return None


def list_windows() -> list[WindowInfo]:
    _require_windows()
    import win32gui

    active_handle = win32gui.GetForegroundWindow()
    items: list[WindowInfo] = []

    def callback(hwnd, _extra):
        info = _window_info(hwnd, active_handle=active_handle)
        if info is not None and info.width > 40 and info.height > 30:
            items.append(info)
        return True

    win32gui.EnumWindows(callback, None)
    items.sort(key=lambda item: (not item.is_active, item.process_name.lower(), item.title.lower()))
    return items


def get_window(handle: int) -> WindowInfo | None:
    _require_windows()
    import win32gui
    return _window_info(int(handle), active_handle=win32gui.GetForegroundWindow())


def active_window() -> WindowInfo | None:
    _require_windows()
    import win32gui
    handle = win32gui.GetForegroundWindow()
    if not handle:
        return None
    return _window_info(handle, active_handle=handle)


def window_at_point(x: int, y: int) -> WindowInfo | None:
    _require_windows()
    import win32con
    import win32gui

    try:
        hwnd = win32gui.WindowFromPoint((int(x), int(y)))
        if not hwnd:
            return None
        root = win32gui.GetAncestor(hwnd, win32con.GA_ROOT)
        return get_window(root or hwnd)
    except Exception:
        return None


def focus_window(handle: int) -> WindowInfo:
    _require_windows()
    import win32con
    import win32gui

    hwnd = int(handle)
    info = get_window(hwnd)
    if info is None:
        raise DesktopControlUnavailable("The requested window is no longer available.")

    try:
        if win32gui.IsIconic(hwnd):
            win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
        win32gui.BringWindowToTop(hwnd)
        win32gui.SetForegroundWindow(hwnd)
    except Exception as exc:
        raise DesktopControlUnavailable(
            "Windows refused to focus that application. Click it manually once, then retry."
        ) from exc

    return get_window(hwnd) or info


def absolute_point(
    *,
    x: int,
    y: int,
    coordinate_space: str,
    window_handle: int | None,
) -> tuple[int, int]:
    if coordinate_space == "screen":
        return int(x), int(y)
    if coordinate_space != "window":
        raise ValueError("coordinate_space must be 'screen' or 'window'.")
    if window_handle is None:
        raise ValueError("window_handle is required for window-relative coordinates.")
    info = get_window(window_handle)
    if info is None:
        raise ValueError("The requested window is no longer available.")
    relative_x = int(x)
    relative_y = int(y)
    if relative_x < 0 or relative_y < 0 or relative_x >= info.width or relative_y >= info.height:
        raise ValueError("Window-relative coordinates must remain inside the requested window.")
    return info.left + relative_x, info.top + relative_y


def matches_pattern(value: str, pattern: str) -> bool:
    return fnmatch.fnmatch(value.casefold(), pattern.casefold())
