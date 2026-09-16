from __future__ import annotations

# JACE_STEP4C4A_NORMALIZED_PROVIDER_EVENT

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any


@dataclass(slots=True)
class NormalizedCalendarEvent:
    external_event_id: str
    title: str
    all_day: bool
    timezone: str
    start_at: datetime | None = None
    end_at: datetime | None = None
    start_date: date | None = None
    end_date_exclusive: date | None = None
    external_series_id: str | None = None
    original_event_id: str | None = None
    ical_uid: str | None = None
    external_version: str | None = None
    description: str = ""
    location: str = ""
    meeting_url: str | None = None
    status: str = "confirmed"
    availability: str = "busy"
    visibility: str = "default"
    organizer: dict[str, Any] = field(default_factory=dict)
    attendees: list[dict[str, Any]] = field(default_factory=list)
    reminders: list[dict[str, Any]] = field(default_factory=list)
    recurrence_rule: str | None = None
    recurrence: dict[str, Any] = field(default_factory=dict)
    provider_created_at: datetime | None = None
    provider_updated_at: datetime | None = None
    provider_data: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    deleted: bool = False
