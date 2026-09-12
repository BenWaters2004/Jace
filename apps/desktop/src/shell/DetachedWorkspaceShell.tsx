import type { ReactNode } from "react";
import type { Screen } from "../types";
import { DetachedWindowFrame } from "./DetachedWindowFrame";
import { DETACHED_WORKSPACE_SCREEN_KEY } from "./windowEntry";

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

export function DetachedWorkspaceShell(props: {
  screen: Screen;
  onScreenChange: (screen: Screen) => void;
  children: ReactNode;
}) {
  const changeScreen = (screen: Screen) => {
    try {
      window.localStorage.setItem(DETACHED_WORKSPACE_SCREEN_KEY, screen);
    } catch {
      // Cross-window screen sync is convenience only.
    }
    props.onScreenChange(screen);
  };

  return (
    <DetachedWindowFrame title="Workspace" subtitle="Interactive Jace workspace">
      <section className="detached-workspace-panel">
        <div className="workspace-tabs-row detached-workspace-tabs">
          <div className="workspace-tabs-scroll">
            {TABS.map((tab) => (
              <button
                type="button"
                key={tab.screen}
                className={props.screen === tab.screen ? "active" : ""}
                onClick={() => changeScreen(tab.screen)}
              >
                {tab.label}
              </button>
            ))}
          </div>
        </div>
        <div className="workspace-host detached-workspace-host">
          {props.children}
        </div>
      </section>
    </DetachedWindowFrame>
  );
}
