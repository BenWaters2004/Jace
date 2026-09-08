export type ChatRole = "user" | "assistant";
export type Screen = "chat" | "memory" | "tools" | "computer" | "control" | "automations" | "settings";
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

export interface AttachmentRecord {
  id: string;
  conversation_id: string;
  message_id: string | null;
  original_name: string;
  mime_type: string;
  media_kind: "image" | "pdf" | "document" | "audio" | string;
  size_bytes: number;
  sha256: string;
  source_type: string;
  source_path: string | null;
  created_at: string;
}

export interface AttachmentStatus {
  enabled: boolean;
  image_max_bytes: number;
  document_max_bytes: number;
  audio_max_bytes: number;
  max_count: number;
  audio_enabled: boolean;
  audio_model: string;
  screen_capture_enabled: boolean;
}

export interface PendingAttachment {
  id: string;
  file: File;
  previewUrl: string | null;
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
  attachments?: AttachmentRecord[];
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
  attachments: AttachmentRecord[];
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
  attachment_ids?: string[];
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
  attachment_count: number;
  attachment_image_count: number;
  attachment_processing_ms: number;
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
  attachment_count: number;
  attachment_image_count: number;
  attachment_processing_ms: number;
  attachments?: Array<{ id: string; name: string; kind: string; metadata?: Record<string, unknown>; error?: string }>;
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


// Phase 8 automation
export type AutomationType = "task" | "watcher";
export type AutomationScheduleType = "once" | "interval" | "daily" | "weekly" | "cron";

export interface AutomationSchedule {
  schedule_type: AutomationScheduleType;
  timezone: string;
  run_at: string | null;
  interval_minutes: number | null;
  time_of_day: string | null;
  days_of_week: number[];
  cron_expression: string | null;
}

export interface AutomationRecord {
  id: string;
  name: string;
  instruction: string;
  automation_type: AutomationType;
  schedule: AutomationSchedule;
  watcher_condition: string | null;
  allowed_tools: string[];
  enabled: boolean;
  notify_on_success: boolean;
  notify_on_failure: boolean;
  notify_on_condition: boolean;
  timeout_seconds: number;
  model: string | null;
  reasoning_mode: ReasoningMode;
  created_at: string;
  updated_at: string;
  next_run_at: string | null;
  last_run_at: string | null;
  last_status: string | null;
  last_result: string | null;
}

export interface AutomationListResponse {
  enabled: boolean;
  automations: AutomationRecord[];
}

export interface AutomationCreateRequest {
  name: string;
  instruction: string;
  automation_type: AutomationType;
  schedule: AutomationSchedule;
  watcher_condition?: string | null;
  allowed_tools: string[];
  enabled: boolean;
  notify_on_success: boolean;
  notify_on_failure: boolean;
  notify_on_condition: boolean;
  timeout_seconds: number;
  model?: string | null;
  reasoning_mode: ReasoningMode;
}

export type AutomationUpdateRequest = Partial<AutomationCreateRequest>;

export interface AutomationRunRecord {
  id: string;
  automation_id: string;
  trigger_type: string;
  status: string;
  started_at: string;
  completed_at: string | null;
  result: string | null;
  error: string | null;
  condition_met: boolean | null;
  tool_names: string[];
  model: string | null;
}

export interface AutomationRunListResponse {
  runs: AutomationRunRecord[];
}

export interface AutomationNotificationRecord {
  id: string;
  automation_id: string;
  run_id: string | null;
  title: string;
  body: string;
  level: string;
  created_at: string;
  read_at: string | null;
}

export interface AutomationNotificationListResponse {
  notifications: AutomationNotificationRecord[];
}

export interface AutomationStatus {
  enabled: boolean;
  scheduler_running: boolean;
  automation_count: number;
  enabled_count: number;
  watcher_count: number;
  unread_notifications: number;
  timezone: string;
}

export interface AutomationDraftRequest {
  instruction: string;
  timezone: string;
}

export interface AutomationDraftResponse {
  name: string;
  instruction: string;
  automation_type: AutomationType;
  schedule: AutomationSchedule;
  watcher_condition: string | null;
  suggested_tools: string[];
  notify_on_success: boolean;
  notify_on_failure: boolean;
  notify_on_condition: boolean;
  reasoning: string;
}

// Phase 9 interactive desktop control
export interface ControlWindowRecord {
  handle: number;
  title: string;
  process_name: string;
  process_id: number;
  left: number;
  top: number;
  right: number;
  bottom: number;
  width: number;
  height: number;
  is_active: boolean;
  blocked: boolean;
  sensitive: boolean;
  policy_id: string | null;
  policy_label: string | null;
  observe_allowed: boolean;
  interact_allowed: boolean;
  sensitive_allowed: boolean;
}

export interface ControlWindowListResponse {
  windows: ControlWindowRecord[];
}

export interface ControlAppPolicy {
  id: string;
  label: string;
  process_pattern: string;
  title_pattern: string;
  observe_enabled: boolean;
  interact_enabled: boolean;
  sensitive_enabled: boolean;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

export interface ControlAppPolicyListResponse {
  policies: ControlAppPolicy[];
}

export interface ControlAppPolicyCreateRequest {
  label: string;
  process_pattern: string;
  title_pattern: string;
  observe_enabled: boolean;
  interact_enabled: boolean;
  sensitive_enabled: boolean;
}

export interface ControlAppPolicyUpdateRequest extends Partial<ControlAppPolicyCreateRequest> {
  is_active?: boolean;
}

export interface ControlSessionRecord {
  id: string;
  conversation_id: string | null;
  status: string;
  step_count: number;
  max_steps: number;
  remaining_steps: number;
  store_screenshots: boolean;
  sensitive_authorized_once: boolean;
  started_at: string;
  updated_at: string;
  ended_at: string | null;
  stop_reason: string | null;
}

export interface ControlSessionListResponse {
  sessions: ControlSessionRecord[];
}

export interface ControlSessionCreateRequest {
  conversation_id?: string | null;
  max_steps: number;
  store_screenshots: boolean;
}

export interface ControlActionRecord {
  id: string;
  session_id: string;
  conversation_id: string | null;
  action_type: string;
  window_handle: string | null;
  process_name: string | null;
  window_title: string | null;
  arguments: Record<string, unknown>;
  status: string;
  result_preview: string | null;
  screenshot_attachment_id: string | null;
  created_at: string;
  completed_at: string | null;
}

export interface ControlActionListResponse {
  actions: ControlActionRecord[];
}

export interface ControlStatus {
  enabled: boolean;
  platform_supported: boolean;
  active_session: ControlSessionRecord | null;
  policy_count: number;
  active_policy_count: number;
  visible_window_count: number;
  physical_failsafe: string;
}
