import { useMemo, type CSSProperties } from "react";

import type { CalendarEvent } from "../../types";
import {
  HOUR_END,
  HOUR_HEIGHT,
  HOUR_START,
  WEEKDAY_LABELS,
  addDays,
  dateKey,
  daysBetween,
  eventDateKey,
  eventMinutes,
  eventTimeLabel,
  formatDate,
  formatTime,
  parseDateKey,
  startOfMonthGrid,
  startOfWeek,
} from "./calendarUtils";


function EventChip(props: {
  event: CalendarEvent;
  timezone: string;
  onClick: (event: CalendarEvent) => void;
}) {
  return (
    <button
      type="button"
      className="calendar-event-chip"
      title={`${props.event.title} · ${eventTimeLabel(props.event, props.timezone)}`}
      style={{
        "--calendar-event-color":
          props.event.calendar_color,
      } as CSSProperties}
      onClick={(event) => {
        event.stopPropagation();
        props.onClick(props.event);
      }}
    >
      <span className="calendar-event-time">
        {eventTimeLabel(
          props.event,
          props.timezone,
        )}
      </span>
      <span className="calendar-event-title">
        {props.event.title}
      </span>
    </button>
  );
}


type AllDaySegment = {
  event: CalendarEvent;
  column: number;
  span: number;
  lane: number;
  startsHere: boolean;
  endsHere: boolean;
};


function weekAllDaySegments(
  events: CalendarEvent[],
  weekStart: Date,
  visibleDays: number,
): {
  segments: AllDaySegment[];
  laneCount: number;
} {
  const weekEnd = addDays(
    weekStart,
    visibleDays,
  );

  const allDay = events
    .filter((event) => (
      event.all_day
      && event.start_date
      && event.end_date_exclusive
      && event.start_date
        < dateKey(weekEnd)
      && event.end_date_exclusive
        > dateKey(weekStart)
    ))
    .slice()
    .sort((left, right) => {
      const startCompare = (
        left.start_date
        ?? ""
      ).localeCompare(
        right.start_date
        ?? "",
      );

      if (
        startCompare !== 0
      ) {
        return startCompare;
      }

      return (
        right.end_date_exclusive
        ?? ""
      ).localeCompare(
        left.end_date_exclusive
        ?? "",
      );
    });

  const occupied: Array<
    Array<{
      start: number;
      end: number;
    }>
  > = [];
  const segments: AllDaySegment[] = [];

  allDay.forEach((event) => {
    const actualStart = parseDateKey(
      event.start_date!,
    );
    const actualEnd = parseDateKey(
      event.end_date_exclusive!,
    );
    const segmentStart = (
      actualStart < weekStart
        ? weekStart
        : actualStart
    );
    const segmentEnd = (
      actualEnd > weekEnd
        ? weekEnd
        : actualEnd
    );
    const column = Math.max(
      0,
      daysBetween(
        weekStart,
        segmentStart,
      ),
    );
    const span = Math.max(
      1,
      daysBetween(
        segmentStart,
        segmentEnd,
      ),
    );
    const interval = {
      start: column,
      end: column + span,
    };

    let lane = 0;

    while (
      occupied[lane]?.some(
        (used) => (
          interval.start < used.end
          && interval.end > used.start
        ),
      )
    ) {
      lane += 1;
    }

    if (!occupied[lane]) {
      occupied[lane] = [];
    }

    occupied[lane].push(
      interval,
    );

    segments.push({
      event,
      column,
      span,
      lane,
      startsHere:
        segmentStart.getTime()
        === actualStart.getTime(),
      endsHere:
        segmentEnd.getTime()
        === actualEnd.getTime(),
    });
  });

  return {
    segments,
    laneCount:
      occupied.length,
  };
}


function AllDayBar(props: {
  segment: AllDaySegment;
  onClick: (
    event: CalendarEvent,
  ) => void;
}) {
  const {
    segment,
  } = props;

  return (
    <button
      type="button"
      className={[
        "calendar-multiday-bar",
        segment.startsHere
          ? "starts-here"
          : "continues-left",
        segment.endsHere
          ? "ends-here"
          : "continues-right",
      ].join(" ")}
      style={{
        gridColumn:
          `${segment.column + 1} / span ${segment.span}`,
        gridRow:
          `${segment.lane + 1}`,
        "--calendar-event-color":
          segment.event.calendar_color,
      } as CSSProperties}
      title={segment.event.title}
      onClick={(event) => {
        event.stopPropagation();
        props.onClick(
          segment.event,
        );
      }}
    >
      {
        !segment.startsHere
        && (
          <span className="calendar-continuation-mark">
            ‹
          </span>
        )
      }
      <span>
        {segment.event.title}
      </span>
      {
        !segment.endsHere
        && (
          <span className="calendar-continuation-mark">
            ›
          </span>
        )
      }
    </button>
  );
}


export function MonthView(props: {
  cursor: Date;
  events: CalendarEvent[];
  timezone: string;
  onSelectDay: (
    date: Date,
  ) => void;
  onSelectEvent: (
    event: CalendarEvent,
  ) => void;
}) {
  const monthStart = startOfMonthGrid(
    props.cursor,
  );
  const today = dateKey(
    new Date(),
  );

  const weeks = useMemo(
    () => Array.from(
      {
        length: 6,
      },
      (
        _,
        weekIndex,
      ) => {
        const weekStart = addDays(
          monthStart,
          weekIndex * 7,
        );
        const days = Array.from(
          {
            length: 7,
          },
          (
            _unused,
            dayIndex,
          ) => addDays(
            weekStart,
            dayIndex,
          ),
        );
        const multi = weekAllDaySegments(
          props.events,
          weekStart,
          7,
        );

        return {
          weekStart,
          days,
          segments:
            multi.segments,
          laneCount:
            multi.laneCount,
        };
      },
    ),
    [
      monthStart.getTime(),
      props.events,
    ],
  );

  const timedByDate = useMemo(
    () => {
      const result = new Map<
        string,
        CalendarEvent[]
      >();

      props.events
        .filter(
          (event) => (
            !event.all_day
          ),
        )
        .forEach(
          (event) => {
            const key = eventDateKey(
              event,
              props.timezone,
            );

            if (!key) {
              return;
            }

            result.set(
              key,
              [
                ...(
                  result.get(key)
                  ?? []
                ),
                event,
              ],
            );
          },
        );

      return result;
    },
    [
      props.events,
      props.timezone,
    ],
  );

  return (
    <div className="calendar-month">
      <div className="calendar-month-weekdays">
        {
          WEEKDAY_LABELS.map(
            (weekday) => (
              <div key={weekday}>
                {weekday}
              </div>
            ),
          )
        }
      </div>

      <div className="calendar-month-weeks calendar-month-weeks-v2">
        {
          weeks.map(
            (week) => (
              <div
                key={
                  dateKey(
                    week.weekStart,
                  )
                }
                className="calendar-month-week calendar-month-week-v2"
                style={{
                  "--calendar-all-day-lanes":
                    week.laneCount,
                } as CSSProperties}
              >
                <div className="calendar-month-date-row">
                  {
                    week.days.map(
                      (day) => {
                        const key = dateKey(
                          day,
                        );
                        const className = [
                          "calendar-month-date-button",
                          day.getMonth()
                          === props.cursor.getMonth()
                            ? ""
                            : "outside",
                          key === today
                            ? "today"
                            : "",
                        ]
                          .filter(Boolean)
                          .join(" ");

                        return (
                          <button
                            key={key}
                            type="button"
                            className={className}
                            onClick={
                              () => props.onSelectDay(
                                day,
                              )
                            }
                          >
                            <span className="calendar-month-day-number">
                              {day.getDate()}
                            </span>
                          </button>
                        );
                      },
                    )
                  }
                </div>

                {
                  week.laneCount > 0
                  && (
                    <div
                      className="calendar-month-bars calendar-month-bars-v2"
                      style={{
                        gridTemplateRows:
                          `repeat(${week.laneCount}, 20px)`,
                      }}
                      aria-label="All-day events"
                    >
                      {
                        week.segments.map(
                          (segment) => (
                            <AllDayBar
                              key={
                                `${segment.event.id}-${segment.column}`
                              }
                              segment={segment}
                              onClick={
                                props.onSelectEvent
                              }
                            />
                          ),
                        )
                      }
                    </div>
                  )
                }

                <div className="calendar-month-event-row">
                  {
                    week.days.map(
                      (day) => {
                        const key = dateKey(
                          day,
                        );
                        const dayEvents = (
                          timedByDate.get(
                            key,
                          )
                          ?? []
                        );

                        return (
                          <button
                            key={key}
                            type="button"
                            className="calendar-month-event-cell"
                            onClick={
                              () => props.onSelectDay(
                                day,
                              )
                            }
                          >
                            {
                              dayEvents
                                .slice(
                                  0,
                                  4,
                                )
                                .map(
                                  (event) => (
                                    <EventChip
                                      key={event.id}
                                      event={event}
                                      timezone={
                                        props.timezone
                                      }
                                      onClick={
                                        props.onSelectEvent
                                      }
                                    />
                                  ),
                                )
                            }

                            {
                              dayEvents.length > 4
                              && (
                                <span className="calendar-more-events">
                                  +{
                                    dayEvents.length
                                    - 4
                                  } more
                                </span>
                              )
                            }
                          </button>
                        );
                      },
                    )
                  }
                </div>
              </div>
            ),
          )
        }
      </div>
    </div>
  );
}


export function TimeGrid(props: {
  cursor: Date;
  days: 1 | 7;
  events: CalendarEvent[];
  timezone: string;
  onSelectDay: (
    date: Date,
  ) => void;
  onSelectEvent: (
    event: CalendarEvent,
  ) => void;
}) {
  const rangeStart = (
    props.days === 1
      ? new Date(
        props.cursor.getFullYear(),
        props.cursor.getMonth(),
        props.cursor.getDate(),
      )
      : startOfWeek(
        props.cursor,
      )
  );

  const columns = Array.from(
    {
      length: props.days,
    },
    (
      _,
      index,
    ) => addDays(
      rangeStart,
      index,
    ),
  );

  const allDayLayout = useMemo(
    () => weekAllDaySegments(
      props.events,
      rangeStart,
      props.days,
    ),
    [
      props.events,
      props.days,
      rangeStart.getTime(),
    ],
  );

  return (
    <div className="calendar-time-view calendar-time-view-v2">
      <div
        className="calendar-time-header"
        style={{
          gridTemplateColumns:
            `72px repeat(${props.days}, minmax(0, 1fr))`,
        }}
      >
        <div />

        {
          columns.map(
            (day) => (
              <button
                key={
                  dateKey(day)
                }
                type="button"
                className="calendar-time-day-head"
                onClick={
                  () => props.onSelectDay(
                    day,
                  )
                }
              >
                <span>
                  {
                    day.toLocaleDateString(
                      "en-GB",
                      {
                        weekday: "short",
                      },
                    )
                  }
                </span>
                <strong>
                  {day.getDate()}
                </strong>
              </button>
            ),
          )
        }
      </div>

      {
        allDayLayout.laneCount > 0
        && (
          <div
            className="calendar-all-day-strip"
            style={{
              gridTemplateColumns:
                "72px minmax(0, 1fr)",
              "--calendar-all-day-lanes":
                allDayLayout.laneCount,
            } as CSSProperties}
          >
            <div className="calendar-all-day-label">
              All day
            </div>

            <div
              className="calendar-all-day-bars"
              style={{
                gridTemplateColumns:
                  `repeat(${props.days}, minmax(0, 1fr))`,
                gridTemplateRows:
                  `repeat(${allDayLayout.laneCount}, 20px)`,
              }}
            >
              {
                allDayLayout.segments.map(
                  (segment) => (
                    <AllDayBar
                      key={
                        `${segment.event.id}-${segment.column}`
                      }
                      segment={segment}
                      onClick={
                        props.onSelectEvent
                      }
                    />
                  ),
                )
              }
            </div>
          </div>
        )
      }

      {/* The calendar-main pane is the only vertical scroll owner. */}
      <div
        className="calendar-time-grid calendar-time-grid-v2"
        style={{
          gridTemplateColumns:
            `72px repeat(${props.days}, minmax(0, 1fr))`,
          height:
            `${(HOUR_END - HOUR_START) * HOUR_HEIGHT}px`,
        }}
      >
        <div className="calendar-hour-axis">
          {
            Array.from(
              {
                length:
                  HOUR_END
                  - HOUR_START
                  + 1,
              },
              (
                _,
                index,
              ) => {
                const hour = (
                  HOUR_START
                  + index
                );

                return (
                  <span
                    key={hour}
                    style={{
                      top:
                        `${index * HOUR_HEIGHT}px`,
                    }}
                  >
                    {
                      String(hour)
                        .padStart(
                          2,
                          "0",
                        )
                    }:00
                  </span>
                );
              },
            )
          }
        </div>

        {
          columns.map(
            (day) => {
              const key = dateKey(
                day,
              );
              const dayEvents = props.events.filter(
                (event) => (
                  !event.all_day
                  && eventDateKey(
                    event,
                    props.timezone,
                  ) === key
                ),
              );

              return (
                <div
                  key={key}
                  className="calendar-time-column"
                  onDoubleClick={
                    () => props.onSelectDay(
                      day,
                    )
                  }
                >
                  {
                    Array.from(
                      {
                        length:
                          HOUR_END
                          - HOUR_START
                          + 1,
                      },
                      (
                        _,
                        index,
                      ) => (
                        <div
                          key={index}
                          className="calendar-hour-line"
                          style={{
                            top:
                              `${index * HOUR_HEIGHT}px`,
                          }}
                        />
                      ),
                    )
                  }

                  {
                    dayEvents.map(
                      (event) => {
                        const startMinutes = eventMinutes(
                          event.start_at,
                          props.timezone,
                        );
                        const endMinutes = eventMinutes(
                          event.end_at,
                          props.timezone,
                        );
                        const top = Math.max(
                          0,
                          (
                            startMinutes
                            - HOUR_START * 60
                          )
                          / 60
                          * HOUR_HEIGHT,
                        );
                        const height = Math.max(
                          26,
                          (
                            endMinutes
                            - startMinutes
                          )
                          / 60
                          * HOUR_HEIGHT,
                        );

                        return (
                          <button
                            type="button"
                            key={event.id}
                            className="calendar-time-event"
                            style={{
                              top:
                                `${top}px`,
                              height:
                                `${height}px`,
                              "--calendar-event-color":
                                event.calendar_color,
                            } as CSSProperties}
                            onClick={
                              () => props.onSelectEvent(
                                event,
                              )
                            }
                          >
                            <strong>
                              {event.title}
                            </strong>
                            <span>
                              {
                                formatTime(
                                  event.start_at,
                                  props.timezone,
                                )
                              }
                              {" – "}
                              {
                                formatTime(
                                  event.end_at,
                                  props.timezone,
                                )
                              }
                            </span>
                          </button>
                        );
                      },
                    )
                  }
                </div>
              );
            },
          )
        }
      </div>
    </div>
  );
}


export function AgendaView(props: {
  events: CalendarEvent[];
  timezone: string;
  onSelectEvent: (
    event: CalendarEvent,
  ) => void;
}) {
  const grouped = useMemo(
    () => {
      const map = new Map<
        string,
        CalendarEvent[]
      >();

      props.events.forEach(
        (event) => {
          if (
            event.all_day
            && event.start_date
            && event.end_date_exclusive
          ) {
            const start = parseDateKey(
              event.start_date,
            );
            const end = parseDateKey(
              event.end_date_exclusive,
            );

            for (
              let day = start;
              day < end;
              day = addDays(
                day,
                1,
              )
            ) {
              const key = dateKey(
                day,
              );
              map.set(
                key,
                [
                  ...(
                    map.get(key)
                    ?? []
                  ),
                  event,
                ],
              );
            }

            return;
          }

          const key = eventDateKey(
            event,
            props.timezone,
          );

          if (!key) {
            return;
          }

          map.set(
            key,
            [
              ...(
                map.get(key)
                ?? []
              ),
              event,
            ],
          );
        },
      );

      return [
        ...map.entries(),
      ].sort(
        (
          [left],
          [right],
        ) => left.localeCompare(
          right,
        ),
      );
    },
    [
      props.events,
      props.timezone,
    ],
  );

  if (
    grouped.length === 0
  ) {
    return (
      <div className="calendar-empty">
        No events in this period.
      </div>
    );
  }

  return (
    <div className="calendar-agenda">
      {
        grouped.map(
          (
            [
              date,
              dayEvents,
            ],
          ) => (
            <section
              key={date}
              className="calendar-agenda-day"
            >
              <div className="calendar-agenda-date">
                <strong>
                  {
                    formatDate(
                      new Date(
                        `${date}T12:00:00`,
                      ),
                      {
                        weekday: "long",
                        day: "numeric",
                        month: "long",
                      },
                    )
                  }
                </strong>
              </div>

              <div className="calendar-agenda-events">
                {
                  dayEvents.map(
                    (event) => (
                      <button
                        type="button"
                        key={
                          `${event.id}-${date}`
                        }
                        className="calendar-agenda-event"
                        onClick={
                          () => props.onSelectEvent(
                            event,
                          )
                        }
                      >
                        <span
                          className="calendar-source-dot"
                          style={{
                            background:
                              event.calendar_color,
                          }}
                        />
                        <span className="calendar-agenda-time">
                          {
                            eventTimeLabel(
                              event,
                              props.timezone,
                            )
                          }
                        </span>
                        <span className="calendar-agenda-main">
                          <strong>
                            {event.title}
                          </strong>
                          {
                            event.location
                            && (
                              <small>
                                {event.location}
                              </small>
                            )
                          }
                        </span>
                        <span className="calendar-agenda-source">
                          {event.calendar_name}
                        </span>
                      </button>
                    ),
                  )
                }
              </div>
            </section>
          ),
        )
      }
    </div>
  );
}
