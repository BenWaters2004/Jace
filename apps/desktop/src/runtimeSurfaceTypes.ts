import type {
  ProcessRuntimeMode,
  ProcessRuntimeRecord,
  ProcessRuntimeShell,
} from "./processRuntimeTypes";
import type {
  TerminalRuntimeRecord,
  TerminalRuntimeShell,
} from "./terminalRuntimeTypes";

export interface ScopedProcessStartRequest {
  scope_id: string;
  shell: ProcessRuntimeShell;
  command: string;
  relative_cwd?: string;
  mode?: ProcessRuntimeMode;
  timeout_seconds?: number | null;
}

export interface ScopedProcessResult {
  scope_id: string;
  process: ProcessRuntimeRecord;
}

export interface ScopedTerminalOpenRequest {
  scope_id: string;
  shell: TerminalRuntimeShell;
  relative_cwd?: string;
  cols?: number;
  rows?: number;
}

export interface ScopedTerminalResult {
  scope_id: string;
  terminal: TerminalRuntimeRecord;
}
