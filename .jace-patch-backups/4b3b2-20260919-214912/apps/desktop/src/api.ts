import { API_BASE_URL } from "./constants";
import type {
  ProcessListResponse,
  ProcessOutputResponse,
  ProcessRuntimeRecord,
  ProcessStartRequest,
} from "./processRuntimeTypes";
import type {
  RuntimeReplayResponse,
  RuntimeStreamTicket,
} from "./runtimeStreamTypes";
import type {
  PrivacyInspectRequest,
  PrivacyInspectResponse,
  PrivacyStatus,
} from "./privacyTypes";
import type {
  ModelGatewayResolveRequest,
  ModelGatewayResolvedRoute,
  ModelGatewayStatus,
} from "./modelGatewayTypes";
import type {
  DeviceCapabilityCatalogResponse,
  DeviceCapabilityExecuteRequest,
  DeviceCapabilityRequestRecord,
} from "./deviceCapabilityTypes";
import type {
  DeviceListResponse,
  DevicePairingCreateRequest,
  DevicePairingResponse,
  DeviceRecord,
  DeviceUpdateRequest,
} from "./deviceTypes";
import {
  clearAuthSession,
  getAuthAccessToken,
  getAuthRefreshToken,
  getOrCreateClientId,
  setAuthSession,
  type AuthBootstrapRequest,
  type AuthLoginRequest,
  type AuthStatusResponse,
  type AuthTokenResponse,
  type AuthUser,
} from "./auth";
import type {
  CapabilityPermissionMode,
  OAuthSession,
  OAuthClientConfig,
  OAuthClientConfigUpdateRequest,
  OAuthClientConfigListResponse,
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
  CapabilitySnapshotResponse,
  ConnectionCreateRequest,
  ConnectionListResponse,
  ConnectionProviderListResponse,
  ConnectionRecord,
  ConnectionUpdateRequest,
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
  ExternalAccessPolicy,
  ExternalAccessPolicyUpdate,
  CalendarEvent,
  CalendarEventCreateRequest,
  CalendarEventListResponse,
  CalendarEventUpdateRequest,
  CalendarSource,
  CalendarSourceListResponse,
  CalendarSourceUpdate,
  CalendarStatus,
  CalendarSyncResponse,
  CalendarPreferences,
  CalendarPreferencesUpdate,
  CalendarEventEnrichment,
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

// JACE_4BS3_DESKTOP_AUTH
let authRefreshPromise: Promise<boolean> | null = null;

function authenticatedHeaders(input?: HeadersInit): Headers {
  const headers = new Headers(input);
  const token = getAuthAccessToken();
  if (token) headers.set("Authorization", `Bearer ${token}`);
  headers.set("X-Jace-Client-ID", getOrCreateClientId());
  return headers;
}

async function refreshAuthSession(): Promise<boolean> {
  const refreshToken = getAuthRefreshToken();
  if (!refreshToken) return false;

  if (!authRefreshPromise) {
    authRefreshPromise = (async () => {
      const response = await fetch(`${API_BASE_URL}/auth/refresh`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-Jace-Client-ID": getOrCreateClientId(),
        },
        body: JSON.stringify({
          refresh_token: refreshToken,
          client_id: getOrCreateClientId(),
        }),
      });

      if (!response.ok) {
        clearAuthSession();
        return false;
      }

      const next = (await response.json()) as AuthTokenResponse;
      setAuthSession(next);
      return true;
    })().finally(() => {
      authRefreshPromise = null;
    });
  }

  return authRefreshPromise;
}

async function authenticatedFetch(
  input: RequestInfo | URL,
  init?: RequestInit,
  retryAuth = true,
): Promise<Response> {
  let response = await fetch(input, {
    ...init,
    headers: authenticatedHeaders(init?.headers),
  });

  if (response.status === 401 && retryAuth && getAuthRefreshToken()) {
    const refreshed = await refreshAuthSession();
    if (refreshed) {
      response = await fetch(input, {
        ...init,
        headers: authenticatedHeaders(init?.headers),
      });
    }
  }

  return response;
}

async function request<T>(
  path: string,
  options?: RequestInit,
): Promise<T> {
  const url = `${API_BASE_URL}${path}`;
  const method = options?.method ?? "GET";

  console.debug("[Jace API]", method, url);

  const response = await authenticatedFetch(url, {
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

// JACE_4B3B1_PROCESS_RUNTIME_API
export const startProcess = (
  payload: ProcessStartRequest,
) =>
  request<ProcessRuntimeRecord>("/processes", {
    method: "POST",
    body: JSON.stringify(payload),
  });

export const listProcesses = (
  query = "",
) =>
  request<ProcessListResponse>(
    `/processes${query ? `?${query}` : ""}`,
  );

export const getProcess = (
  processId: string,
) =>
  request<ProcessRuntimeRecord>(
    `/processes/${encodeURIComponent(processId)}`,
  );

export const getProcessOutput = (
  processId: string,
  afterSequence = 0,
  limit = 500,
) =>
  request<ProcessOutputResponse>(
    `/processes/${encodeURIComponent(processId)}/output?after_sequence=${Math.max(0, afterSequence)}&limit=${Math.max(1, limit)}`,
  );

export const terminateProcess = (
  processId: string,
  force = false,
) =>
  request<ProcessRuntimeRecord>(
    `/processes/${encodeURIComponent(processId)}/terminate`,
    {
      method: "POST",
      body: JSON.stringify({ force }),
    },
  );


// JACE_4B3A_RUNTIME_STREAM_API
export const getRuntimeStreamTicket = () =>
  request<RuntimeStreamTicket>("/runtime/stream-ticket", {
    method: "POST",
  });

export const replayRuntimeEvents = (
  afterSequence = 0,
  limit = 200,
) =>
  request<RuntimeReplayResponse>(
    `/runtime/events/replay?after_sequence=${Math.max(0, afterSequence)}&limit=${Math.max(1, limit)}`,
  );


// JACE_4BS8_PRIVACY_GATEWAY_API
export const getPrivacyStatus = () =>
  request<PrivacyStatus>("/privacy/status");

export const inspectPrivacy = (
  payload: PrivacyInspectRequest,
) =>
  request<PrivacyInspectResponse>("/privacy/inspect", {
    method: "POST",
    body: JSON.stringify(payload),
  });


// JACE_4BS7_MODEL_GATEWAY_API
export const getModelGatewayStatus = () =>
  request<ModelGatewayStatus>("/model-gateway/status");

export const resolveModelGatewayRoute = (
  payload: ModelGatewayResolveRequest,
) =>
  request<ModelGatewayResolvedRoute>("/model-gateway/resolve", {
    method: "POST",
    body: JSON.stringify(payload),
  });


// JACE_4BS6_DEVICE_CAPABILITY_API
export const getDeviceCapabilityCatalog = () =>
  request<DeviceCapabilityCatalogResponse>(
    "/capabilities/device/catalog",
  );

export const executeDeviceCapability = (
  payload: DeviceCapabilityExecuteRequest,
) =>
  request<DeviceCapabilityRequestRecord>(
    "/capabilities/device/execute",
    {
      method: "POST",
      body: JSON.stringify(payload),
    },
  );

export const getDeviceCapabilityRequest = (
  requestId: string,
) =>
  request<DeviceCapabilityRequestRecord>(
    `/capabilities/device/requests/${encodeURIComponent(requestId)}`,
  );

export const cancelDeviceCapabilityRequest = (
  requestId: string,
) =>
  request<DeviceCapabilityRequestRecord>(
    `/capabilities/device/requests/${encodeURIComponent(requestId)}/cancel`,
    { method: "POST" },
  );


// JACE_4BS4_DEVICE_API
export const getDevices = () =>
  request<DeviceListResponse>("/devices");

export const getDevice = (deviceId: string) =>
  request<DeviceRecord>(`/devices/${encodeURIComponent(deviceId)}`);

export const createDevicePairing = (
  payload: DevicePairingCreateRequest = {},
) =>
  request<DevicePairingResponse>("/devices/pairing", {
    method: "POST",
    body: JSON.stringify(payload),
  });

export const updateDevice = (
  deviceId: string,
  payload: DeviceUpdateRequest,
) =>
  request<DeviceRecord>(`/devices/${encodeURIComponent(deviceId)}`, {
    method: "PATCH",
    body: JSON.stringify(payload),
  });

export const revokeDevice = (deviceId: string) =>
  request<DeviceRecord>(`/devices/${encodeURIComponent(deviceId)}`, {
    method: "DELETE",
  });


// Phase 4B.S3 authentication API.
export const getAuthStatus = () =>
  request<AuthStatusResponse>("/auth/status");

export async function bootstrapAuth(
  payload: AuthBootstrapRequest,
  bootstrapToken: string,
): Promise<AuthTokenResponse> {
  const session = await request<AuthTokenResponse>("/auth/bootstrap", {
    method: "POST",
    headers: { "X-Jace-Bootstrap-Token": bootstrapToken },
    body: JSON.stringify(payload),
  });
  setAuthSession(session);
  return session;
}

export async function loginAuth(
  payload: AuthLoginRequest,
): Promise<AuthTokenResponse> {
  const session = await request<AuthTokenResponse>("/auth/login", {
    method: "POST",
    body: JSON.stringify(payload),
  });
  setAuthSession(session);
  return session;
}

export const getCurrentAuthUser = () =>
  request<AuthUser>("/auth/me");

export async function logoutAuth(): Promise<void> {
  try {
    await request<{ success: boolean }>("/auth/logout", { method: "POST" });
  } finally {
    clearAuthSession();
  }
}


export const getAttachmentStatus = () => request<AttachmentStatus>("/attachments/status");
export const getAttachment = (id: string) => request<AttachmentRecord>(`/attachments/${id}`);
export const attachmentContentUrl = (id: string) => `${API_BASE_URL}/attachments/${id}/content`;

export async function uploadAttachment(conversationId: string, file: File): Promise<AttachmentRecord> {
  const form = new FormData();
  form.append("file", file, file.name);
  const response = await authenticatedFetch(`${API_BASE_URL}/attachments?conversation_id=${encodeURIComponent(conversationId)}`, {
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
  const response = await authenticatedFetch(`${API_BASE_URL}/voice/transcribe`, { method: "POST", body: form });
  if (!response.ok) throw new Error(await getErrorMessage(response));
  return response.json() as Promise<VoiceTranscriptionResponse>;
}

export async function synthesizeVoice(payload: {
  text: string;
  voice?: string;
  speed?: number;
  language?: string;
}): Promise<ArrayBuffer> {
  const response = await authenticatedFetch(`${API_BASE_URL}/voice/synthesize`, {
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


// JACE_STEP4A1_CONNECTIONS_FOUNDATION
export const getConnectionProviders = () =>
  request<ConnectionProviderListResponse>("/connections/providers");
export const getConnections = () =>
  request<ConnectionListResponse>("/connections");
export const createConnection = (payload: ConnectionCreateRequest) =>
  request<ConnectionRecord>("/connections", {
    method: "POST",
    body: JSON.stringify(payload),
  });
export const updateConnection = (id: string, payload: ConnectionUpdateRequest) =>
  request<ConnectionRecord>(`/connections/${encodeURIComponent(id)}`, {
    method: "PATCH",
    body: JSON.stringify(payload),
  });
export const disconnectConnection = (id: string) =>
  request<ConnectionRecord>(`/connections/${encodeURIComponent(id)}/disconnect`, {
    method: "POST",
  });
export async function deleteConnection(id: string): Promise<void> {
  await request(`/connections/${encodeURIComponent(id)}`, { method: "DELETE" });
}

// JACE_STEP4A2_OAUTH_PROVIDER_ACCOUNTS
export const getOAuthClientConfigs = () =>
  request<OAuthClientConfigListResponse>("/connections/oauth/config");
export const saveOAuthClientConfig = (providerId: string, payload: OAuthClientConfigUpdateRequest) =>
  request<OAuthClientConfig>(`/connections/oauth/config/${encodeURIComponent(providerId)}`, {
    method: "PUT",
    body: JSON.stringify(payload),
  });
export async function deleteOAuthClientConfig(providerId: string): Promise<void> {
  await request(`/connections/oauth/config/${encodeURIComponent(providerId)}`, { method: "DELETE" });
}
export const startOAuthConnection = (providerId: string) =>
  request<OAuthSession>(`/connections/oauth/${encodeURIComponent(providerId)}/start`, { method: "POST" });
export const getOAuthSession = (sessionId: string) =>
  request<OAuthSession>(`/connections/oauth/session/${encodeURIComponent(sessionId)}`);
export const verifyConnection = (id: string) =>
  request<ConnectionRecord>(`/connections/${encodeURIComponent(id)}/verify`, { method: "POST" });

export const updateConnectionCapabilityPermission = (connectionId: string, capabilityId: string, permission: CapabilityPermissionMode) =>
  request<CapabilitySnapshotResponse>(`/capabilities/connections/${encodeURIComponent(connectionId)}/${encodeURIComponent(capabilityId)}/permission`, {
    method: "PATCH",
    body: JSON.stringify({ permission }),
  });

export const getCapabilities = () =>
  request<CapabilitySnapshotResponse>("/capabilities");

export const getExternalAccessPolicy = () =>
  request<ExternalAccessPolicy>("/security/external-access");

export const updateExternalAccessPolicy = (
  payload: ExternalAccessPolicyUpdate,
) =>
  request<ExternalAccessPolicy>("/security/external-access", {
    method: "PATCH",
    body: JSON.stringify(payload),
  });

export const emergencyStopExternalAccess = () =>
  request<ExternalAccessPolicy>(
    "/security/external-access/emergency-stop",
    {
      method: "POST",
    },
  );

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

// JACE_STEP4C4B_CALENDAR_WORKSPACE
export const getCalendarStatus = () =>
  request<CalendarStatus>("/calendar/status");


// JACE_STEP4C4E_CALENDAR_UX
export const getCalendarPreferences = () =>
  request<CalendarPreferences>("/calendar/preferences");

export const updateCalendarPreferences = (
  payload: CalendarPreferencesUpdate,
) =>
  request<CalendarPreferences>("/calendar/preferences", {
    method: "PATCH",
    body: JSON.stringify(payload),
  });

export const enrichCalendarEvent = (
  id: string,
  timezone: string,
) => {
  const query = new URLSearchParams({ timezone });

  return request<CalendarEventEnrichment>(
    `/calendar/events/${encodeURIComponent(id)}/enrich?${query.toString()}`,
    {
      method: "POST",
    },
  );
};

export const getCalendarSources = () =>
  request<CalendarSourceListResponse>("/calendar/sources");

export const updateCalendarSource = (
  id: string,
  payload: CalendarSourceUpdate,
) =>
  request<CalendarSource>(
    `/calendar/sources/${encodeURIComponent(id)}`,
    {
      method: "PATCH",
      body: JSON.stringify(payload),
    },
  );

export const getCalendarEvents = (
  start: string,
  end: string,
  timezone: string,
  sourceIds: string[] = [],
) => {
  const query = new URLSearchParams({
    start,
    end,
    timezone,
  });

  sourceIds.forEach((id) => {
    query.append("source_id", id);
  });

  return request<CalendarEventListResponse>(
    `/calendar/events?${query.toString()}`,
  );
};

export const getCalendarEvent = (id: string) =>
  request<CalendarEvent>(
    `/calendar/events/${encodeURIComponent(id)}`,
  );

export const createCalendarEvent = (
  payload: CalendarEventCreateRequest,
) =>
  request<CalendarEvent>("/calendar/events", {
    method: "POST",
    body: JSON.stringify(payload),
  });

export const updateCalendarEvent = (
  id: string,
  payload: CalendarEventUpdateRequest,
) =>
  request<CalendarEvent>(
    `/calendar/events/${encodeURIComponent(id)}`,
    {
      method: "PATCH",
      body: JSON.stringify(payload),
    },
  );

export async function deleteCalendarEvent(
  id: string,
): Promise<void> {
  await request(
    `/calendar/events/${encodeURIComponent(id)}`,
    {
      method: "DELETE",
    },
  );
}

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
  const response = await authenticatedFetch(`${API_BASE_URL}/chat/stream`, {
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

// JACE_STEP4C4C_GOOGLE_CALENDAR_SYNC
export const syncCalendar = () =>
  request<CalendarSyncResponse>("/calendar/sync", {
    method: "POST",
  });

