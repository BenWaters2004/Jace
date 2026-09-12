import {
  useCallback,
  useEffect,
  useRef,
  useState,
} from "react";
import { getCurrentWindow } from "@tauri-apps/api/window";

export type JacePanelId = "core" | "office" | "workspace";

type PersistedPanelLayout = {
  minimized: JacePanelId[];
  focused: JacePanelId | null;
};

const STORAGE_KEY = "jace.desktop.panel-layout.v1";
const PANEL_IDS: JacePanelId[] = ["core", "office", "workspace"];

function isPanelId(value: unknown): value is JacePanelId {
  return typeof value === "string" && PANEL_IDS.includes(value as JacePanelId);
}

function readLayout(): PersistedPanelLayout {
  if (typeof window === "undefined") return { minimized: [], focused: null };

  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (!raw) return { minimized: [], focused: null };

    const parsed = JSON.parse(raw) as Partial<PersistedPanelLayout>;
    const minimized = Array.isArray(parsed.minimized)
      ? parsed.minimized.filter(isPanelId)
      : [];
    const focused = isPanelId(parsed.focused) ? parsed.focused : null;

    return {
      minimized: [...new Set(minimized)],
      focused: focused && !minimized.includes(focused) ? focused : null,
    };
  } catch {
    return { minimized: [], focused: null };
  }
}

async function setNativeFullscreen(enabled: boolean): Promise<void> {
  try {
    await getCurrentWindow().setFullscreen(enabled);
    return;
  } catch {
    // Browser/Vite preview fallback.
  }

  try {
    if (enabled) {
      if (!document.fullscreenElement) {
        await document.documentElement.requestFullscreen();
      }
    } else if (document.fullscreenElement) {
      await document.exitFullscreen();
    }
  } catch {
    // Fullscreen is best-effort; panel focus still works without it.
  }
}

export function usePanelManager() {
  const [initial] = useState<PersistedPanelLayout>(() => readLayout());

  const [minimized, setMinimized] = useState<JacePanelId[]>(
    initial.minimized,
  );
  const [focused, setFocused] = useState<JacePanelId | null>(
    initial.focused,
  );
  const [fullscreenPanel, setFullscreenPanel] =
    useState<JacePanelId | null>(null);
  const focusBeforeFullscreenRef = useRef<JacePanelId | null>(null);

  useEffect(() => {
    if (fullscreenPanel !== null) return;

    try {
      window.localStorage.setItem(
        STORAGE_KEY,
        JSON.stringify({ minimized, focused }),
      );
    } catch {
      // Layout persistence is convenience only.
    }
  }, [focused, fullscreenPanel, minimized]);

  const restore = useCallback((panel: JacePanelId) => {
    setMinimized((current) => current.filter((item) => item !== panel));
    // A restore action should make the panel visible immediately even when
    // another panel was previously maximized.
    setFocused(null);
  }, []);

  const minimize = useCallback(
    (panel: JacePanelId) => {
      if (fullscreenPanel === panel) {
        void setNativeFullscreen(false);
        setFullscreenPanel(null);
      }

      setMinimized((current) =>
        current.includes(panel) ? current : [...current, panel],
      );
      setFocused((current) => (current === panel ? null : current));
    },
    [fullscreenPanel],
  );

  const toggleMaximized = useCallback((panel: JacePanelId) => {
    setMinimized((current) => current.filter((item) => item !== panel));
    setFocused((current) => (current === panel ? null : panel));
  }, []);

  const exitFullscreen = useCallback(async () => {
    if (fullscreenPanel === null) return;

    await setNativeFullscreen(false);
    setFullscreenPanel(null);
    setFocused(focusBeforeFullscreenRef.current);
    focusBeforeFullscreenRef.current = null;
  }, [fullscreenPanel]);

  const toggleFullscreen = useCallback(
    async (panel: JacePanelId) => {
      if (fullscreenPanel === panel) {
        await exitFullscreen();
        return;
      }

      if (fullscreenPanel !== null) {
        await setNativeFullscreen(false);
      }

      focusBeforeFullscreenRef.current = focused;
      setMinimized((current) => current.filter((item) => item !== panel));
      setFocused(panel);
      setFullscreenPanel(panel);
      await setNativeFullscreen(true);
    },
    [exitFullscreen, focused, fullscreenPanel],
  );

  useEffect(() => {
    let disposed = false;
    let unlisten: (() => void) | null = null;

    const syncNativeFullscreen = async () => {
      if (disposed || fullscreenPanel === null) return;

      try {
        const nativeFullscreen = await getCurrentWindow().isFullscreen();
        if (!nativeFullscreen) {
          setFullscreenPanel(null);
          setFocused(focusBeforeFullscreenRef.current);
          focusBeforeFullscreenRef.current = null;
        }
      } catch {
        if (
          typeof document !== "undefined" &&
          !document.fullscreenElement
        ) {
          setFullscreenPanel(null);
          setFocused(focusBeforeFullscreenRef.current);
          focusBeforeFullscreenRef.current = null;
        }
      }
    };

    try {
      const currentWindow = getCurrentWindow();
      void currentWindow.onResized(() => {
        void syncNativeFullscreen();
      }).then((remove) => {
        if (disposed) remove();
        else unlisten = remove;
      });
    } catch {
      // Normal browser preview.
    }

    const onBrowserFullscreenChange = () => {
      void syncNativeFullscreen();
    };
    document.addEventListener("fullscreenchange", onBrowserFullscreenChange);

    return () => {
      disposed = true;
      unlisten?.();
      document.removeEventListener(
        "fullscreenchange",
        onBrowserFullscreenChange,
      );
    };
  }, [fullscreenPanel]);

  const restoreAll = useCallback(() => {
    setMinimized([]);
    setFocused(null);
  }, []);

  const isMinimized = useCallback(
    (panel: JacePanelId) => minimized.includes(panel),
    [minimized],
  );

  return {
    minimized,
    focused,
    fullscreenPanel,
    isMinimized,
    minimize,
    restore,
    restoreAll,
    toggleMaximized,
    toggleFullscreen,
    exitFullscreen,
  };
}

export type JacePanelManager = ReturnType<typeof usePanelManager>;
