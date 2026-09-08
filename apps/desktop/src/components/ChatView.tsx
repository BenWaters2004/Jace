import type { FormEvent, KeyboardEvent } from "react";
import type { ChatMessage, ModelInfo, PerformanceDiagnostics, ReasoningMode, ToolActivity } from "../types";

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
  onInputChange: (value: string) => void;
  onSubmit: (event?: FormEvent<HTMLFormElement>) => void;
  onStop: () => void;
  onDismissError: () => void;
  onModelChange: (model: string) => void;
  onReasoningChange: (mode: ReasoningMode) => void;
}

function formatDuration(ms: number | null) {
  if (ms == null) return "—";
  return ms < 1000 ? `${Math.round(ms)} ms` : `${(ms / 1000).toFixed(1)} s`;
}

function initial(value: string, fallback: string) {
  return value.trim().charAt(0).toUpperCase() || fallback;
}

function toolStatusText(status: ToolActivity["status"]) {
  switch (status) {
    case "requested": return "Requested";
    case "awaiting_approval": return "Waiting for approval";
    case "completed": return "Completed";
    case "denied": return "Denied";
    case "failed": return "Failed";
  }
}

export function ChatView(props: ChatViewProps) {
  function keyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      props.onSubmit();
    }
  }

  return (
    <section className="content-shell chat-shell">
      <header className="page-header compact-header">
        <div>
          <h1>{props.title}</h1>
          <p>{props.selectedModel || "No model selected"}</p>
        </div>
        <div className="chat-controls">
          {props.memoryContextCount > 0 && <span className="memory-context-badge">◇ {props.memoryContextCount} memories</span>}
          {props.toolContextCount > 0 && <span className="tool-context-badge">⌁ {props.toolContextCount} tools</span>}
          <select value={props.reasoningMode} onChange={(event) => props.onReasoningChange(event.target.value as ReasoningMode)} disabled={props.isGenerating}>
            <option value="fast">Fast</option>
            <option value="balanced">Balanced</option>
            <option value="deep">Deep</option>
          </select>
          <select value={props.selectedModel} onChange={(event) => props.onModelChange(event.target.value)} disabled={props.isGenerating}>
            {props.models.map((model) => <option key={model.name} value={model.name}>{model.name}</option>)}
          </select>
        </div>
      </header>

      {props.performanceDiagnostics && (
        <div className="performance-strip">
          <span><strong>Prep</strong> {formatDuration(props.performanceDiagnostics.preprocess_ms)}</span>
          <span>
            <strong>Memory</strong> {props.performanceDiagnostics.memory_retrieval_used
              ? `${formatDuration(props.performanceDiagnostics.memory_retrieval_ms)} · ${props.performanceDiagnostics.memory_count} hit${props.performanceDiagnostics.memory_count === 1 ? "" : "s"}`
              : "skipped"}
          </span>
          <span><strong>History</strong> {props.performanceDiagnostics.history_messages} msgs</span>
          <span>
            <strong>Tools</strong> {props.performanceDiagnostics.tool_names.length
              ? props.performanceDiagnostics.tool_names.join(", ")
              : "none"}
          </span>
        </div>
      )}

      <div className="chat-scroll">
        {props.messages.length === 0 ? (
          <div className="welcome-panel">
            <div className="welcome-mark">J</div>
            <h2>How can I help?</h2>
            <p>{props.assistantName} can use controlled local tools and read the public web while keeping you in charge of permissions.</p>
            <div className="prompt-cards">
              <button onClick={() => props.onInputChange("Search the web for the latest developments in local AI assistants and summarise the most relevant sources.")}>
                <strong>Web research</strong><span>Search and read current public sources</span>
              </button>
              <button onClick={() => props.onInputChange("Search my past conversations for Project Jace and summarise what you find.")}>
                <strong>History</strong><span>Search stored conversation history</span>
              </button>
              <button onClick={() => props.onInputChange("Read https://playwright.dev/python/ and tell me what Playwright is used for.")}>
                <strong>Read a page</strong><span>Fetch a specific public webpage safely</span>
              </button>
            </div>
          </div>
        ) : (
          <div className="messages">
            {props.messages.map((message) => (
              <article key={message.id} className={`message ${message.role} ${message.isStreaming ? "streaming" : ""}`}>
                <div className="message-avatar">{message.role === "user" ? initial(props.userName, "U") : initial(props.assistantName, "J")}</div>
                <div className="message-body">
                  <div className="message-author">{message.role === "user" ? props.userName : props.assistantName}</div>
                  <div className="message-content">{message.content || (message.stopped ? "Generation stopped." : "")}</div>
                  {message.stopped && <div className="generation-stats"><span className="stopped">■ Stopped</span></div>}
                  {message.stats && (
                    <div className="generation-stats">
                      {message.stats.tokensPerSecond != null && <span>{message.stats.tokensPerSecond.toFixed(1)} tok/s</span>}
                      {message.stats.timeToFirstTokenMs != null && <span>First token {formatDuration(message.stats.timeToFirstTokenMs)}</span>}
                      {message.stats.evalCount != null && <span>{message.stats.evalCount} output tokens</span>}
                      {message.stats.promptEvalCount != null && <span>{message.stats.promptEvalCount} prompt tokens</span>}
                      {message.stats.totalDurationMs != null && <span>Model {formatDuration(message.stats.totalDurationMs)}</span>}
                    </div>
                  )}
                </div>
              </article>
            ))}
          </div>
        )}
      </div>

      <div className="composer-wrap">
        {props.toolActivity.length > 0 && (
          <div className="tool-activity-strip">
            {props.toolActivity.map((activity) => (
              <div className={`tool-activity-item ${activity.status}`} key={activity.callId}>
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
            <div><strong>Jace encountered a problem</strong><span>{props.error}</span></div>
            <button onClick={props.onDismissError}>×</button>
          </div>
        )}

        <form className="composer" onSubmit={props.onSubmit}>
          <textarea
            value={props.input}
            onChange={(event) => props.onInputChange(event.target.value)}
            onKeyDown={keyDown}
            placeholder={!props.online ? "Waiting for Jace..." : props.isGenerating ? `${props.assistantName} is working...` : `Message ${props.assistantName}...`}
            disabled={!props.online || props.isGenerating}
            rows={1}
          />
          {props.isGenerating ? (
            <button type="button" className="stop-button" onClick={props.onStop} title="Stop generation"><span /></button>
          ) : (
            <button className="send-button" type="submit" disabled={!props.online || !props.input.trim() || !props.selectedModel}>↑</button>
          )}
        </form>
        <div className="composer-hint">Enter to send · Shift + Enter for a new line · Internet tools use the same Allow / Ask / Deny policy as local tools</div>
      </div>
    </section>
  );
}
