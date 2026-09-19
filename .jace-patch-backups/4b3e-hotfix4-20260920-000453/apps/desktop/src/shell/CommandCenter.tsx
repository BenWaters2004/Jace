import {
  useLayoutEffect,
  useRef,
  useState,
  type ReactNode,
} from "react";
import type {
  AutomationNotificationRecord,
  AutomationRecord,
  ConversationSummary,
  PendingToolApproval,
  Screen,
  ToolActivity,
  VoicePhase,
} from "../types";
import type { JaceRuntimeState } from "./runtime";
import { JaceCore } from "./JaceCore";
import { AgentOffice } from "./AgentOffice";
import { AttentionPanel } from "./AttentionPanel";
import { PanelControls } from "./PanelControls";
import { usePanelManager, type JacePanelId } from "./usePanelManager";
import { useDesktopWindowMode } from "./desktopWindowMode";
import { WindowChromeControls } from "./WindowChromeControls";
import { WindowResizeHandles } from "./WindowResizeHandles";

// JACE_PHASE3G_WORKSPACE_CONSOLIDATION
const TABS: Array<{ screen: Screen; label: string }> = [
  { screen: "chat", label: "Chat" },
  { screen: "calendar", label: "Calendar" },
  { screen: "computer", label: "Computer" },
  { screen: "automations", label: "Automations" },
  { screen: "memory", label: "Memory" },
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
  onOpenSettings: () => void;
  onNewChat: () => void;
  onLoadConversation: (id: string) => void;
  onDeleteConversation: (conversation: ConversationSummary) => void;
  onOpenApproval: () => void;
  onEmergencyStop: () => void;
}) {
  const [drawerOpen, setDrawerOpen] = useState(false);
  // JACE_DESKTOP_WINDOWS_PHASE_2A
  // JACE_DESKTOP_WINDOWS_PHASE_2B
  // JACE_SETTINGS_FULLPAGE_V2
  // JACE_PHASE2E_STABILITY_POLISH
  const panels = usePanelManager();
  // JACE_DESKTOP_WINDOWS_PHASE_2C
  const desktopWindow = useDesktopWindowMode();
  const restoreLabels: Record<JacePanelId, string> = {
    core: "Core",
    office: "Office",
    workspace: "Workspace",
  };

  /*
   * Jace should always open ready for a new conversation rather than
   * reopening yesterday's/latest transcript.
   *
   * App.tsx keeps previous conversations in the drawer. onNewChat only
   * clears the active UI state; the backend does not create an empty
   * conversation until the user actually sends something.
   *
   * useLayoutEffect avoids a visible one-frame flash of the most recently
   * loaded conversation during application startup.
   */
  const startedFreshChatRef = useRef(false);

  useLayoutEffect(() => {
    if (startedFreshChatRef.current) return;

    startedFreshChatRef.current = true;
    props.onNewChat();
  }, [props.onNewChat]);

  const shellClassName = [
    "command-center-shell",
    `window-mode-${desktopWindow.mode}`,
    panels.focused ? `focus-${panels.focused}` : "focus-none",
    ...panels.minimized.map((panel) => `min-${panel}`),
    panels.fullscreenPanel ? "panel-fullscreen-active" : "",
    panels.fullscreenPanel ? `panel-fullscreen-${panels.fullscreenPanel}` : "",
  ].filter(Boolean).join(" ");

  return (
    <main className={shellClassName}>
      <header className="command-topbar">
        <div className="command-brand">
          <span className="command-mark">J</span>
          <div>
            <strong>{props.assistantName}</strong>
            <small>COMMAND CENTER · v{props.appVersion}</small>
          </div>
        </div>


        {desktopWindow.isFrameless && (
          <div
            className="command-window-drag-zone"
            onMouseDown={desktopWindow.handleDragMouseDown}
            title="Drag Jace window · double-click to maximize"
          />
        )}
        <div className="command-actions">
          {panels.minimized.length > 0 && (
            <div className="panel-restore-strip" aria-label="Restore minimized panels">
              {panels.minimized.map((panel) => (
                <button type="button" key={panel} className="panel-restore-button"
                  onClick={() => panels.restore(panel)} title={`Restore ${restoreLabels[panel]}`}>
                  + {restoreLabels[panel]}
                </button>
              ))}
            </div>
          )}
          {panels.detached.length > 0 && (
            <div className="panel-restore-strip detached" aria-label="Detached panels">
              {panels.detached.map((panel) => (
                <button
                  type="button"
                  key={`detached-${panel}`}
                  className="panel-restore-button detached"
                  onClick={() => void panels.focusDetached(panel)}
                  title={`Bring detached ${restoreLabels[panel]} to front`}
                >
                  ↗ {restoreLabels[panel]}
                </button>
              ))}
            </div>
          )}
          <button onClick={() => setDrawerOpen((open) => !open)}>Chats</button>
          <button
            type="button"
            onClick={props.onOpenSettings}
            title="Open Settings"
            aria-label="Open Settings"
          >
            ⚙
          </button>
                  {desktopWindow.isFrameless && (
            <WindowChromeControls />
          )}
</div>
      </header>

      <div className="command-grid">
        <AttentionPanel
          online={props.online}
          memoryCount={props.memoryCount}
          activeAutomations={props.automations.filter((item) => item.enabled)}
          notifications={props.notifications}
          pendingApproval={props.pendingApproval}
          onOpenTasks={() => props.onScreenChange("automations")}
          onOpenApproval={props.onOpenApproval}
        />

        <div className="command-center-column">
          {/* JACE_4B3E_HOTFIX3_CORE_BLOCK_REPAIR */}
          {!panels.isHidden("core") && (
            <JaceCore
              name={props.assistantName}
              state={props.state}
              model={props.model}
              runtimeConnected={props.runtimeConnected}
              amplitude={props.voiceAmplitude}
              onExpand={() => panels.toggleMaximized("core")}
              controls={<PanelControls panel="core" manager={panels} />}
            />
          )}
          {!panels.isHidden("office") && (
            <AgentOffice
                        activities={props.toolActivity}
                        onExpand={() => panels.toggleMaximized("office")}
                        controls={<PanelControls panel="office" manager={panels} />}
            />
          )}
        </div>

        {!panels.isHidden("workspace") && (
        <section className="workspace-column cc-panel">
          <div className="workspace-tabs-row">
            <div className="workspace-tabs-scroll">
              {TABS.map((tab) => (
                <button
                  key={tab.screen}
                  className={props.screen === tab.screen ? "active" : ""}
                  onClick={() => props.onScreenChange(tab.screen)}
                >
                  {tab.label}
                </button>
              ))}
            </div>

            <PanelControls
              panel="workspace"
              manager={panels}
              detachContext={{
                screen: props.screen,
                conversationId: props.activeConversationId,
              }}
            />
          </div>

          <div className="workspace-host">{props.workspace}</div>
        </section>
        )}
      </div>

      <footer className="command-footer">
        <button
          className={`voice-placeholder voice-live voice-${props.voicePhase}`}
          disabled={
            !props.voiceReady || props.voicePhase === "transcribing"
          }
          title={
            props.voiceReady
              ? "Hold while speaking. Release to send. Press while Jace is speaking to interrupt."
              : "Local voice runtime is not ready."
          }
          onPointerDown={(event) => {
            if (!props.voiceReady || props.voicePhase === "transcribing") {
              return;
            }

            event.currentTarget.setPointerCapture(event.pointerId);
            void props.onVoiceStart();
          }}
          onPointerUp={(event) => {
            if (event.currentTarget.hasPointerCapture(event.pointerId)) {
              event.currentTarget.releasePointerCapture(event.pointerId);
            }

            if (props.voicePhase === "listening") {
              void props.onVoiceStop();
            }
          }}
          onPointerCancel={() => {
            if (props.voicePhase === "listening") {
              void props.onVoiceStop();
            }
          }}
          onKeyDown={(event) => {
            if (
              (event.key === " " || event.key === "Enter") &&
              !event.repeat &&
              props.voiceReady &&
              props.voicePhase !== "transcribing"
            ) {
              event.preventDefault();
              void props.onVoiceStart();
            }
          }}
          onKeyUp={(event) => {
            if (
              (event.key === " " || event.key === "Enter") &&
              props.voicePhase === "listening"
            ) {
              event.preventDefault();
              void props.onVoiceStop();
            }
          }}
        >
          <span>🎙</span>

          {props.voicePhase === "listening" && (
            <>
              LISTENING <small>RELEASE TO SEND</small>
            </>
          )}

          {props.voicePhase === "transcribing" && (
            <>
              TRANSCRIBING <small>LOCAL WHISPER</small>
            </>
          )}

          {props.voicePhase === "speaking" && (
            <>
              SPEAKING <small>HOLD TO INTERRUPT</small>
            </>
          )}

          {(props.voicePhase === "idle" || props.voicePhase === "error") && (
            <>
              HOLD TO TALK <small>{props.voiceReady ? "LOCAL" : "SETUP"}</small>
            </>
          )}
        </button>

        <div className="footer-state">
          <span className={`state-led state-${props.state}`} />
          <span>
            {props.state === "idle"
              ? "Ready when you are."
              : props.state.replace(/_/g, " ")}
          </span>

          {props.voiceLastTranscript && (
            <small className="footer-transcript">
              Heard: {props.voiceLastTranscript}
            </small>
          )}
        </div>

        <div className="footer-private">● Local / Private</div>
      </footer>

      {drawerOpen && (
        <aside className="conversation-drawer">
          <div className="drawer-head">
            <div>
              <span className="cc-kicker">Conversations</span>
              <h2>Recent chats</h2>
            </div>
            <button onClick={() => setDrawerOpen(false)}>×</button>
          </div>

          <button
            className="drawer-new"
            onClick={() => {
              props.onNewChat();
              setDrawerOpen(false);
            }}
          >
            ＋ New chat
          </button>

          <div className="drawer-list">
            {/* JACE_UI_CHAT_POLISH_2026_09_19 */}
            {props.conversations.map((conversation) => (
              <div
                key={conversation.id}
                className={`drawer-conversation-row ${
                  conversation.id === props.activeConversationId ? "active" : ""
                }`}
              >
                <button
                  type="button"
                  className="drawer-conversation-select"
                  onClick={() => {
                    props.onLoadConversation(conversation.id);
                    setDrawerOpen(false);
                  }}
                  title={conversation.title}
                >
                  <strong>{conversation.title}</strong>
                  <small>{conversation.message_count} messages</small>
                </button>

                <button
                  type="button"
                  className="drawer-conversation-delete"
                  onClick={(event) => {
                    event.stopPropagation();
                    props.onDeleteConversation(conversation);
                  }}
                  title={`Delete "${conversation.title}"`}
                  aria-label={`Delete conversation ${conversation.title}`}
                >
                  <svg
                    viewBox="0 0 20 20"
                    aria-hidden="true"
                    focusable="false"
                  >
                    <path d="M6.5 6.5v8M10 6.5v8M13.5 6.5v8" />
                    <path d="M4.5 4.5h11M8 4.5V3h4v1.5M5.5 4.5l.7 12h7.6l.7-12" />
                  </svg>
                </button>
              </div>
            ))}
          </div>
        </aside>
      )}

      {props.controlActive && (
        <button
          className="global-control-stop command-stop"
          onClick={props.onEmergencyStop}
        >
          ■ STOP CONTROL
        </button>
      )}
      <WindowResizeHandles
        enabled={
          desktopWindow.isFrameless &&
          !panels.fullscreenPanel
        }
      />
    </main>
  );
}
