/** C4D.1 — read-only workflow summaries from Agent Office's existing task snapshot. */
import type { AgentTask } from "./types";

export type WorkflowVisibilityState =
  | "manual_review"
  | "in_progress"
  | "queued"
  | "failed"
  | "finalizing"
  | "completed";

export interface DirectorWorkflowSummary {
  id: string;
  state: WorkflowVisibilityState;
  recovered: boolean;
  taskCount: number;
  completedCount: number;
  sourceReaderTasks: number;
  updatedAt: string;
  finalized: boolean;
  tasks: AgentTask[];
  recordedModels: string[];
}

const ACTIVE = new Set(["running", "thinking", "using_tool", "waiting_permission"]);
const SOURCE_READERS = new Set(["read_workspace_file", "read_web_page"]);
const VALID_WORKFLOW_ID = /^[a-zA-Z0-9_-]{8,90}$/;

export function collectDirectorWorkflows(tasks: AgentTask[], maxWorkflows = 8): DirectorWorkflowSummary[] {
  const groups = new Map<string, AgentTask[]>();
  for (const task of tasks) {
    const metadata = task.metadata;
    if (!metadata || typeof metadata !== "object") continue;
    const value = metadata.director_workflow_id;
    if (typeof value !== "string" || !VALID_WORKFLOW_ID.test(value)) continue;
    const list = groups.get(value) ?? [];
    list.push(task);
    groups.set(value, list);
  }
  const output: DirectorWorkflowSummary[] = [];
  for (const [id, records] of groups) {
    const ordered = [...records].sort((a, b) =>
      Date.parse(b.updated_at || b.created_at) - Date.parse(a.updated_at || a.created_at),
    );
    const quarantined = records.some(task => task.metadata?.recovery_quarantined === true);
    const active = records.some(task => ACTIVE.has(task.status));
    const queued = records.some(task => task.status === "queued");
    const failed = records.some(task => task.status === "failed" || task.status === "cancelled");
    const allComplete = records.every(task => task.status === "completed");
    const finalized = records.some(task => task.metadata?.director_workflow_finalized === true);
    const state: WorkflowVisibilityState = quarantined ? "manual_review" :
      active ? "in_progress" : queued ? "queued" : failed ? "failed" :
      allComplete && finalized ? "completed" : "finalizing";
    const readTasks = records.filter(task => Array.isArray(task.used_tools) &&
      task.used_tools.some(name => SOURCE_READERS.has(name))).length;
    const recordedModels = [...new Set(records.map(task => task.model).filter(
      (value): value is string => typeof value === "string" && value.trim().length > 0,
    ))].slice(0, 5);
    output.push({
      id, state, finalized,
      recovered: records.some(task => task.metadata?.director_recovered === true),
      taskCount: records.length,
      completedCount: records.filter(task => task.status === "completed").length,
      sourceReaderTasks: readTasks,
      updatedAt: ordered[0]?.updated_at ?? ordered[0]?.created_at ?? "",
      tasks: ordered,
      recordedModels,
    });
  }
  return output.sort((a, b) => (Date.parse(b.updatedAt) || 0) - (Date.parse(a.updatedAt) || 0))
    .slice(0, Math.max(0, Math.min(30, maxWorkflows)));
}
