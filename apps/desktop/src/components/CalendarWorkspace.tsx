import { useCallback, useEffect, useMemo, useState } from "react";

import {
  createCalendarEvent,
  deleteCalendarEvent,
  getCalendarEvents,
  getCalendarSources,
  getCalendarStatus,
  updateCalendarEvent,
  updateCalendarSource,
  syncCalendar,
} from "../api";
import type {
  CalendarEvent,
  CalendarSource,
  CalendarStatus,
  CalendarViewMode,
} from "../types";
import {
  EventDetails,
  EventEditor,
  blankEventForm,
  createToUpdatePayload,
  eventToForm,
  formToCreatePayload,
  type EventFormState,
} from "./calendar/CalendarEventPanel";
import { AgendaView, MonthView, TimeGrid } from "./calendar/CalendarViews";
import {
  addDays,
  dateKey,
  eventDateKey,
  eventTimeLabel,
  formatDate,
  providerName,
  startOfDay,
  startOfWeek,
  viewRange,
} from "./calendar/calendarUtils";

export function CalendarWorkspace() {
  const [status, setStatus] = useState<CalendarStatus | null>(null);
  const [sources, setSources] = useState<CalendarSource[]>([]);
  const [events, setEvents] = useState<CalendarEvent[]>([]);
  const [enabledSourceIds, setEnabledSourceIds] = useState<Set<string>>(new Set());
  const [view, setView] = useState<CalendarViewMode>("month");
  const [cursor, setCursor] = useState(() => new Date());
  const [selectedEvent, setSelectedEvent] = useState<CalendarEvent | null>(null);
  const [form, setForm] = useState<EventFormState | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const timezone = status?.timezone ?? "Europe/London";
  const range = useMemo(() => viewRange(cursor, view), [cursor, view]);
  const activeSourceIds = useMemo(
    () => sources.filter((source) => source.enabled && enabledSourceIds.has(source.id)).map((source) => source.id),
    [sources, enabledSourceIds],
  );
  const jaceSources = useMemo(
    () => sources.filter((source) => source.provider_id === "jace" && !source.read_only),
    [sources],
  );

  const loadSources = useCallback(async () => {
    const [nextStatus, sourceResponse] = await Promise.all([
      getCalendarStatus(),
      getCalendarSources(),
    ]);
    setStatus(nextStatus);
    setSources(sourceResponse.sources);
    setEnabledSourceIds(
      new Set(
        sourceResponse.sources
          .filter((source) => source.enabled)
          .map((source) => source.id),
      ),
    );
    return sourceResponse.sources;
  }, []);

  const loadEvents = useCallback(
    async (sourceIds = activeSourceIds) => {
      const response = await getCalendarEvents(
        range.start.toISOString(),
        range.end.toISOString(),
        timezone,
        sourceIds,
      );
      setEvents(response.events);
      return response.events;
    },
    [activeSourceIds, range.end, range.start, timezone],
  );

  // JACE_STEP4C4C_GOOGLE_CALENDAR_SYNC
  const [syncing, setSyncing] = useState(false);

  const refreshAll = useCallback(async () => {
    setError(null);
    setLoading(true);
    setSyncing(true);

    try {
      const syncResult = await syncCalendar();

      if (syncResult.needs_reconnect) {
        setError(
          "Google Calendar access needs to be authorized. "
          + "Reconnect Google in Settings → Connections after adding calendar.readonly.",
        );
      } else if (syncResult.errors.length > 0) {
        setError(
          `Calendar sync completed with warnings: ${syncResult.errors.join(" · ")}`,
        );
      }

      const nextSources = await loadSources();
      const selected = nextSources
        .filter((source) => source.enabled)
        .map((source) => source.id);

      const response = await getCalendarEvents(
        range.start.toISOString(),
        range.end.toISOString(),
        timezone,
        selected,
      );
      setEvents(response.events);
    } catch (refreshError) {
      setError(
        refreshError instanceof Error
          ? refreshError.message
          : "Could not synchronize the calendar.",
      );
    } finally {
      setSyncing(false);
      setLoading(false);
    }
  }, [loadSources, range.end, range.start, timezone]);

  useEffect(() => {
    void refreshAll();
    // Initial calendar boot only; view/range changes are handled below.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (!status) return;
    void loadEvents().catch((refreshError) => {
      setError(refreshError instanceof Error ? refreshError.message : "Could not refresh events.");
    });
  }, [activeSourceIds.join("|"), range.end.getTime(), range.start.getTime(), timezone]);

  useEffect(() => {
    const intervalId = window.setInterval(() => {
      void refreshAll();
    }, 5 * 60 * 1000);

    return () => {
      window.clearInterval(intervalId);
    };
  }, [refreshAll]);

  const upcoming = useMemo(() => {
    const now = new Date();
    return events
      .filter((event) => {
        if (event.all_day) {
          return event.start_date ? new Date(`${event.start_date}T12:00:00`) >= startOfDay(now) : false;
        }
        return event.end_at ? new Date(event.end_at) >= now : false;
      })
      .slice()
      .sort((left, right) => eventDateKey(left).localeCompare(eventDateKey(right)))
      .slice(0, 6);
  }, [events]);

  const heading = useMemo(() => {
    if (view === "month") {
      return cursor.toLocaleDateString([], { month: "long", year: "numeric" });
    }
    if (view === "day") {
      return formatDate(cursor, { weekday: "long", day: "numeric", month: "long", year: "numeric" });
    }
    if (view === "week") {
      const start = startOfWeek(cursor);
      const end = addDays(start, 6);
      return `${formatDate(start, { day: "numeric", month: "short" })} – ${formatDate(end, { day: "numeric", month: "short", year: "numeric" })}`;
    }
    return `Agenda from ${formatDate(cursor)}`;
  }, [cursor, view]);

  function moveCursor(direction: -1 | 1) {
    if (view === "month") {
      setCursor(new Date(cursor.getFullYear(), cursor.getMonth() + direction, 1));
    } else if (view === "week") {
      setCursor(addDays(cursor, 7 * direction));
    } else if (view === "day") {
      setCursor(addDays(cursor, direction));
    } else {
      setCursor(addDays(cursor, 30 * direction));
    }
  }

  function openCreate(date = cursor) {
    const source = jaceSources.find((item) => item.is_primary) ?? jaceSources[0];
    if (!source) {
      setError("No writable Jace calendar is available.");
      return;
    }
    setSelectedEvent(null);
    setForm(blankEventForm(source, date));
  }

  function openEdit(event: CalendarEvent) {
    setSelectedEvent(null);
    setForm(eventToForm(event));
  }

  async function saveForm() {
    if (!form) return;
    setSaving(true);
    setError(null);
    try {
      const payload = formToCreatePayload(form);
      if (form.id) {
        await updateCalendarEvent(form.id, createToUpdatePayload(payload));
      } else {
        await createCalendarEvent(payload);
      }
      setForm(null);
      await loadEvents();
    } catch (saveError) {
      setError(saveError instanceof Error ? saveError.message : "Could not save the event.");
    } finally {
      setSaving(false);
    }
  }

  async function removeEvent(event: CalendarEvent) {
    if (!window.confirm(`Delete "${event.title}" from the Jace calendar?`)) return;
    try {
      await deleteCalendarEvent(event.id);
      setSelectedEvent(null);
      await loadEvents();
    } catch (deleteError) {
      setError(deleteError instanceof Error ? deleteError.message : "Could not delete the event.");
    }
  }

  async function toggleSource(source: CalendarSource) {
    const nextEnabled = !enabledSourceIds.has(source.id);
    setEnabledSourceIds((current) => {
      const next = new Set(current);
      if (nextEnabled) next.add(source.id);
      else next.delete(source.id);
      return next;
    });

    if (source.enabled !== nextEnabled) {
      try {
        const updated = await updateCalendarSource(source.id, { enabled: nextEnabled });
        setSources((current) => current.map((item) => item.id === updated.id ? updated : item));
      } catch (sourceError) {
        setError(sourceError instanceof Error ? sourceError.message : "Could not update the calendar source.");
      }
    }
  }

  return (
    <section className="calendar-workspace">
      <header className="calendar-toolbar">
        <div className="calendar-toolbar-leading">
          <button type="button" className="secondary-button" onClick={() => setCursor(new Date())}>Today</button>
          <div className="calendar-nav-arrows">
            <button type="button" className="calendar-icon-button" onClick={() => moveCursor(-1)} aria-label="Previous period">‹</button>
            <button type="button" className="calendar-icon-button" onClick={() => moveCursor(1)} aria-label="Next period">›</button>
          </div>
          <div className="calendar-heading">
            <h2>{heading}</h2>
            <span>{timezone}</span>
          </div>
        </div>

        <div className="calendar-toolbar-actions">
          <div className="calendar-view-switcher" aria-label="Calendar view">
            {(["month", "week", "day", "agenda"] as CalendarViewMode[]).map((item) => (
              <button key={item} type="button" className={view === item ? "active" : ""} onClick={() => setView(item)}>
                {item[0].toUpperCase() + item.slice(1)}
              </button>
            ))}
          </div>
          <button
            type="button"
            className="secondary-button"
            disabled={loading || syncing}
            onClick={() => void refreshAll()}
          >
            {syncing ? "Syncing…" : loading ? "Refreshing…" : "Refresh"}
          </button>
          <button type="button" className="primary-button" onClick={() => openCreate()}>+ New event</button>
        </div>
      </header>

      {error && (
        <div className="calendar-error">
          <span>{error}</span>
          <button type="button" onClick={() => setError(null)}>×</button>
        </div>
      )}

      <div className="calendar-layout">
        <aside className="calendar-sidebar">
          <section>
            <div className="calendar-sidebar-heading"><h3>Calendars</h3><span>{sources.length}</span></div>
            <div className="calendar-source-list">
              {sources.map((source) => (
                <label key={source.id} className="calendar-source-row">
                  <input type="checkbox" checked={enabledSourceIds.has(source.id)} onChange={() => void toggleSource(source)} />
                  <span className="calendar-source-dot" style={{ background: source.color }} />
                  <span className="calendar-source-name">
                    <strong>{source.name}</strong>
                    <small>{providerName(source.provider_id)}{source.account_hint ? ` · ${source.account_hint}` : ""}</small>
                  </span>
                  {source.sync_status === "error" && <span className="calendar-source-warning" title="Calendar sync error">!</span>}
                </label>
              ))}
            </div>
          </section>

          <section>
            <div className="calendar-sidebar-heading"><h3>Upcoming</h3></div>
            <div className="calendar-upcoming-list">
              {upcoming.length === 0 ? (
                <p className="calendar-muted">Nothing upcoming in this view.</p>
              ) : upcoming.map((event) => (
                <button type="button" key={event.id} className="calendar-upcoming-item" onClick={() => setSelectedEvent(event)}>
                  <span className="calendar-source-dot" style={{ background: event.calendar_color }} />
                  <span>
                    <strong>{event.title}</strong>
                    <small>{eventTimeLabel(event)} · {eventDateKey(event)}</small>
                  </span>
                </button>
              ))}
            </div>
          </section>

          {status && (
            <section className="calendar-summary-card">
              <span>Jace calendar</span>
              <strong>{status.local_event_count} local events</strong>
              <small>{status.external_event_count} synced external events</small>
            </section>
          )}
        </aside>

        <main className="calendar-main">
          {loading && events.length === 0 ? (
            <div className="calendar-empty">Loading calendar…</div>
          ) : view === "month" ? (
            <MonthView cursor={cursor} events={events} onSelectDay={openCreate} onSelectEvent={setSelectedEvent} />
          ) : view === "week" ? (
            <TimeGrid cursor={cursor} days={7} events={events} onSelectDay={openCreate} onSelectEvent={setSelectedEvent} />
          ) : view === "day" ? (
            <TimeGrid cursor={cursor} days={1} events={events} onSelectDay={openCreate} onSelectEvent={setSelectedEvent} />
          ) : (
            <AgendaView events={events} onSelectEvent={setSelectedEvent} />
          )}
        </main>

        {selectedEvent && !form && (
          <EventDetails event={selectedEvent} onClose={() => setSelectedEvent(null)} onEdit={openEdit} onDelete={removeEvent} />
        )}
        {form && (
          <EventEditor form={form} jaceSources={jaceSources} saving={saving} onChange={setForm} onClose={() => setForm(null)} onSave={saveForm} />
        )}
      </div>
    </section>
  );
}
