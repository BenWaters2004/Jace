import type { ToolActivity } from "../types";
import { useAgentOffice } from "../agents/useAgentOffice";
import { PixelAgentOffice } from "./PixelAgentOffice";
import "./AgentOffice.css";

function formatElapsed(start: string | null, end: string | null): string {
  if (!start) return "—";

  const startMs = new Date(start).getTime();
  const endMs = end ? new Date(end).getTime() : Date.now();
  const seconds = Math.max(0, Math.floor((endMs - startMs) / 1000));

  if (seconds < 60) return `${seconds}s`;

  const minutes = Math.floor(seconds / 60);
  const remainder = seconds % 60;

  if (minutes < 60) return `${minutes}m ${remainder}s`;

  const hours = Math.floor(minutes / 60);
  return `${hours}h ${minutes % 60}m`;
}

export function AgentOffice(props: {
  activities: ToolActivity[];
  onExpand: () => void;
}) {
  // `activities` remains in the public component contract because CommandCenter
  // already supplies it. Phase 11B now renders real background agent tasks
  // instead of inferring pretend agents from primary-chat tool calls.
  void props.activities;

  const office = useAgentOffice();

  const busyCount = office.activeTasks.length;
  const workerCount = office.status?.workers ?? 0;

  return (
    <section className="cc-panel agent-office-panel phase11-agent-office">
      <div className="cc-panel-topline agent-office-topline">
        <div>
          <span className="cc-kicker">Jace office</span>
          <strong>
            {office.error
              ? "Agent office unavailable"
              : busyCount > 0
                ? `${busyCount} background job${busyCount === 1 ? "" : "s"} active`
                : "Agents standing by"}
          </strong>
        </div>

        <div className="agent-office-actions">
          {office.status && (
            <span
              className={`agent-manager-pill ${
                office.status.manager_running ? "online" : "offline"
              }`}
            >
              {office.status.manager_running ? "●" : "○"} {workerCount} worker
              {workerCount === 1 ? "" : "s"}
            </span>
          )}

          <button
            className="cc-icon-button"
            onClick={props.onExpand}
            title="Focus agent office"
          >
            □
          </button>
        </div>
      </div>

      {office.error ? (
        <div className="agent-office-error">
          <strong>Could not connect to background agents</strong>
          <span>{office.error}</span>
          <button type="button" onClick={() => void office.refresh()}>
            Retry
          </button>
        </div>
      ) : (
        <>
          <PixelAgentOffice
            workers={office.workers}
            selectedTaskId={office.selectedTaskId}
            onSelectTask={office.setSelectedTaskId}
          />

          {office.selectedTask && (
            <div className="agent-task-inspector">
              <div className="agent-task-inspector-head">
                <div>
                  <span>{office.selectedTask.agent_name}</span>
                  <strong>{office.selectedTask.title}</strong>
                </div>

                <button
                  type="button"
                  onClick={() => office.setSelectedTaskId(null)}
                  aria-label="Close task details"
                >
                  ×
                </button>
              </div>

              <div className="agent-task-meta">
                <span className={`agent-task-status ${office.selectedTask.status}`}>
                  {office.selectedTask.status.replace(/_/g, " ")}
                </span>
                <span>
                  {Math.round(office.selectedTask.progress * 100)}%
                </span>
                <span>
                  {formatElapsed(
                    office.selectedTask.started_at,
                    office.selectedTask.completed_at,
                  )}
                </span>
              </div>

              <p>{office.selectedTask.instruction}</p>

              {office.selectedTask.progress_message && (
                <div className="agent-current-action">
                  {office.selectedTask.progress_message}
                </div>
              )}

              {office.selectedTask.used_tools.length > 0 && (
                <div className="agent-tool-chips">
                  {office.selectedTask.used_tools.map((tool) => (
                    <span key={tool}>{tool}</span>
                  ))}
                </div>
              )}

              {office.selectedTask.result && (
                <div className="agent-result-preview">
                  <strong>Result</strong>
                  <pre>{office.selectedTask.result}</pre>
                </div>
              )}

              {office.selectedTask.error && (
                <div className="agent-result-preview error">
                  <strong>Error</strong>
                  <pre>{office.selectedTask.error}</pre>
                </div>
              )}

              <div className="agent-task-inspector-actions">
                {[
                  "queued",
                  "running",
                  "thinking",
                  "using_tool",
                  "waiting_permission",
                ].includes(office.selectedTask.status) && (
                  <button
                    type="button"
                    className="danger"
                    onClick={() => void office.cancel(office.selectedTask!.id)}
                  >
                    Cancel job
                  </button>
                )}

                {["failed", "cancelled"].includes(
                  office.selectedTask.status,
                ) && (
                  <button
                    type="button"
                    onClick={() => void office.retry(office.selectedTask!.id)}
                  >
                    Retry job
                  </button>
                )}
              </div>
            </div>
          )}
        </>
      )}
    </section>
  );
}
