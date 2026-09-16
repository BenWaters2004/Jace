import { useEffect, useState } from "react";

import { enrichCalendarEvent } from "../../api";
import type {
  CalendarEvent,
  CalendarEventCreateRequest,
  CalendarEventEnrichment,
  CalendarEventUpdateRequest,
  CalendarSource,
} from "../../types";
import {
  addDays,
  dateKey,
  formatDate,
  formatInstantDate,
  formatTime,
  isoLocal,
  pad,
  parseDateKey,
  partsForInstant,
  providerName,
} from "./calendarUtils";

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

export function blankEventForm(
  source: CalendarSource,
  date: Date,
  displayTimezone = "Europe/London",
): EventFormState {
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
    timezone: displayTimezone || source.timezone || "Europe/London",
  };
}

export function eventToForm(
  event: CalendarEvent,
  displayTimezone = event.timezone || "Europe/London",
): EventFormState {
  if (event.all_day) {
    const startDate = event.start_date ?? dateKey(new Date());
    const inclusiveEnd = event.end_date_exclusive
      ? dateKey(addDays(parseDateKey(event.end_date_exclusive), -1))
      : startDate;

    return {
      id: event.id,
      sourceId: event.source_id,
      title: event.title,
      description: event.description,
      location: event.location,
      allDay: true,
      date: startDate,
      endDate: inclusiveEnd,
      startTime: "09:00",
      endTime: "10:00",
      timezone: displayTimezone,
    };
  }

  const start = event.start_at
    ? partsForInstant(event.start_at, displayTimezone)
    : null;
  const end = event.end_at
    ? partsForInstant(event.end_at, displayTimezone)
    : null;

  const startDate = start
    ? `${start.year}-${start.month}-${start.day}`
    : dateKey(new Date());

  return {
    id: event.id,
    sourceId: event.source_id,
    title: event.title,
    description: event.description,
    location: event.location,
    allDay: false,
    date: startDate,
    endDate: startDate,
    startTime: start
      ? `${pad(start.hour)}:${pad(start.minute)}`
      : "09:00",
    endTime: end
      ? `${pad(end.hour)}:${pad(end.minute)}`
      : "10:00",
    timezone: displayTimezone,
  };
}

export function formToCreatePayload(
  form: EventFormState,
): CalendarEventCreateRequest {
  if (form.allDay) {
    const inclusiveEnd = parseDateKey(
      form.endDate || form.date,
    );

    return {
      source_id: form.sourceId,
      title: form.title.trim(),
      description: form.description,
      location: form.location,
      all_day: true,
      start_date: form.date,
      end_date_exclusive: dateKey(
        addDays(inclusiveEnd, 1),
      ),
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

export function createToUpdatePayload(
  payload: CalendarEventCreateRequest,
): CalendarEventUpdateRequest {
  const {
    source_id: _sourceId,
    created_by: _createdBy,
    ...rest
  } = payload;

  return rest;
}

function EmailEnrichment(props: {
  enrichment: CalendarEventEnrichment;
}) {
  const enrichment = props.enrichment;

  if (enrichment.status === "no_match") {
    return (
      <div className="calendar-email-enrichment muted">
        <strong>Source email not matched</strong>
        <span>
          Jace recognised this as a Gmail-created calendar event, but could not
          confidently match it to a message in the connected mailbox.
        </span>
      </div>
    );
  }

  if (enrichment.status !== "matched" || !enrichment.source_email) {
    return null;
  }

  const email = enrichment.source_email;

  return (
    <section className="calendar-email-enrichment">
      <div className="calendar-email-enrichment-heading">
        <div>
          <span className="calendar-drawer-eyebrow">Source Gmail message</span>
          <strong>{email.subject || "(no subject)"}</strong>
        </div>
        <span className="calendar-email-match">
          {enrichment.confidence === "high"
            ? "High confidence"
            : enrichment.confidence === "medium"
              ? "Likely match"
              : "Possible match"}
        </span>
      </div>

      <div className="calendar-email-meta">
        {email.from && (
          <div>
            <span>From</span>
            <strong>{email.from}</strong>
          </div>
        )}
        {email.received_at && (
          <div>
            <span>Received</span>
            <strong>
              {formatInstantDate(
                email.received_at,
                enrichment.display_timezone,
                {
                  day: "numeric",
                  month: "short",
                  year: "numeric",
                  hour: "2-digit",
                  minute: "2-digit",
                },
              )}
            </strong>
          </div>
        )}
      </div>

      {enrichment.details.length > 0 && (
        <div className="calendar-email-details-grid">
          {enrichment.details.map((detail, index) => (
            <div key={`${detail.label}-${index}`}>
              <span>{detail.label}</span>
              <strong>{detail.value}</strong>
            </div>
          ))}
        </div>
      )}

      {email.body && (
        <details className="calendar-email-body-details" open>
          <summary>Email details</summary>
          <pre>{email.body}</pre>
        </details>
      )}
    </section>
  );
}

export function EventDetails(props: {
  event: CalendarEvent;
  timezone: string;
  onClose: () => void;
  onEdit: (event: CalendarEvent) => void;
  onDelete: (event: CalendarEvent) => Promise<void>;
}) {
  const { event } = props;
  const [
    enrichment,
    setEnrichment,
  ] = useState<CalendarEventEnrichment | null>(null);
  const [
    enrichmentLoading,
    setEnrichmentLoading,
  ] = useState(false);
  const [
    enrichmentError,
    setEnrichmentError,
  ] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;

    setEnrichment(null);
    setEnrichmentError(null);

    if (!event.can_enrich_from_email) {
      return () => {
        cancelled = true;
      };
    }

    setEnrichmentLoading(true);

    void enrichCalendarEvent(
      event.id,
      props.timezone,
    )
      .then((result) => {
        if (!cancelled) {
          setEnrichment(result);
        }
      })
      .catch((error: unknown) => {
        if (!cancelled) {
          setEnrichmentError(
            error instanceof Error
              ? error.message
              : "Could not read the source Gmail message.",
          );
        }
      })
      .finally(() => {
        if (!cancelled) {
          setEnrichmentLoading(false);
        }
      });

    return () => {
      cancelled = true;
    };
  }, [
    event.id,
    event.can_enrich_from_email,
    props.timezone,
  ]);

  const showProviderDescription = Boolean(
    event.description
    && enrichment?.status !== "matched",
  );

  return (
    <aside className="calendar-drawer">
      <div className="calendar-drawer-head">
        <div>
          <span className="calendar-drawer-eyebrow">
            {providerName(event.provider_id)} · {event.calendar_name}
          </span>
          <h3>{event.title}</h3>
        </div>
        <button
          type="button"
          className="calendar-icon-button"
          onClick={props.onClose}
          aria-label="Close event details"
        >
          ×
        </button>
      </div>

      <div className="calendar-detail-list">
        <div>
          <span>When</span>
          <strong>
            {event.all_day
              ? event.end_date_exclusive && event.start_date
                ? `${formatDate(
                    parseDateKey(event.start_date),
                    { day: "numeric", month: "short", year: "numeric" },
                  )} – ${formatDate(
                    addDays(parseDateKey(event.end_date_exclusive), -1),
                    { day: "numeric", month: "short", year: "numeric" },
                  )}`
                : (event.start_date ?? "All day")
              : `${formatInstantDate(
                  event.start_at,
                  props.timezone,
                )} · ${formatTime(
                  event.start_at,
                  props.timezone,
                )}–${formatTime(
                  event.end_at,
                  props.timezone,
                )}`}
          </strong>
        </div>

        <div>
          <span>Calendar</span>
          <strong>{event.calendar_name}</strong>
        </div>

        {event.account_hint && (
          <div>
            <span>Account</span>
            <strong>{event.account_hint}</strong>
          </div>
        )}

        {event.location && (
          <div>
            <span>Location</span>
            <strong>{event.location}</strong>
          </div>
        )}

        {showProviderDescription && (
          <div className="calendar-detail-description">
            <span>Description</span>
            <p>{event.description}</p>
          </div>
        )}

        {event.can_enrich_from_email && enrichmentLoading && (
          <div className="calendar-email-loading">
            <span>Source email</span>
            <strong>Reading Gmail…</strong>
          </div>
        )}

        {enrichmentError && (
          <div className="calendar-email-error">
            <span>Source email</span>
            <strong>{enrichmentError}</strong>
          </div>
        )}

        {enrichment && (
          <EmailEnrichment enrichment={enrichment} />
        )}

        <div>
          <span>Status</span>
          <strong>{event.status}</strong>
        </div>

        <div>
          <span>Display timezone</span>
          <strong>{props.timezone}</strong>
        </div>
      </div>

      <div className="calendar-drawer-actions">
        {event.can_edit && (
          <button
            type="button"
            className="primary-button"
            onClick={() => props.onEdit(event)}
          >
            Edit
          </button>
        )}

        {event.can_delete && (
          <button
            type="button"
            className="secondary-button danger-soft"
            onClick={() => void props.onDelete(event)}
          >
            Delete
          </button>
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
          <span className="calendar-drawer-eyebrow">
            {form.id ? "Edit Jace event" : "New Jace event"}
          </span>
          <h3>{form.id ? "Edit event" : "Create event"}</h3>
        </div>
        <button
          type="button"
          className="calendar-icon-button"
          onClick={props.onClose}
          aria-label="Close event editor"
        >
          ×
        </button>
      </div>

      <div className="calendar-form-grid">
        <label className="calendar-form-wide">
          <span>Title</span>
          <input
            value={form.title}
            autoFocus
            onChange={(event) =>
              props.onChange({
                ...form,
                title: event.target.value,
              })
            }
          />
        </label>

        <label className="calendar-form-wide">
          <span>Calendar</span>
          <select
            value={form.sourceId}
            disabled={form.id !== null}
            onChange={(event) =>
              props.onChange({
                ...form,
                sourceId: event.target.value,
              })
            }
          >
            {props.jaceSources.map((source) => (
              <option
                key={source.id}
                value={source.id}
              >
                {source.name}
              </option>
            ))}
          </select>
        </label>

        <label className="calendar-check-row calendar-form-wide">
          <input
            type="checkbox"
            checked={form.allDay}
            onChange={(event) =>
              props.onChange({
                ...form,
                allDay: event.target.checked,
              })
            }
          />
          <span>All day</span>
        </label>

        <label>
          <span>{form.allDay ? "Start date" : "Date"}</span>
          <input
            type="date"
            value={form.date}
            onChange={(event) =>
              props.onChange({
                ...form,
                date: event.target.value,
              })
            }
          />
        </label>

        {form.allDay ? (
          <label>
            <span>End date</span>
            <input
              type="date"
              value={form.endDate}
              onChange={(event) =>
                props.onChange({
                  ...form,
                  endDate: event.target.value,
                })
              }
            />
          </label>
        ) : (
          <>
            <label>
              <span>Start</span>
              <input
                type="time"
                value={form.startTime}
                onChange={(event) =>
                  props.onChange({
                    ...form,
                    startTime: event.target.value,
                  })
                }
              />
            </label>

            <label>
              <span>End</span>
              <input
                type="time"
                value={form.endTime}
                onChange={(event) =>
                  props.onChange({
                    ...form,
                    endTime: event.target.value,
                  })
                }
              />
            </label>
          </>
        )}

        <label className="calendar-form-wide">
          <span>Timezone</span>
          <input
            value={form.timezone}
            onChange={(event) =>
              props.onChange({
                ...form,
                timezone: event.target.value,
              })
            }
          />
        </label>

        <label className="calendar-form-wide">
          <span>Location</span>
          <input
            value={form.location}
            onChange={(event) =>
              props.onChange({
                ...form,
                location: event.target.value,
              })
            }
          />
        </label>

        <label className="calendar-form-wide">
          <span>Description</span>
          <textarea
            rows={6}
            value={form.description}
            onChange={(event) =>
              props.onChange({
                ...form,
                description: event.target.value,
              })
            }
          />
        </label>
      </div>

      <div className="calendar-drawer-actions">
        <button
          type="button"
          className="secondary-button"
          disabled={props.saving}
          onClick={props.onClose}
        >
          Cancel
        </button>

        <button
          type="button"
          className="primary-button"
          disabled={
            props.saving
            || !form.title.trim()
          }
          onClick={() => void props.onSave()}
        >
          {props.saving
            ? "Saving…"
            : form.id
              ? "Save changes"
              : "Create event"}
        </button>
      </div>
    </aside>
  );
}
