export type AgentTaskStatus =
  | "queued"
  | "running"
  | "thinking"
  | "using_tool"
  | "waiting_permission"
  | "completed"
  | "failed"
  | "cancelled";

export type AgentReasoningMode = "fast" | "balanced" | "deep";
export type AgentWorkerExecutionState = "idle" | "running";

export interface AgentDefinition {
  id: string;
  name: string;
  role: string;
  description: string;
  default_tools: string[];
  optional_tools: string[];
  accent: string;
  glyph: string;
}

export interface AgentDefinitionListResponse {
  agents: AgentDefinition[];
}

export interface AgentWorkerRuntime {
  id: string;
  index: number;
  state: AgentWorkerExecutionState;
  task_id: string | null;
  agent_id: string | null;
  task_title: string | null;
  assigned_at: string | null;
  updated_at: string;
}

export interface AgentWorkerListResponse {
  workers: AgentWorkerRuntime[];
}

export interface AgentTaskCreateRequest {
  agent_id: string;
  title: string;
  instruction: string;
  conversation_id?: string | null;
  parent_task_id?: string | null;
  priority?: number;
  model?: string | null;
  reasoning_mode?: AgentReasoningMode;
  allowed_tools?: string[] | null;
  metadata?: Record<string, unknown>;
}

export interface AgentTask {
  id: string;
  conversation_id: string | null;
  parent_task_id: string | null;
  agent_id: string;
  agent_name: string;
  agent_role: string;
  accent: string;
  glyph: string;

  title: string;
  instruction: string;
  status: AgentTaskStatus;
  priority: number;
  progress: number;
  progress_message: string | null;
  model: string | null;
  reasoning_mode: string;
  allowed_tools: string[];
  used_tools: string[];
  metadata: Record<string, unknown>;
  result: string | null;
  error: string | null;
  cancel_requested: boolean;

  created_at: string;
  updated_at: string;
  started_at: string | null;
  completed_at: string | null;
}

export interface AgentTaskListResponse {
  tasks: AgentTask[];
}

export interface AgentStatus {
  enabled: boolean;
  manager_running: boolean;
  workers: number;
  active_tasks: number;
  queued_tasks: number;
  counts: Record<string, number>;
}

export interface AgentTaskEvent {
  id: string;
  task_id: string;
  event_type: string;
  message: string;
  data: Record<string, unknown>;
  created_at: string;
}

export interface AgentTaskEventsResponse {
  events: AgentTaskEvent[];
}
