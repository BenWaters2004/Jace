from __future__ import annotations

import asyncio
import ctypes
import time
from ctypes import wintypes

from jace.config import settings
from jace.control.service import ControlError, assert_physical_failsafe


KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_UNICODE = 0x0004
INPUT_KEYBOARD = 1


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", wintypes.WORD),
        ("wScan", wintypes.WORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
    ]


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", wintypes.LONG),
        ("dy", wintypes.LONG),
        ("mouseData", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
    ]


class HARDWAREINPUT(ctypes.Structure):
    _fields_ = [
        ("uMsg", wintypes.DWORD),
        ("wParamL", wintypes.WORD),
        ("wParamH", wintypes.WORD),
    ]


class INPUTUNION(ctypes.Union):
    _fields_ = [("ki", KEYBDINPUT), ("mi", MOUSEINPUT), ("hi", HARDWAREINPUT)]


class INPUT(ctypes.Structure):
    _fields_ = [("type", wintypes.DWORD), ("union", INPUTUNION)]


def _pause() -> None:
    time.sleep(max(0, settings.interactive_action_pause_ms) / 1000.0)


def move_pointer(x: int, y: int, duration_ms: int = 0) -> None:
    assert_physical_failsafe()
    import win32api

    duration = max(0, min(int(duration_ms), 2000)) / 1000.0
    if duration <= 0:
        win32api.SetCursorPos((int(x), int(y)))
        _pause()
        return

    start_x, start_y = win32api.GetCursorPos()
    steps = max(2, min(60, int(duration * 60)))
    for index in range(1, steps + 1):
        assert_physical_failsafe()
        fraction = index / steps
        next_x = round(start_x + (x - start_x) * fraction)
        next_y = round(start_y + (y - start_y) * fraction)
        win32api.SetCursorPos((next_x, next_y))
        time.sleep(duration / steps)
    _pause()


def click_pointer(x: int, y: int, *, button: str = "left", clicks: int = 1) -> None:
    assert_physical_failsafe()
    import win32api
    import win32con

    mapping = {
        "left": (win32con.MOUSEEVENTF_LEFTDOWN, win32con.MOUSEEVENTF_LEFTUP),
        "right": (win32con.MOUSEEVENTF_RIGHTDOWN, win32con.MOUSEEVENTF_RIGHTUP),
        "middle": (win32con.MOUSEEVENTF_MIDDLEDOWN, win32con.MOUSEEVENTF_MIDDLEUP),
    }
    if button not in mapping:
        raise ControlError("Mouse button must be left, right, or middle.")
    count = max(1, min(int(clicks), 2))
    win32api.SetCursorPos((int(x), int(y)))
    down_flag, up_flag = mapping[button]
    for _ in range(count):
        assert_physical_failsafe()
        win32api.mouse_event(down_flag, 0, 0, 0, 0)
        win32api.mouse_event(up_flag, 0, 0, 0, 0)
        time.sleep(0.08)
    _pause()


def scroll_pointer(x: int, y: int, amount: int) -> None:
    assert_physical_failsafe()
    import win32api
    import win32con

    win32api.SetCursorPos((int(x), int(y)))
    bounded = max(-20, min(20, int(amount)))
    # Win32 wheel direction: positive scrolls up, negative scrolls down.
    win32api.mouse_event(win32con.MOUSEEVENTF_WHEEL, 0, 0, bounded * 120, 0)
    _pause()


def _send_unicode_character(character: str) -> None:
    codepoint = ord(character)
    # SendInput's KEYEVENTF_UNICODE expects UTF-16 code units. Python gives us
    # Unicode scalar values, so supplementary characters are encoded as a pair.
    units = character.encode("utf-16-le")
    for index in range(0, len(units), 2):
        unit = int.from_bytes(units[index:index + 2], "little")
        extra = ctypes.c_ulong(0)
        down = INPUT(
            type=INPUT_KEYBOARD,
            union=INPUTUNION(
                ki=KEYBDINPUT(0, unit, KEYEVENTF_UNICODE, 0, ctypes.pointer(extra))
            ),
        )
        up = INPUT(
            type=INPUT_KEYBOARD,
            union=INPUTUNION(
                ki=KEYBDINPUT(0, unit, KEYEVENTF_UNICODE | KEYEVENTF_KEYUP, 0, ctypes.pointer(extra))
            ),
        )
        array = (INPUT * 2)(down, up)
        sent = ctypes.windll.user32.SendInput(2, ctypes.byref(array), ctypes.sizeof(INPUT))
        if sent != 2:
            raise ControlError("Windows could not inject keyboard text.")


def type_text(text: str) -> None:
    assert_physical_failsafe()
    interval = max(0, settings.interactive_type_interval_ms) / 1000.0
    for character in text:
        assert_physical_failsafe()
        _send_unicode_character(character)
        if interval:
            time.sleep(interval)
    _pause()


def press_keys(keys: list[str]) -> None:
    assert_physical_failsafe()
    try:
        import pyautogui
    except ImportError as exc:
        raise ControlError("PyAutoGUI is not installed.") from exc

    normalized = [key.casefold().strip() for key in keys if key.strip()]
    if not normalized:
        raise ControlError("At least one key is required.")
    if len(normalized) > settings.interactive_max_hotkey_keys:
        raise ControlError("Too many keys were supplied for one shortcut.")
    invalid = [key for key in normalized if key not in pyautogui.KEYBOARD_KEYS]
    if invalid:
        raise ControlError(f"Unsupported keyboard key(s): {', '.join(invalid)}")

    pyautogui.FAILSAFE = True
    pyautogui.PAUSE = max(0, settings.interactive_action_pause_ms) / 1000.0
    if len(normalized) == 1:
        pyautogui.press(normalized[0])
    else:
        pyautogui.hotkey(*normalized)
    _pause()


async def run_blocking(function, *args, **kwargs):
    return await asyncio.to_thread(function, *args, **kwargs)
