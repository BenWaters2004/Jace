import type { FormEvent, KeyboardEvent } from "react";
import type { ChatMessage, ModelInfo, ReasoningMode } from "../types";

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

      <div className="chat-scroll">
        {props.messages.length === 0 ? (
          <div className="welcome-panel">
            <div className="welcome-mark">J</div>
            <h2>How can I help?</h2>
            <p>{props.assistantName} is running locally with persistent conversations and long-term memory.</p>
            <div className="prompt-cards">
              <button onClick={() => props.onInputChange("What do you remember about my current projects?")}>
                <strong>Memory</strong><span>Review relevant long-term context</span>
              </button>
              <button onClick={() => props.onInputChange("Help me plan the next stage of Project Jace.")}>
                <strong>Plan</strong><span>Work through a project decision</span>
              </button>
              <button onClick={() => props.onInputChange("Explain your current capabilities and limitations.")}>
                <strong>Capabilities</strong><span>See what Jace can currently do</span>
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
            placeholder={!props.online ? "Waiting for Jace..." : props.isGenerating ? `${props.assistantName} is responding...` : `Message ${props.assistantName}...`}
            disabled={!props.online || props.isGenerating}
            rows={1}
          />
          {props.isGenerating ? (
            <button type="button" className="stop-button" onClick={props.onStop} title="Stop generation"><span /></button>
          ) : (
            <button className="send-button" type="submit" disabled={!props.online || !props.input.trim() || !props.selectedModel}>↑</button>
          )}
        </form>
        <div className="composer-hint">Enter to send · Shift + Enter for a new line · Memory can be managed from the Memory screen</div>
      </div>
    </section>
  );
}
