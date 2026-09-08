from __future__ import annotations

import threading


# Process-local kill switch for the currently running desktop input primitive.
# Database session state remains the source of truth between tool calls; this
# event exists so the Control screen's emergency stop can also interrupt a
# mouse move or long text injection that is already executing in a worker
# thread.
_EMERGENCY_STOP = threading.Event()


def activate_emergency_stop() -> None:
    _EMERGENCY_STOP.set()


def clear_emergency_stop() -> None:
    _EMERGENCY_STOP.clear()


def emergency_stop_active() -> bool:
    return _EMERGENCY_STOP.is_set()
