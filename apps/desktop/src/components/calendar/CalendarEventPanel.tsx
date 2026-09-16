import type { CalendarEvent, CalendarEventCreateRequest, CalendarEventUpdateRequest, CalendarSource } from "../../types";
import { addDays, dateKey, formatDate, formatTime, isoLocal, pad, parseDateKey, providerName } from "./calendarUtils";

export type EventFormState = {
  id: string | null;
  sourceId: string;
  title: string;
  description: string;
  location: string;
  allDay: boolean;
  date: string;
  endDate: string;
  startTime: string;
  endTime: string;
  timezone: string;
};

export function blankEventForm(source: CalendarSource, date: Date): EventFormState {
  const day = dateKey(date);
  return {
    id: null,
    sourceId: source.id,
    title: "",
    description: "",
    location: "",
    allDay: false,
    date: day,
    endDate: day,
    startTime: "09:00",
    endTime: "10:00",
    timezone: source.timezone || "Europe/London",
  };
}

export function eventToForm(event: CalendarEvent): EventFormState {
  const start = event.start_at
    ? new Date(event.start_at)
    : event.start_date
      ? parseDateKey(event.start_date)
      : new Date();
  const end = event.end_at
    ? new Date(event.end_at)
    : event.end_date_exclusive
      ? addDays(parseDateKey(event.end_date_exclusive), -1)
      : start;

  return {
    id: event.id,
    sourceId: event.source_id,
    title: event.title,
    description: event.description,
    location: event.location,
    allDay: event.all_day,
    date: dateKey(start),
    endDate: dateKey(end),
    startTime: event.all_day ? "09:00" : `${pad(start.getHours())}:${pad(start.getMinutes())}`,
    endTime: event.all_day ? "10:00" : `${pad(end.getHours())}:${pad(end.getMinutes())}`,
    timezone: event.timezone,
  };
}

export function formToCreatePayload(form: EventFormState): CalendarEventCreateRequest {
  if (form.allDay) {
    const inclusiveEnd = parseDateKey(form.endDate || form.date);
    return {
      source_id: form.sourceId,
      title: form.title.trim(),
      description: form.description,
      location: form.location,
      all_day: true,
      start_date: form.date,
      end_date_exclusive: dateKey(addDays(inclusiveEnd, 1)),
      start_at: null,
      end_at: null,
      timezone: form.timezone,
      created_by: "user",
    };
  }

  return {
    source_id: form.sourceId,
    title: form.title.trim(),
    description: form.description,
    location: form.location,
    all_day: false,
    start_at: isoLocal(form.date, form.startTime),
    end_at: isoLocal(form.date, form.endTime),
    start_date: null,
    end_date_exclusive: null,
    timezone: form.timezone,
    created_by: "user",
  };
}

export function createToUpdatePayload(payload: CalendarEventCreateRequest): CalendarEventUpdateRequest {
  const { source_id: _sourceId, created_by: _createdBy, ...rest } = payload;
  return rest;
}

export function EventDetails(props: {
  event: CalendarEvent;
  onClose: () => void;
  onEdit: (event: CalendarEvent) => void;
  onDelete: (event: CalendarEvent) => Promise<void>;
}) {
  const { event } = props;
  return (
    <aside className="calendar-drawer">
      <div className="calendar-drawer-head">
        <div>
          <span className="calendar-drawer-eyebrow">
            {providerName(event.provider_id)} · {event.calendar_name}
          </span>
          <h3>{event.title}</h3>
        </div>
        <button type="button" className="calendar-icon-button" onClick={props.onClose} aria-label="Close event details">×</button>
      </div>

      <div className="calendar-detail-list">
        <div>
          <span>When</span>
          <strong>
            {event.all_day
              ? (event.start_date ?? "All day")
              : `${formatDate(new Date(event.start_at ?? ""))} · ${formatTime(event.start_at)}–${formatTime(event.end_at)}`}
          </strong>
        </div>
        <div><span>Calendar</span><strong>{event.calendar_name}</strong></div>
        {event.account_hint && <div><span>Account</span><strong>{event.account_hint}</strong></div>}
        {event.location && <div><span>Location</span><strong>{event.location}</strong></div>}
        {event.description && (
          <div className="calendar-detail-description">
            <span>Description</span>
            <p>{event.description}</p>
          </div>
        )}
        <div><span>Status</span><strong>{event.status}</strong></div>
        <div><span>Timezone</span><strong>{event.timezone}</strong></div>
      </div>

      <div className="calendar-drawer-actions">
        {event.can_edit && (
          <button type="button" className="primary-button" onClick={() => props.onEdit(event)}>Edit</button>
        )}
        {event.can_delete && (
          <button type="button" className="secondary-button danger-soft" onClick={() => void props.onDelete(event)}>Delete</button>
        )}
        {!event.can_edit && (
          <p className="calendar-readonly-note">
            External provider editing is intentionally read-only until 4C.5.
          </p>
        )}
      </div>
    </aside>
  );
}

export function EventEditor(props: {
  form: EventFormState;
  jaceSources: CalendarSource[];
  saving: boolean;
  onChange: (next: EventFormState) => void;
  onClose: () => void;
  onSave: () => Promise<void>;
}) {
  const { form } = props;
  return (
    <aside className="calendar-drawer editor">
      <div className="calendar-drawer-head">
        <div>
          <span className="calendar-drawer-eyebrow">{form.id ? "Edit Jace event" : "New Jace event"}</span>
          <h3>{form.id ? "Edit event" : "Create event"}</h3>
        </div>
        <button type="button" className="calendar-icon-button" onClick={props.onClose} aria-label="Close event editor">×</button>
      </div>

      <div className="calendar-form-grid">
        <label className="calendar-form-wide">
          <span>Title</span>
          <input value={form.title} autoFocus onChange={(event) => props.onChange({ ...form, title: event.target.value })} />
        </label>

        <label className="calendar-form-wide">
          <span>Calendar</span>
          <select value={form.sourceId} disabled={form.id !== null} onChange={(event) => props.onChange({ ...form, sourceId: event.target.value })}>
            {props.jaceSources.map((source) => (
              <option key={source.id} value={source.id}>{source.name}</option>
            ))}
          </select>
        </label>

        <label className="calendar-check-row calendar-form-wide">
          <input type="checkbox" checked={form.allDay} onChange={(event) => props.onChange({ ...form, allDay: event.target.checked })} />
          <span>All day</span>
        </label>

        <label>
          <span>{form.allDay ? "Start date" : "Date"}</span>
          <input type="date" value={form.date} onChange={(event) => props.onChange({ ...form, date: event.target.value })} />
        </label>

        {form.allDay ? (
          <label>
            <span>End date</span>
            <input type="date" value={form.endDate} onChange={(event) => props.onChange({ ...form, endDate: event.target.value })} />
          </label>
        ) : (
          <>
            <label>
              <span>Start</span>
              <input type="time" value={form.startTime} onChange={(event) => props.onChange({ ...form, startTime: event.target.value })} />
            </label>
            <label>
              <span>End</span>
              <input type="time" value={form.endTime} onChange={(event) => props.onChange({ ...form, endTime: event.target.value })} />
            </label>
          </>
        )}

        <label className="calendar-form-wide">
          <span>Location</span>
          <input value={form.location} onChange={(event) => props.onChange({ ...form, location: event.target.value })} />
        </label>
        <label className="calendar-form-wide">
          <span>Description</span>
          <textarea rows={6} value={form.description} onChange={(event) => props.onChange({ ...form, description: event.target.value })} />
        </label>
      </div>

      <div className="calendar-drawer-actions">
        <button type="button" className="secondary-button" disabled={props.saving} onClick={props.onClose}>Cancel</button>
        <button type="button" className="primary-button" disabled={props.saving || !form.title.trim()} onClick={() => void props.onSave()}>
          {props.saving ? "Saving…" : form.id ? "Save changes" : "Create event"}
        </button>
      </div>
    </aside>
  );
}
