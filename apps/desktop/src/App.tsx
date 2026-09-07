import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { FormEvent } from "react";
import {
  createConversation,
  createMemory,
  deleteConversation,
  deleteMemory,
  getConversation,
  getConversations,
  getHealth,
  getMemories,
  getModels,
  getSettings,
  resetSettings,
  sendChatStream,
  updateConversation,
  updateMemory,
  updateSettings,
} from "./api";
import { ChatView } from "./components/ChatView";
import { MemoryView } from "./components/MemoryView";
import { SettingsView } from "./components/SettingsView";
import { Sidebar } from "./components/Sidebar";
import type {
  ApiGenerationStats,
  AssistantSettings,
  ChatMessage,
  ConversationDetail,
  ConversationSummary,
  GenerationStats,
  HealthResponse,
  MemoryCreateRequest,
  MemoryRecord,
  MemoryUpdateRequest,
  ModelInfo,
  ReasoningMode,
  Screen,
  StreamDoneEvent,
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
  }));
}

export default function App() {
  const [screen, setScreen] = useState<Screen>("chat");
  const [connectionState, setConnectionState] = useState<ConnectionState>("checking");
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [models, setModels] = useState<ModelInfo[]>([]);
  const [settings, setSettings] = useState<AssistantSettings | null>(null);
  const [conversations, setConversations] = useState<ConversationSummary[]>([]);
  const [memories, setMemories] = useState<MemoryRecord[]>([]);
  const [activeConversationId, setActiveConversationId] = useState<string | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [selectedModel, setSelectedModel] = useState("");
  const [conversationPrompt, setConversationPrompt] = useState("");
  const [reasoningMode, setReasoningMode] = useState<ReasoningMode>("fast");
  const [input, setInput] = useState("");
  const [conversationSearch, setConversationSearch] = useState("");
  const [isGenerating, setIsGenerating] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [memoryContextCount, setMemoryContextCount] = useState(0);
  const abortRef = useRef<AbortController | null>(null);

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

  const loadConversation = useCallback(async (id: string) => {
    if (isGenerating) return;
    try {
      const conversation = await getConversation(id);
      setActiveConversationId(conversation.id);
      setMessages(mapMessages(conversation));
      setSelectedModel(conversation.model);
      setConversationPrompt(conversation.system_prompt);
      setMemoryContextCount(0);
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
      const [profile, conversationResponse, memoryResponse] = await Promise.all([
        getSettings(),
        getConversations(),
        getMemories(false),
      ]);
      setSettings(profile);
      setReasoningMode(profile.reasoning_mode);
      setSelectedModel(profile.default_model);
      setConversationPrompt(profile.system_prompt);
      setConversations(conversationResponse.conversations);
      setMemories(memoryResponse.memories);

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
  }, []);

  useEffect(() => { void initialise(); }, [initialise]);

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

  async function submit(event?: FormEvent<HTMLFormElement>) {
    event?.preventDefault();
    const text = input.trim();
    if (!text || isGenerating || connectionState !== "online" || !settings || !selectedModel) return;

    let conversationId: string;
    try {
      conversationId = await ensureConversation();
    } catch (conversationError) {
      setError(conversationError instanceof Error ? conversationError.message : "Could not create conversation.");
      return;
    }

    const user = localMessage("user", text);
    const assistant: ChatMessage = { ...localMessage("assistant", ""), isStreaming: true };
    setMessages((current) => [...current, user, assistant]);
    setInput("");
    setError(null);
    setMemoryContextCount(0);
    setIsGenerating(true);

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
        },
        {
          onContext: (context) => setMemoryContextCount(context.memory_count),
          onToken: (content) => updateAssistant(assistant.id, (message) => ({ ...message, content: message.content + content })),
          onDone: (done: StreamDoneEvent) => updateAssistant(assistant.id, (message) => ({
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
          })),
        },
        controller.signal,
      );
      await refreshConversations();
      const saved = await getConversation(conversationId);
      setMessages(mapMessages(saved));
      setSelectedModel(saved.model);
      setConversationPrompt(saved.system_prompt);

      // Extraction is intentionally asynchronous; refresh once shortly after the main response.
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
      setIsGenerating(false);
    }
  }

  function newChat() {
    if (isGenerating || !settings) return;
    setActiveConversationId(null);
    setMessages([]);
    setInput("");
    setConversationSearch("");
    setSelectedModel(settings.default_model);
    setConversationPrompt(settings.system_prompt);
    setReasoningMode(settings.reasoning_mode);
    setMemoryContextCount(0);
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
  const title = activeConversation?.title ?? "New conversation";

  return (
    <main className="app-shell">
      <Sidebar
        screen={screen}
        assistantName={settings.assistant_name}
        appVersion={health?.app_version ?? "0.3.0"}
        connectionState={connectionState}
        conversations={conversations}
        activeConversationId={activeConversationId}
        isGenerating={isGenerating}
        search={conversationSearch}
        memoryCount={activeMemoryCount}
        onSearchChange={setConversationSearch}
        onScreenChange={setScreen}
        onNewChat={newChat}
        onLoadConversation={(id) => void loadConversation(id)}
        onRenameConversation={(conversation) => void renameConversation(conversation)}
        onDeleteConversation={(conversation) => void removeConversation(conversation)}
      />

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
          onInputChange={setInput}
          onSubmit={(event) => void submit(event)}
          onStop={() => abortRef.current?.abort()}
          onDismissError={() => setError(null)}
          onModelChange={(model) => void changeModel(model)}
          onReasoningChange={setReasoningMode}
        />
      )}

      {screen === "memory" && (
        <MemoryView
          memories={memories}
          enabled={settings.memory_enabled}
          onRefresh={() => void refreshMemories()}
          onCreate={addMemory}
          onUpdate={patchMemory}
          onDelete={removeMemory}
          onOpenSource={openMemorySource}
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
    </main>
  );
}
