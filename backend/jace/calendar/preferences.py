from __future__ import annotations

# JACE_STEP4C4E_CALENDAR_PREFERENCES

from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, Field, field_validator
from sqlalchemy import DateTime, String
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from jace.db.models import Base, utc_now


DEFAULT_CALENDAR_TIMEZONE = "Europe/London"
CALENDAR_PREFERENCES_ID = "default"


class CalendarPreferences(Base):
    __tablename__ = "calendar_preferences"

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=CALENDAR_PREFERENCES_ID,
    )
    timezone: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        default=DEFAULT_CALENDAR_TIMEZONE,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
    )


class CalendarPreferencesResponse(BaseModel):
    timezone: str
    created_at: datetime
    updated_at: datetime


class CalendarPreferencesUpdate(BaseModel):
    timezone: str = Field(
        min_length=1,
        max_length=100,
    )

    @field_validator("timezone")
    @classmethod
    def validate_timezone(
        cls,
        value: str,
    ) -> str:
        cleaned = value.strip()

        try:
            ZoneInfo(cleaned)
        except ZoneInfoNotFoundError as exc:
            raise ValueError(
                f"Unknown IANA timezone: {cleaned}"
            ) from exc

        return cleaned


async def ensure_calendar_preferences(
    session: AsyncSession,
) -> CalendarPreferences:
    row = await session.get(
        CalendarPreferences,
        CALENDAR_PREFERENCES_ID,
    )

    if row is not None:
        return row

    row = CalendarPreferences(
        id=CALENDAR_PREFERENCES_ID,
        timezone=DEFAULT_CALENDAR_TIMEZONE,
    )
    session.add(row)
    await session.flush()

    return row


async def update_calendar_preferences(
    session: AsyncSession,
    request: CalendarPreferencesUpdate,
) -> CalendarPreferences:
    row = await ensure_calendar_preferences(
        session
    )
    row.timezone = request.timezone
    row.updated_at = utc_now()
    await session.flush()
    return row


def preferences_payload(
    row: CalendarPreferences,
) -> dict[str, object]:
    return {
        "timezone": row.timezone,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }
