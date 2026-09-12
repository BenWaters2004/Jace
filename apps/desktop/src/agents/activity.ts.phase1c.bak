import type { AgentTask, AgentTaskEvent, AgentTaskStatus } from "./types";

export const ACTIVE_AGENT_TASK_STATUSES: ReadonlySet<AgentTaskStatus> =
  new Set<AgentTaskStatus>([
    "queued",
    "running",
    "thinking",
    "using_tool",
    "waiting_permission",
  ]);

export const TERMINAL_AGENT_TASK_STATUSES: ReadonlySet<AgentTaskStatus> =
  new Set<AgentTaskStatus>(["completed", "failed"]);

export function isAgentTaskActive(
  taskOrStatus: AgentTask | AgentTaskStatus,
): boolean {
  const status =
    typeof taskOrStatus === "string" ? taskOrStatus : taskOrStatus.status;

  return ACTIVE_AGENT_TASK_STATUSES.has(status);
}

export function taskTimestamp(task: AgentTask): number {
  const value =
    task.completed_at ??
    task.updated_at ??
    task.started_at ??
    task.created_at;

  const timestamp = Date.parse(value);
  return Number.isFinite(timestamp) ? timestamp : 0;
}

export interface AgentBubbleDescriptor {
  text: string;
  tone: "working" | "thinking" | "permission" | "success" | "error";
}

function shorten(value: string, maxLength = 36): string {
  const trimmed = value.trim().replace(/\s+/g, " ");
  if (trimmed.length <= maxLength) return trimmed;
  return `${trimmed.slice(0, Math.max(1, maxLength - 1)).trimEnd()}…`;
}

function basename(value: string): string {
  const normalized = value.replace(/\\/g, "/").replace(/\/$/, "");
  const pieces = normalized.split("/");
  return pieces[pieces.length - 1] || value;
}

function findMetadataPath(value: unknown, depth = 0): string | null {
  if (depth > 2 || !value || typeof value !== "object") return null;

  const record = value as Record<string, unknown>;
  const directKeys = [
    "path",
    "file",
    "file_path",
    "filepath",
    "target_path",
    "target",
  ];

  for (const key of directKeys) {
    const candidate = record[key];
    if (typeof candidate === "string" && candidate.trim()) {
      return basename(candidate.trim());
    }
  }

  const nestedKeys = ["args", "arguments", "input", "tool_args", "tool_input"];
  for (const key of nestedKeys) {
    const candidate = findMetadataPath(record[key], depth + 1);
    if (candidate) return candidate;
  }

  return null;
}

function currentTool(
  task: AgentTask,
  latestEvent?: AgentTaskEvent | null,
): string {
  const eventTool = latestEvent?.data?.tool_name;
  if (typeof eventTool === "string" && eventTool.trim()) {
    return eventTool.trim().toLowerCase();
  }

  const progressMatch = task.progress_message?.match(/^Using\s+([^\s:]+)(?::|$)/i);
  if (progressMatch?.[1]) return progressMatch[1].toLowerCase();

  return (task.used_tools[task.used_tools.length - 1] ?? "").toLowerCase();
}

function meaningfulProgressMessage(task: AgentTask): string | null {
  const message = task.progress_message?.trim();
  if (!message) return null;
  if (/^using\s+[^\s:]+$/i.test(message)) return null;

  const cleaned = message.replace(/[.…]+$/, "");
  if (!cleaned) return null;
  return `${shorten(cleaned, 34)}…`;
}

export function getAgentBubbleDescriptor(
  task: AgentTask | null,
  now = Date.now(),
  latestEvent?: AgentTaskEvent | null,
): AgentBubbleDescriptor | null {
  if (!task) return null;

  if (task.status === "waiting_permission") {
    return { text: "Waiting for permission", tone: "permission" };
  }

  if (task.status === "completed") {
    const finishedAt = taskTimestamp(task);
    if (finishedAt > 0 && now - finishedAt <= 6500) {
      return { text: "Task complete", tone: "success" };
    }
    return null;
  }

  if (task.status === "failed") {
    const finishedAt = taskTimestamp(task);
    if (finishedAt > 0 && now - finishedAt <= 6500) {
      return { text: "Task failed", tone: "error" };
    }
    return null;
  }

  if (task.status === "cancelled") return null;
  if (task.status === "queued") {
    return { text: "Queued…", tone: "working" };
  }

  if (task.status === "thinking") {
    const progress = meaningfulProgressMessage(task);
    return {
      text: progress ?? "Thinking…",
      tone: "thinking",
    };
  }

  const progress = meaningfulProgressMessage(task);
  if (progress) {
    return {
      text: progress,
      tone: task.status === "using_tool" ? "working" : "thinking",
    };
  }

  const tool = currentTool(task, latestEvent);
  const file =
    findMetadataPath(latestEvent?.data) ??
    findMetadataPath(task.metadata);

  if (tool.includes("web") || tool.includes("search")) {
    return { text: "Searching web…", tone: "working" };
  }

  if (
    tool.includes("read") ||
    tool.includes("workspace") ||
    tool.includes("file") ||
    tool.includes("list")
  ) {
    return {
      text: file ? `Reading ${shorten(file, 23)}…` : "Reading project files…",
      tone: "working",
    };
  }

  if (tool.includes("memory")) {
    return { text: "Checking memory…", tone: "thinking" };
  }

  if (tool.includes("command") || tool.includes("terminal") || tool.includes("shell")) {
    return { text: "Running command…", tone: "working" };
  }

  if (
    tool.includes("write") ||
    tool.includes("replace") ||
    tool.includes("edit") ||
    tool.includes("move") ||
    tool.includes("delete")
  ) {
    return {
      text: file ? `Editing ${shorten(file, 23)}…` : "Editing files…",
      tone: "working",
    };
  }

  if (task.status === "using_tool") {
    return { text: "Using tools…", tone: "working" };
  }

  return { text: "Working…", tone: "working" };
}
