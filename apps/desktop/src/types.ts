export type ChatRole =
  | "user"
  | "assistant";


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


export interface ChatMessage {
  id: string;

  role: ChatRole;

  content: string;

  isStreaming?: boolean;
  stopped?: boolean;

  stats?: GenerationStats;
}


export interface ApiChatMessage {
  role: ChatRole;
  content: string;
}


export interface HealthResponse {
  status: string;

  ollama_connected: boolean;

  app_version: string;

  default_model: string;

  installed_models: number;
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


export interface ChatRequest {
  model: string;

  messages: ApiChatMessage[];

  system_prompt: string;
}


export interface StreamMetrics {
  total_duration_ms: number | null;

  load_duration_ms: number | null;

  prompt_eval_count: number | null;

  prompt_eval_cached_count: number | null;

  prompt_eval_duration_ms: number | null;

  eval_count: number | null;

  eval_duration_ms: number | null;

  tokens_per_second: number | null;
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


export type ChatStreamEvent =
  | StreamTokenEvent
  | StreamDoneEvent
  | StreamErrorEvent;