import { API_BASE_URL } from "./constants";
import type {
  AutomationCreateRequest,
  AutomationDraftRequest,
  AutomationDraftResponse,
  AutomationListResponse,
  AutomationNotificationListResponse,
  AutomationRecord,
  AutomationRunListResponse,
  AutomationStatus,
  AutomationUpdateRequest,
  AssistantSettings,
  AttachmentRecord,
  AttachmentStatus,
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
  ControlActionListResponse,
  ControlAppPolicy,
  ControlAppPolicyCreateRequest,
  ControlAppPolicyListResponse,
  ControlAppPolicyUpdateRequest,
  ControlSessionCreateRequest,
  ControlSessionListResponse,
  ControlSessionRecord,
  ControlStatus,
  ControlWindowListResponse,
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
  VoiceSettings,
  VoiceSettingsUpdate,
  VoiceStatus,
  VoiceTranscriptionResponse,
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

async function request<T>(
  path: string,
  options?: RequestInit,
): Promise<T> {
  const url = `${API_BASE_URL}${path}`;
  const method = options?.method ?? "GET";

  console.debug("[Jace API]", method, url);

  const response = await fetch(url, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...(options?.headers ?? {}),
    },
  });

  if (!response.ok) {
    const detail = await getErrorMessage(response);

    throw new Error(
      `${method} ${url} returned ${response.status}: ${detail}`,
    );
  }

  return response.json() as Promise<T>;
}

export const getHealth = () => request<HealthResponse>("/health");

export const getAttachmentStatus = () => request<AttachmentStatus>("/attachments/status");
export const getAttachment = (id: string) => request<AttachmentRecord>(`/attachments/${id}`);
export const attachmentContentUrl = (id: string) => `${API_BASE_URL}/attachments/${id}/content`;

export async function uploadAttachment(conversationId: string, file: File): Promise<AttachmentRecord> {
  const form = new FormData();
  form.append("file", file, file.name);
  const response = await fetch(`${API_BASE_URL}/attachments?conversation_id=${encodeURIComponent(conversationId)}`, {
    method: "POST",
    body: form,
  });
  if (!response.ok) throw new Error(await getErrorMessage(response));
  return response.json() as Promise<AttachmentRecord>;
}

export async function deleteAttachment(id: string): Promise<void> {
  await request(`/attachments/${id}`, { method: "DELETE" });
}
export const getModels = () => request<ModelsResponse>("/models");

// Phase 10B local voice / presence
export const getVoiceStatus = () => request<VoiceStatus>("/voice/status");
export const getVoiceSettings = () => request<VoiceSettings>("/voice/settings");
export const resetVoiceSettings = () => request<VoiceSettings>("/voice/settings/reset", { method: "POST" });
export const updateVoiceSettings = (payload: VoiceSettingsUpdate) =>
  request<VoiceSettings>("/voice/settings", { method: "PATCH", body: JSON.stringify(payload) });
export const setVoiceListening = (active: boolean) =>
  request<{ success: boolean }>("/voice/listening", { method: "POST", body: JSON.stringify({ active }) });
export const setVoiceSpeaking = (active: boolean) =>
  request<{ success: boolean }>("/voice/speaking", { method: "POST", body: JSON.stringify({ active }) });

export async function transcribeVoiceRecording(blob: Blob): Promise<VoiceTranscriptionResponse> {
  const form = new FormData();
  const extension = blob.type.includes("ogg") ? "ogg" : blob.type.includes("wav") ? "wav" : "webm";
  form.append("file", blob, `jace-voice.${extension}`);
  const response = await fetch(`${API_BASE_URL}/voice/transcribe`, { method: "POST", body: form });
  if (!response.ok) throw new Error(await getErrorMessage(response));
  return response.json() as Promise<VoiceTranscriptionResponse>;
}

export async function synthesizeVoice(payload: {
  text: string;
  voice?: string;
  speed?: number;
  language?: string;
}): Promise<ArrayBuffer> {
  const response = await fetch(`${API_BASE_URL}/voice/synthesize`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!response.ok) throw new Error(await getErrorMessage(response));
  return response.arrayBuffer();
}

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

// Phase 9 interactive control
export const getControlStatus = () => request<ControlStatus>("/control/status");
export const getControlWindows = () => request<ControlWindowListResponse>("/control/windows");
export const getControlPolicies = () => request<ControlAppPolicyListResponse>("/control/policies");
export const createControlPolicy = (payload: ControlAppPolicyCreateRequest) =>
  request<ControlAppPolicy>("/control/policies", { method: "POST", body: JSON.stringify(payload) });
export const updateControlPolicy = (id: string, payload: ControlAppPolicyUpdateRequest) =>
  request<ControlAppPolicy>(`/control/policies/${id}`, { method: "PATCH", body: JSON.stringify(payload) });
export async function deleteControlPolicy(id: string): Promise<void> {
  await request(`/control/policies/${id}`, { method: "DELETE" });
}
export const getControlSessions = (limit = 50) =>
  request<ControlSessionListResponse>(`/control/sessions?limit=${limit}`);
export const createControlSession = (payload: ControlSessionCreateRequest) =>
  request<ControlSessionRecord>("/control/sessions", { method: "POST", body: JSON.stringify(payload) });
export const stopControlSession = (id: string) =>
  request<ControlSessionRecord>(`/control/sessions/${id}/stop`, { method: "POST" });
export const authorizeSensitiveControl = (id: string) =>
  request<ControlSessionRecord>(`/control/sessions/${id}/authorize-sensitive`, { method: "POST" });
export async function emergencyStopControl(): Promise<number> {
  const result = await request<{ success: boolean; stopped_sessions: number }>("/control/emergency-stop", { method: "POST" });
  return result.stopped_sessions;
}
export const getControlActions = (sessionId?: string | null, limit = 100) => {
  const query = new URLSearchParams({ limit: String(limit) });
  if (sessionId) query.set("session_id", sessionId);
  return request<ControlActionListResponse>(`/control/actions?${query.toString()}`);
};


// Phase 8 automation
export const getAutomationStatus = () => request<AutomationStatus>("/automations/status");
export const getAutomations = () => request<AutomationListResponse>("/automations");
export const getAutomation = (id: string) => request<AutomationRecord>(`/automations/${id}`);
export const createAutomation = (payload: AutomationCreateRequest) =>
  request<AutomationRecord>("/automations", { method: "POST", body: JSON.stringify(payload) });
export const updateAutomation = (id: string, payload: AutomationUpdateRequest) =>
  request<AutomationRecord>(`/automations/${id}`, { method: "PATCH", body: JSON.stringify(payload) });
export async function deleteAutomation(id: string): Promise<void> {
  await request(`/automations/${id}`, { method: "DELETE" });
}
export async function runAutomationNow(id: string): Promise<void> {
  await request(`/automations/${id}/run`, { method: "POST" });
}
export const getAutomationRuns = (id: string, limit = 50) =>
  request<AutomationRunListResponse>(`/automations/${id}/runs?limit=${limit}`);
export const draftAutomation = (payload: AutomationDraftRequest) =>
  request<AutomationDraftResponse>("/automations/draft", { method: "POST", body: JSON.stringify(payload) });
export const getAutomationNotifications = (unreadOnly = true, limit = 100) =>
  request<AutomationNotificationListResponse>(`/automations/notifications/list?unread_only=${unreadOnly ? "true" : "false"}&limit=${limit}`);
export async function markAutomationNotificationRead(id: string): Promise<void> {
  await request(`/automations/notifications/${id}/read`, { method: "POST" });
}
export async function markAllAutomationNotificationsRead(): Promise<void> {
  await request("/automations/notifications/read-all", { method: "POST" });
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
