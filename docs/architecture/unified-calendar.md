# Unified Calendar Architecture

Step 4C.4A establishes one local calendar domain shared by the future Calendar
workspace, Jace tools, Google Calendar sync and Microsoft Calendar sync.

## Core flow

```text
Google Calendar ----\
                     \
Outlook Calendar ----- > CalendarSource + CalendarEvent ---> Calendar UI
                     /                         |
Jace-native Calendar-/                         +-----------> Jace tools
```

The visual UI and the assistant must never maintain separate copies of calendar
logic. Both use the Calendar Service and the same SQLite tables.

## Tables

### calendar_sources

One visible calendar. `provider_id` is `jace`, `google` or `microsoft`. External
sources reference a Jace `connection_id`; credentials remain in the connection
vault and are never copied into calendar storage.

### calendar_events

One normalized event. Timed events store UTC instants plus their original IANA
timezone. All-day events store date-only values with an exclusive end date.

External IDs, iCal UID, series IDs and provider versions are retained so sync can
reconcile updates instead of producing duplicates.

### calendar_sync_state

One provider cursor per source. It reserves:

- `sync_token` for Google Calendar incremental sync;
- `delta_url` for Microsoft Graph delta sync;
- sync window, timestamps, provider state and errors.

## Native Jace calendar

The stable source ID is:

```text
jace-default
```

It is created automatically at backend startup. 4C.4A allows manual/API CRUD only
for Jace-native events. External provider write-back intentionally waits for 4C.5.

## Provider adapter contract

4C.4C and 4C.4D should translate raw provider events into
`NormalizedCalendarEvent` and call `upsert_provider_event()`. This keeps Google
and Microsoft payload quirks out of the UI and generic calendar intelligence.

## API

```text
GET    /calendar/status
GET    /calendar/sources
PATCH  /calendar/sources/{source_id}
GET    /calendar/events?start=...&end=...&timezone=...
POST   /calendar/events
GET    /calendar/events/{event_id}
PATCH  /calendar/events/{event_id}
DELETE /calendar/events/{event_id}
```

Mutations publish `calendar.changed` runtime events so the desktop Calendar
workspace can refresh without inventing a separate event bus later.

## Next phases

- 4C.4B: Calendar workspace UI.
- 4C.4C: Google Calendar list + incremental sync.
- 4C.4D: Microsoft calendar list + delta sync.
- 4C.4E: Jace calendar intelligence/tools.
- 4C.5: Provider create/edit/delete and advanced scheduling.
