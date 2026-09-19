import { useState } from "react";

import type {
  PendingToolApproval,
  ToolApprovalDecision,
} from "../types";

import { Modal } from "./Modal";


interface ToolApprovalModalProps {
  approval: PendingToolApproval | null;
  onDecision: (
    decision: ToolApprovalDecision,
  ) => Promise<void>;
}


const EMAIL_WRITE_TOOLS = new Set([
  "gmail_create_draft",
  "gmail_send_email",
  "outlook_create_draft",
  "outlook_send_email",
]);

const CALENDAR_WRITE_TOOLS = new Set([
  "google_calendar_create_event",
  "google_calendar_modify_event",
  "microsoft_calendar_create_event",
  "microsoft_calendar_modify_event",
]);


function prettyArguments(
  value: Record<string, unknown>,
) {
  return JSON.stringify(value, null, 2);
}


function providerLabel(
  providerId: string | null | undefined,
): string {
  switch (providerId) {
    case "google":
      return "Google";
    case "microsoft":
      return "Microsoft";
    case "github":
      return "GitHub";
    case "custom_api":
      return "Custom API";
    default:
      return providerId || "External service";
  }
}


function stringList(
  value: unknown,
): string[] {
  if (!Array.isArray(value)) {
    return [];
  }

  return value.filter(
    (item): item is string => (
      typeof item === "string"
      && item.length > 0
    ),
  );
}


function objectValue(
  value: unknown,
): Record<string, unknown> | null {
  if (
    value
    && typeof value === "object"
    && !Array.isArray(value)
  ) {
    return value as Record<string, unknown>;
  }

  return null;
}


function objects(
  value: unknown,
): Record<string, unknown>[] {
  if (!Array.isArray(value)) {
    return [];
  }

  return value
    .map(objectValue)
    .filter(
      (
        item,
      ): item is Record<string, unknown> => (
        item !== null
      ),
    );
}


function stringValue(
  value: unknown,
): string {
  return typeof value === "string"
    ? value
    : "";
}


function EmailApprovalSummary({
  approval,
}: {
  approval: PendingToolApproval;
}) {
  const args = approval.arguments;
  const draftId = stringValue(args.draft_id);
  const to = stringList(args.to);
  const cc = stringList(args.cc);
  const bcc = stringList(args.bcc);
  const subject = stringValue(args.subject);
  const body = stringValue(args.body);
  const bodyFormat = (
    args.body_format === "html"
      ? "HTML"
      : "Plain text"
  );

  if (draftId) {
    return (
      <>
        <div className="approval-details">
          <span>Existing draft</span>
          <code>{draftId}</code>
        </div>
        <div className="approval-details">
          <span>Action</span>
          <code>Send this existing draft</code>
        </div>
      </>
    );
  }

  return (
    <>
      <div className="approval-details">
        <span>To</span>
        <code>
          {to.length > 0 ? to.join(", ") : "(none)"}
        </code>
      </div>

      {cc.length > 0 && (
        <div className="approval-details">
          <span>Cc</span>
          <code>{cc.join(", ")}</code>
        </div>
      )}

      {bcc.length > 0 && (
        <div className="approval-details">
          <span>Bcc</span>
          <code>{bcc.join(", ")}</code>
        </div>
      )}

      <div className="approval-details">
        <span>Subject</span>
        <code>{subject || "(no subject)"}</code>
      </div>

      <div className="approval-details">
        <span>Body format</span>
        <code>{bodyFormat}</code>
      </div>

      <div className="approval-arguments">
        <span>Message body</span>
        <pre>{body || "(empty message body)"}</pre>
      </div>
    </>
  );
}


function attendeeLabel(
  attendee: Record<string, unknown>,
): string {
  const email = stringValue(attendee.email);
  const name = stringValue(attendee.name);
  const type = stringValue(attendee.type) || "required";

  return [
    name ? `${name} <${email}>` : email,
    type,
  ].filter(Boolean).join(" · ");
}


function recurrenceLabel(
  value: Record<string, unknown> | null,
): string {
  if (!value) {
    return "";
  }

  const frequency = stringValue(value.frequency);
  const interval = Number(value.interval || 1);
  const weekdays = stringList(value.weekdays);
  const count = Number(value.count || 0);
  const until = stringValue(value.until);

  const pieces = [
    frequency
      ? `Every ${interval > 1 ? `${interval} ` : ""}${frequency}`
      : "Recurring",
  ];

  if (weekdays.length > 0) {
    pieces.push(weekdays.join(", "));
  }

  if (count > 0) {
    pieces.push(`${count} occurrences`);
  } else if (until) {
    pieces.push(`until ${until}`);
  } else {
    pieces.push("no end date");
  }

  return pieces.join(" · ");
}


function CalendarApprovalSummary({
  approval,
}: {
  approval: PendingToolApproval;
}) {
  const args = approval.arguments;
  const create = approval.capability_id === "calendar.create";
  const action = stringValue(args.action) || "update";
  const deleteAction = action === "delete";
  const title = stringValue(args.title);
  const calendar = stringValue(args.calendar);
  const nestedAttendees = objects(args.attendees);
  const flatRequired = stringList(args.attendee_emails);
  const flatOptional = stringList(args.optional_attendee_emails);
  const flatResources = stringList(args.resource_attendee_emails);

  const attendees = (
    nestedAttendees.length > 0
      ? nestedAttendees
      : [
        ...flatRequired.map((email) => ({
          email,
          type: "required",
        })),
        ...flatOptional.map((email) => ({
          email,
          type: "optional",
        })),
        ...flatResources.map((email) => ({
          email,
          type: "resource",
        })),
      ]
  );

  const nestedReminders = objects(args.reminders);
  const flatReminderMinutes = (
    Array.isArray(args.reminder_minutes)
      ? args.reminder_minutes.filter(
        (value): value is number => typeof value === "number",
      )
      : []
  );

  const reminders = (
    nestedReminders.length > 0
      ? nestedReminders
      : flatReminderMinutes.map((minutes) => ({
        minutes_before_start: minutes,
        method: "popup",
      }))
  );

  const nestedRecurrence = objectValue(args.recurrence);
  const recurrenceFrequency = stringValue(args.recurrence_frequency);

  const recurrence = (
    nestedRecurrence
    ?? (
      recurrenceFrequency
        ? {
          frequency: recurrenceFrequency,
          interval: Number(args.recurrence_interval || 1),
          weekdays: stringList(args.recurrence_weekdays),
          day_of_month: args.recurrence_day_of_month,
          month: args.recurrence_month,
          count: args.recurrence_count,
          until: args.recurrence_until,
        }
        : null
    )
  );

  const scope = stringValue(args.recurrence_scope) || "single";
  const onlineMeeting = (
    stringValue(args.online_meeting)
    || (
      args.add_online_meeting === true
        ? (
          approval.provider_id === "google"
            ? "google_meet"
            : approval.provider_id === "microsoft"
              ? "microsoft_teams"
              : "online_meeting"
        )
        : ""
    )
  );
  const notifyAttendees = args.notify_attendees !== false;
  const allDay = args.all_day === true;

  const start = (
    allDay
      ? stringValue(args.start_date)
      : stringValue(args.start_at)
  );
  const end = (
    allDay
      ? stringValue(args.end_date_exclusive)
      : stringValue(args.end_at)
  );

  const microsoft = approval.provider_id === "microsoft";
  const hasPotentialInvites = (
    attendees.length > 0
    || (
      !create
      && (
        deleteAction
        || Object.prototype.hasOwnProperty.call(
          args,
          "attendees",
        )
      )
    )
  );

  return (
    <div className="calendar-approval-summary">
      <div className="approval-details">
        <span>Calendar action</span>
        <code>
          {
            create
              ? "Create event"
              : deleteAction
                ? (
                  scope === "series"
                    ? "Delete recurring series"
                    : "Delete occurrence / event"
                )
                : (
                  scope === "series"
                    ? "Update recurring series"
                    : "Update occurrence / event"
                )
          }
        </code>
      </div>

      {title && (
        <div className="approval-details">
          <span>Event</span>
          <code>{title}</code>
        </div>
      )}

      {calendar && (
        <div className="approval-details">
          <span>Calendar</span>
          <code>{calendar}</code>
        </div>
      )}

      {(start || end) && (
        <div className="approval-details">
          <span>{allDay ? "Dates" : "When"}</span>
          <code>
            {start || "unchanged"}
            {end ? ` → ${end}` : ""}
          </code>
        </div>
      )}

      {attendees.length > 0 && (
        <section className="calendar-approval-section">
          <span className="calendar-approval-heading">
            Attendees ({attendees.length})
          </span>

          <div className="calendar-approval-attendees">
            {attendees.map((attendee, index) => (
              <code key={`${stringValue(attendee.email)}-${index}`}>
                {attendeeLabel(attendee)}
              </code>
            ))}
          </div>
        </section>
      )}

      {recurrence && (
        <div className="approval-details">
          <span>Recurrence</span>
          <code>{recurrenceLabel(recurrence)}</code>
        </div>
      )}

      {reminders.length > 0 && (
        <div className="approval-details">
          <span>Reminders</span>
          <code>
            {
              reminders.map((reminder) => (
                `${
                  Number(reminder.minutes_before_start || 0)
                } min · ${
                  stringValue(reminder.method) || "popup"
                }`
              )).join(", ")
            }
          </code>
        </div>
      )}

      {(
        (
          Array.isArray(args.reminders)
          || Array.isArray(args.reminder_minutes)
        )
        && reminders.length === 0
      ) && (
        <div className="approval-details">
          <span>Reminders</span>
          <code>Disable reminders</code>
        </div>
      )}

      {onlineMeeting && (
        <div className="approval-details">
          <span>Online meeting</span>
          <code>
            {
              onlineMeeting === "google_meet"
                ? "Create Google Meet"
                : onlineMeeting === "microsoft_teams"
                  ? "Create Microsoft Teams meeting"
                  : onlineMeeting
            }
          </code>
        </div>
      )}

      {hasPotentialInvites && (
        <div className="calendar-approval-warning">
          <strong>Attendee notification side effect</strong>
          <span>
            {
              microsoft
                ? (
                  "Microsoft controls meeting invitations/updates for events "
                  + "with attendees. Creating, changing or cancelling the "
                  + "meeting can send messages to those attendees."
                )
                : notifyAttendees
                  ? (
                    "Google attendee updates are enabled for this write, so "
                    + "affected attendees can receive invitation/update emails."
                  )
                  : (
                    "Google attendee update emails are explicitly suppressed "
                    + "for this write."
                  )
            }
          </span>
        </div>
      )}

      {scope === "series" && (
        <div className="calendar-approval-warning">
          <strong>Entire recurring series</strong>
          <span>
            This action targets the recurring series rather than only the
            selected occurrence.
          </span>
        </div>
      )}

      <details className="calendar-approval-raw">
        <summary>Raw write arguments</summary>
        <pre>{prettyArguments(args)}</pre>
      </details>
    </div>
  );
}


export function ToolApprovalModal({
  approval,
  onDecision,
}: ToolApprovalModalProps) {
  const [submitting, setSubmitting] = useState(false);

  if (!approval) {
    return null;
  }

  const external = Boolean(
    approval.connection_id
    && approval.capability_id,
  );
  const emailWrite = EMAIL_WRITE_TOOLS.has(
    approval.tool_name,
  );
  const calendarWrite = CALENDAR_WRITE_TOOLS.has(
    approval.tool_name,
  );
  const isSend = approval.capability_id === "email.send";

  async function decide(
    decision: ToolApprovalDecision,
  ) {
    if (submitting) {
      return;
    }

    setSubmitting(true);

    try {
      await onDecision(decision);
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <Modal
      title={
        isSend
          ? "Confirm email send"
          : calendarWrite
            ? "Calendar approval required"
            : "Tool approval required"
      }
      onClose={() => void decide("deny_once")}
    >
      <div className="approval-content">
        <div
          className={`approval-risk ${approval.risk}`}
        >
          {
            isSend
              ? "Sends external email"
              : calendarWrite
                ? "Changes external calendar"
                : approval.risk === "write"
                  ? (
                    external
                      ? "Changes external data"
                      : "Changes local data"
                  )
                  : approval.risk === "execute"
                    ? "Runs an action"
                    : "Read only"
          }
        </div>

        <h3>{approval.label}</h3>
        <p>{approval.description}</p>

        {external && (
          <>
            <div className="approval-details">
              <span>Connected account</span>
              <code>
                {
                  `${providerLabel(
                    approval.provider_id,
                  )}${
                    approval.account_hint
                      ? ` · ${approval.account_hint}`
                      : ""
                  }`
                }
              </code>
            </div>

            <div className="approval-details">
              <span>Capability</span>
              <code>{approval.capability_id}</code>
            </div>
          </>
        )}

        <div className="approval-details">
          <span>Requested action</span>
          <code>{approval.tool_name}</code>
        </div>

        {approval.source === "agent" && (
          <div className="approval-details">
            <span>Requested by</span>
            <code>
              {
                `${
                  (
                    approval.agent_id
                    || "background"
                  ).toUpperCase()
                } AGENT`
              }
            </code>
          </div>
        )}

        {
          emailWrite
            ? (
              <EmailApprovalSummary approval={approval} />
            )
            : calendarWrite
              ? (
                <CalendarApprovalSummary approval={approval} />
              )
              : (
                <div className="approval-arguments">
                  <span>Arguments</span>
                  <pre>
                    {prettyArguments(approval.arguments)}
                  </pre>
                </div>
              )
        }

        <p className="approval-help">
          {
            isSend
              ? (
                "Send once authorizes only this email. "
                + "Always allow changes the saved send permission for "
                + "this capability on this connected account."
              )
              : external
                ? (
                  "Allow once applies only to this call. "
                  + "Always allow/deny changes the saved permission for "
                  + "this capability on this connected account only."
                )
                : (
                  "Allow once applies only to this call. "
                  + "Always allow changes the saved permission for this tool."
                )
          }
        </p>
      </div>

      <div className="approval-actions">
        <button
          className="secondary-button danger-soft"
          disabled={submitting}
          onClick={() => void decide("deny_always")}
        >
          Always deny
        </button>

        <button
          className="secondary-button"
          disabled={submitting}
          onClick={() => void decide("deny_once")}
        >
          {isSend ? "Cancel" : "Deny once"}
        </button>

        <button
          className="secondary-button"
          disabled={submitting}
          onClick={() => void decide("allow_always")}
        >
          {isSend ? "Always allow sending" : "Always allow"}
        </button>

        <button
          className="primary-button"
          disabled={submitting}
          onClick={() => void decide("allow_once")}
        >
          {
            isSend
              ? "Send once"
              : calendarWrite
                ? "Approve calendar change"
                : "Allow once"
          }
        </button>
      </div>
    </Modal>
  );
}
