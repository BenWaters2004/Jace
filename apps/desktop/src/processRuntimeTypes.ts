export type ProcessRuntimeStatus =
  | "starting"
  | "running"
  | "cancel_requested"
  | "completed"
  | "failed"
  | "cancelled"
  | "timed_out"
  | "lost";

export type ProcessRuntimeShell =
  | "powershell"
  | "cmd"
  | "wsl"
  | "bash";

export type ProcessRuntimeMode =
  | "foreground"
  | "background";

export interface ProcessStartRequest {
  device_id: string;
  shell: ProcessRuntimeShell;
  command: string;
  cwd?: string | null;
  mode?: ProcessRuntimeMode;
  timeout_seconds?: number | null;
  wait_for_exit?: boolean;
  wait_timeout_seconds?: number;
  project_id?: string | null;
  task_id?: string | null;
  agent_id?: string | null;
  conversation_id?: string | null;
}

export interface ProcessRuntimeRecord {
  id: string;
  device_id: string;
  mode: ProcessRuntimeMode;
  shell: ProcessRuntimeShell;
  command_preview: string;
  command_sha256: string;
  cwd: string | null;
  status: ProcessRuntimeStatus;
  pid: number | null;
  exit_code: number | null;
  timeout_seconds: number | null;
  output_bytes: number;
  output_truncated: boolean;
  last_agent_sequence: number;
  error: string | null;
  project_id: string | null;
  task_id: string | null;
  agent_id: string | null;
  conversation_id: string | null;
  created_at: string;
  started_at: string | null;
  completed_at: string | null;
  cancel_requested_at: string | null;
  lost_at: string | null;
}

export interface ProcessListResponse {
  processes: ProcessRuntimeRecord[];
}

export interface ProcessOutputItem {
  sequence: number;
  agent_sequence: number;
  stream: "stdout" | "stderr" | "system";
  text: string;
  byte_count: number;
  created_at: string;
}

export interface ProcessOutputResponse {
  process_id: string;
  output: ProcessOutputItem[];
  count: number;
  next_sequence: number;
}
