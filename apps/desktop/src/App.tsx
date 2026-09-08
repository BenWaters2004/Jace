import { isPermissionGranted, requestPermission, sendNotification } from "@tauri-apps/plugin-notification";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { FormEvent } from "react";
import {
  clearToolAudit,
  createAutomation,
  deleteAutomation,
  draftAutomation,
  getAutomationNotifications,
  getAutomations,
  getAutomationRuns,
  getAutomationStatus,
  markAllAutomationNotificationsRead,
  markAutomationNotificationRead,
  runAutomationNow,
  updateAutomation,
  deleteAttachment,
  createComputerCommand,
  createComputerWorkspace,
  createControlPolicy,
  createControlSession,
  createConversation,
  createMemory,
  deleteComputerCommand,
  deleteComputerWorkspace,
  deleteControlPolicy,
  deleteConversation,
  deleteMemory,
  getAttachmentStatus,
  getComputerStatus,
  getComputerWorkspaces,
  getControlActions,
  getControlPolicies,
  getControlSessions,
  getControlStatus,
  getControlWindows,
  getConversation,
  getConversations,
  getHealth,
  getMemories,
  getModels,
  getSettings,
  getToolAudit,
  getTools,
  resetSettings,
  resolveToolApproval,
  authorizeSensitiveControl,
  emergencyStopControl,
  stopControlSession,
  sendChatStream,
  updateComputerCommand,
  updateComputerWorkspace,
  updateControlPolicy,
  updateConversation,
  updateMemory,
  updateSettings,
  updateToolPermission,
  uploadAttachment,
} from "./api";
import { AutomationsView } from "./components/AutomationsView";
import { ChatView } from "./components/ChatView";
import { ComputerView } from "./components/ComputerView";
import { ControlView } from "./components/ControlView";
import { MemoryView } from "./components/MemoryView";
import { OutputView } from "./components/OutputView";
import { WebWorkspaceView } from "./components/WebWorkspaceView";
import { SettingsView } from "./components/SettingsView";
import { CommandCenter } from "./shell/CommandCenter";
import { useRuntimeEvents, type JaceRuntimeState } from "./shell/runtime";
import { ToolApprovalModal } from "./components/ToolApprovalModal";
import { ToolsView } from "./components/ToolsView";
import type {
  ApiGenerationStats,
  AutomationCreateRequest,
  AutomationDraftResponse,
  AutomationNotificationRecord,
  AutomationRecord,
  AutomationRunRecord,
  AutomationStatus,
  AutomationUpdateRequest,
  AttachmentStatus,
  AssistantSettings,
  ChatMessage,
  ComputerCommandCreateRequest,
  ComputerCommandPreset,
  ComputerCommandUpdateRequest,
  ComputerStatus,
  ComputerWorkspace,
  ComputerWorkspaceCreateRequest,
  ComputerWorkspaceUpdateRequest,
  ControlActionRecord,
  ControlAppPolicy,
  ControlAppPolicyCreateRequest,
  ControlAppPolicyUpdateRequest,
  ControlSessionRecord,
  ControlStatus,
  ControlWindowRecord,
  ConversationDetail,
  ConversationSummary,
  GenerationStats,
  HealthResponse,
  MemoryCreateRequest,
  MemoryRecord,
  MemoryUpdateRequest,
  ModelInfo,
  PendingAttachment,
  PendingToolApproval,
  PerformanceDiagnostics,
  ReasoningMode,
  Screen,
  StreamApprovalRequiredEvent,
  StreamDoneEvent,
  StreamToolCallEvent,
  StreamToolResultEvent,
  ToolActivity,
  ToolApprovalDecision,
  ToolAuditRecord,
  ToolPermissionMode,
  ToolRecord,
} from "./types";
import "./styles.css";

type ConnectionState = "checking" | "online" | "backend-offline" | "ollama-offline";

function localMessage(role: "user" | "assistant", content: string): ChatMessage {
  return { id: crypto.randomUUID(), role, content };
}

function mapStats(stats: ApiGenerationStats | null): GenerationStats | undefined {
  if (!stats) return undefined;
  return {
    timeToFirstTokenMs: stats.time_to_first_token_ms,
    totalDurationMs: stats.total_duration_ms,
    loadDurationMs: stats.load_duration_ms,
    promptEvalCount: stats.prompt_eval_count,
    promptEvalCachedCount: stats.prompt_eval_cached_count,
    promptEvalDurationMs: stats.prompt_eval_duration_ms,
    evalCount: stats.eval_count,
    evalDurationMs: stats.eval_duration_ms,
    tokensPerSecond: stats.tokens_per_second,
  };
}

function mapMessages(conversation: ConversationDetail): ChatMessage[] {
  return conversation.messages.map((message) => ({
    id: message.id,
    conversation_id: message.conversation_id,
    role: message.role,
    content: message.content,
    status: message.status,
    model: message.model,
    created_at: message.created_at,
    stopped: message.status === "stopped",
    stats: mapStats(message.stats),
    attachments: message.attachments,
  }));
}

export default function App() {
  const [screen, setScreen] = useState<Screen>("chat");
  const [connectionState, setConnectionState] = useState<ConnectionState>("checking");
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [attachmentStatus, setAttachmentStatus] = useState<AttachmentStatus | null>(null);
  const [models, setModels] = useState<ModelInfo[]>([]);
  const [settings, setSettings] = useState<AssistantSettings | null>(null);
  const [conversations, setConversations] = useState<ConversationSummary[]>([]);
  const [memories, setMemories] = useState<MemoryRecord[]>([]);
  const [toolsEnabled, setToolsEnabled] = useState(true);
  const [tools, setTools] = useState<ToolRecord[]>([]);
  const [toolAudit, setToolAudit] = useState<ToolAuditRecord[]>([]);
  const [computerStatus, setComputerStatus] = useState<ComputerStatus | null>(null);
  const [computerWorkspaces, setComputerWorkspaces] = useState<ComputerWorkspace[]>([]);
  const [controlStatus, setControlStatus] = useState<ControlStatus | null>(null);
  const [controlWindows, setControlWindows] = useState<ControlWindowRecord[]>([]);
  const [controlPolicies, setControlPolicies] = useState<ControlAppPolicy[]>([]);
  const [controlSessions, setControlSessions] = useState<ControlSessionRecord[]>([]);
  const [controlActions, setControlActions] = useState<ControlActionRecord[]>([]);
  const [automationStatus, setAutomationStatus] = useState<AutomationStatus | null>(null);
  const [automations, setAutomations] = useState<AutomationRecord[]>([]);
  const [automationNotifications, setAutomationNotifications] = useState<AutomationNotificationRecord[]>([]);
  const notificationSeenRef = useRef<Set<string>>(new Set());
  const [pendingApproval, setPendingApproval] = useState<PendingToolApproval | null>(null);
  const [toolActivity, setToolActivity] = useState<ToolActivity[]>([]);

  const [activeConversationId, setActiveConversationId] = useState<string | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [selectedModel, setSelectedModel] = useState("");
  const [conversationPrompt, setConversationPrompt] = useState("");
  const [reasoningMode, setReasoningMode] = useState<ReasoningMode>("fast");
  const [input, setInput] = useState("");
  const [pendingAttachments, setPendingAttachments] = useState<PendingAttachment[]>([]);
  const [conversationSearch, setConversationSearch] = useState("");
  const [isGenerating, setIsGenerating] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [memoryContextCount, setMemoryContextCount] = useState(0);
  const [toolContextCount, setToolContextCount] = useState(0);
  const [performanceDiagnostics, setPerformanceDiagnostics] = useState<PerformanceDiagnostics | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  const submitLockRef = useRef(false);
  const fallbackRuntimeState: JaceRuntimeState = pendingApproval
    ? "waiting_permission"
    : isGenerating
      ? (toolActivity.some((item) => item.status === "requested") ? "working" : "thinking")
      : connectionState === "online"
        ? "idle"
        : "offline";
  const runtime = useRuntimeEvents(fallbackRuntimeState);

  const activeConversation = useMemo(
    () => conversations.find((conversation) => conversation.id === activeConversationId) ?? null,
    [conversations, activeConversationId],
  );

  const refreshConversations = useCallback(async () => {
    const response = await getConversations();
    setConversations(response.conversations);
    return response.conversations;
  }, []);

  const refreshMemories = useCallback(async () => {
    const response = await getMemories(false);
    setMemories(response.memories);
    return response.memories;
  }, []);

  const refreshTools = useCallback(async () => {
    const [toolResponse, auditResponse] = await Promise.all([getTools(), getToolAudit(100)]);
    setToolsEnabled(toolResponse.enabled);
    setTools(toolResponse.tools);
    setToolAudit(auditResponse.entries);
    return toolResponse.tools;
  }, []);

  const refreshComputer = useCallback(async () => {
    const [statusResponse, workspaceResponse] = await Promise.all([
      getComputerStatus(),
      getComputerWorkspaces(),
    ]);
    setComputerStatus(statusResponse);
    setComputerWorkspaces(workspaceResponse.workspaces);
    return workspaceResponse.workspaces;
  }, []);

  const refreshControl = useCallback(async () => {
    const [statusResponse, policyResponse, sessionResponse, actionResponse] = await Promise.all([
      getControlStatus(),
      getControlPolicies(),
      getControlSessions(50),
      getControlActions(null, 100),
    ]);
    setControlStatus(statusResponse);
    setControlPolicies(policyResponse.policies);
    setControlSessions(sessionResponse.sessions);
    setControlActions(actionResponse.actions);

    if (statusResponse.enabled && statusResponse.platform_supported) {
      try {
        const windowResponse = await getControlWindows();
        setControlWindows(windowResponse.windows);
      } catch {
        setControlWindows([]);
      }
    } else {
      setControlWindows([]);
    }
    return statusResponse;
  }, []);

  const refreshAutomations = useCallback(async () => {
    const [statusResponse, automationResponse, notificationResponse] = await Promise.all([
      getAutomationStatus(),
      getAutomations(),
      getAutomationNotifications(true, 100),
    ]);
    setAutomationStatus(statusResponse);
    setAutomations(automationResponse.automations);
    setAutomationNotifications(notificationResponse.notifications);
    return automationResponse.automations;
  }, []);

  const loadConversation = useCallback(async (id: string) => {
    if (isGenerating) return;
    try {
      const conversation = await getConversation(id);
      setActiveConversationId(conversation.id);
      setMessages(mapMessages(conversation));
      setSelectedModel(conversation.model);
      setConversationPrompt(conversation.system_prompt);
      setMemoryContextCount(0);
      setToolContextCount(0);
      setPerformanceDiagnostics(null);
      clearPendingAttachments();
      setToolActivity([]);
      setError(null);
      setScreen("chat");
    } catch (loadError) {
      setError(loadError instanceof Error ? loadError.message : "Could not load conversation.");
    }
  }, [isGenerating]);

  const initialise = useCallback(async () => {
    setConnectionState("checking");
    setError(null);

    try {
      const currentHealth = await getHealth();
      setHealth(currentHealth);

      const [profile, conversationResponse, memoryResponse, toolResponse, auditResponse, computerStatusResponse, computerWorkspaceResponse, attachmentStatusResponse, automationStatusResponse, automationResponse, notificationResponse] = await Promise.all([
        getSettings(),
        getConversations(),
        getMemories(false),
        getTools(),
        getToolAudit(100),
        getComputerStatus(),
        getComputerWorkspaces(),
        getAttachmentStatus(),
        getAutomationStatus(),
        getAutomations(),
        getAutomationNotifications(true, 100),
      ]);

      setSettings(profile);
      setReasoningMode(profile.reasoning_mode);
      setSelectedModel(profile.default_model);
      setConversationPrompt(profile.system_prompt);
      setConversations(conversationResponse.conversations);
      setMemories(memoryResponse.memories);
      setToolsEnabled(toolResponse.enabled);
      setTools(toolResponse.tools);
      setToolAudit(auditResponse.entries);
      setComputerStatus(computerStatusResponse);
      setComputerWorkspaces(computerWorkspaceResponse.workspaces);
      setAttachmentStatus(attachmentStatusResponse);
      setAutomationStatus(automationStatusResponse);
      setAutomations(automationResponse.automations);
      setAutomationNotifications(notificationResponse.notifications);
      notificationSeenRef.current = new Set(notificationResponse.notifications.map((item) => item.id));

      try {
        await refreshControl();
      } catch {
        setControlStatus(null);
        setControlWindows([]);
        setControlPolicies([]);
        setControlSessions([]);
        setControlActions([]);
      }

      if (!currentHealth.ollama_connected) {
        setConnectionState("ollama-offline");
        return;
      }

      const modelResponse = await getModels();
      setModels(modelResponse.models);
      setConnectionState("online");

      if (conversationResponse.conversations.length > 0) {
        const latest = await getConversation(conversationResponse.conversations[0].id);
        setActiveConversationId(latest.id);
        setMessages(mapMessages(latest));
        setSelectedModel(latest.model);
        setConversationPrompt(latest.system_prompt);
      }
    } catch (initialiseError) {
      setConnectionState("backend-offline");
      setError(initialiseError instanceof Error ? initialiseError.message : "Could not initialise Jace.");
    }
  }, [refreshControl]);

  useEffect(() => { void initialise(); }, [initialise]);

  useEffect(() => {
    if (connectionState === "backend-offline") return;

    let cancelled = false;

    async function pollNotifications() {
      try {
        const response = await getAutomationNotifications(true, 100);
        if (cancelled) return;

        const newItems = response.notifications.filter((item) => !notificationSeenRef.current.has(item.id));
        setAutomationNotifications(response.notifications);
        setAutomationStatus((current) => current ? { ...current, unread_notifications: response.notifications.length } : current);

        for (const item of response.notifications) notificationSeenRef.current.add(item.id);

        if (newItems.length > 0) {
          try {
            let granted = await isPermissionGranted();
            if (!granted) granted = (await requestPermission()) === "granted";
            if (granted) {
              for (const item of newItems) {
                sendNotification({ title: item.title, body: item.body });
              }
            }
          } catch {
            // Native notifications are best-effort; the in-app inbox remains authoritative.
          }
        }
      } catch {
        // Polling must not interfere with chat if the automation API is temporarily unavailable.
      }
    }

    const timer = window.setInterval(() => { void pollNotifications(); }, 10_000);
    return () => { cancelled = true; window.clearInterval(timer); };
  }, [connectionState]);

  useEffect(() => {
    if (connectionState === "backend-offline") return;
    if (screen !== "control" && !controlStatus?.active_session) return;

    const timer = window.setInterval(() => {
      void refreshControl();
    }, 2500);
    return () => window.clearInterval(timer);
  }, [connectionState, screen, controlStatus?.active_session?.id, refreshControl]);

  async function ensureConversation(): Promise<string> {
    if (activeConversationId) return activeConversationId;
    if (!settings) throw new Error("Jace settings are not available yet.");

    const conversation = await createConversation({
      model: selectedModel || settings.default_model,
      system_prompt: conversationPrompt || settings.system_prompt,
    });

    setActiveConversationId(conversation.id);
    await refreshConversations();
    return conversation.id;
  }

  function updateAssistant(id: string, updater: (message: ChatMessage) => ChatMessage) {
    setMessages((current) => current.map((message) => message.id === id ? updater(message) : message));
  }

  function registerToolCall(event: StreamToolCallEvent) {
    setToolActivity((current) => {
      const next: ToolActivity = {
        callId: event.call_id,
        toolName: event.tool_name,
        label: event.label,
        status: event.permission === "ask" ? "awaiting_approval" : "requested",
        arguments: event.arguments,
      };
      return [...current.filter((item) => item.callId !== event.call_id), next];
    });
  }

  function registerApproval(event: StreamApprovalRequiredEvent, conversationId?: string | null) {
    setPendingApproval({
      approval_id: event.approval_id,
      call_id: event.call_id,
      conversation_id: conversationId ?? activeConversationId,
      tool_name: event.tool_name,
      label: event.label,
      description: event.description,
      risk: event.risk,
      arguments: event.arguments,
    });

    setToolActivity((current) => current.map((item) =>
      item.callId === event.call_id ? { ...item, status: "awaiting_approval" } : item,
    ));
  }

  function registerToolResult(event: StreamToolResultEvent) {
    setToolActivity((current) => current.map((item) =>
      item.callId === event.call_id
        ? { ...item, status: event.status, summary: event.summary }
        : item,
    ));
    setPendingApproval((current) => current?.call_id === event.call_id ? null : current);
    window.setTimeout(() => { void refreshTools(); }, 250);
  }

  function clearPendingAttachments() {
    setPendingAttachments((current) => {
      for (const item of current) {
        if (item.previewUrl) URL.revokeObjectURL(item.previewUrl);
      }
      return [];
    });
  }

  function addPendingFiles(files: File[]) {
    if (!attachmentStatus?.enabled || isGenerating) return;
    setPendingAttachments((current) => {
      const room = Math.max(0, attachmentStatus.max_count - current.length);
      const accepted = files.slice(0, room);
      if (accepted.length < files.length) {
        setError(`Jace accepts up to ${attachmentStatus.max_count} attachments per message.`);
      }
      const additions: PendingAttachment[] = [];
      for (const file of accepted) {
        const lower = file.name.toLowerCase();
        const isImage = file.type.startsWith("image/");
        const isAudio = file.type.startsWith("audio/") || /\.(mp3|m4a|wav|flac|ogg|oga|webm|aac|wma)$/.test(lower);
        const maxBytes = isImage
          ? attachmentStatus.image_max_bytes
          : isAudio
            ? attachmentStatus.audio_max_bytes
            : attachmentStatus.document_max_bytes;
        if (file.size > maxBytes) {
          setError(`${file.name} is too large (${(file.size / 1024 / 1024).toFixed(1)} MB).`);
          continue;
        }
        additions.push({
          id: crypto.randomUUID(),
          file,
          previewUrl: isImage ? URL.createObjectURL(file) : null,
        });
      }
      return [...current, ...additions];
    });
  }

  function removePendingAttachment(id: string) {
    setPendingAttachments((current) => {
      const target = current.find((item) => item.id === id);
      if (target?.previewUrl) URL.revokeObjectURL(target.previewUrl);
      return current.filter((item) => item.id !== id);
    });
  }

  async function submit(event?: FormEvent<HTMLFormElement>) {
    event?.preventDefault();
    const text = input.trim();

    if (
      (!text && pendingAttachments.length === 0)
      || isGenerating
      || submitLockRef.current
      || connectionState !== "online"
      || !settings
      || !selectedModel
    ) {
      return;
    }

    // React state updates are asynchronous, so use a synchronous ref as the
    // authoritative submission lock. This closes the small window where a
    // second submit could arrive while a new conversation or its attachments
    // are still being created.
    submitLockRef.current = true;
    setIsGenerating(true);

    let conversationId: string;
    try {
      conversationId = await ensureConversation();
    } catch (conversationError) {
      submitLockRef.current = false;
      setIsGenerating(false);
      setError(conversationError instanceof Error ? conversationError.message : "Could not create conversation.");
      return;
    }

    let uploadedAttachments = [] as Awaited<ReturnType<typeof uploadAttachment>>[];
    try {
      for (const pending of pendingAttachments) {
        uploadedAttachments.push(await uploadAttachment(conversationId, pending.file));
      }
    } catch (uploadError) {
      for (const attachment of uploadedAttachments) {
        try { await deleteAttachment(attachment.id); } catch { /* best-effort orphan cleanup */ }
      }
      submitLockRef.current = false;
      setIsGenerating(false);
      setError(uploadError instanceof Error ? uploadError.message : "Could not upload attachment.");
      return;
    }

    const displayText = text || (uploadedAttachments.length === 1
      ? `Attached ${uploadedAttachments[0].original_name}`
      : `Attached ${uploadedAttachments.length} files`);
    const user = { ...localMessage("user", displayText), attachments: uploadedAttachments };
    const assistant: ChatMessage = { ...localMessage("assistant", ""), isStreaming: true };
    setMessages((current) => [...current, user, assistant]);
    setInput("");
    clearPendingAttachments();
    setError(null);
    setMemoryContextCount(0);
    setToolContextCount(0);
    setPerformanceDiagnostics(null);
    setToolActivity([]);
    setPendingApproval(null);

    const controller = new AbortController();
    abortRef.current = controller;

    try {
      await sendChatStream(
        {
          conversation_id: conversationId,
          message: text,
          model: selectedModel,
          system_prompt: conversationPrompt,
          reasoning_mode: reasoningMode,
          temperature: settings.temperature,
          attachment_ids: uploadedAttachments.map((attachment) => attachment.id),
        },
        {
          onContext: (context) => {
            setMemoryContextCount(context.memory_count);
            setToolContextCount(context.tool_count);
            setPerformanceDiagnostics({
              preprocess_ms: context.preprocess_ms,
              memory_retrieval_used: context.memory_retrieval_used,
              memory_retrieval_ms: context.memory_retrieval_ms,
              memory_count: context.memory_count,
              tool_routing_ms: context.tool_routing_ms,
              tool_names: context.tool_names,
              history_messages: context.history_messages,
              history_chars: context.history_chars,
              attachment_count: context.attachment_count,
              attachment_image_count: context.attachment_image_count,
              attachment_processing_ms: context.attachment_processing_ms,
            });
          },
          onToken: (content) => updateAssistant(assistant.id, (message) => ({ ...message, content: message.content + content })),
          onToolCall: registerToolCall,
          onApprovalRequired: (approval) => registerApproval(approval, conversationId),
          onToolResult: registerToolResult,
          onDone: (done: StreamDoneEvent) => {
            if (done.diagnostics) setPerformanceDiagnostics(done.diagnostics);
            updateAssistant(assistant.id, (message) => ({
              ...message,
              isStreaming: false,
              stats: {
                timeToFirstTokenMs: done.metrics.time_to_first_token_ms,
                totalDurationMs: done.metrics.total_duration_ms,
                loadDurationMs: done.metrics.load_duration_ms,
                promptEvalCount: done.metrics.prompt_eval_count,
                promptEvalCachedCount: done.metrics.prompt_eval_cached_count,
                promptEvalDurationMs: done.metrics.prompt_eval_duration_ms,
                evalCount: done.metrics.eval_count,
                evalDurationMs: done.metrics.eval_duration_ms,
                tokensPerSecond: done.metrics.tokens_per_second,
              },
            }));
          },
        },
        controller.signal,
      );

      await refreshConversations();
      const saved = await getConversation(conversationId);
      setMessages(mapMessages(saved));
      setSelectedModel(saved.model);
      setConversationPrompt(saved.system_prompt);
      await refreshTools();
      window.setTimeout(() => { void refreshMemories(); }, 1200);
    } catch (chatError) {
      if (controller.signal.aborted) {
        updateAssistant(assistant.id, (message) => ({ ...message, isStreaming: false, stopped: true }));
      } else {
        updateAssistant(assistant.id, (message) => ({ ...message, isStreaming: false }));
        setError(chatError instanceof Error ? chatError.message : "Jace could not generate a response.");
      }
    } finally {
      abortRef.current = null;
      setPendingApproval(null);
      submitLockRef.current = false;
      setIsGenerating(false);
    }
  }

  async function decideToolApproval(decision: ToolApprovalDecision) {
    if (!pendingApproval) return;
    try {
      await resolveToolApproval(pendingApproval.approval_id, decision);
      if (decision === "allow_always" || decision === "deny_always") {
        await refreshTools();
      }
      setPendingApproval(null);
    } catch (approvalError) {
      setError(approvalError instanceof Error ? approvalError.message : "Could not resolve tool approval.");
      throw approvalError;
    }
  }

  function newChat() {
    if (isGenerating || !settings) return;
    setActiveConversationId(null);
    setMessages([]);
    setInput("");
    clearPendingAttachments();
    setConversationSearch("");
    setSelectedModel(settings.default_model);
    setConversationPrompt(settings.system_prompt);
    setReasoningMode(settings.reasoning_mode);
    setMemoryContextCount(0);
    setToolContextCount(0);
    setPerformanceDiagnostics(null);
    setToolActivity([]);
    setPendingApproval(null);
    setError(null);
    setScreen("chat");
  }

  async function renameConversation(conversation: ConversationSummary) {
    if (isGenerating) return;
    const title = window.prompt("Rename conversation", conversation.title);
    if (!title?.trim()) return;
    try {
      await updateConversation(conversation.id, { title: title.trim() });
      await refreshConversations();
    } catch (renameError) {
      setError(renameError instanceof Error ? renameError.message : "Could not rename conversation.");
    }
  }

  async function removeConversation(conversation: ConversationSummary) {
    if (isGenerating || !window.confirm(`Delete "${conversation.title}"?`)) return;
    try {
      await deleteConversation(conversation.id);
      const remaining = await refreshConversations();
      if (activeConversationId === conversation.id) {
        if (remaining.length) await loadConversation(remaining[0].id);
        else newChat();
      }
    } catch (deleteError) {
      setError(deleteError instanceof Error ? deleteError.message : "Could not delete conversation.");
    }
  }

  async function changeModel(model: string) {
    setSelectedModel(model);
    if (!activeConversationId) return;
    try {
      await updateConversation(activeConversationId, { model });
      await refreshConversations();
    } catch (updateError) {
      setError(updateError instanceof Error ? updateError.message : "Could not update the conversation model.");
    }
  }

  async function saveSettings(next: AssistantSettings) {
    const updated = await updateSettings({
      assistant_name: next.assistant_name,
      user_name: next.user_name,
      system_prompt: next.system_prompt,
      default_model: next.default_model,
      reasoning_mode: next.reasoning_mode,
      response_style: next.response_style,
      temperature: next.temperature,
      memory_enabled: next.memory_enabled,
      memory_auto_extract: next.memory_auto_extract,
      memory_top_k: next.memory_top_k,
      memory_min_similarity: next.memory_min_similarity,
    });
    setSettings(updated);
    if (!activeConversationId) {
      setSelectedModel(updated.default_model);
      setConversationPrompt(updated.system_prompt);
      setReasoningMode(updated.reasoning_mode);
    }
  }

  async function resetProfile() {
    const updated = await resetSettings();
    setSettings(updated);
    if (!activeConversationId) {
      setSelectedModel(updated.default_model);
      setConversationPrompt(updated.system_prompt);
      setReasoningMode(updated.reasoning_mode);
    }
  }

  async function applySettingsToCurrent() {
    if (!settings || !activeConversationId) return;
    await updateConversation(activeConversationId, {
      model: settings.default_model,
      system_prompt: settings.system_prompt,
    });
    setSelectedModel(settings.default_model);
    setConversationPrompt(settings.system_prompt);
    setReasoningMode(settings.reasoning_mode);
    await refreshConversations();
  }

  async function addMemory(payload: MemoryCreateRequest) {
    try {
      await createMemory(payload);
      await refreshMemories();
    } catch (memoryError) {
      setError(memoryError instanceof Error ? memoryError.message : "Could not create memory.");
      throw memoryError;
    }
  }

  async function patchMemory(id: string, payload: MemoryUpdateRequest) {
    try {
      await updateMemory(id, payload);
      await refreshMemories();
    } catch (memoryError) {
      setError(memoryError instanceof Error ? memoryError.message : "Could not update memory.");
      throw memoryError;
    }
  }

  async function removeMemory(memory: MemoryRecord) {
    if (!window.confirm(`Permanently delete the memory "${memory.subject}"?\n\nDeactivate it instead if you may want the history later.`)) return;
    try {
      await deleteMemory(memory.id);
      await refreshMemories();
    } catch (memoryError) {
      setError(memoryError instanceof Error ? memoryError.message : "Could not delete memory.");
    }
  }

  function openMemorySource(conversationId: string) {
    void loadConversation(conversationId);
  }

  async function changeToolPermission(tool: ToolRecord, permission: ToolPermissionMode) {
    try {
      const updated = await updateToolPermission(tool.name, permission);
      setTools((current) => current.map((item) => item.name === updated.name ? updated : item));
    } catch (toolError) {
      setError(toolError instanceof Error ? toolError.message : "Could not update tool permission.");
      throw toolError;
    }
  }

  async function removeToolAudit() {
    try {
      await clearToolAudit();
      setToolAudit([]);
    } catch (toolError) {
      setError(toolError instanceof Error ? toolError.message : "Could not clear the tool audit log.");
      throw toolError;
    }
  }

  async function addComputerWorkspace(payload: ComputerWorkspaceCreateRequest) {
    try {
      await createComputerWorkspace(payload);
      await refreshComputer();
    } catch (computerError) {
      setError(computerError instanceof Error ? computerError.message : "Could not add computer workspace.");
      throw computerError;
    }
  }

  async function patchComputerWorkspace(workspace: ComputerWorkspace, payload: ComputerWorkspaceUpdateRequest) {
    try {
      await updateComputerWorkspace(workspace.id, payload);
      await refreshComputer();
    } catch (computerError) {
      setError(computerError instanceof Error ? computerError.message : "Could not update computer workspace.");
      throw computerError;
    }
  }

  async function removeComputerWorkspace(workspace: ComputerWorkspace) {
    try {
      await deleteComputerWorkspace(workspace.id);
      await refreshComputer();
    } catch (computerError) {
      setError(computerError instanceof Error ? computerError.message : "Could not remove computer workspace.");
      throw computerError;
    }
  }

  async function addComputerCommand(workspace: ComputerWorkspace, payload: ComputerCommandCreateRequest) {
    try {
      await createComputerCommand(workspace.id, payload);
      await refreshComputer();
    } catch (computerError) {
      setError(computerError instanceof Error ? computerError.message : "Could not create command preset.");
      throw computerError;
    }
  }

  async function patchComputerCommand(command: ComputerCommandPreset, payload: ComputerCommandUpdateRequest) {
    try {
      await updateComputerCommand(command.id, payload);
      await refreshComputer();
    } catch (computerError) {
      setError(computerError instanceof Error ? computerError.message : "Could not update command preset.");
      throw computerError;
    }
  }

  async function removeComputerCommand(command: ComputerCommandPreset) {
    try {
      await deleteComputerCommand(command.id);
      await refreshComputer();
    } catch (computerError) {
      setError(computerError instanceof Error ? computerError.message : "Could not delete command preset.");
      throw computerError;
    }
  }

  async function addControlPolicy(payload: ControlAppPolicyCreateRequest) {
    try {
      await createControlPolicy(payload);
      await refreshControl();
    } catch (controlError) {
      setError(controlError instanceof Error ? controlError.message : "Could not create app control policy.");
      throw controlError;
    }
  }

  async function patchControlPolicy(policy: ControlAppPolicy, payload: ControlAppPolicyUpdateRequest) {
    try {
      await updateControlPolicy(policy.id, payload);
      await refreshControl();
    } catch (controlError) {
      setError(controlError instanceof Error ? controlError.message : "Could not update app control policy.");
      throw controlError;
    }
  }

  async function removeControlPolicy(policy: ControlAppPolicy) {
    if (!window.confirm(`Delete the control policy "${policy.label}"?`)) return;
    try {
      await deleteControlPolicy(policy.id);
      await refreshControl();
    } catch (controlError) {
      setError(controlError instanceof Error ? controlError.message : "Could not delete app control policy.");
      throw controlError;
    }
  }

  async function startDesktopControl(maxSteps: number, storeScreenshots: boolean) {
    try {
      await createControlSession({
        conversation_id: activeConversationId,
        max_steps: maxSteps,
        store_screenshots: storeScreenshots,
      });
      await refreshControl();
    } catch (controlError) {
      setError(controlError instanceof Error ? controlError.message : "Could not start interactive control.");
      throw controlError;
    }
  }

  async function stopDesktopControl(session: ControlSessionRecord) {
    try {
      await stopControlSession(session.id);
      await refreshControl();
    } catch (controlError) {
      setError(controlError instanceof Error ? controlError.message : "Could not stop interactive control.");
      throw controlError;
    }
  }

  async function authorizeSensitiveDesktopControl(session: ControlSessionRecord) {
    if (!window.confirm(
      "Authorize the NEXT sensitive GUI action only?\n\nThis authorization is consumed after one detected sensitive click/type/key action."
    )) return;
    try {
      await authorizeSensitiveControl(session.id);
      await refreshControl();
    } catch (controlError) {
      setError(controlError instanceof Error ? controlError.message : "Could not authorize the sensitive action.");
      throw controlError;
    }
  }

  async function emergencyStopDesktopControl() {
    // Stop the live agent stream as well as the backend control session so the
    // model cannot immediately queue another GUI action after the user hits
    // the emergency control button.
    abortRef.current?.abort();
    setPendingApproval(null);
    try {
      await emergencyStopControl();
      await refreshControl();
    } catch (controlError) {
      setError(controlError instanceof Error ? controlError.message : "Could not emergency-stop control.");
      throw controlError;
    }
  }

  async function addAutomation(payload: AutomationCreateRequest) {
    try {
      await createAutomation(payload);
      await refreshAutomations();
    } catch (automationError) {
      setError(automationError instanceof Error ? automationError.message : "Could not create automation.");
      throw automationError;
    }
  }

  async function patchAutomation(automation: AutomationRecord, payload: AutomationUpdateRequest) {
    try {
      await updateAutomation(automation.id, payload);
      await refreshAutomations();
    } catch (automationError) {
      setError(automationError instanceof Error ? automationError.message : "Could not update automation.");
      throw automationError;
    }
  }

  async function removeAutomation(automation: AutomationRecord) {
    try {
      await deleteAutomation(automation.id);
      await refreshAutomations();
    } catch (automationError) {
      setError(automationError instanceof Error ? automationError.message : "Could not delete automation.");
      throw automationError;
    }
  }

  async function executeAutomationNow(automation: AutomationRecord) {
    try {
      await runAutomationNow(automation.id);
      window.setTimeout(() => { void refreshAutomations(); }, 750);
    } catch (automationError) {
      setError(automationError instanceof Error ? automationError.message : "Could not start automation.");
      throw automationError;
    }
  }

  async function buildAutomationDraft(text: string, timezone: string): Promise<AutomationDraftResponse> {
    try {
      return await draftAutomation({ instruction: text, timezone });
    } catch (automationError) {
      setError(automationError instanceof Error ? automationError.message : "Could not build automation draft.");
      throw automationError;
    }
  }

  async function loadAutomationRuns(automation: AutomationRecord): Promise<AutomationRunRecord[]> {
    try {
      const response = await getAutomationRuns(automation.id, 100);
      return response.runs;
    } catch (automationError) {
      setError(automationError instanceof Error ? automationError.message : "Could not load automation history.");
      throw automationError;
    }
  }

  async function readAutomationNotification(notification: AutomationNotificationRecord) {
    try {
      await markAutomationNotificationRead(notification.id);
      notificationSeenRef.current.delete(notification.id);
      await refreshAutomations();
    } catch (automationError) {
      setError(automationError instanceof Error ? automationError.message : "Could not update notification.");
    }
  }

  async function readAllAutomationNotifications() {
    try {
      await markAllAutomationNotificationsRead();
      setAutomationNotifications([]);
      setAutomationStatus((current) => current ? { ...current, unread_notifications: 0 } : current);
    } catch (automationError) {
      setError(automationError instanceof Error ? automationError.message : "Could not clear notifications.");
    }
  }

  if (!settings) {
    return (
      <main className="boot-screen">
        <div className="welcome-mark">J</div>
        <h1>Starting Jace</h1>
        <p>{error ?? "Connecting to the local backend..."}</p>
        {error && <button className="primary-button" onClick={() => void initialise()}>Retry</button>}
      </main>
    );
  }

  const activeMemoryCount = memories.filter((memory) => memory.is_active).length;
  const availableToolCount = tools.filter((tool) => tool.permission !== "deny").length;
  const title = activeConversation?.title ?? "New conversation";

  const workspace = (
    <>
      {screen === "chat" && (
        <ChatView
          title={title}
          assistantName={settings.assistant_name}
          userName={settings.user_name}
          messages={messages}
          input={input}
          isGenerating={isGenerating}
          error={error}
          online={connectionState === "online"}
          models={models}
          selectedModel={selectedModel}
          reasoningMode={reasoningMode}
          memoryContextCount={memoryContextCount}
          toolContextCount={toolContextCount}
          performanceDiagnostics={performanceDiagnostics}
          toolActivity={toolActivity}
          pendingAttachments={pendingAttachments}
          attachmentLimit={attachmentStatus?.max_count ?? 6}
          onFilesAdded={addPendingFiles}
          onRemovePendingAttachment={removePendingAttachment}
          onInputChange={setInput}
          onSubmit={(event) => void submit(event)}
          onStop={() => abortRef.current?.abort()}
          onDismissError={() => setError(null)}
          onModelChange={(model) => void changeModel(model)}
          onReasoningChange={setReasoningMode}
        />
      )}

      {screen === "output" && (
        <OutputView diagnostics={performanceDiagnostics} activities={toolActivity} />
      )}

      {screen === "web" && (
        <WebWorkspaceView audit={toolAudit} />
      )}

      {screen === "memory" && (
        <MemoryView memories={memories} enabled={settings.memory_enabled} onRefresh={() => void refreshMemories()} onCreate={addMemory} onUpdate={patchMemory} onDelete={removeMemory} onOpenSource={openMemorySource} />
      )}

      {screen === "tools" && (
        <ToolsView enabled={toolsEnabled} tools={tools} audit={toolAudit} onRefresh={() => void refreshTools()} onPermissionChange={changeToolPermission} onClearAudit={removeToolAudit} />
      )}

      {screen === "computer" && (
        <ComputerView
          status={computerStatus}
          workspaces={computerWorkspaces}
          onRefresh={() => void refreshComputer()}
          onCreateWorkspace={addComputerWorkspace}
          onUpdateWorkspace={patchComputerWorkspace}
          onDeleteWorkspace={removeComputerWorkspace}
          onCreateCommand={addComputerCommand}
          onUpdateCommand={patchComputerCommand}
          onDeleteCommand={removeComputerCommand}
        />
      )}

      {screen === "control" && (
        <ControlView
          status={controlStatus}
          windows={controlWindows}
          policies={controlPolicies}
          sessions={controlSessions}
          actions={controlActions}
          activeConversationId={activeConversationId}
          onRefresh={async () => { await refreshControl(); }}
          onCreatePolicy={addControlPolicy}
          onUpdatePolicy={patchControlPolicy}
          onDeletePolicy={removeControlPolicy}
          onStartSession={startDesktopControl}
          onStopSession={stopDesktopControl}
          onAuthorizeSensitive={authorizeSensitiveDesktopControl}
          onEmergencyStop={emergencyStopDesktopControl}
        />
      )}

      {screen === "automations" && (
        <AutomationsView
          status={automationStatus}
          automations={automations}
          notifications={automationNotifications}
          tools={tools}
          timezone={automationStatus?.timezone ?? "Europe/London"}
          onRefresh={() => void refreshAutomations()}
          onDraft={buildAutomationDraft}
          onCreate={addAutomation}
          onUpdate={patchAutomation}
          onDelete={removeAutomation}
          onRunNow={executeAutomationNow}
          onLoadRuns={loadAutomationRuns}
          onReadNotification={readAutomationNotification}
          onReadAllNotifications={readAllAutomationNotifications}
        />
      )}

      {screen === "settings" && (
        <SettingsView
          settings={settings}
          models={models}
          hasActiveConversation={activeConversationId !== null}
          onSave={saveSettings}
          onReset={resetProfile}
          onApplyToCurrentConversation={applySettingsToCurrent}
        />
      )}
    </>
  );

  return (
    <>
      <CommandCenter
        assistantName={settings.assistant_name}
        appVersion={health?.app_version ?? "0.10.0-alpha.2"}
        model={selectedModel}
        state={runtime.state}
        runtimeConnected={runtime.connected}
        screen={screen}
        workspace={workspace}
        conversations={conversations}
        activeConversationId={activeConversationId}
        toolActivity={toolActivity}
        pendingApproval={pendingApproval}
        memoryCount={activeMemoryCount}
        automations={automations}
        notifications={automationNotifications}
        online={connectionState === "online"}
        controlActive={Boolean(controlStatus?.active_session)}
        onScreenChange={setScreen}
        onNewChat={newChat}
        onLoadConversation={(id) => void loadConversation(id)}
        onOpenApproval={() => setScreen("tools")}
        onEmergencyStop={() => void emergencyStopDesktopControl()}
      />
      <ToolApprovalModal approval={pendingApproval} onDecision={decideToolApproval} />
    </>
  );
}
