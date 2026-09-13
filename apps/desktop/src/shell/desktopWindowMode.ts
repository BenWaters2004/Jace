import {
  useCallback,
  useEffect,
  useState,
  type MouseEvent as ReactMouseEvent,
} from "react";
import { getCurrentWindow } from "@tauri-apps/api/window";

export type DesktopWindowMode = "normal" | "frameless";

export const DESKTOP_WINDOW_MODE_KEY =
  "jace.desktop.window-mode.v1";

const CHANNEL_NAME = "jace-desktop-window-mode";

function isWindowMode(value: unknown): value is DesktopWindowMode {
  return value === "normal" || value === "frameless";
}

export function readDesktopWindowMode(): DesktopWindowMode {
  if (typeof window === "undefined") return "normal";

  try {
    const stored = window.localStorage.getItem(
      DESKTOP_WINDOW_MODE_KEY,
    );
    return isWindowMode(stored) ? stored : "normal";
  } catch {
    return "normal";
  }
}

async function applyModeToCurrentWindow(
  mode: DesktopWindowMode,
): Promise<void> {
  if (typeof document !== "undefined") {
    document.documentElement.dataset.windowMode = mode;
  }

  try {
    await getCurrentWindow().setDecorations(mode === "normal");
  } catch {
    // Browser/Vite preview or native API unavailable.
  }
}

export async function applyStoredDesktopWindowMode(): Promise<void> {
  await applyModeToCurrentWindow(readDesktopWindowMode());
}

function broadcastMode(mode: DesktopWindowMode): void {
  try {
    window.localStorage.setItem(DESKTOP_WINDOW_MODE_KEY, mode);
  } catch {
    // Persistence is convenience only.
  }

  window.dispatchEvent(
    new CustomEvent("jace:desktop-window-mode", {
      detail: { mode },
    }),
  );

  try {
    const channel = new BroadcastChannel(CHANNEL_NAME);
    channel.postMessage({ mode });
    channel.close();
  } catch {
    // BroadcastChannel is optional.
  }
}

export function useDesktopWindowMode() {
  const [mode, setModeState] = useState<DesktopWindowMode>(
    () => readDesktopWindowMode(),
  );

  useEffect(() => {
    let disposed = false;
    let channel: BroadcastChannel | null = null;

    const accept = (value: unknown) => {
      if (!disposed && isWindowMode(value)) {
        setModeState(value);
      }
    };

    const onCustom = (event: Event) => {
      accept(
        (event as CustomEvent<{ mode?: unknown }>).detail?.mode,
      );
    };

    const onStorage = (event: StorageEvent) => {
      if (event.key === DESKTOP_WINDOW_MODE_KEY) {
        accept(event.newValue);
      }
    };

    window.addEventListener("jace:desktop-window-mode", onCustom);
    window.addEventListener("storage", onStorage);

    try {
      channel = new BroadcastChannel(CHANNEL_NAME);
      channel.onmessage = (event) => accept(event.data?.mode);
    } catch {
      channel = null;
    }

    return () => {
      disposed = true;
      window.removeEventListener(
        "jace:desktop-window-mode",
        onCustom,
      );
      window.removeEventListener("storage", onStorage);
      channel?.close();
    };
  }, []);

  useEffect(() => {
    void applyModeToCurrentWindow(mode);
  }, [mode]);

  const setMode = useCallback((next: DesktopWindowMode) => {
    setModeState(next);
    broadcastMode(next);
  }, []);

  const handleDragMouseDown = useCallback(
    (event: ReactMouseEvent<HTMLElement>) => {
      if (mode !== "frameless" || event.button !== 0) return;

      const target = event.target as HTMLElement;
      if (
        target.closest(
          "button, input, select, textarea, a, [role='button']",
        )
      ) {
        return;
      }

      event.preventDefault();

      void (async () => {
        try {
          const current = getCurrentWindow();
          if (event.detail >= 2) {
            await current.toggleMaximize();
          } else {
            await current.startDragging();
          }
        } catch {
          // Browser preview.
        }
      })();
    },
    [mode],
  );

  return {
    mode,
    setMode,
    isFrameless: mode === "frameless",
    handleDragMouseDown,
  };
}
