import type { ConversationSummary, Screen } from "../types";

interface SidebarProps {
  screen: Screen;
  assistantName: string;
  appVersion: string;
  connectionState: "checking" | "online" | "backend-offline" | "ollama-offline";
  conversations: ConversationSummary[];
  activeConversationId: string | null;
  isGenerating: boolean;
  search: string;
  memoryCount: number;
  toolCount: number;
  onSearchChange: (value: string) => void;
  onScreenChange: (screen: Screen) => void;
  onNewChat: () => void;
  onLoadConversation: (id: string) => void;
  onRenameConversation: (conversation: ConversationSummary) => void;
  onDeleteConversation: (conversation: ConversationSummary) => void;
}

function dateLabel(value: string) {
  const date = new Date(value);
  const today = new Date();
  if (date.toDateString() === today.toDateString()) {
    return date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  }
  return date.toLocaleDateString([], { day: "2-digit", month: "short" });
}

export function Sidebar(props: SidebarProps) {
  const query = props.search.trim().toLowerCase();
  const filtered = props.conversations.filter((conversation) =>
    conversation.title.toLowerCase().includes(query),
  );

  return (
    <aside className="sidebar">
      <div className="brand">
        <div className="brand-mark">J</div>
        <div className="brand-copy">
          <strong>{props.assistantName}</strong>
          <span>v{props.appVersion || "0.5.0"}</span>
        </div>
      </div>

      <button className="primary-sidebar-button" onClick={props.onNewChat} disabled={props.isGenerating}>
        <span>＋</span> New chat
      </button>

      <nav className="main-nav" aria-label="Jace navigation">
        <button className={props.screen === "chat" ? "active" : ""} onClick={() => props.onScreenChange("chat")}>
          <span className="nav-icon">◫</span> Chat
        </button>
        <button className={props.screen === "memory" ? "active" : ""} onClick={() => props.onScreenChange("memory")}>
          <span className="nav-icon">◇</span> Memory
          <span className="nav-count">{props.memoryCount}</span>
        </button>
        <button className={props.screen === "tools" ? "active" : ""} onClick={() => props.onScreenChange("tools")}>
          <span className="nav-icon">⌁</span> Tools
          <span className="nav-count">{props.toolCount}</span>
        </button>
        <button className={props.screen === "settings" ? "active" : ""} onClick={() => props.onScreenChange("settings")}>
          <span className="nav-icon">⚙</span> Settings
        </button>
      </nav>

      <div className="sidebar-divider" />

      <div className="conversation-heading">
        <span>Conversations</span>
        <span>{props.conversations.length}</span>
      </div>
      <input
        className="sidebar-search"
        value={props.search}
        onChange={(event) => props.onSearchChange(event.target.value)}
        placeholder="Search conversations..."
      />

      <div className="conversation-list">
        {filtered.length === 0 ? (
          <div className="sidebar-empty">No conversations found.</div>
        ) : (
          filtered.map((conversation) => (
            <div
              key={conversation.id}
              className={`conversation-row ${props.activeConversationId === conversation.id ? "active" : ""}`}
            >
              <button
                className="conversation-select"
                onClick={() => props.onLoadConversation(conversation.id)}
                disabled={props.isGenerating}
              >
                <span className="conversation-title">{conversation.title}</span>
                <span className="conversation-meta">
                  {conversation.message_count} messages · {dateLabel(conversation.updated_at)}
                </span>
              </button>
              <div className="conversation-actions">
                <button title="Rename" onClick={() => props.onRenameConversation(conversation)}>✎</button>
                <button title="Delete" onClick={() => props.onDeleteConversation(conversation)}>×</button>
              </div>
            </div>
          ))
        )}
      </div>

      <div className="sidebar-status">
        <span className={`status-dot ${props.connectionState}`} />
        <div>
          <strong>
            {props.connectionState === "online"
              ? "Local AI online"
              : props.connectionState === "checking"
                ? "Connecting"
                : "Jace unavailable"}
          </strong>
          <span>Private · local-first</span>
        </div>
      </div>
    </aside>
  );
}
