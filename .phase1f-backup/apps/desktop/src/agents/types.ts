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
export type AgentWorkerExecutionState = "idle" | "running" | "recovering" | "offline";

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
  dispatch_generation: number | null;
  assigned_at: string | null;
  updated_at: string;
  restart_count: number;
  last_error: string | null;
  last_exit_at: string | null;
}

export interface AgentWorkerListResponse {
  workers: AgentWorkerRuntime[];
}

export type AgentReadinessStatus = "ready" | "degraded" | "unavailable";
export type AgentReadinessIssueSeverity = "info" | "warning" | "error";

export interface AgentReadinessIssue {
  code: string;
  severity: AgentReadinessIssueSeverity;
  message: string;
}

export interface AgentToolReadiness {
  name: string;
  label: string;
  category: string;
  risk: string;
  kind: "default" | "optional";
  registered: boolean;
  permission: "allow" | "ask" | "deny" | "missing";
  available: boolean;
  requires_approval: boolean;
}

export interface AgentReadiness {
  agent_id: string;
  agent_name: string;
  status: AgentReadinessStatus;
  summary: string;
  model: string;
  model_available: boolean;
  readable_workspace_count: number;
  writable_workspace_count: number;
  issues: AgentReadinessIssue[];
  tools: AgentToolReadiness[];
}

export interface AgentReadinessWorkspace {
  id: string;
  label: string;
  root_path: string;
}

export interface AgentReadinessSnapshot {
  generated_at: string;
  manager_running: boolean;
  agent_system_enabled: boolean;
  ollama_connected: boolean;
  ollama_error: string | null;
  default_model: string;
  installed_models: string[];
  readable_workspaces: AgentReadinessWorkspace[];
  writable_workspaces: AgentReadinessWorkspace[];
  agents: AgentReadiness[];
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
  executor_id: string | null;
  queue_position: number | null;
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
