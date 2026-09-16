import { useMemo } from "react";

import type { CalendarEvent } from "../../types";
import {
  HOUR_END,
  HOUR_HEIGHT,
  HOUR_START,
  WEEKDAY_LABELS,
  addDays,
  dateKey,
  eventDateKey,
  eventTimeLabel,
  formatDate,
  formatTime,
  startOfMonthGrid,
  startOfWeek,
} from "./calendarUtils";

function EventChip(props: {
  event: CalendarEvent;
  onClick: (event: CalendarEvent) => void;
}) {
  return (
    <button
      type="button"
      className="calendar-event-chip"
      title={`${props.event.title} · ${eventTimeLabel(props.event)}`}
      style={{ borderLeftColor: props.event.calendar_color }}
      onClick={(event) => {
        event.stopPropagation();
        props.onClick(props.event);
      }}
    >
      <span className="calendar-event-time">{eventTimeLabel(props.event)}</span>
      <span className="calendar-event-title">{props.event.title}</span>
    </button>
  );
}

export function MonthView(props: {
  cursor: Date;
  events: CalendarEvent[];
  onSelectDay: (date: Date) => void;
  onSelectEvent: (event: CalendarEvent) => void;
}) {
  const start = startOfMonthGrid(props.cursor);
  const days = Array.from({ length: 42 }, (_, index) => addDays(start, index));
  const today = dateKey(new Date());

  const grouped = useMemo(() => {
    const map = new Map<string, CalendarEvent[]>();
    props.events.forEach((event) => {
      const key = eventDateKey(event);
      if (!key) return;
      map.set(key, [...(map.get(key) ?? []), event]);
    });
    return map;
  }, [props.events]);

  return (
    <div className="calendar-month">
      <div className="calendar-month-weekdays">
        {WEEKDAY_LABELS.map((weekday) => <div key={weekday}>{weekday}</div>)}
      </div>
      <div className="calendar-month-grid">
        {days.map((day) => {
          const key = dateKey(day);
          const dayEvents = grouped.get(key) ?? [];
          const className = [
            "calendar-month-cell",
            day.getMonth() === props.cursor.getMonth() ? "" : "outside",
            key === today ? "today" : "",
          ].filter(Boolean).join(" ");

          return (
            <button key={key} type="button" className={className} onClick={() => props.onSelectDay(day)}>
              <div className="calendar-month-day-number">{day.getDate()}</div>
              <div className="calendar-month-events">
                {dayEvents.slice(0, 4).map((event) => (
                  <EventChip key={event.id} event={event} onClick={props.onSelectEvent} />
                ))}
                {dayEvents.length > 4 && (
                  <span className="calendar-more-events">+{dayEvents.length - 4} more</span>
                )}
              </div>
            </button>
          );
        })}
      </div>
    </div>
  );
}

export function TimeGrid(props: {
  cursor: Date;
  days: 1 | 7;
  events: CalendarEvent[];
  onSelectDay: (date: Date) => void;
  onSelectEvent: (event: CalendarEvent) => void;
}) {
  const rangeStart = props.days === 1
    ? new Date(props.cursor.getFullYear(), props.cursor.getMonth(), props.cursor.getDate())
    : startOfWeek(props.cursor);
  const columns = Array.from({ length: props.days }, (_, index) => addDays(rangeStart, index));

  return (
    <div className="calendar-time-view">
      <div className="calendar-time-header" style={{ gridTemplateColumns: `72px repeat(${props.days}, minmax(0, 1fr))` }}>
        <div />
        {columns.map((day) => (
          <button key={dateKey(day)} type="button" className="calendar-time-day-head" onClick={() => props.onSelectDay(day)}>
            <span>{day.toLocaleDateString([], { weekday: "short" })}</span>
            <strong>{day.getDate()}</strong>
          </button>
        ))}
      </div>

      <div className="calendar-all-day-row" style={{ gridTemplateColumns: `72px repeat(${props.days}, minmax(0, 1fr))` }}>
        <div className="calendar-all-day-label">All day</div>
        {columns.map((day) => {
          const key = dateKey(day);
          const allDay = props.events.filter((event) => event.all_day && eventDateKey(event) === key);
          return (
            <div key={key} className="calendar-all-day-cell">
              {allDay.map((event) => <EventChip key={event.id} event={event} onClick={props.onSelectEvent} />)}
            </div>
          );
        })}
      </div>

      <div className="calendar-time-scroll">
        <div
          className="calendar-time-grid"
          style={{
            gridTemplateColumns: `72px repeat(${props.days}, minmax(0, 1fr))`,
            minHeight: `${(HOUR_END - HOUR_START) * HOUR_HEIGHT}px`,
          }}
        >
          <div className="calendar-hour-axis">
            {Array.from({ length: HOUR_END - HOUR_START + 1 }, (_, index) => {
              const hour = HOUR_START + index;
              return <span key={hour} style={{ top: `${index * HOUR_HEIGHT}px` }}>{String(hour).padStart(2, "0")}:00</span>;
            })}
          </div>

          {columns.map((day) => {
            const key = dateKey(day);
            const dayEvents = props.events.filter((event) => !event.all_day && eventDateKey(event) === key);
            return (
              <div key={key} className="calendar-time-column" onDoubleClick={() => props.onSelectDay(day)}>
                {Array.from({ length: HOUR_END - HOUR_START + 1 }, (_, index) => (
                  <div key={index} className="calendar-hour-line" style={{ top: `${index * HOUR_HEIGHT}px` }} />
                ))}
                {dayEvents.map((event) => {
                  const start = new Date(event.start_at ?? "");
                  const end = new Date(event.end_at ?? event.start_at ?? "");
                  const startMinutes = start.getHours() * 60 + start.getMinutes();
                  const endMinutes = end.getHours() * 60 + end.getMinutes();
                  const top = Math.max(0, (startMinutes - HOUR_START * 60) / 60 * HOUR_HEIGHT);
                  const height = Math.max(26, (endMinutes - startMinutes) / 60 * HOUR_HEIGHT);

                  return (
                    <button
                      type="button"
                      key={event.id}
                      className="calendar-time-event"
                      style={{ top: `${top}px`, height: `${height}px`, borderLeftColor: event.calendar_color }}
                      onClick={() => props.onSelectEvent(event)}
                    >
                      <strong>{event.title}</strong>
                      <span>{formatTime(event.start_at)} – {formatTime(event.end_at)}</span>
                    </button>
                  );
                })}
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}

export function AgendaView(props: {
  events: CalendarEvent[];
  onSelectEvent: (event: CalendarEvent) => void;
}) {
  const grouped = useMemo(() => {
    const map = new Map<string, CalendarEvent[]>();
    props.events.forEach((event) => {
      const key = eventDateKey(event);
      if (!key) return;
      map.set(key, [...(map.get(key) ?? []), event]);
    });
    return [...map.entries()].sort(([left], [right]) => left.localeCompare(right));
  }, [props.events]);

  if (grouped.length === 0) {
    return <div className="calendar-empty">No events in this period.</div>;
  }

  return (
    <div className="calendar-agenda">
      {grouped.map(([date, dayEvents]) => (
        <section key={date} className="calendar-agenda-day">
          <div className="calendar-agenda-date">
            <strong>{formatDate(new Date(`${date}T12:00:00`), { weekday: "long", day: "numeric", month: "long" })}</strong>
          </div>
          <div className="calendar-agenda-events">
            {dayEvents.map((event) => (
              <button type="button" key={event.id} className="calendar-agenda-event" onClick={() => props.onSelectEvent(event)}>
                <span className="calendar-source-dot" style={{ background: event.calendar_color }} />
                <span className="calendar-agenda-time">{eventTimeLabel(event)}</span>
                <span className="calendar-agenda-main">
                  <strong>{event.title}</strong>
                  {event.location && <small>{event.location}</small>}
                </span>
                <span className="calendar-agenda-source">{event.calendar_name}</span>
              </button>
            ))}
          </div>
        </section>
      ))}
    </div>
  );
}
