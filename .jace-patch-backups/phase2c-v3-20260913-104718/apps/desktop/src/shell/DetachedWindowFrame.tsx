import { useEffect, useState, type ReactNode } from "react";
import { getCurrentWindow } from "@tauri-apps/api/window";

export function DetachedWindowFrame(props: {
  title: string;
  subtitle?: string;
  children: ReactNode;
}) {
  const [fullscreen, setFullscreen] = useState(false);

  useEffect(() => {
    let disposed = false;
    let unlisten: (() => void) | null = null;
    const current = getCurrentWindow();

    const refresh = async () => {
      try {
        const next = await current.isFullscreen();
        if (!disposed) setFullscreen(next);
      } catch {
        // Browser/Vite preview.
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

  const toggleFullscreen = async () => {
    try {
      const current = getCurrentWindow();
      const next = !(await current.isFullscreen());
      await current.setFullscreen(next);
      setFullscreen(next);
      return;
    } catch {
      // Browser fallback below.
    }

    if (!document.fullscreenElement) {
      await document.documentElement.requestFullscreen();
      setFullscreen(true);
    } else {
      await document.exitFullscreen();
      setFullscreen(false);
    }
  };

  const attach = async () => {
    try {
      await getCurrentWindow().close();
    } catch {
      window.close();
    }
  };

  return (
    <main className="detached-window-shell">
      <header className="detached-window-header">
        <span
          className="detached-window-badge"
          title={`${props.title}${props.subtitle ? ` · ${props.subtitle}` : ""}`}
        >
          ↗ Detached
        </span>

        <div className="detached-window-actions">
          <button
            type="button"
            className={fullscreen ? "active" : ""}
            onClick={() => void toggleFullscreen()}
            title={fullscreen ? "Exit fullscreen" : "Fullscreen"}
            aria-label={fullscreen ? "Exit fullscreen" : "Fullscreen"}
          >
            ⛶
          </button>

          <button
            type="button"
            className="detached-attach-button"
            onClick={() => void attach()}
            title="Attach this panel back to the Command Center"
            aria-label="Attach this panel back to the Command Center"
          >
            <span aria-hidden="true">↙</span>
            <span>Attach</span>
          </button>
        </div>
      </header>

      <div className="detached-window-content">{props.children}</div>
    </main>
  );
}
