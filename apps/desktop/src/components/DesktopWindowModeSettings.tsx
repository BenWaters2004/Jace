import { useDesktopWindowMode } from "../shell/desktopWindowMode";

export function DesktopWindowModeSettings() {
  const desktopWindow = useDesktopWindowMode();

  return (
    <section className="settings-card full-card desktop-window-settings-card">
      <div className="settings-card-heading">
        <div>
          <span className="section-kicker">Desktop shell</span>
          <h2>Window appearance</h2>
        </div>
        <span className="settings-icon">▣</span>
      </div>

      <p className="field-help">
        Choose between the normal operating-system frame and Jace's
        custom frameless shell. This preference is stored on this
        computer and applies to the Command Center and detached windows.
      </p>

      <div className="desktop-window-mode-grid">
        <button
          type="button"
          className={`desktop-window-mode-option ${
            desktopWindow.mode === "normal" ? "active" : ""
          }`}
          onClick={() => desktopWindow.setMode("normal")}
        >
          <span className="desktop-window-mode-preview normal">
            <i />
            <b />
          </span>
          <strong>Standard window</strong>
          <small>
            Keep the native Windows title bar and controls.
          </small>
        </button>

        <button
          type="button"
          className={`desktop-window-mode-option ${
            desktopWindow.mode === "frameless" ? "active" : ""
          }`}
          onClick={() => desktopWindow.setMode("frameless")}
        >
          <span className="desktop-window-mode-preview frameless">
            <i />
            <b />
          </span>
          <strong>Frameless Jace</strong>
          <small>
            Use Jace's own drag, resize, minimize, maximize and close controls.
          </small>
        </button>
      </div>

      <div className="info-box desktop-window-mode-info">
        <strong>
          {desktopWindow.isFrameless
            ? "Frameless mode active"
            : "Standard window active"}
        </strong>
        <span>
          Changes apply immediately. Frameless mode remains resizable
          from every edge and corner.
        </span>
      </div>
    </section>
  );
}
