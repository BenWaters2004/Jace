import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import type {
  ChangeEvent,
  DragEvent,
  FormEvent,
  KeyboardEvent,
  UIEvent,
} from "react";
import { attachmentContentUrl, getConversation } from "../api";
import type {
  AttachmentRecord,
  ChatMessage,
  ModelInfo,
  PendingAttachment,
  PerformanceDiagnostics,
  ReasoningMode,
  ToolActivity,
} from "../types";
import type { AgentTask } from "../agents/types";
import {
  AGENT_TERMINAL_BROWSER_EVENT,
} from "../agents/useAgentOffice";
import "./ChatView.css";

interface ChatViewProps {
  title: string;
  assistantName: string;
  userName: string;
  messages: ChatMessage[];
  input: string;
  isGenerating: boolean;
  error: string | null;
  online: boolean;
  models: ModelInfo[];
  selectedModel: string;
  reasoningMode: ReasoningMode;
  memoryContextCount: number;
  toolContextCount: number;
  performanceDiagnostics: PerformanceDiagnostics | null;
  toolActivity: ToolActivity[];
  pendingAttachments: PendingAttachment[];
  attachmentLimit: number;
  onFilesAdded: (files: File[]) => void;
  onRemovePendingAttachment: (id: string) => void;
  onInputChange: (value: string) => void;
  onSubmit: (event?: FormEvent<HTMLFormElement>) => void;
  onStop: () => void;
  onDismissError: () => void;
  onModelChange: (model: string) => void;
  onReasoningChange: (mode: ReasoningMode) => void;
}

const BOTTOM_THRESHOLD_PX = 56;

function formatDuration(ms: number | null) {
  if (ms == null) return "—";
  return ms < 1000 ? `${Math.round(ms)} ms` : `${(ms / 1000).toFixed(1)} s`;
}

function formatBytes(bytes: number) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function initial(value: string, fallback: string) {
  return value.trim().charAt(0).toUpperCase() || fallback;
}

function toolStatusText(status: ToolActivity["status"]) {
  switch (status) {
    case "requested":
      return "Requested";
    case "awaiting_approval":
      return "Waiting for approval";
    case "completed":
      return "Completed";
    case "denied":
      return "Denied";
    case "failed":
      return "Failed";
  }
}

function attachmentGlyph(kind: string) {
  if (kind === "image") return "▧";
  if (kind === "pdf") return "PDF";
  if (kind === "audio") return "♪";
  return "≡";
}

function MessageAttachment({ attachment }: { attachment: AttachmentRecord }) {
  const url = attachmentContentUrl(attachment.id);

  if (attachment.media_kind === "image") {
    return (
      <a
        className="message-image-link"
        href={url}
        target="_blank"
        rel="noreferrer"
        title={attachment.original_name}
      >
        <img
          className="message-image"
          src={url}
          alt={attachment.original_name}
          loading="lazy"
        />
        <span>{attachment.original_name}</span>
      </a>
    );
  }

  return (
    <a
      className="message-file-card"
      href={url}
      target="_blank"
      rel="noreferrer"
    >
      <span className={`file-glyph kind-${attachment.media_kind}`}>
        {attachmentGlyph(attachment.media_kind)}
      </span>
      <span className="file-card-copy">
        <strong>{attachment.original_name}</strong>
        <small>
          {attachment.media_kind} · {formatBytes(attachment.size_bytes)}
        </small>
      </span>
    </a>
  );
}


function agentHandoffContent(task: AgentTask): string {
  if (task.status === "completed") {
    return (
      `${task.agent_name} finished the background task “${task.title}”.\n\n` +
      (task.result || "The agent completed but returned no textual result.")
    );
  }

  return (
    `${task.agent_name} failed the background task “${task.title}”.\n\n` +
    (task.error || "No error detail was recorded.")
  );
}

function conversationIdFromMessages(messages: ChatMessage[]): string | null {
  for (let index = messages.length - 1; index >= 0; index -= 1) {
    const id = messages[index].conversation_id;
    if (id) return id;
  }

  return null;
}

function persistedAgentMessages(
  conversation: Awaited<ReturnType<typeof getConversation>>,
): ChatMessage[] {
  return conversation.messages
    .filter(
      (message) =>
        message.role === "assistant" &&
        Boolean(message.model?.startsWith("agent:")),
    )
    .map((message) => ({
      id: message.id,
      conversation_id: message.conversation_id,
      role: message.role,
      content: message.content,
      status: message.status,
      model: message.model,
      created_at: message.created_at,
      stopped: message.status === "stopped",
      attachments: message.attachments,
    }));
}

export function ChatView(props: ChatViewProps) {
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const scrollRef = useRef<HTMLDivElement | null>(null);

  /*
   * True means the user is at/near the newest message and Jace is allowed
   * to keep following streamed output automatically.
   */
  const pinnedToBottomRef = useRef(true);
  const conversationKeyRef = useRef<string | null>(null);

  const [showScrollToBottom, setShowScrollToBottom] = useState(false);
  const [liveAgentHandoffs, setLiveAgentHandoffs] = useState<ChatMessage[]>([]);
  const [persistedHandoffs, setPersistedHandoffs] = useState<ChatMessage[]>([]);

  const currentConversationId = useMemo(
    () => conversationIdFromMessages(props.messages),
    [props.messages],
  );

  const refreshPersistedAgentHandoffs = useCallback(
    async (conversationId: string) => {
      try {
        const conversation = await getConversation(conversationId);
        setPersistedHandoffs(persistedAgentMessages(conversation));
      } catch {
        // The main App still owns authoritative chat error handling. A missed
        // background refresh must never interfere with the composer.
      }
    },
    [],
  );

  useEffect(() => {
    setLiveAgentHandoffs([]);
    setPersistedHandoffs([]);

    if (!currentConversationId || props.isGenerating) return;

    void refreshPersistedAgentHandoffs(currentConversationId);
  }, [
    currentConversationId,
    props.isGenerating,
    refreshPersistedAgentHandoffs,
  ]);

  useEffect(() => {
    const handleTerminalTask = (event: Event) => {
      const task = (event as CustomEvent<AgentTask>).detail;

      if (
        !task ||
        !task.conversation_id ||
        task.conversation_id !== currentConversationId
      ) {
        return;
      }

      const content = agentHandoffContent(task);

      setLiveAgentHandoffs((current) => {
        if (current.some((message) => message.id === `agent-handoff-${task.id}`)) {
          return current;
        }

        return [
          ...current,
          {
            id: `agent-handoff-${task.id}`,
            conversation_id: task.conversation_id ?? undefined,
            role: "assistant",
            content,
            status: "complete",
            model: `agent:${task.agent_id}`,
            created_at: task.completed_at ?? task.updated_at,
          },
        ];
      });

      // The backend persists the same handoff into the real conversation.
      // Refresh shortly afterwards so the local bubble is replaced by the
      // database-backed message automatically.
      window.setTimeout(() => {
        if (task.conversation_id) {
          void refreshPersistedAgentHandoffs(task.conversation_id);
        }
      }, 300);
    };

    window.addEventListener(
      AGENT_TERMINAL_BROWSER_EVENT,
      handleTerminalTask,
    );

    return () => {
      window.removeEventListener(
        AGENT_TERMINAL_BROWSER_EVENT,
        handleTerminalTask,
      );
    };
  }, [currentConversationId, refreshPersistedAgentHandoffs]);

  const displayedMessages = useMemo(() => {
    const output = [...props.messages];
    const seenIds = new Set(output.map((message) => message.id));
    const seenContent = new Set(
      output
        .filter(
          (message) =>
            message.role === "assistant" &&
            Boolean(message.model?.startsWith("agent:")),
        )
        .map((message) => message.content),
    );

    const candidates = [
      ...persistedHandoffs,
      ...liveAgentHandoffs,
    ];

    candidates
      .sort((a, b) =>
        String(a.created_at ?? "").localeCompare(
          String(b.created_at ?? ""),
        ),
      )
      .forEach((message) => {
        if (seenIds.has(message.id) || seenContent.has(message.content)) {
          return;
        }

        output.push(message);
        seenIds.add(message.id);
        seenContent.add(message.content);
      });

    return output;
  }, [liveAgentHandoffs, persistedHandoffs, props.messages]);

  function keyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      props.onSubmit();
    }
  }

  function selectedFiles(event: ChangeEvent<HTMLInputElement>) {
    const files = Array.from(event.target.files ?? []);
    if (files.length) props.onFilesAdded(files);
    event.target.value = "";
  }

  function dropFiles(event: DragEvent<HTMLFormElement>) {
    event.preventDefault();
    if (props.isGenerating || !props.online) return;

    const files = Array.from(event.dataTransfer.files ?? []);
    if (files.length) props.onFilesAdded(files);
  }

  const scrollToBottom = useCallback((behavior: ScrollBehavior = "smooth") => {
    const element = scrollRef.current;
    if (!element) return;

    pinnedToBottomRef.current = true;
    setShowScrollToBottom(false);

    element.scrollTo({
      top: element.scrollHeight,
      behavior,
    });
  }, []);

  function handleChatScroll(event: UIEvent<HTMLDivElement>) {
    const element = event.currentTarget;
    const distanceFromBottom =
      element.scrollHeight - element.scrollTop - element.clientHeight;

    const atBottom = distanceFromBottom <= BOTTOM_THRESHOLD_PX;

    pinnedToBottomRef.current = atBottom;
    setShowScrollToBottom(
      !atBottom && element.scrollHeight > element.clientHeight + 4,
    );
  }

  /*
   * A conversation is considered different when the first persisted
   * conversation id / first message id changes.
   *
   * This lets old chats opened from the drawer start at their newest
   * message even if the user had scrolled up in the previous chat.
   */
  const conversationKey =
    props.messages[0]?.conversation_id ??
    props.messages[0]?.id ??
    "__new_chat__";

  useLayoutEffect(() => {
    const conversationChanged = conversationKeyRef.current !== conversationKey;

    if (conversationChanged) {
      conversationKeyRef.current = conversationKey;
      pinnedToBottomRef.current = true;
    }

    if (!pinnedToBottomRef.current) {
      return;
    }

    /*
     * Wait until React has committed the latest message/token dimensions,
     * then pin the transcript to the newest content.
     */
    const frame = window.requestAnimationFrame(() => {
      scrollToBottom("auto");
    });

    return () => window.cancelAnimationFrame(frame);
  }, [conversationKey, displayedMessages, scrollToBottom]);

  const canSend =
    props.online &&
    !props.isGenerating &&
    Boolean(props.selectedModel) &&
    (Boolean(props.input.trim()) || props.pendingAttachments.length > 0);

  return (
    <section className="content-shell chat-shell">
      <header className="page-header compact-header">
        <div>
          <h1>{props.title}</h1>
          <p>{props.selectedModel || "No model selected"}</p>
        </div>

        <div className="chat-controls">
          {props.memoryContextCount > 0 && (
            <span className="memory-context-badge">
              ◇ {props.memoryContextCount} memories
            </span>
          )}

          {props.toolContextCount > 0 && (
            <span className="tool-context-badge">
              ⌁ {props.toolContextCount} tools
            </span>
          )}

          <select
            value={props.reasoningMode}
            onChange={(event) =>
              props.onReasoningChange(event.target.value as ReasoningMode)
            }
            disabled={props.isGenerating}
          >
            <option value="fast">Fast</option>
            <option value="balanced">Balanced</option>
            <option value="deep">Deep</option>
          </select>

          <select
            value={props.selectedModel}
            onChange={(event) => props.onModelChange(event.target.value)}
            disabled={props.isGenerating}
          >
            {props.models.map((model) => (
              <option key={model.name} value={model.name}>
                {model.name}
              </option>
            ))}
          </select>
        </div>
      </header>

      {props.performanceDiagnostics && (
        <div className="performance-strip">
          <span>
            <strong>Prep</strong>{" "}
            {formatDuration(props.performanceDiagnostics.preprocess_ms)}
          </span>

          <span>
            <strong>Memory</strong>{" "}
            {props.performanceDiagnostics.memory_retrieval_used
              ? `${formatDuration(
                  props.performanceDiagnostics.memory_retrieval_ms,
                )} · ${props.performanceDiagnostics.memory_count} hit${
                  props.performanceDiagnostics.memory_count === 1 ? "" : "s"
                }`
              : "skipped"}
          </span>

          <span>
            <strong>History</strong>{" "}
            {props.performanceDiagnostics.history_messages} msgs
          </span>

          {props.performanceDiagnostics.attachment_count > 0 && (
            <span>
              <strong>Media</strong>{" "}
              {props.performanceDiagnostics.attachment_count} ·{" "}
              {formatDuration(
                props.performanceDiagnostics.attachment_processing_ms,
              )}
            </span>
          )}

          <span>
            <strong>Tools</strong>{" "}
            {props.performanceDiagnostics.tool_names.length
              ? props.performanceDiagnostics.tool_names.join(", ")
              : "none"}
          </span>
        </div>
      )}

      <div className="chat-scroll-shell">
        <div
          ref={scrollRef}
          className="chat-scroll chat-scroll-bottom"
          onScroll={handleChatScroll}
        >
          {displayedMessages.length === 0 ? (
            <div className="welcome-panel">
              <div className="welcome-mark">J</div>
              <h2>How can I help?</h2>
              <p>
                {props.assistantName} can now understand images, PDFs,
                documents and local audio alongside controlled web and
                computer tools.
              </p>

              <div className="prompt-cards">
                <button onClick={() => fileInputRef.current?.click()}>
                  <strong>Inspect a file</strong>
                  <span>Attach an image, PDF, document or audio file</span>
                </button>

                <button
                  onClick={() =>
                    props.onInputChange(
                      "Look at my current screen and help me understand what is happening.",
                    )
                  }
                >
                  <strong>Screen help</strong>
                  <span>Request a permissioned local screenshot</span>
                </button>

                <button
                  onClick={() =>
                    props.onInputChange(
                      "Search the web for the latest developments in local multimodal AI assistants and summarise the best sources.",
                    )
                  }
                >
                  <strong>Web research</strong>
                  <span>
                    Combine current public sources with local reasoning
                  </span>
                </button>
              </div>
            </div>
          ) : (
            <div className="messages chat-messages-bottom">
              {displayedMessages.map((message) => (
                <article
                  key={message.id}
                  className={`message ${message.role} ${
                    message.isStreaming ? "streaming" : ""
                  } ${
                    message.model?.startsWith("agent:")
                      ? "agent-handoff-message"
                      : ""
                  }`}
                >
                  <div className="message-avatar">
                    {message.role === "user"
                      ? initial(props.userName, "U")
                      : initial(props.assistantName, "J")}
                  </div>

                  <div className="message-body">
                    <div className="message-author">
                      {message.role === "user"
                        ? props.userName
                        : message.model?.startsWith("agent:")
                          ? `${props.assistantName} · Agent Handoff`
                          : props.assistantName}
                    </div>

                    {message.attachments &&
                      message.attachments.length > 0 && (
                        <div className="message-attachments">
                          {message.attachments.map((attachment) => (
                            <MessageAttachment
                              key={attachment.id}
                              attachment={attachment}
                            />
                          ))}
                        </div>
                      )}

                    <div className="message-content">
                      {message.content ||
                        (message.stopped ? "Generation stopped." : "")}
                    </div>

                    {message.stopped && (
                      <div className="generation-stats">
                        <span className="stopped">■ Stopped</span>
                      </div>
                    )}

                    {message.stats && (
                      <div className="generation-stats">
                        {message.stats.tokensPerSecond != null && (
                          <span>
                            {message.stats.tokensPerSecond.toFixed(1)} tok/s
                          </span>
                        )}

                        {message.stats.timeToFirstTokenMs != null && (
                          <span>
                            First token{" "}
                            {formatDuration(message.stats.timeToFirstTokenMs)}
                          </span>
                        )}

                        {message.stats.evalCount != null && (
                          <span>{message.stats.evalCount} output tokens</span>
                        )}

                        {message.stats.promptEvalCount != null && (
                          <span>
                            {message.stats.promptEvalCount} prompt tokens
                          </span>
                        )}

                        {message.stats.totalDurationMs != null && (
                          <span>
                            Model{" "}
                            {formatDuration(message.stats.totalDurationMs)}
                          </span>
                        )}
                      </div>
                    )}
                  </div>
                </article>
              ))}
            </div>
          )}
        </div>

        {showScrollToBottom && (
          <button
            type="button"
            className="chat-scroll-to-bottom"
            onClick={() => scrollToBottom("smooth")}
            title="Jump to latest message"
            aria-label="Jump to latest message"
          >
            ↓
          </button>
        )}
      </div>

      <div className="composer-wrap">
        {props.toolActivity.length > 0 && (
          <div className="tool-activity-strip">
            {props.toolActivity.map((activity) => (
              <div
                className={`tool-activity-item ${activity.status}`}
                key={activity.callId}
              >
                <span className="tool-activity-icon">⌁</span>

                <div>
                  <strong>{activity.label}</strong>
                  <span>{activity.summary || toolStatusText(activity.status)}</span>
                </div>
              </div>
            ))}
          </div>
        )}

        {props.error && (
          <div className="error-banner">
            <div>
              <strong>Jace encountered a problem</strong>
              <span>{props.error}</span>
            </div>
            <button onClick={props.onDismissError}>×</button>
          </div>
        )}

        {props.pendingAttachments.length > 0 && (
          <div className="pending-attachments">
            {props.pendingAttachments.map((attachment) => (
              <div className="pending-attachment" key={attachment.id}>
                {attachment.previewUrl ? (
                  <img src={attachment.previewUrl} alt="" />
                ) : (
                  <span className="pending-file-glyph">
                    {attachmentGlyph(
                      attachment.file.type.startsWith("audio/")
                        ? "audio"
                        : attachment.file.name.toLowerCase().endsWith(".pdf")
                          ? "pdf"
                          : "document",
                    )}
                  </span>
                )}

                <div>
                  <strong>{attachment.file.name}</strong>
                  <small>{formatBytes(attachment.file.size)}</small>
                </div>

                <button
                  type="button"
                  onClick={() =>
                    props.onRemovePendingAttachment(attachment.id)
                  }
                  title="Remove attachment"
                >
                  ×
                </button>
              </div>
            ))}
          </div>
        )}

        <form
          className="composer multimodal-composer"
          onSubmit={props.onSubmit}
          onDragOver={(event) => event.preventDefault()}
          onDrop={dropFiles}
        >
          <input
            ref={fileInputRef}
            className="attachment-input"
            type="file"
            multiple
            accept="image/*,.pdf,.txt,.md,.csv,.json,.xml,.html,.log,.ini,.cfg,.yaml,.yml,.toml,.py,.php,.js,.jsx,.ts,.tsx,.css,.sql,.docx,audio/*,.mp3,.m4a,.wav,.flac,.ogg,.webm"
            onChange={selectedFiles}
            disabled={
              !props.online ||
              props.isGenerating ||
              props.pendingAttachments.length >= props.attachmentLimit
            }
          />

          <button
            type="button"
            className="attach-button"
            onClick={() => fileInputRef.current?.click()}
            disabled={
              !props.online ||
              props.isGenerating ||
              props.pendingAttachments.length >= props.attachmentLimit
            }
            title="Attach image, PDF, document or audio"
          >
            +
          </button>

          <textarea
            value={props.input}
            onChange={(event) => props.onInputChange(event.target.value)}
            onKeyDown={keyDown}
            placeholder={
              !props.online
                ? "Waiting for Jace..."
                : props.isGenerating
                  ? `${props.assistantName} is working...`
                  : `Message ${props.assistantName} or attach a file...`
            }
            disabled={!props.online || props.isGenerating}
            rows={1}
          />

          {props.isGenerating ? (
            <button
              type="button"
              className="stop-button"
              onClick={props.onStop}
              title="Stop generation"
            >
              <span />
            </button>
          ) : (
            <button className="send-button" type="submit" disabled={!canSend}>
              ↑
            </button>
          )}
        </form>

        <div className="composer-hint">
          Enter to send · Shift + Enter for a new line · Drag files here · Up
          to {props.attachmentLimit} attachments
        </div>
      </div>
    </section>
  );
}
