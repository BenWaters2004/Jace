/** C4D.1 — read-only Agent Director visibility; no new permissions or tool calls. */
import { useEffect, useMemo, useState } from "react";
import { API_BASE_URL } from "../constants";
import { authenticatedFetch } from "../api";
import type { AgentTask } from "../agents/types";
import { collectDirectorWorkflows, type WorkflowVisibilityState } from "../agents/workflowInsightsModel";
import "./DirectorWorkflowInsights.css";

interface CollaborationStatus {
  enabled: boolean;
  privacy_enabled: boolean;
  cloud_egress_enabled: boolean;
  drafter_configured: boolean;
  reviewer_configured: boolean;
  retrieved_source_review_enabled: boolean;
  supplied_excerpt_review_enabled: boolean;
}

const labels: Record<WorkflowVisibilityState, string> = {
  manual_review: "MANUAL REVIEW",
  in_progress: "IN PROGRESS",
  queued: "QUEUED",
  failed: "INCOMPLETE",
  finalizing: "FINALISING",
  completed: "COMPLETED",
};

function displayTime(value: string): string {
  const parsed = Date.parse(value);
  return Number.isFinite(parsed) ? new Date(parsed).toLocaleString() : "—";
}

function safeLabel(value: string, limit = 72): string {
  return value.length > limit ? `${value.slice(0, limit)}…` : value;
}

export function DirectorWorkflowInsights(props: {
  tasks: AgentTask[];
  realtimeConnected: boolean;
  onRefresh: () => void;
}) {
  const workflows = useMemo(() => collectDirectorWorkflows(props.tasks, 12), [props.tasks]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [collaboration, setCollaboration] = useState<CollaborationStatus | null>(null);
  const [statusError, setStatusError] = useState(false);
  useEffect(() => {
    let disposed = false;
    async function load() {
      try {
        const response = await authenticatedFetch(`${API_BASE_URL}/collaboration/status`);
        if (!response.ok) throw new Error("status unavailable");
        const data: unknown = await response.json();
        if (!data || typeof data !== "object" ||
            typeof (data as { enabled?: unknown }).enabled !== "boolean") {
          throw new Error("status response was invalid");
        }
        if (!disposed) { setCollaboration(data as CollaborationStatus); setStatusError(false); }
      } catch {
        if (!disposed) { setStatusError(true); setCollaboration(null); }
      }
    }
    void load();
    return () => { disposed = true; };
  }, []);

  const selected = workflows.find(workflow => workflow.id === selectedId) ?? workflows[0] ?? null;
  const manualReviewCount = workflows.filter(item => item.state === "manual_review").length;
  const activeCount = workflows.filter(item => item.state === "in_progress" || item.state === "queued").length;
  const cloudReady = Boolean(collaboration?.enabled && collaboration.privacy_enabled &&
    collaboration.cloud_egress_enabled && collaboration.drafter_configured && collaboration.reviewer_configured);

  return (
    <section className="jace-director-insights" aria-label="Agent Director workflow insights">
      <div className="jdi-head">
        <div><span className="jdi-eyebrow">C4D.1 · WORKFLOW INSIGHTS</span><h3>Agent Director</h3><p>Recent workflows from the existing agent task feed.</p></div>
        <button type="button" className="jdi-refresh" onClick={props.onRefresh}>Refresh</button>
      </div>
      <div className="jdi-stats" aria-label="Recent workflow summary">
        <div><span>Recent workflows</span><strong>{workflows.length}</strong></div>
        <div><span>Active / queued</span><strong>{activeCount}</strong></div>
        <div><span>Manual review</span><strong>{manualReviewCount}</strong></div>
        <div><span>Task feed</span><strong>{props.realtimeConnected ? "LIVE" : "POLLING"}</strong></div>
      </div>
      <div className="jdi-provider-bar" aria-live="polite">
        <div><strong>Cross-provider configuration</strong><span>{statusError ? "Status unavailable" : collaboration ? (cloudReady ? "Configured + cloud egress permitted" : "Not fully enabled") : "Checking settings…"}</span></div>
        {collaboration && <div className="jdi-provider-tags">
          <span>Drafter: {collaboration.drafter_configured ? "configured" : "not configured"}</span>
          <span>Reviewer: {collaboration.reviewer_configured ? "configured" : "not configured"}</span>
          <span>Evidence review: {collaboration.supplied_excerpt_review_enabled ? "enabled" : "disabled"}</span>
        </div>}
      </div>
      <p className="jdi-disclaimer">Configuration is not proof that a model was called. Source reads are not factual verification. Detailed cross-provider assessments remain in the Director's final chat handoff.</p>
      {workflows.length === 0 ? (
        <div className="jdi-empty">No recent Agent Director tasks are present in this feed. Start a background Director workflow to see it here.</div>
      ) : (
        <div className="jdi-layout">
          <div className="jdi-list" role="group" aria-label="Recent Agent Director workflows">
            {workflows.map(workflow => (
              <button key={workflow.id} type="button" className={`jdi-workflow ${selected?.id === workflow.id ? "selected" : ""}`}
                aria-pressed={selected?.id === workflow.id} onClick={() => setSelectedId(workflow.id)}>
                <span className="jdi-workflow-title"><strong>Workflow {workflow.id.slice(0, 8)}</strong><small>{displayTime(workflow.updatedAt)}</small></span>
                <span className={`jdi-state ${workflow.state}`}>{labels[workflow.state]}</span>
                <small>{workflow.completedCount}/{workflow.taskCount} specialist tasks completed{workflow.recovered ? " · restarted" : ""}</small>
              </button>
            ))}
          </div>
          {selected && <div className="jdi-details" aria-label="Selected workflow details">
            <div className="jdi-details-head"><strong>Workflow {selected.id.slice(0, 8)}</strong><span className={`jdi-state ${selected.state}`}>{labels[selected.state]}</span></div>
            <p>{selected.finalized ? "Director finalisation recorded in task metadata." : "No completed Director handoff marker is present in the loaded task feed."}</p>
            {selected.state === "manual_review" && <p className="jdi-warning">An interrupted task was quarantined. Inspect its history before deciding whether to start fresh work; automatic Retry is blocked for safety.</p>}
            {selected.recovered && <p className="jdi-info">At least one specialist was resumed after a restart.</p>}
            <div className="jdi-keyfacts"><span>{selected.sourceReaderTasks} specialist task(s) recorded source-reader tools</span><span>Actual recorded task models: {selected.recordedModels.length ? selected.recordedModels.map(m => safeLabel(m, 32)).join(", ") : "not reported"}</span></div>
            <div className="jdi-step-list">
              {selected.tasks.map(task => <div key={task.id} className="jdi-step">
                <span><strong>{safeLabel(task.title)}</strong><small>{task.agent_name} · {task.progress_message ? safeLabel(task.progress_message, 65) : task.status.replace(/_/g, " ")}</small></span>
                <span className={`jdi-state ${task.metadata?.recovery_quarantined === true ? "manual_review" : task.status === "completed" ? "completed" : task.status === "failed" ? "failed" : "queued"}`}>
                  {task.metadata?.recovery_quarantined === true ? "REVIEW" : task.status.toUpperCase().replace(/_/g, " ")}
                </span>
              </div>)}
            </div>
          </div>}
        </div>
      )}
      <footer className="jdi-footnote">Read-only · Recent task feed (maximum 100 fetched by the existing Agent Office) · No additional agent executions or provider requests</footer>
    </section>
  );
}
