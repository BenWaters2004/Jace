export type TerminalRuntimeStatus =
  | "starting"
  | "running"
  | "close_requested"
  | "closed"
  | "failed"
  | "lost";

export type TerminalRuntimeShell =
  | "powershell"
  | "cmd"
  | "wsl"
  | "bash";

export interface TerminalOpenRequest {
  device_id: string;
  shell: TerminalRuntimeShell;
  cwd?: string | null;
  cols?: number;
  rows?: number;
  project_id?: string | null;
  task_id?: string | null;
  agent_id?: string | null;
  conversation_id?: string | null;
}

export interface TerminalRuntimeRecord {
  id: string;
  device_id: string;
  shell: TerminalRuntimeShell;
  cwd: string | null;
  cols: number;
  rows: number;
  status: TerminalRuntimeStatus;
  pid: number | null;
  backend: string | null;
  exit_code: number | null;
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
  close_requested_at: string | null;
  lost_at: string | null;
}

export interface TerminalListResponse {
  terminals: TerminalRuntimeRecord[];
}

export interface TerminalOutputItem {
  sequence: number;
  agent_sequence: number;
  text: string;
  byte_count: number;
  created_at: string;
}

export interface TerminalOutputResponse {
  terminal_id: string;
  output: TerminalOutputItem[];
  count: number;
  next_sequence: number;
}
