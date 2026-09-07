export type ChatRole = "user" | "assistant";
export type Screen = "chat" | "memory" | "settings";
export type MemoryType = "fact" | "preference" | "project" | "decision" | "goal" | "temporary" | "other";
export type ReasoningMode = "fast" | "balanced" | "deep";
export type ResponseStyle = "concise" | "balanced" | "detailed";

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

export interface StreamContextEvent {
  type: "context";
  memory_count: number;
  reasoning_mode: ReasoningMode;
}

export interface StreamTokenEvent {
  type: "token";
  content: string;
}

export interface StreamDoneEvent {
  type: "done";
  model: string;
  done_reason: string | null;
  metrics: StreamMetrics;
}

export interface StreamErrorEvent {
  type: "error";
  message: string;
}

export type ChatStreamEvent = StreamContextEvent | StreamTokenEvent | StreamDoneEvent | StreamErrorEvent;
