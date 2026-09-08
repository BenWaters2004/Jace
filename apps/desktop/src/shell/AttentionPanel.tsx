import type { AutomationNotificationRecord, AutomationRecord, PendingToolApproval, ToolActivity } from "../types";

export function AttentionPanel(props: {
  online: boolean;
  memoryCount: number;
  activeAutomations: AutomationRecord[];
  notifications: AutomationNotificationRecord[];
  pendingApproval: PendingToolApproval | null;
  activities: ToolActivity[];
  onOpenTasks: () => void;
  onOpenApproval: () => void;
}) {
  const activeActivities = props.activities.filter((item) => item.status === "requested" || item.status === "awaiting_approval");
  return (
    <aside className="attention-panel">
      <div className="attention-heading"><span className="cc-kicker">Attention</span><h2>Right now</h2></div>

      {props.pendingApproval && (
        <button className="attention-card permission-card" onClick={props.onOpenApproval}>
          <span className="attention-card-icon">!</span>
          <div><strong>Permission needed</strong><small>{props.pendingApproval.label}</small></div>
        </button>
      )}

      <div className="attention-section">
        <div className="attention-section-title"><span>Active</span><b>{activeActivities.length}</b></div>
        {activeActivities.length === 0 ? <p className="attention-empty">No live tool actions.</p> : activeActivities.slice(-4).map((item) => (
          <div className="attention-row" key={item.callId}>
            <span className={`attention-dot ${item.status}`} />
            <div><strong>{item.label}</strong><small>{item.status.replace(/_/g, " ")}</small></div>
          </div>
        ))}
      </div>

      <div className="attention-section">
        <div className="attention-section-title"><span>Background</span><button onClick={props.onOpenTasks}>Open</button></div>
        {props.activeAutomations.length === 0 ? <p className="attention-empty">No enabled automations.</p> : props.activeAutomations.slice(0, 3).map((item) => (
          <div className="attention-row" key={item.id}>
            <span className="attention-dot automation" />
            <div><strong>{item.name}</strong><small>{item.next_run_at ? new Date(item.next_run_at).toLocaleString() : "Scheduled"}</small></div>
          </div>
        ))}
      </div>

      <div className="attention-section">
        <div className="attention-section-title"><span>Inbox</span><b>{props.notifications.length}</b></div>
        {props.notifications.slice(0, 3).map((item) => (
          <div className="attention-row" key={item.id}><span className="attention-dot notice" /><div><strong>{item.title}</strong><small>{item.body}</small></div></div>
        ))}
        {props.notifications.length === 0 && <p className="attention-empty">Nothing needs your attention.</p>}
      </div>

      <div className="attention-system-card">
        <div><span className={`system-light ${props.online ? "online" : "offline"}`} /><strong>{props.online ? "Local backend online" : "Backend unavailable"}</strong></div>
        <small>{props.memoryCount} active memories · private local runtime</small>
      </div>
    </aside>
  );
}
