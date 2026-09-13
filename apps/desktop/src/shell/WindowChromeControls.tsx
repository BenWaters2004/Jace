import { useEffect, useState } from "react";
import { getCurrentWindow } from "@tauri-apps/api/window";

export function WindowChromeControls(props: {
  compact?: boolean;
}) {
  const [maximized, setMaximized] = useState(false);

  useEffect(() => {
    let disposed = false;
    let unlisten: (() => void) | null = null;
    const current = getCurrentWindow();

    const refresh = async () => {
      try {
        const next = await current.isMaximized();
        if (!disposed) setMaximized(next);
      } catch {
        // Browser preview.
      }
    };

    void refresh();
    void current
      .onResized(() => {
        void refresh();
      })
      .then((remove) => {
        if (disposed) remove();
        else unlisten = remove;
      });

    return () => {
      disposed = true;
      unlisten?.();
    };
  }, []);

  const minimize = async () => {
    try {
      await getCurrentWindow().minimize();
    } catch {}
  };

  const toggleMaximize = async () => {
    try {
      const current = getCurrentWindow();
      await current.toggleMaximize();
      setMaximized(await current.isMaximized());
    } catch {}
  };

  const close = async () => {
    try {
      await getCurrentWindow().close();
    } catch {
      window.close();
    }
  };

  return (
    <div
      className={`window-chrome-controls ${
        props.compact ? "compact" : ""
      }`}
      aria-label="Window controls"
    >
      <button
        type="button"
        className="window-chrome-button"
        onClick={() => void minimize()}
        title="Minimize"
        aria-label="Minimize window"
      >
        <span className="window-icon minimize" />
      </button>

      <button
        type="button"
        className="window-chrome-button"
        onClick={() => void toggleMaximize()}
        title={maximized ? "Restore" : "Maximize"}
        aria-label={maximized ? "Restore window" : "Maximize window"}
      >
        <span
          className={`window-icon ${
            maximized ? "restore" : "maximize"
          }`}
        />
      </button>

      <button
        type="button"
        className="window-chrome-button close"
        onClick={() => void close()}
        title="Close"
        aria-label="Close window"
      >
        <span className="window-icon close" />
      </button>
    </div>
  );
}
