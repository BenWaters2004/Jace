import { useMemo, useState } from "react";
import { Modal } from "./Modal";
import type {
  AutomationCreateRequest,
  AutomationDraftResponse,
  AutomationNotificationRecord,
  AutomationRecord,
  AutomationRunRecord,
  AutomationSchedule,
  AutomationScheduleType,
  AutomationStatus,
  AutomationType,
  AutomationUpdateRequest,
  ReasoningMode,
  ToolRecord,
} from "../types";

interface AutomationsViewProps {
  status: AutomationStatus | null;
  automations: AutomationRecord[];
  notifications: AutomationNotificationRecord[];
  tools: ToolRecord[];
  timezone: string;
  onRefresh: () => void;
  onDraft: (text: string, timezone: string) => Promise<AutomationDraftResponse>;
  onCreate: (payload: AutomationCreateRequest) => Promise<void>;
  onUpdate: (automation: AutomationRecord, payload: AutomationUpdateRequest) => Promise<void>;
  onDelete: (automation: AutomationRecord) => Promise<void>;
  onRunNow: (automation: AutomationRecord) => Promise<void>;
  onLoadRuns: (automation: AutomationRecord) => Promise<AutomationRunRecord[]>;
  onReadNotification: (notification: AutomationNotificationRecord) => Promise<void>;
  onReadAllNotifications: () => Promise<void>;
}

interface EditorDraft {
  name: string;
  instruction: string;
  automation_type: AutomationType;
  schedule_type: AutomationScheduleType;
  timezone: string;
  run_at: string;
  interval_minutes: number;
  time_of_day: string;
  days_of_week: number[];
  cron_expression: string;
  watcher_condition: string;
  allowed_tools: string[];
  enabled: boolean;
  notify_on_success: boolean;
  notify_on_failure: boolean;
  notify_on_condition: boolean;
  timeout_seconds: number;
  reasoning_mode: ReasoningMode;
}

const DAY_LABELS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

function localDateTimeInput(value: string | null, timeZone?: string) {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";

  if (timeZone) {
    try {
      const parts = new Intl.DateTimeFormat("en-GB", {
        timeZone,
        year: "numeric",
        month: "2-digit",
        day: "2-digit",
        hour: "2-digit",
        minute: "2-digit",
        hourCycle: "h23",
      }).formatToParts(date);
      const valueOf = (type: string) => parts.find((part) => part.type === type)?.value ?? "";
      return `${valueOf("year")}-${valueOf("month")}-${valueOf("day")}T${valueOf("hour")}:${valueOf("minute")}`;
    } catch {
      // Fall back to the desktop timezone if an invalid IANA name reaches the editor.
    }
  }

  const pad = (n: number) => String(n).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

function timeZoneOffsetMs(date: Date, timeZone: string) {
  const parts = new Intl.DateTimeFormat("en-US", {
    timeZone,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hourCycle: "h23",
  }).formatToParts(date);
  const valueOf = (type: string) => Number(parts.find((part) => part.type === type)?.value ?? 0);
  const representedAsUtc = Date.UTC(
    valueOf("year"),
    valueOf("month") - 1,
    valueOf("day"),
    valueOf("hour"),
    valueOf("minute"),
    valueOf("second"),
  );
  return representedAsUtc - date.getTime();
}

function zonedLocalToIso(value: string, timeZone: string) {
  const match = value.match(/^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})$/);
  if (!match) throw new Error("Invalid one-time date/time.");
  const [, year, month, day, hour, minute] = match;
  const wallClockUtc = Date.UTC(Number(year), Number(month) - 1, Number(day), Number(hour), Number(minute), 0);

  // Resolve the IANA offset twice so dates close to a DST boundary settle on
  // the offset that applies to the resulting instant.
  let instant = wallClockUtc - timeZoneOffsetMs(new Date(wallClockUtc), timeZone);
  instant = wallClockUtc - timeZoneOffsetMs(new Date(instant), timeZone);
  return new Date(instant).toISOString();
}

function formatInZone(value: string, timeZone: string) {
  try {
    return new Date(value).toLocaleString([], { timeZone, timeZoneName: "short" });
  } catch {
    return new Date(value).toLocaleString();
  }
}

function emptyDraft(timezone: string): EditorDraft {
  return {
    name: "",
    instruction: "",
    automation_type: "task",
    schedule_type: "once",
    timezone,
    run_at: "",
    interval_minutes: 60,
    time_of_day: "08:00",
    days_of_week: [0],
    cron_expression: "0 8 * * 1-5",
    watcher_condition: "",
    allowed_tools: [],
    enabled: true,
    notify_on_success: true,
    notify_on_failure: true,
    notify_on_condition: true,
    timeout_seconds: 300,
    reasoning_mode: "fast",
  };
}

function recordToDraft(record: AutomationRecord): EditorDraft {
  return {
    name: record.name,
    instruction: record.instruction,
    automation_type: record.automation_type,
    schedule_type: record.schedule.schedule_type,
    timezone: record.schedule.timezone,
    run_at: localDateTimeInput(record.schedule.run_at, record.schedule.timezone),
    interval_minutes: record.schedule.interval_minutes ?? 60,
    time_of_day: record.schedule.time_of_day ?? "08:00",
    days_of_week: record.schedule.days_of_week ?? [],
    cron_expression: record.schedule.cron_expression ?? "0 8 * * 1-5",
    watcher_condition: record.watcher_condition ?? "",
    allowed_tools: record.allowed_tools,
    enabled: record.enabled,
    notify_on_success: record.notify_on_success,
    notify_on_failure: record.notify_on_failure,
    notify_on_condition: record.notify_on_condition,
    timeout_seconds: record.timeout_seconds,
    reasoning_mode: record.reasoning_mode,
  };
}

function draftResponseToEditor(draft: AutomationDraftResponse, fallbackTimezone: string): EditorDraft {
  return {
    ...emptyDraft(fallbackTimezone),
    name: draft.name,
    instruction: draft.instruction,
    automation_type: draft.automation_type,
    schedule_type: draft.schedule.schedule_type,
    timezone: draft.schedule.timezone || fallbackTimezone,
    run_at: localDateTimeInput(draft.schedule.run_at, draft.schedule.timezone || fallbackTimezone),
    interval_minutes: draft.schedule.interval_minutes ?? 60,
    time_of_day: draft.schedule.time_of_day ?? "08:00",
    days_of_week: draft.schedule.days_of_week ?? [],
    cron_expression: draft.schedule.cron_expression ?? "0 8 * * 1-5",
    watcher_condition: draft.watcher_condition ?? "",
    allowed_tools: draft.suggested_tools,
    notify_on_success: draft.notify_on_success,
    notify_on_failure: draft.notify_on_failure,
    notify_on_condition: draft.notify_on_condition,
  };
}

function toSchedule(draft: EditorDraft): AutomationSchedule {
  return {
    schedule_type: draft.schedule_type,
    timezone: draft.timezone,
    run_at: draft.run_at ? zonedLocalToIso(draft.run_at, draft.timezone) : null,
    interval_minutes: draft.schedule_type === "interval" ? draft.interval_minutes : null,
    time_of_day: ["daily", "weekly"].includes(draft.schedule_type) ? draft.time_of_day : null,
    days_of_week: draft.schedule_type === "weekly" ? draft.days_of_week : [],
    cron_expression: draft.schedule_type === "cron" ? draft.cron_expression : null,
  };
}

function scheduleLabel(automation: AutomationRecord) {
  const schedule = automation.schedule;
  if (schedule.schedule_type === "once") {
    return schedule.run_at ? `Once · ${formatInZone(schedule.run_at, schedule.timezone)}` : "Once";
  }
  if (schedule.schedule_type === "interval") return `Every ${schedule.interval_minutes} min`;
  if (schedule.schedule_type === "daily") return `Daily · ${schedule.time_of_day} · ${schedule.timezone}`;
  if (schedule.schedule_type === "weekly") {
    const days = schedule.days_of_week.map((day) => DAY_LABELS[day]).join(", ");
    return `${days} · ${schedule.time_of_day} · ${schedule.timezone}`;
  }
  return `Cron · ${schedule.cron_expression} · ${schedule.timezone}`;
}

function statusClass(status: string | null) {
  if (!status) return "idle";
  if (status === "success") return "success";
  if (status === "condition_not_met") return "quiet";
  if (status === "failed" || status === "missed") return "failed";
  return "running";
}

function canSave(draft: EditorDraft) {
  if (!draft.name.trim() || !draft.instruction.trim() || !draft.timezone.trim()) return false;
  if (draft.automation_type === "watcher" && !draft.watcher_condition.trim()) return false;
  if (draft.schedule_type === "once" && !draft.run_at) return false;
  if (draft.schedule_type === "weekly" && draft.days_of_week.length === 0) return false;
  if (draft.schedule_type === "cron" && !draft.cron_expression.trim()) return false;
  return true;
}

export function AutomationsView(props: AutomationsViewProps) {
  const [naturalText, setNaturalText] = useState("");
  const [editor, setEditor] = useState<EditorDraft | null>(null);
  const [editing, setEditing] = useState<AutomationRecord | null>(null);
  const [runsFor, setRunsFor] = useState<AutomationRecord | null>(null);
  const [runs, setRuns] = useState<AutomationRunRecord[]>([]);
  const [busy, setBusy] = useState(false);
  const [drafting, setDrafting] = useState(false);
  const [filter, setFilter] = useState<"all" | "task" | "watcher">("all");

  const usableTools = useMemo(
    () => props.tools.filter(
      (tool) =>
        tool.permission !== "deny"
        && !["create_automation", "set_automation_enabled", "run_automation_now"].includes(tool.name),
    ),
    [props.tools],
  );
  const visible = useMemo(
    () => props.automations.filter((item) => filter === "all" || item.automation_type === filter),
    [props.automations, filter],
  );

  function openCreate() {
    setEditing(null);
    setEditor(emptyDraft(props.timezone));
  }

  function openEdit(automation: AutomationRecord) {
    setEditing(automation);
    setEditor(recordToDraft(automation));
  }

  async function parseNaturalLanguage() {
    if (!naturalText.trim()) return;
    setDrafting(true);
    try {
      const result = await props.onDraft(naturalText.trim(), props.timezone);
      setEditing(null);
      setEditor(draftResponseToEditor(result, props.timezone));
    } finally {
      setDrafting(false);
    }
  }

  async function saveEditor() {
    if (!editor || !canSave(editor)) return;
    setBusy(true);
    try {
      const payload: AutomationCreateRequest = {
        name: editor.name.trim(),
        instruction: editor.instruction.trim(),
        automation_type: editor.automation_type,
        schedule: toSchedule(editor),
        watcher_condition: editor.automation_type === "watcher" ? editor.watcher_condition.trim() : null,
        allowed_tools: editor.allowed_tools,
        enabled: editor.enabled,
        notify_on_success: editor.notify_on_success,
        notify_on_failure: editor.notify_on_failure,
        notify_on_condition: editor.notify_on_condition,
        timeout_seconds: editor.timeout_seconds,
        reasoning_mode: editor.reasoning_mode,
      };
      if (editing) await props.onUpdate(editing, payload);
      else await props.onCreate(payload);
      setEditor(null);
      setEditing(null);
      setNaturalText("");
    } finally {
      setBusy(false);
    }
  }

  async function showRuns(automation: AutomationRecord) {
    setRunsFor(automation);
    setRuns(await props.onLoadRuns(automation));
  }

  function toggleDay(day: number) {
    if (!editor) return;
    const next = editor.days_of_week.includes(day)
      ? editor.days_of_week.filter((value) => value !== day)
      : [...editor.days_of_week, day].sort();
    setEditor({ ...editor, days_of_week: next });
  }

  function toggleTool(name: string) {
    if (!editor) return;
    const allowed = editor.allowed_tools.includes(name);
    setEditor({
      ...editor,
      allowed_tools: allowed
        ? editor.allowed_tools.filter((item) => item !== name)
        : [...editor.allowed_tools, name],
    });
  }

  return (
    <section className="content-shell page-shell automations-page">
      <header className="page-header">
        <div>
          <h1>Automations</h1>
          <p>Schedule Jace to work later, repeat tasks, or watch for meaningful changes.</p>
        </div>
        <div className="header-actions">
          <button className="secondary-button" onClick={props.onRefresh}>Refresh</button>
          <button className="primary-button" onClick={openCreate}>New automation</button>
        </div>
      </header>

      {!props.status?.enabled && (
        <div className="notice-banner">Automation is disabled by backend configuration. Set JACE_AUTOMATION_ENABLED=true and restart Jace.</div>
      )}
      {props.status?.enabled && !props.status.scheduler_running && (
        <div className="notice-banner warning">The scheduler is not running. Restart the Jace backend before relying on scheduled work.</div>
      )}

      <div className="stat-grid automation-stat-grid">
        <div className="stat-card"><strong>{props.status?.automation_count ?? props.automations.length}</strong><span>Automations</span></div>
        <div className="stat-card"><strong>{props.status?.enabled_count ?? props.automations.filter((a) => a.enabled).length}</strong><span>Enabled</span></div>
        <div className="stat-card"><strong>{props.status?.watcher_count ?? props.automations.filter((a) => a.automation_type === "watcher").length}</strong><span>Watchers</span></div>
        <div className="stat-card"><strong>{props.status?.unread_notifications ?? 0}</strong><span>Unread results</span></div>
      </div>

      <section className="automation-natural-card">
        <div>
          <span className="section-kicker">Natural language</span>
          <h2>Describe what Jace should do</h2>
          <p>Jace will turn this into a draft. You still review the schedule and tool permissions before anything is created.</p>
        </div>
        <div className="automation-natural-row">
          <textarea
            value={naturalText}
            onChange={(event) => setNaturalText(event.target.value)}
            placeholder='e.g. "Every weekday at 8am, check the latest Ollama release and notify me only when it changes."'
          />
          <button className="primary-button" disabled={drafting || !naturalText.trim()} onClick={() => void parseNaturalLanguage()}>
            {drafting ? "Building draft…" : "Create draft"}
          </button>
        </div>
      </section>

      {props.notifications.length > 0 && (
        <section className="automation-notifications">
          <div className="section-heading-row">
            <div><span className="section-kicker">Results</span><h2>Unread notifications</h2></div>
            <button className="secondary-button" onClick={() => void props.onReadAllNotifications()}>Mark all read</button>
          </div>
          <div className="automation-notification-list">
            {props.notifications.map((notification) => (
              <article className={`automation-notification ${notification.level}`} key={notification.id}>
                <div><strong>{notification.title}</strong><span>{new Date(notification.created_at).toLocaleString()}</span><p>{notification.body}</p></div>
                <button className="icon-button" title="Mark read" onClick={() => void props.onReadNotification(notification)}>×</button>
              </article>
            ))}
          </div>
        </section>
      )}

      <div className="automation-toolbar">
        <div className="segmented-control">
          {(["all", "task", "watcher"] as const).map((value) => (
            <button key={value} className={filter === value ? "active" : ""} onClick={() => setFilter(value)}>
              {value === "all" ? "All" : value === "task" ? "Tasks" : "Watchers"}
            </button>
          ))}
        </div>
        <span>Times shown in your local desktop timezone unless a task specifies otherwise.</span>
      </div>

      <div className="automation-list">
        {visible.length === 0 ? (
          <div className="large-empty">
            <div>⏱</div>
            <h3>No automations yet</h3>
            <p>Create a reminder, recurring task, or condition watcher.</p>
          </div>
        ) : visible.map((automation) => (
          <article className={`automation-card ${automation.enabled ? "" : "inactive"}`} key={automation.id}>
            <div className="automation-card-main">
              <div className="automation-title-line">
                <span className={`automation-kind ${automation.automation_type}`}>{automation.automation_type}</span>
                <h2>{automation.name}</h2>
                <span className={`automation-run-status ${statusClass(automation.last_status)}`}>{automation.last_status ?? "Never run"}</span>
              </div>
              <p>{automation.instruction}</p>
              {automation.automation_type === "watcher" && automation.watcher_condition && (
                <div className="watcher-condition"><strong>Notify when</strong> {automation.watcher_condition}</div>
              )}
              <div className="automation-meta-row">
                <span>{scheduleLabel(automation)}</span>
                <span>{automation.next_run_at ? `Next: ${new Date(automation.next_run_at).toLocaleString()}` : "No next run"}</span>
                <span>{automation.allowed_tools.length ? `${automation.allowed_tools.length} scoped tool${automation.allowed_tools.length === 1 ? "" : "s"}` : "No tools"}</span>
              </div>
              {automation.last_result && <div className="automation-last-result">{automation.last_result}</div>}
            </div>
            <div className="automation-card-actions">
              <label className="automation-switch" title={automation.enabled ? "Disable" : "Enable"}>
                <input
                  type="checkbox"
                  checked={automation.enabled}
                  onChange={(event) => void props.onUpdate(automation, { enabled: event.target.checked })}
                />
                <span />
              </label>
              <button className="secondary-button" onClick={() => void props.onRunNow(automation)}>Run now</button>
              <button className="secondary-button" onClick={() => void showRuns(automation)}>History</button>
              <button className="secondary-button" onClick={() => openEdit(automation)}>Edit</button>
              <button
                className="danger-button"
                onClick={() => {
                  if (window.confirm(`Delete automation "${automation.name}" and its run history?`)) void props.onDelete(automation);
                }}
              >Delete</button>
            </div>
          </article>
        ))}
      </div>

      {editor && (
        <Modal
          title={editing ? "Edit automation" : "Create automation"}
          onClose={() => { setEditor(null); setEditing(null); }}
          footer={(
            <>
              <button className="secondary-button" onClick={() => { setEditor(null); setEditing(null); }}>Cancel</button>
              <button className="primary-button" disabled={busy || !canSave(editor)} onClick={() => void saveEditor()}>
                {busy ? "Saving…" : editing ? "Save changes" : "Create automation"}
              </button>
            </>
          )}
        >
          <div className="automation-editor">
            <div className="automation-form-grid">
              <label><span>Name</span><input value={editor.name} onChange={(e) => setEditor({ ...editor, name: e.target.value })} /></label>
              <label>
                <span>Type</span>
                <select value={editor.automation_type} onChange={(e) => setEditor({ ...editor, automation_type: e.target.value as AutomationType })}>
                  <option value="task">Scheduled task</option>
                  <option value="watcher">Condition watcher</option>
                </select>
              </label>
              <label className="wide-field"><span>Instruction</span><textarea rows={4} value={editor.instruction} onChange={(e) => setEditor({ ...editor, instruction: e.target.value })} /></label>
              {editor.automation_type === "watcher" && (
                <label className="wide-field"><span>Notify condition</span><textarea rows={2} value={editor.watcher_condition} onChange={(e) => setEditor({ ...editor, watcher_condition: e.target.value })} placeholder="Notify me only when the version differs from the previous observation." /></label>
              )}
            </div>

            <div className="automation-editor-section">
              <div className="section-heading-row"><div><span className="section-kicker">Schedule</span><h3>When should this run?</h3></div></div>
              <div className="automation-form-grid">
                <label>
                  <span>Schedule type</span>
                  <select value={editor.schedule_type} onChange={(e) => setEditor({ ...editor, schedule_type: e.target.value as AutomationScheduleType })}>
                    <option value="once">One time</option>
                    <option value="interval">Interval</option>
                    <option value="daily">Daily</option>
                    <option value="weekly">Weekly</option>
                    <option value="cron">Cron</option>
                  </select>
                </label>
                <label><span>Timezone</span><input value={editor.timezone} onChange={(e) => setEditor({ ...editor, timezone: e.target.value })} placeholder="Europe/London" /></label>
                {editor.schedule_type === "once" && <label><span>Run at</span><input type="datetime-local" value={editor.run_at} onChange={(e) => setEditor({ ...editor, run_at: e.target.value })} /></label>}
                {editor.schedule_type === "interval" && <label><span>Every (minutes)</span><input type="number" min={1} value={editor.interval_minutes} onChange={(e) => setEditor({ ...editor, interval_minutes: Number(e.target.value) })} /></label>}
                {["daily", "weekly"].includes(editor.schedule_type) && <label><span>Time</span><input type="time" value={editor.time_of_day} onChange={(e) => setEditor({ ...editor, time_of_day: e.target.value })} /></label>}
                {editor.schedule_type === "cron" && <label className="wide-field"><span>Cron expression</span><input value={editor.cron_expression} onChange={(e) => setEditor({ ...editor, cron_expression: e.target.value })} placeholder="0 8 * * 1-5" /></label>}
              </div>
              {editor.schedule_type === "weekly" && (
                <div className="weekday-picker">
                  {DAY_LABELS.map((label, day) => <button key={label} className={editor.days_of_week.includes(day) ? "active" : ""} onClick={() => toggleDay(day)}>{label}</button>)}
                </div>
              )}
            </div>

            <div className="automation-editor-section">
              <div className="section-heading-row">
                <div><span className="section-kicker">Capabilities</span><h3>Pre-approved tools</h3></div>
                <span className="section-note">Global Deny still overrides this list.</span>
              </div>
              <div className="automation-tool-grid">
                {usableTools.length === 0 ? <p className="muted-copy">No globally available tools.</p> : usableTools.map((tool) => (
                  <label className={`automation-tool-option risk-${tool.risk}`} key={tool.name}>
                    <input type="checkbox" checked={editor.allowed_tools.includes(tool.name)} onChange={() => toggleTool(tool.name)} />
                    <span><strong>{tool.label}</strong><small>{tool.description}</small><em>{tool.risk}</em></span>
                  </label>
                ))}
              </div>
            </div>

            <div className="automation-editor-section">
              <div className="automation-form-grid">
                <label>
                  <span>Reasoning</span>
                  <select value={editor.reasoning_mode} onChange={(e) => setEditor({ ...editor, reasoning_mode: e.target.value as ReasoningMode })}>
                    <option value="fast">Fast</option><option value="balanced">Balanced</option><option value="deep">Deep</option>
                  </select>
                </label>
                <label><span>Timeout (seconds)</span><input type="number" min={30} max={1800} value={editor.timeout_seconds} onChange={(e) => setEditor({ ...editor, timeout_seconds: Number(e.target.value) })} /></label>
              </div>
              <div className="automation-toggle-grid">
                <label className="toggle-line"><input type="checkbox" checked={editor.enabled} onChange={(e) => setEditor({ ...editor, enabled: e.target.checked })} /><span><strong>Enabled</strong><small>Schedule this automation immediately after saving.</small></span></label>
                {editor.automation_type === "task" && <label className="toggle-line"><input type="checkbox" checked={editor.notify_on_success} onChange={(e) => setEditor({ ...editor, notify_on_success: e.target.checked })} /><span><strong>Notify on completion</strong><small>Create a desktop notification after successful runs.</small></span></label>}
                {editor.automation_type === "watcher" && <label className="toggle-line"><input type="checkbox" checked={editor.notify_on_condition} onChange={(e) => setEditor({ ...editor, notify_on_condition: e.target.checked })} /><span><strong>Notify when condition matches</strong><small>Quiet runs remain visible in history without interrupting you.</small></span></label>}
                <label className="toggle-line"><input type="checkbox" checked={editor.notify_on_failure} onChange={(e) => setEditor({ ...editor, notify_on_failure: e.target.checked })} /><span><strong>Notify on failure</strong><small>Surface timeouts and failed automation runs.</small></span></label>
              </div>
            </div>
          </div>
        </Modal>
      )}

      {runsFor && (
        <Modal title={`${runsFor.name} · Run history`} onClose={() => { setRunsFor(null); setRuns([]); }}>
          <div className="automation-run-list">
            {runs.length === 0 ? <div className="sidebar-empty">This automation has not run yet.</div> : runs.map((run) => (
              <article className="automation-run-row" key={run.id}>
                <div className="automation-run-head">
                  <span className={`automation-run-status ${statusClass(run.status)}`}>{run.status}</span>
                  <strong>{new Date(run.started_at).toLocaleString()}</strong>
                  <span>{run.trigger_type}</span>
                </div>
                {run.result && <p>{run.result}</p>}
                {run.error && <p className="run-error">{run.error}</p>}
                <div className="automation-run-meta">
                  <span>{run.completed_at ? `Finished ${new Date(run.completed_at).toLocaleTimeString()}` : "Running"}</span>
                  <span>{run.tool_names.length ? `Tools: ${run.tool_names.join(", ")}` : "No tools"}</span>
                  {run.condition_met !== null && <span>Condition: {run.condition_met ? "met" : "not met"}</span>}
                </div>
              </article>
            ))}
          </div>
        </Modal>
      )}
    </section>
  );
}
