import {
  useEffect,
  useState,
} from "react";
import {
  bringAllJaceWindowsToCurrentMonitor,
  clearSavedWindowLayout,
  getDetachedRestoreCount,
  getSavedWindowCount,
  saveOpenWindowLayoutNow,
  subscribeWindowLayoutChanges,
  useWindowLayoutPreferences,
} from "../shell/windowLayout";

export function WindowLayoutSettings() {
  const layout = useWindowLayoutPreferences();
  const [savedWindows, setSavedWindows] =
    useState(() => getSavedWindowCount());
  const [detachedWindows, setDetachedWindows] =
    useState(() => getDetachedRestoreCount());
  const [busy, setBusy] = useState(false);
  const [message, setMessage] =
    useState<string | null>(null);

  useEffect(() => {
    const refresh = () => {
      setSavedWindows(getSavedWindowCount());
      setDetachedWindows(
        getDetachedRestoreCount(),
      );
    };

    refresh();
    return subscribeWindowLayoutChanges(refresh);
  }, []);

  async function saveNow() {
    setBusy(true);
    setMessage(null);

    try {
      const count =
        await saveOpenWindowLayoutNow();
      setMessage(
        count > 0
          ? `Saved the geometry of ${count} open Jace window${
              count === 1 ? "" : "s"
            }.`
          : "No Jace window geometry was saved.",
      );
    } finally {
      setBusy(false);
    }
  }

  async function bringHere() {
    setBusy(true);
    setMessage(null);

    try {
      const count =
        await bringAllJaceWindowsToCurrentMonitor();
      setMessage(
        count > 0
          ? `Moved ${count} Jace window${
              count === 1 ? "" : "s"
            } onto this monitor.`
          : "No Jace windows could be moved.",
      );
    } finally {
      setBusy(false);
    }
  }

  function forgetLayout() {
    if (
      !window.confirm(
        "Forget all saved Jace window positions, sizes and detached-window restore state?",
      )
    ) {
      return;
    }

    clearSavedWindowLayout();
    setMessage(
      "Saved window layout cleared. Current windows were left unchanged.",
    );
  }

  const preferences = layout.preferences;

  return (
    <section className="settings-card full-card window-layout-settings-card">
      <div className="settings-card-heading">
        <div>
          <span className="section-kicker">
            Desktop layout
          </span>
          <h2>Window persistence</h2>
        </div>
        <span className="settings-icon">▦</span>
      </div>

      <p className="field-help">
        Remember where Jace windows live across monitors and recover
        them safely if a monitor is disconnected.
      </p>

      <div className="toggle-grid window-layout-toggle-grid">
        <label className="toggle-card">
          <div>
            <strong>
              Remember window positions
            </strong>
            <span>
              Save the size and physical screen position of the main
              window and each detached Core, Office and Workspace.
            </span>
          </div>
          <input
            type="checkbox"
            checked={
              preferences.rememberWindowGeometry
            }
            onChange={(event) =>
              layout.update({
                rememberWindowGeometry:
                  event.target.checked,
              })
            }
          />
        </label>

        <label className="toggle-card">
          <div>
            <strong>
              Restore detached windows
            </strong>
            <span>
              Reopen Core, Agent Office and Workspace after restarting
              Jace when they were detached at the end of the last
              session.
            </span>
          </div>
          <input
            type="checkbox"
            checked={
              preferences.restoreDetachedWindows
            }
            onChange={(event) =>
              layout.update({
                restoreDetachedWindows:
                  event.target.checked,
              })
            }
          />
        </label>

        <label
          className={`toggle-card ${
            !preferences.rememberWindowGeometry
              ? "disabled"
              : ""
          }`}
        >
          <div>
            <strong>
              Restore maximized state
            </strong>
            <span>
              Reopen a window maximized when it was maximized during
              the previous session.
            </span>
          </div>
          <input
            type="checkbox"
            disabled={
              !preferences.rememberWindowGeometry
            }
            checked={
              preferences.restoreMaximizedState
            }
            onChange={(event) =>
              layout.update({
                restoreMaximizedState:
                  event.target.checked,
              })
            }
          />
        </label>
      </div>

      <div className="window-layout-summary">
        <div>
          <span>Saved geometry</span>
          <strong>{savedWindows}</strong>
        </div>
        <div>
          <span>Detached restore plan</span>
          <strong>{detachedWindows}</strong>
        </div>
      </div>

      <div className="window-layout-actions">
        <button
          type="button"
          className="secondary-button"
          disabled={
            busy ||
            !preferences.rememberWindowGeometry
          }
          onClick={() => void saveNow()}
        >
          Save layout now
        </button>

        <button
          type="button"
          className="secondary-button"
          disabled={busy}
          onClick={() => void bringHere()}
        >
          Bring all windows to this screen
        </button>

        <button
          type="button"
          className="danger-button window-layout-reset"
          disabled={busy}
          onClick={forgetLayout}
        >
          Forget saved layout
        </button>
      </div>

      {message && (
        <div className="info-box window-layout-message">
          <strong>Desktop layout</strong>
          <span>{message}</span>
        </div>
      )}

      <div className="info-box">
        <strong>Monitor recovery</strong>
        <span>
          If a saved monitor is no longer connected, Jace clamps that
          window into an available monitor's work area instead of
          reopening it off-screen.
        </span>
      </div>
    </section>
  );
}
