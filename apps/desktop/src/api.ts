import { API_BASE_URL } from "./constants";
import type {
  AssistantSettings,
  AssistantSettingsUpdate,
  ChatRequest,
  ComputerCommandCreateRequest,
  ComputerCommandPreset,
  ComputerCommandUpdateRequest,
  ComputerStatus,
  ComputerWorkspace,
  ComputerWorkspaceCreateRequest,
  ComputerWorkspaceListResponse,
  ComputerWorkspaceUpdateRequest,
  ChatStreamEvent,
  ConversationDetail,
  ConversationListResponse,
  HealthResponse,
  MemoryCreateRequest,
  MemoryListResponse,
  MemoryRecord,
  MemoryUpdateRequest,
  ModelsResponse,
  PendingToolApprovalsResponse,
  StreamApprovalRequiredEvent,
  StreamContextEvent,
  StreamDoneEvent,
  StreamToolCallEvent,
  StreamToolResultEvent,
  ToolApprovalDecision,
  ToolApprovalDecisionResponse,
  ToolAuditListResponse,
  ToolListResponse,
  ToolPermissionMode,
  ToolRecord,
} from "./types";

async function getErrorMessage(response: Response): Promise<string> {
  try {
    const body = await response.json();
    if (typeof body?.detail === "string") return body.detail;
    if (typeof body?.message === "string") return body.message;
  } catch {
    // Fall back to HTTP status.
  }
  return `${response.status} ${response.statusText}`;
}

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...(options?.headers ?? {}),
    },
  });

  if (!response.ok) throw new Error(await getErrorMessage(response));
  return response.json() as Promise<T>;
}

export const getHealth = () => request<HealthResponse>("/health");
export const getModels = () => request<ModelsResponse>("/models");

export const getSettings = () => request<AssistantSettings>("/settings");
export const resetSettings = () => request<AssistantSettings>("/settings/reset", { method: "POST" });
export const updateSettings = (payload: AssistantSettingsUpdate) =>
  request<AssistantSettings>("/settings", { method: "PATCH", body: JSON.stringify(payload) });

export const getConversations = () => request<ConversationListResponse>("/conversations");
export const getConversation = (id: string) => request<ConversationDetail>(`/conversations/${id}`);
export const createConversation = (payload: { model?: string; system_prompt?: string }) =>
  request<ConversationDetail>("/conversations", { method: "POST", body: JSON.stringify(payload) });
export const updateConversation = (id: string, payload: { title?: string; model?: string; system_prompt?: string }) =>
  request<ConversationDetail>(`/conversations/${id}`, { method: "PATCH", body: JSON.stringify(payload) });
export async function deleteConversation(id: string): Promise<void> {
  await request(`/conversations/${id}`, { method: "DELETE" });
}

export function getMemories(activeOnly = false): Promise<MemoryListResponse> {
  return request<MemoryListResponse>(`/memories?active_only=${activeOnly ? "true" : "false"}`);
}
export const createMemory = (payload: MemoryCreateRequest) =>
  request<MemoryRecord>("/memories", { method: "POST", body: JSON.stringify(payload) });
export const updateMemory = (id: string, payload: MemoryUpdateRequest) =>
  request<MemoryRecord>(`/memories/${id}`, { method: "PATCH", body: JSON.stringify(payload) });
export async function deleteMemory(id: string): Promise<void> {
  await request(`/memories/${id}`, { method: "DELETE" });
}


export const getComputerStatus = () => request<ComputerStatus>("/computer/status");
export const getComputerWorkspaces = () => request<ComputerWorkspaceListResponse>("/computer/workspaces");
export const createComputerWorkspace = (payload: ComputerWorkspaceCreateRequest) =>
  request<ComputerWorkspace>("/computer/workspaces", { method: "POST", body: JSON.stringify(payload) });
export const updateComputerWorkspace = (id: string, payload: ComputerWorkspaceUpdateRequest) =>
  request<ComputerWorkspace>(`/computer/workspaces/${id}`, { method: "PATCH", body: JSON.stringify(payload) });
export async function deleteComputerWorkspace(id: string): Promise<void> {
  await request(`/computer/workspaces/${id}`, { method: "DELETE" });
}
export const createComputerCommand = (workspaceId: string, payload: ComputerCommandCreateRequest) =>
  request<ComputerCommandPreset>(`/computer/workspaces/${workspaceId}/commands`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
export const updateComputerCommand = (id: string, payload: ComputerCommandUpdateRequest) =>
  request<ComputerCommandPreset>(`/computer/commands/${id}`, { method: "PATCH", body: JSON.stringify(payload) });
export async function deleteComputerCommand(id: string): Promise<void> {
  await request(`/computer/commands/${id}`, { method: "DELETE" });
}

export const getTools = () => request<ToolListResponse>("/tools");
export const updateToolPermission = (name: string, permission: ToolPermissionMode) =>
  request<ToolRecord>(`/tools/${encodeURIComponent(name)}/permission`, {
    method: "PATCH",
    body: JSON.stringify({ permission }),
  });
export const getToolAudit = (limit = 100) => request<ToolAuditListResponse>(`/tools/audit?limit=${limit}`);
export async function clearToolAudit(): Promise<void> {
  await request("/tools/audit", { method: "DELETE" });
}
export const getPendingToolApprovals = () => request<PendingToolApprovalsResponse>("/tools/approvals");
export const resolveToolApproval = (approvalId: string, decision: ToolApprovalDecision) =>
  request<ToolApprovalDecisionResponse>(`/tools/approvals/${approvalId}`, {
    method: "POST",
    body: JSON.stringify({ decision }),
  });

interface StreamCallbacks {
  onContext?: (event: StreamContextEvent) => void;
  onToken: (content: string) => void;
  onToolCall?: (event: StreamToolCallEvent) => void;
  onApprovalRequired?: (event: StreamApprovalRequiredEvent) => void;
  onToolResult?: (event: StreamToolResultEvent) => void;
  onDone: (event: StreamDoneEvent) => void;
}

export async function sendChatStream(
  payload: ChatRequest,
  callbacks: StreamCallbacks,
  signal: AbortSignal,
): Promise<void> {
  const response = await fetch(`${API_BASE_URL}/chat/stream`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
    signal,
  });

  if (!response.ok) throw new Error(await getErrorMessage(response));
  if (!response.body) throw new Error("The Jace backend did not provide a response stream.");

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  function processLine(line: string) {
    const trimmed = line.trim();
    if (!trimmed) return;

    let event: ChatStreamEvent;
    try {
      event = JSON.parse(trimmed) as ChatStreamEvent;
    } catch {
      throw new Error("Jace received malformed streaming data.");
    }

    switch (event.type) {
      case "context":
        callbacks.onContext?.(event);
        break;
      case "token":
        callbacks.onToken(event.content);
        break;
      case "tool_call":
        callbacks.onToolCall?.(event);
        break;
      case "approval_required":
        callbacks.onApprovalRequired?.(event);
        break;
      case "tool_result":
        callbacks.onToolResult?.(event);
        break;
      case "done":
        callbacks.onDone(event);
        break;
      case "error":
        throw new Error(event.message);
    }
  }

  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split("\n");
      buffer = lines.pop() ?? "";
      for (const line of lines) processLine(line);
    }

    buffer += decoder.decode();
    if (buffer.trim()) processLine(buffer);
  } finally {
    reader.releaseLock();
  }
}
