from __future__ import annotations

# JACE_STEP4C4F_CALENDAR_DATE_RESOLUTION

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
import re
from zoneinfo import ZoneInfo


MONTHS = {
    "jan": 1,
    "january": 1,
    "feb": 2,
    "february": 2,
    "mar": 3,
    "march": 3,
    "apr": 4,
    "april": 4,
    "may": 5,
    "jun": 6,
    "june": 6,
    "jul": 7,
    "july": 7,
    "aug": 8,
    "august": 8,
    "sep": 9,
    "sept": 9,
    "september": 9,
    "oct": 10,
    "october": 10,
    "nov": 11,
    "november": 11,
    "dec": 12,
    "december": 12,
}

WEEKDAYS = {
    "monday": 0,
    "mon": 0,
    "tuesday": 1,
    "tue": 1,
    "tues": 1,
    "wednesday": 2,
    "wed": 2,
    "thursday": 3,
    "thu": 3,
    "thur": 3,
    "thurs": 3,
    "friday": 4,
    "fri": 4,
    "saturday": 5,
    "sat": 5,
    "sunday": 6,
    "sun": 6,
}


class CalendarDateResolutionError(ValueError):
    pass


@dataclass(slots=True, frozen=True)
class ResolvedCalendarRange:
    expression: str
    timezone: str
    start: datetime
    end: datetime
    label: str
    resolution: str

    def as_dict(self) -> dict[str, str]:
        return {
            "expression": self.expression,
            "timezone": self.timezone,
            "start": self.start.isoformat(),
            "end": self.end.isoformat(),
            "label": self.label,
            "resolution": self.resolution,
        }


def _portable_day_label(value: date) -> str:
    return (
        f"{value.strftime('%A')} "
        f"{value.day} "
        f"{value.strftime('%B %Y')}"
    )


def _make_day_range(
    value: date,
    zone: ZoneInfo,
    *,
    expression: str,
    resolution: str,
) -> ResolvedCalendarRange:
    start = datetime.combine(
        value,
        time.min,
        tzinfo=zone,
    )

    return ResolvedCalendarRange(
        expression=expression,
        timezone=str(zone),
        start=start,
        end=start + timedelta(days=1),
        label=_portable_day_label(value),
        resolution=resolution,
    )


def _week_start(value: date) -> date:
    return (
        value
        - timedelta(
            days=value.weekday(),
        )
    )


def _strip_prefixes(value: str) -> str:
    cleaned = value.strip().casefold()
    cleaned = re.sub(
        r"[?,.!]+$",
        "",
        cleaned,
    )

    # Tool input should normally be the date phrase itself, but tolerate the
    # most common words models retain when copying user text.
    previous = None

    while cleaned != previous:
        previous = cleaned
        cleaned = re.sub(
            r"^(?:for|on|during|in)\s+",
            "",
            cleaned,
        ).strip()

    return cleaned


def _valid_date(
    year: int,
    month: int,
    day: int,
    *,
    expression: str,
) -> date:
    try:
        return date(
            year,
            month,
            day,
        )
    except ValueError as exc:
        raise CalendarDateResolutionError(
            f"Could not resolve {expression!r}: "
            f"{day} is not a valid day for {year:04d}-{month:02d}."
        ) from exc


def _month_number(value: str) -> int | None:
    return MONTHS.get(
        value.casefold()
    )


def _resolve_weekday(
    weekday_name: str,
    modifier: str | None,
    today: date,
) -> date:
    target = WEEKDAYS[
        weekday_name.casefold()
    ]

    if modifier == "last":
        days_back = (
            today.weekday()
            - target
        ) % 7

        if days_back == 0:
            days_back = 7

        return (
            today
            - timedelta(
                days=days_back,
            )
        )

    if modifier == "this":
        monday = _week_start(
            today
        )

        return (
            monday
            + timedelta(
                days=target,
            )
        )

    days_forward = (
        target
        - today.weekday()
    ) % 7

    if modifier == "next":
        if days_forward == 0:
            days_forward = 7
        elif days_forward < 7:
            # "next Friday" means the next occurrence after today.
            pass
    elif days_forward == 0:
        # Bare weekday means today when today is that weekday.
        return today

    return (
        today
        + timedelta(
            days=days_forward,
        )
    )


def resolve_calendar_range(
    expression: str,
    *,
    timezone_name: str,
    now: datetime | None = None,
) -> ResolvedCalendarRange:
    if not expression.strip():
        raise CalendarDateResolutionError(
            "Calendar date expression cannot be empty."
        )

    try:
        zone = ZoneInfo(
            timezone_name
        )
    except Exception as exc:
        raise CalendarDateResolutionError(
            f"Unknown calendar timezone: {timezone_name}"
        ) from exc

    current = (
        now.astimezone(
            zone
        )
        if now is not None
        and now.tzinfo is not None
        else now.replace(
            tzinfo=zone
        )
        if now is not None
        else datetime.now(
            zone
        )
    )
    today = current.date()
    raw = expression.strip()
    cleaned = _strip_prefixes(
        raw
    )

    # Be tolerant if the model copies a little more than the date phrase.
    # This still resolves deterministically and never asks the model to invent
    # a year/month behind the scenes.
    embedded_relative = re.search(
        r"\b(?:the day before yesterday|day before yesterday|"
        r"the day after tomorrow|day after tomorrow|"
        r"yesterday|today|tomorrow)\b",
        cleaned,
    )

    if embedded_relative:
        cleaned = embedded_relative.group(
            0
        )

    relative_days = {
        "today": 0,
        "yesterday": -1,
        "tomorrow": 1,
        "day before yesterday": -2,
        "the day before yesterday": -2,
        "day after tomorrow": 2,
        "the day after tomorrow": 2,
    }

    if cleaned in relative_days:
        target = (
            today
            + timedelta(
                days=relative_days[
                    cleaned
                ],
            )
        )

        return _make_day_range(
            target,
            zone,
            expression=raw,
            resolution="relative_day",
        )

    if cleaned in {
        "this week",
        "current week",
    }:
        start_date = _week_start(
            today
        )
        start = datetime.combine(
            start_date,
            time.min,
            tzinfo=zone,
        )

        return ResolvedCalendarRange(
            expression=raw,
            timezone=timezone_name,
            start=start,
            end=start + timedelta(
                days=7
            ),
            label=(
                f"week of "
                f"{start_date.day} "
                f"{start_date.strftime('%B %Y')}"
            ),
            resolution="this_week",
        )

    if cleaned == "last week":
        start_date = (
            _week_start(
                today
            )
            - timedelta(
                days=7,
            )
        )
        start = datetime.combine(
            start_date,
            time.min,
            tzinfo=zone,
        )

        return ResolvedCalendarRange(
            expression=raw,
            timezone=timezone_name,
            start=start,
            end=start + timedelta(
                days=7
            ),
            label=(
                f"week of "
                f"{start_date.day} "
                f"{start_date.strftime('%B %Y')}"
            ),
            resolution="last_week",
        )

    if cleaned == "next week":
        start_date = (
            _week_start(
                today
            )
            + timedelta(
                days=7,
            )
        )
        start = datetime.combine(
            start_date,
            time.min,
            tzinfo=zone,
        )

        return ResolvedCalendarRange(
            expression=raw,
            timezone=timezone_name,
            start=start,
            end=start + timedelta(
                days=7
            ),
            label=(
                f"week of "
                f"{start_date.day} "
                f"{start_date.strftime('%B %Y')}"
            ),
            resolution="next_week",
        )

    if cleaned in {
        "this weekend",
        "weekend",
    }:
        monday = _week_start(
            today
        )
        saturday = (
            monday
            + timedelta(
                days=5,
            )
        )

        if (
            cleaned == "weekend"
            and today.weekday() > 6
        ):
            saturday += timedelta(
                days=7
            )

        start = datetime.combine(
            saturday,
            time.min,
            tzinfo=zone,
        )

        return ResolvedCalendarRange(
            expression=raw,
            timezone=timezone_name,
            start=start,
            end=start + timedelta(
                days=2
            ),
            label=(
                f"weekend of "
                f"{saturday.day} "
                f"{saturday.strftime('%B %Y')}"
            ),
            resolution="weekend",
        )

    if cleaned == "next weekend":
        monday = (
            _week_start(
                today
            )
            + timedelta(
                days=7,
            )
        )
        saturday = (
            monday
            + timedelta(
                days=5,
            )
        )
        start = datetime.combine(
            saturday,
            time.min,
            tzinfo=zone,
        )

        return ResolvedCalendarRange(
            expression=raw,
            timezone=timezone_name,
            start=start,
            end=start + timedelta(
                days=2
            ),
            label=(
                f"weekend of "
                f"{saturday.day} "
                f"{saturday.strftime('%B %Y')}"
            ),
            resolution="next_weekend",
        )

    iso_match = re.fullmatch(
        r"(\d{4})-(\d{2})-(\d{2})",
        cleaned,
    )

    if iso_match:
        target = _valid_date(
            int(
                iso_match.group(
                    1
                )
            ),
            int(
                iso_match.group(
                    2
                )
            ),
            int(
                iso_match.group(
                    3
                )
            ),
            expression=raw,
        )

        return _make_day_range(
            target,
            zone,
            expression=raw,
            resolution="iso_date",
        )

    uk_numeric = re.fullmatch(
        r"(\d{1,2})[/-](\d{1,2})(?:[/-](\d{2,4}))?",
        cleaned,
    )

    if uk_numeric:
        day = int(
            uk_numeric.group(
                1
            )
        )
        month = int(
            uk_numeric.group(
                2
            )
        )
        year_raw = uk_numeric.group(
            3
        )
        year = (
            today.year
            if year_raw is None
            else int(
                year_raw
            )
        )

        if year < 100:
            year += 2000

        target = _valid_date(
            year,
            month,
            day,
            expression=raw,
        )

        return _make_day_range(
            target,
            zone,
            expression=raw,
            resolution="uk_numeric_date",
        )

    day_month = re.fullmatch(
        r"(?:the\s+)?(\d{1,2})(?:st|nd|rd|th)?"
        r"(?:\s+of)?\s+"
        r"([a-z]+)"
        r"(?:\s+(\d{4}))?",
        cleaned,
    )

    if day_month:
        month = _month_number(
            day_month.group(
                2
            )
        )

        if month is not None:
            year = int(
                day_month.group(
                    3
                )
                or today.year
            )
            target = _valid_date(
                year,
                month,
                int(
                    day_month.group(
                        1
                    )
                ),
                expression=raw,
            )

            return _make_day_range(
                target,
                zone,
                expression=raw,
                resolution="named_date",
            )

    month_day = re.fullmatch(
        r"([a-z]+)\s+"
        r"(?:the\s+)?"
        r"(\d{1,2})(?:st|nd|rd|th)?"
        r"(?:[\s,]+(\d{4}))?",
        cleaned,
    )

    if month_day:
        month = _month_number(
            month_day.group(
                1
            )
        )

        if month is not None:
            year = int(
                month_day.group(
                    3
                )
                or today.year
            )
            target = _valid_date(
                year,
                month,
                int(
                    month_day.group(
                        2
                    )
                ),
                expression=raw,
            )

            return _make_day_range(
                target,
                zone,
                expression=raw,
                resolution="named_date",
            )

    ordinal_only = re.fullmatch(
        r"(?:the\s+)?"
        r"(\d{1,2})"
        r"(?:st|nd|rd|th)?",
        cleaned,
    )

    if ordinal_only is None:
        embedded_ordinals = list(
            re.finditer(
                r"\b(?:the\s+)?(\d{1,2})(?:st|nd|rd|th)\b",
                cleaned,
            )
        )

        if len(
            embedded_ordinals
        ) == 1:
            ordinal_only = embedded_ordinals[
                0
            ]

    if ordinal_only:
        day = int(
            ordinal_only.group(
                1
            )
        )
        target = _valid_date(
            today.year,
            today.month,
            day,
            expression=raw,
        )

        return _make_day_range(
            target,
            zone,
            expression=raw,
            resolution="current_month_day",
        )

    weekday_match = re.fullmatch(
        r"(?:(last|this|next)\s+)?"
        r"(monday|mon|tuesday|tue|tues|wednesday|wed|"
        r"thursday|thu|thur|thurs|friday|fri|"
        r"saturday|sat|sunday|sun)",
        cleaned,
    )

    if weekday_match:
        target = _resolve_weekday(
            weekday_match.group(
                2
            ),
            weekday_match.group(
                1
            ),
            today,
        )

        return _make_day_range(
            target,
            zone,
            expression=raw,
            resolution="weekday",
        )

    raise CalendarDateResolutionError(
        "Jace could not deterministically resolve the calendar date "
        f"expression {raw!r}. Use a phrase such as yesterday, tomorrow, "
        "the 16th, 16 September 2026, next Friday, or this week."
    )
