from __future__ import annotations

# JACE_STEP4C5B_V2_FLAT_CREATE_SCHEMA

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from jace.tools.calendar_write_common import (
    CalendarAttendeeInput,
    CalendarCreateEventInput,
    CalendarRecurrenceInput,
    CalendarReminderInput,
)


ProviderId = Literal["google", "microsoft"]
RecurrenceFrequency = Literal["daily", "weekly", "monthly", "yearly"]
Weekday = Literal[
    "monday",
    "tuesday",
    "wednesday",
    "thursday",
    "friday",
    "saturday",
    "sunday",
]


class CalendarCreateFlatInput(BaseModel):
    """
    Model-facing Calendar create schema.

    Keep this intentionally flat. Small local models are much more reliable
    with primitive fields/lists than nested attendee/recurrence/reminder
    objects. Provider handlers convert it back into the richer internal model.
    """

    calendar: str | None = Field(
        default=None,
        max_length=300,
        description="Optional human calendar name. Leave empty for primary.",
    )
    title: str = Field(min_length=1, max_length=1000)
    description: str = Field(default="", max_length=20_000)
    location: str = Field(default="", max_length=2000)

    all_day: bool = False
    start_at: datetime | None = Field(
        default=None,
        description=(
            "Timed-event start as ISO 8601. Use the user's local Calendar "
            "timezone when the request gives a local wall-clock time."
        ),
    )
    end_at: datetime | None = Field(
        default=None,
        description="Timed-event end as ISO 8601.",
    )
    start_date: date | None = None
    end_date_exclusive: date | None = None
    timezone: str | None = Field(default=None, max_length=100)

    attendee_emails: list[str] = Field(
        default_factory=list,
        max_length=200,
        description="Required attendee email addresses.",
    )
    optional_attendee_emails: list[str] = Field(
        default_factory=list,
        max_length=200,
    )
    resource_attendee_emails: list[str] = Field(
        default_factory=list,
        max_length=200,
    )

    recurrence_frequency: RecurrenceFrequency | None = None
    recurrence_interval: int = Field(default=1, ge=1, le=99)
    recurrence_weekdays: list[Weekday] = Field(
        default_factory=list,
        max_length=7,
    )
    recurrence_day_of_month: int | None = Field(default=None, ge=1, le=31)
    recurrence_month: int | None = Field(default=None, ge=1, le=12)
    recurrence_count: int | None = Field(default=None, ge=1, le=999)
    recurrence_until: date | None = None

    reminder_minutes: list[int] = Field(
        default_factory=list,
        max_length=5,
        description=(
            "Reminder offsets in minutes before the event. Google can use "
            "multiple values. Microsoft accepts one."
        ),
    )

    add_online_meeting: bool = False
    notify_attendees: bool = True
    allow_new_time_proposals: bool = True

    availability: Literal["busy", "free"] = "busy"
    visibility: Literal[
        "default",
        "public",
        "private",
        "confidential",
    ] = "default"

    @field_validator(
        "attendee_emails",
        "optional_attendee_emails",
        "resource_attendee_emails",
    )
    @classmethod
    def clean_emails(
        cls,
        values: list[str],
    ) -> list[str]:
        result: list[str] = []
        seen: set[str] = set()

        for value in values:
            cleaned = value.strip()
            if not cleaned:
                continue

            key = cleaned.casefold()
            if key in seen:
                continue

            seen.add(key)
            result.append(cleaned)

        return result

    @field_validator("reminder_minutes")
    @classmethod
    def valid_reminders(
        cls,
        values: list[int],
    ) -> list[int]:
        for value in values:
            if value < 0 or value > 40_320:
                raise ValueError(
                    "Reminder minutes must be between 0 and 40,320."
                )
        return values

    @model_validator(mode="after")
    def validate_dates_and_recurrence(self):
        if self.all_day:
            if self.start_date is None or self.end_date_exclusive is None:
                raise ValueError(
                    "All-day events require start_date and end_date_exclusive."
                )
            if self.end_date_exclusive <= self.start_date:
                raise ValueError(
                    "end_date_exclusive must be after start_date."
                )
        else:
            if self.start_at is None or self.end_at is None:
                raise ValueError(
                    "Timed events require start_at and end_at."
                )

        if (
            self.recurrence_count is not None
            and self.recurrence_until is not None
        ):
            raise ValueError(
                "Use recurrence_count or recurrence_until, not both."
            )

        if (
            self.recurrence_frequency is None
            and (
                self.recurrence_count is not None
                or self.recurrence_until is not None
                or self.recurrence_weekdays
                or self.recurrence_day_of_month is not None
                or self.recurrence_month is not None
            )
        ):
            raise ValueError(
                "Set recurrence_frequency when recurrence fields are used."
            )

        return self


def to_calendar_create_input(
    data: CalendarCreateFlatInput,
    *,
    provider_id: ProviderId,
) -> CalendarCreateEventInput:
    attendees: list[CalendarAttendeeInput] = []

    for email in data.attendee_emails:
        attendees.append(
            CalendarAttendeeInput(
                email=email,
                type="required",
            )
        )

    for email in data.optional_attendee_emails:
        attendees.append(
            CalendarAttendeeInput(
                email=email,
                type="optional",
            )
        )

    for email in data.resource_attendee_emails:
        attendees.append(
            CalendarAttendeeInput(
                email=email,
                type="resource",
            )
        )

    recurrence = None

    if data.recurrence_frequency is not None:
        recurrence = CalendarRecurrenceInput(
            frequency=data.recurrence_frequency,
            interval=data.recurrence_interval,
            weekdays=data.recurrence_weekdays,
            day_of_month=data.recurrence_day_of_month,
            month=data.recurrence_month,
            count=data.recurrence_count,
            until=data.recurrence_until,
        )

    reminders = (
        [
            CalendarReminderInput(
                minutes_before_start=value,
                method="popup",
            )
            for value in data.reminder_minutes
        ]
        if data.reminder_minutes
        else None
    )

    online_meeting = None

    if data.add_online_meeting:
        online_meeting = (
            "google_meet"
            if provider_id == "google"
            else "microsoft_teams"
        )

    return CalendarCreateEventInput(
        calendar=data.calendar,
        title=data.title,
        description=data.description,
        location=data.location,
        all_day=data.all_day,
        start_at=data.start_at,
        end_at=data.end_at,
        start_date=data.start_date,
        end_date_exclusive=data.end_date_exclusive,
        timezone=data.timezone,
        availability=data.availability,
        visibility=data.visibility,
        attendees=attendees,
        reminders=reminders,
        recurrence=recurrence,
        online_meeting=online_meeting,
        notify_attendees=data.notify_attendees,
        allow_new_time_proposals=data.allow_new_time_proposals,
    )
