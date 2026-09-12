import type { JacePanelId, JacePanelManager } from "./usePanelManager";

const PANEL_NAMES: Record<JacePanelId, string> = {
  core: "Jace Core",
  office: "Agent Office",
  workspace: "Workspace",
};

export function PanelControls(props: {
  panel: JacePanelId;
  manager: JacePanelManager;
}) {
  const maximized = props.manager.focused === props.panel;
  const fullscreen = props.manager.fullscreenPanel === props.panel;
  const name = PANEL_NAMES[props.panel];

  return (
    <div className="jace-panel-controls" aria-label={`${name} panel controls`}>
      <button
        type="button"
        onClick={() => props.manager.minimize(props.panel)}
        title={`Minimize ${name}`}
        aria-label={`Minimize ${name}`}
      >
        —
      </button>
      <button
        type="button"
        onClick={() => props.manager.toggleMaximized(props.panel)}
        title={maximized ? `Restore ${name}` : `Maximize ${name}`}
        aria-label={maximized ? `Restore ${name}` : `Maximize ${name}`}
        className={maximized ? "active" : ""}
      >
        {maximized ? "▣" : "□"}
      </button>
      <button
        type="button"
        onClick={() => void props.manager.toggleFullscreen(props.panel)}
        title={fullscreen ? `Exit ${name} fullscreen` : `Fullscreen ${name}`}
        aria-label={fullscreen ? `Exit ${name} fullscreen` : `Fullscreen ${name}`}
        className={fullscreen ? "active" : ""}
      >
        ⛶
      </button>
    </div>
  );
}
