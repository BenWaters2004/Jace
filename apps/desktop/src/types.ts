export type ChatRole = "user" | "assistant";
export type Screen = "chat" | "memory" | "tools" | "computer" | "settings";
export type MemoryType = "fact" | "preference" | "project" | "decision" | "goal" | "temporary" | "other";
export type ReasoningMode = "fast" | "balanced" | "deep";
export type ResponseStyle = "concise" | "balanced" | "detailed";
export type ToolPermissionMode = "allow" | "ask" | "deny";
export type ToolRisk = "read" | "write" | "execute";
export type ToolActivityStatus = "requested" | "awaiting_approval" | "completed" | "denied" | "failed";
export type ToolApprovalDecision = "allow_once" | "allow_always" | "deny_once" | "deny_always";

export interface GenerationStats {
  timeToFirstTokenMs: number | null;
  totalDurationMs: number | null;
  loadDurationMs: number | null;
  promptEvalCount: number | null;
  promptEvalCachedCount: number | null;
  promptEvalDurationMs: number | null;
  evalCount: number | null;
  evalDurationMs: number | null;
  tokensPerSecond: number | null;
}

export interface ApiGenerationStats {
  time_to_first_token_ms: number | null;
  total_duration_ms: number | null;
  load_duration_ms: number | null;
  prompt_eval_count: number | null;
  prompt_eval_cached_count: number | null;
  prompt_eval_duration_ms: number | null;
  eval_count: number | null;
  eval_duration_ms: number | null;
  tokens_per_second: number | null;
}

export interface ChatMessage {
  id: string;
  conversation_id?: string;
  role: ChatRole;
  content: string;
  status?: string;
  model?: string | null;
  created_at?: string;
  isStreaming?: boolean;
  stopped?: boolean;
  stats?: GenerationStats;
}

export interface ApiMessage {
  id: string;
  conversation_id: string;
  role: ChatRole;
  content: string;
  status: string;
  model: string | null;
  created_at: string;
  stats: ApiGenerationStats | null;
}

export interface HealthResponse {
  status: string;
  ollama_connected: boolean;
  app_version: string;
  default_model: string;
  embedding_model: string;
  installed_models: number;
  database_path: string;
}

export interface ModelInfo {
  name: string;
  size: number | null;
  parameter_size: string | null;
  quantization_level: string | null;
}

export interface ModelsResponse {
  models: ModelInfo[];
}

export interface ConversationSummary {
  id: string;
  title: string;
  model: string;
  created_at: string;
  updated_at: string;
  message_count: number;
}

export interface ConversationDetail {
  id: string;
  title: string;
  model: string;
  system_prompt: string;
  created_at: string;
  updated_at: string;
  messages: ApiMessage[];
}

export interface ConversationListResponse {
  conversations: ConversationSummary[];
}

export interface AssistantSettings {
  assistant_name: string;
  user_name: string;
  system_prompt: string;
  default_model: string;
  reasoning_mode: ReasoningMode;
  response_style: ResponseStyle;
  temperature: number;
  memory_enabled: boolean;
  memory_auto_extract: boolean;
  memory_top_k: number;
  memory_min_similarity: number;
  created_at: string;
  updated_at: string;
}

export interface AssistantSettingsUpdate {
  assistant_name?: string;
  user_name?: string;
  system_prompt?: string;
  default_model?: string;
  reasoning_mode?: ReasoningMode;
  response_style?: ResponseStyle;
  temperature?: number;
  memory_enabled?: boolean;
  memory_auto_extract?: boolean;
  memory_top_k?: number;
  memory_min_similarity?: number;
}

export interface MemoryRecord {
  id: string;
  memory_type: MemoryType;
  subject: string;
  content: string;
  importance: number;
  confidence: number;
  source_type: string;
  source_conversation_id: string | null;
  source_message_id: string | null;
  embedding_model: string;
  is_pinned: boolean;
  is_active: boolean;
  created_at: string;
  updated_at: string;
  last_accessed_at: string | null;
  access_count: number;
}

export interface MemoryListResponse {
  memories: MemoryRecord[];
}

export interface MemoryCreateRequest {
  memory_type: MemoryType;
  subject: string;
  content: string;
  importance: number;
  confidence: number;
  is_pinned: boolean;
}

export interface MemoryUpdateRequest extends Partial<MemoryCreateRequest> {
  is_active?: boolean;
}

export interface ChatRequest {
  conversation_id: string;
  message: string;
  model?: string;
  system_prompt?: string;
  reasoning_mode?: ReasoningMode;
  temperature?: number;
}

export interface StreamMetrics {
  time_to_first_token_ms: number | null;
  total_duration_ms: number | null;
  load_duration_ms: number | null;
  prompt_eval_count: number | null;
  prompt_eval_cached_count: number | null;
  prompt_eval_duration_ms: number | null;
  eval_count: number | null;
  eval_duration_ms: number | null;
  tokens_per_second: number | null;
}


export interface PerformanceDiagnostics {
  preprocess_ms: number;
  memory_retrieval_used: boolean;
  memory_retrieval_ms: number;
  memory_count: number;
  tool_routing_ms: number;
  tool_names: string[];
  history_messages: number;
  history_chars: number;
}

export interface StreamContextEvent {
  type: "context";
  memory_count: number;
  memory_retrieval_used: boolean;
  memory_retrieval_ms: number;
  tool_count: number;
  tool_names: string[];
  tool_routing_ms: number;
  history_messages: number;
  history_chars: number;
  preprocess_ms: number;
  reasoning_mode: ReasoningMode;
}

export interface StreamTokenEvent {
  type: "token";
  content: string;
}

export interface StreamToolCallEvent {
  type: "tool_call";
  call_id: string;
  tool_name: string;
  label: string;
  description: string;
  risk: ToolRisk;
  permission: ToolPermissionMode;
  arguments: Record<string, unknown>;
}

export interface StreamApprovalRequiredEvent {
  type: "approval_required";
  approval_id: string;
  call_id: string;
  tool_name: string;
  label: string;
  description: string;
  risk: ToolRisk;
  arguments: Record<string, unknown>;
}

export interface StreamToolResultEvent {
  type: "tool_result";
  call_id: string;
  tool_name: string;
  label: string;
  status: "completed" | "denied" | "failed";
  summary: string;
}

export interface StreamDoneEvent {
  type: "done";
  model: string;
  done_reason: string | null;
  metrics: StreamMetrics;
  model_turns?: number;
  tool_calls?: number;
  diagnostics?: PerformanceDiagnostics;
}

export interface StreamErrorEvent {
  type: "error";
  message: string;
}

export type ChatStreamEvent =
  | StreamContextEvent
  | StreamTokenEvent
  | StreamToolCallEvent
  | StreamApprovalRequiredEvent
  | StreamToolResultEvent
  | StreamDoneEvent
  | StreamErrorEvent;

export interface ToolRecord {
  name: string;
  label: string;
  description: string;
  category: string;
  risk: ToolRisk;
  permission: ToolPermissionMode;
  default_permission: ToolPermissionMode;
  parameters: Record<string, unknown>;
}

export interface ToolListResponse {
  enabled: boolean;
  tools: ToolRecord[];
}

export interface ToolAuditRecord {
  id: string;
  conversation_id: string | null;
  tool_name: string;
  permission_mode: string;
  status: string;
  arguments: Record<string, unknown>;
  result_preview: string | null;
  error: string | null;
  approval_id: string | null;
  created_at: string;
  completed_at: string | null;
}

export interface ToolAuditListResponse {
  entries: ToolAuditRecord[];
}

export interface PendingToolApproval {
  approval_id: string;
  conversation_id: string | null;
  tool_name: string;
  label: string;
  description: string;
  risk: ToolRisk;
  arguments: Record<string, unknown>;
  created_at?: string;
  call_id?: string;
}

export interface PendingToolApprovalsResponse {
  approvals: PendingToolApproval[];
}

export interface ToolApprovalDecisionResponse {
  approval_id: string;
  resolved: boolean;
  decision: ToolApprovalDecision;
  tool_name: string;
}

export interface ToolActivity {
  callId: string;
  toolName: string;
  label: string;
  status: ToolActivityStatus;
  arguments: Record<string, unknown>;
  summary?: string;
}


export interface ComputerCommandPreset {
  id: string;
  workspace_id: string;
  label: string;
  executable: string;
  arguments: string[];
  relative_cwd: string;
  timeout_seconds: number;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

export interface ComputerWorkspace {
  id: string;
  label: string;
  root_path: string;
  read_enabled: boolean;
  write_enabled: boolean;
  is_active: boolean;
  created_at: string;
  updated_at: string;
  commands: ComputerCommandPreset[];
}

export interface ComputerWorkspaceListResponse {
  enabled: boolean;
  workspaces: ComputerWorkspace[];
}

export interface ComputerStatus {
  enabled: boolean;
  workspace_count: number;
  active_workspace_count: number;
  command_preset_count: number;
  sensitive_files_allowed: boolean;
}

export interface ComputerWorkspaceCreateRequest {
  label: string;
  root_path: string;
  read_enabled: boolean;
  write_enabled: boolean;
}

export interface ComputerWorkspaceUpdateRequest {
  label?: string;
  root_path?: string;
  read_enabled?: boolean;
  write_enabled?: boolean;
  is_active?: boolean;
}

export interface ComputerCommandCreateRequest {
  label: string;
  executable: string;
  arguments: string[];
  relative_cwd: string;
  timeout_seconds: number;
}

export interface ComputerCommandUpdateRequest extends Partial<ComputerCommandCreateRequest> {
  is_active?: boolean;
}
