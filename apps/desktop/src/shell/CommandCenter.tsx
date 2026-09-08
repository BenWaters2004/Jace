import { useState, type ReactNode } from "react";
import type { ConversationSummary, Screen, VoicePhase } from "../types";
import type { JaceRuntimeState } from "./runtime";
import { JaceCore } from "./JaceCore";
import { AgentOffice } from "./AgentOffice";
import { AttentionPanel } from "./AttentionPanel";
import type { AutomationNotificationRecord, AutomationRecord, PendingToolApproval, ToolActivity } from "../types";

const TABS: Array<{ screen: Screen; label: string }> = [
  { screen: "chat", label: "Chat" },
  { screen: "output", label: "Output" },
  { screen: "computer", label: "Files" },
  { screen: "web", label: "Web" },
  { screen: "automations", label: "Tasks" },
  { screen: "memory", label: "Memory" },
  { screen: "control", label: "Control" },
  { screen: "tools", label: "Tools" },
  { screen: "settings", label: "Settings" },
];

export function CommandCenter(props: {
  assistantName: string;
  appVersion: string;
  model: string;
  state: JaceRuntimeState;
  runtimeConnected: boolean;
  screen: Screen;
  workspace: ReactNode;
  conversations: ConversationSummary[];
  activeConversationId: string | null;
  toolActivity: ToolActivity[];
  pendingApproval: PendingToolApproval | null;
  memoryCount: number;
  automations: AutomationRecord[];
  notifications: AutomationNotificationRecord[];
  online: boolean;
  controlActive: boolean;
  voicePhase: VoicePhase;
  voiceAmplitude: number;
  voiceReady: boolean;
  voiceLastTranscript: string;
  onVoiceStart: () => void | Promise<void>;
  onVoiceStop: () => void | Promise<void>;
  onScreenChange: (screen: Screen) => void;
  onNewChat: () => void;
  onLoadConversation: (id: string) => void;
  onOpenApproval: () => void;
  onEmergencyStop: () => void;
}) {
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [focus, setFocus] = useState<"none" | "core" | "office" | "workspace">("none");

  return (
    <main className={`command-center-shell focus-${focus}`}>
      <header className="command-topbar">
        <div className="command-brand"><span className="command-mark">J</span><div><strong>{props.assistantName}</strong><small>COMMAND CENTER · v{props.appVersion}</small></div></div>
        <div className="command-statuses">
          <span className={`status-chip ${props.online ? "online" : "offline"}`}>● {props.online ? "LOCAL" : "OFFLINE"}</span>
          <span className="status-chip">{props.model || "No model"}</span>
          <span className="status-chip private">◆ PRIVATE</span>
        </div>
        <div className="command-actions">
          <button onClick={() => setDrawerOpen((open) => !open)}>Chats</button>
          <button onClick={() => props.onScreenChange("settings")}>⚙</button>
        </div>
      </header>

      <div className="command-grid">
        <AttentionPanel
          online={props.online}
          memoryCount={props.memoryCount}
          activeAutomations={props.automations.filter((item) => item.enabled)}
          notifications={props.notifications}
          pendingApproval={props.pendingApproval}
          activities={props.toolActivity}
          onOpenTasks={() => props.onScreenChange("automations")}
          onOpenApproval={props.onOpenApproval}
        />

        <div className="command-center-column">
          <JaceCore name={props.assistantName} state={props.state} model={props.model} runtimeConnected={props.runtimeConnected} amplitude={props.voiceAmplitude} onExpand={() => setFocus(focus === "core" ? "none" : "core")} />
          <AgentOffice activities={props.toolActivity} onExpand={() => setFocus(focus === "office" ? "none" : "office")} />
        </div>

        <section className="workspace-column cc-panel">
          <div className="workspace-tabs-row">
            <div className="workspace-tabs-scroll">
              {TABS.map((tab) => <button key={tab.screen} className={props.screen === tab.screen ? "active" : ""} onClick={() => props.onScreenChange(tab.screen)}>{tab.label}</button>)}
            </div>
            <button className="cc-icon-button" onClick={() => setFocus(focus === "workspace" ? "none" : "workspace")}>□</button>
          </div>
          <div className="workspace-host">{props.workspace}</div>
        </section>
      </div>

      <footer className="command-footer">
        <button
          className={`voice-placeholder voice-live voice-${props.voicePhase}`}
          disabled={!props.voiceReady || props.voicePhase === "transcribing"}
          title={props.voiceReady ? "Hold while speaking. Release to send. Press while Jace is speaking to interrupt." : "Local voice runtime is not ready."}
          onPointerDown={(event) => {
            if (!props.voiceReady || props.voicePhase === "transcribing") return;
            event.currentTarget.setPointerCapture(event.pointerId);
            void props.onVoiceStart();
          }}
          onPointerUp={(event) => {
            if (event.currentTarget.hasPointerCapture(event.pointerId)) event.currentTarget.releasePointerCapture(event.pointerId);
            if (props.voicePhase === "listening") void props.onVoiceStop();
          }}
          onPointerCancel={() => { if (props.voicePhase === "listening") void props.onVoiceStop(); }}
          onKeyDown={(event) => {
            if ((event.key === " " || event.key === "Enter") && !event.repeat && props.voiceReady && props.voicePhase !== "transcribing") {
              event.preventDefault();
              void props.onVoiceStart();
            }
          }}
          onKeyUp={(event) => {
            if ((event.key === " " || event.key === "Enter") && props.voicePhase === "listening") {
              event.preventDefault();
              void props.onVoiceStop();
            }
          }}
        >
          <span>🎙</span>
          {props.voicePhase === "listening" && <>LISTENING <small>RELEASE TO SEND</small></>}
          {props.voicePhase === "transcribing" && <>TRANSCRIBING <small>LOCAL WHISPER</small></>}
          {props.voicePhase === "speaking" && <>SPEAKING <small>HOLD TO INTERRUPT</small></>}
          {(props.voicePhase === "idle" || props.voicePhase === "error") && <>HOLD TO TALK <small>{props.voiceReady ? "LOCAL" : "SETUP"}</small></>}
        </button>
        <div className="footer-state">
          <span className={`state-led state-${props.state}`} />
          <span>{props.state === "idle" ? "Ready when you are." : props.state.replace(/_/g, " ")}</span>
          {props.voiceLastTranscript && <small className="footer-transcript">Heard: {props.voiceLastTranscript}</small>}
        </div>
        <div className="footer-private">● Local / Private</div>
      </footer>

      {drawerOpen && (
        <aside className="conversation-drawer">
          <div className="drawer-head"><div><span className="cc-kicker">Conversations</span><h2>Recent chats</h2></div><button onClick={() => setDrawerOpen(false)}>×</button></div>
          <button className="drawer-new" onClick={() => { props.onNewChat(); setDrawerOpen(false); }}>＋ New chat</button>
          <div className="drawer-list">
            {props.conversations.map((conversation) => (
              <button key={conversation.id} className={conversation.id === props.activeConversationId ? "active" : ""} onClick={() => { props.onLoadConversation(conversation.id); setDrawerOpen(false); }}>
                <strong>{conversation.title}</strong><small>{conversation.message_count} messages</small>
              </button>
            ))}
          </div>
        </aside>
      )}

      {props.controlActive && <button className="global-control-stop command-stop" onClick={props.onEmergencyStop}>■ STOP CONTROL</button>}
    </main>
  );
}
