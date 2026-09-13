import {
  Component,
  useEffect,
  type ErrorInfo,
  type ReactNode,
} from "react";
import { createPortal } from "react-dom";
import { useDesktopWindowMode } from "../shell/desktopWindowMode";
import { WindowChromeControls } from "../shell/WindowChromeControls";
import { WindowResizeHandles } from "../shell/WindowResizeHandles";

type SettingsSurfaceBoundaryState = {
  error: Error | null;
};

class SettingsSurfaceBoundary extends Component<
  { children: ReactNode; onClose: () => void },
  SettingsSurfaceBoundaryState
> {
  state: SettingsSurfaceBoundaryState = {
    error: null,
  };

  static getDerivedStateFromError(
    error: Error,
  ): SettingsSurfaceBoundaryState {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error(
      "Full-page Settings render failed.",
      error,
      info,
    );
  }

  render() {
    if (!this.state.error) {
      return this.props.children;
    }

    return (
      <div className="settings-fullpage-error">
        <span className="section-kicker">Settings recovered safely</span>
        <h1>Settings could not be displayed</h1>
        <p>
          Jace caught a Settings-only render error instead of allowing
          it to blank the entire application.
        </p>

        <div className="info-box">
          <strong>{this.state.error.name || "Error"}</strong>
          <span>
            {this.state.error.message ||
              "Unknown Settings render error."}
          </span>
        </div>

        <div className="header-actions">
          <button
            type="button"
            className="secondary-button"
            onClick={() => this.setState({ error: null })}
          >
            Retry settings
          </button>
          <button
            type="button"
            className="primary-button"
            onClick={this.props.onClose}
          >
            Back to Jace
          </button>
        </div>
      </div>
    );
  }
}

export function SettingsOverlay(props: {
  open: boolean;
  onClose: () => void;
  children: ReactNode;
}) {
  const desktopWindow = useDesktopWindowMode();

  useEffect(() => {
    if (!props.open) return;

    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      event.preventDefault();
      props.onClose();
    };

    window.addEventListener("keydown", onKeyDown);
    return () => {
      window.removeEventListener("keydown", onKeyDown);
    };
  }, [props.open, props.onClose]);

  if (!props.open || typeof document === "undefined") {
    return null;
  }

  return createPortal(
    <section
      className={`settings-fullpage-overlay window-mode-${desktopWindow.mode}`}
      role="dialog"
      aria-modal="true"
      aria-label="Jace settings"
    >
      <header className="settings-fullpage-toolbar">
        <button
          type="button"
          className="settings-fullpage-back"
          onClick={props.onClose}
          title="Return to Jace"
        >
          <span aria-hidden="true">←</span>
          <span>Back to Jace</span>
        </button>

        <div
          className={`settings-fullpage-drag-zone ${
            desktopWindow.isFrameless ? "active" : ""
          }`}
          onMouseDown={desktopWindow.handleDragMouseDown}
          title={
            desktopWindow.isFrameless
              ? "Drag Jace window · double-click to maximize"
              : undefined
          }
        >
          <span>SETTINGS</span>
        </div>

        {desktopWindow.isFrameless && (
          <WindowChromeControls />
        )}
      </header>

      <div className="settings-fullpage-body">
        <SettingsSurfaceBoundary onClose={props.onClose}>
          {props.children}
        </SettingsSurfaceBoundary>
      </div>

      <WindowResizeHandles
        enabled={desktopWindow.isFrameless}
      />
    </section>,
    document.body,
  );
}
