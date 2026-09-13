import { useCallback, useEffect, useRef, useState } from "react";
import { WebviewWindow } from "@tauri-apps/api/webviewWindow";
import { getCurrentWindow } from "@tauri-apps/api/window";

export type JacePanelId = "core" | "office" | "workspace";

export type DetachedPanelContext = {
  screen?: string | null;
  conversationId?: string | null;
};

type PersistedPanelLayout = {
  minimized: JacePanelId[];
  focused: JacePanelId | null;
};

const STORAGE_KEY = "jace.desktop.panel-layout.v1";
const PANEL_IDS: JacePanelId[] = ["core", "office", "workspace"];

const DETACHED_LABELS: Record<JacePanelId, string> = {
  core: "jace-core",
  office: "jace-office",
  workspace: "jace-workspace",
};

const DETACHED_TITLES: Record<JacePanelId, string> = {
  core: "Jace Core",
  office: "Jace · Agent Office",
  workspace: "Jace · Workspace",
};

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
      focused:
        focused && !minimized.includes(focused)
          ? focused
          : null,
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
    // Best effort.
  }
}

function detachedUrl(
  panel: JacePanelId,
  context?: DetachedPanelContext,
): string {
  const params = new URLSearchParams();
  params.set("jaceDetached", panel);

  if (panel === "workspace") {
    if (context?.screen) params.set("screen", context.screen);
    if (context?.conversationId) {
      params.set("conversation", context.conversationId);
    }
  }

  return `index.html?${params.toString()}`;
}

export function usePanelManager() {
  const [initial] = useState<PersistedPanelLayout>(() => readLayout());
  const [minimized, setMinimized] = useState<JacePanelId[]>(initial.minimized);
  const [focused, setFocused] = useState<JacePanelId | null>(initial.focused);
  const [fullscreenPanel, setFullscreenPanel] =
    useState<JacePanelId | null>(null);
  const [detached, setDetached] = useState<JacePanelId[]>([]);
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

  const focusDetached = useCallback(async (panel: JacePanelId) => {
    try {
      const existing = await WebviewWindow.getByLabel(DETACHED_LABELS[panel]);
      if (!existing) {
        setDetached((current) => current.filter((item) => item !== panel));
        return false;
      }
      await existing.unminimize();
      await existing.setFocus();
      return true;
    } catch {
      return false;
    }
  }, []);

  const restore = useCallback(
    (panel: JacePanelId) => {
      if (detached.includes(panel)) {
        void focusDetached(panel);
        return;
      }
      setMinimized((current) => current.filter((item) => item !== panel));
      setFocused(null);
    },
    [detached, focusDetached],
  );

  const minimize = useCallback(
    (panel: JacePanelId) => {
      if (detached.includes(panel)) {
        void focusDetached(panel);
        return;
      }
      if (fullscreenPanel === panel) {
        void setNativeFullscreen(false);
        setFullscreenPanel(null);
      }
      setMinimized((current) =>
        current.includes(panel) ? current : [...current, panel],
      );
      setFocused((current) => (current === panel ? null : current));
    },
    [detached, focusDetached, fullscreenPanel],
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
      if (detached.includes(panel)) {
        await focusDetached(panel);
        return;
      }
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
    [detached, exitFullscreen, focusDetached, focused, fullscreenPanel],
  );

  const detach = useCallback(
    async (
      panel: JacePanelId,
      context?: DetachedPanelContext,
    ): Promise<boolean> => {
      if (fullscreenPanel === panel) {
        await exitFullscreen();
      }

      try {
        const label = DETACHED_LABELS[panel];
        const existing = await WebviewWindow.getByLabel(label);

        if (existing) {
          setDetached((current) =>
            current.includes(panel) ? current : [...current, panel],
          );
          setMinimized((current) => current.filter((item) => item !== panel));
          setFocused((current) => (current === panel ? null : current));
          await existing.unminimize();
          await existing.setFocus();
          return true;
        }

        const workspace = panel === "workspace";
        const detachedWindow = new WebviewWindow(label, {
          url: detachedUrl(panel, context),
          title: DETACHED_TITLES[panel],
          width: workspace ? 1260 : 980,
          height: workspace ? 840 : 760,
          minWidth: workspace ? 760 : 640,
          minHeight: workspace ? 520 : 480,
          resizable: true,
          focus: true,
        });

        void detachedWindow.once("tauri://error", (event) => {
          console.error(
            `Could not create detached ${panel} window.`,
            event.payload,
          );
          setDetached((current) => current.filter((item) => item !== panel));
        });

        setDetached((current) =>
          current.includes(panel) ? current : [...current, panel],
        );
        setMinimized((current) => current.filter((item) => item !== panel));
        setFocused((current) => (current === panel ? null : current));
        return true;
      } catch (error) {
        console.error(`Could not detach ${panel} panel.`, error);
        return false;
      }
    },
    [exitFullscreen, fullscreenPanel],
  );

  useEffect(() => {
    if (detached.length === 0) return;

    let disposed = false;
    const reconcile = async () => {
      for (const panel of detached) {
        try {
          const current = await WebviewWindow.getByLabel(DETACHED_LABELS[panel]);
          if (!current && !disposed) {
            setDetached((items) => items.filter((item) => item !== panel));
            setMinimized((items) => items.filter((item) => item !== panel));
            window.dispatchEvent(
              new CustomEvent("jace:panel-reattached", {
                detail: { panel },
              }),
            );
          }
        } catch {
          // Retry next watchdog tick.
        }
      }
    };

    void reconcile();
    const timer = window.setInterval(() => void reconcile(), 900);

    return () => {
      disposed = true;
      window.clearInterval(timer);
    };
  }, [detached]);

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

    const browserHandler = () => void syncNativeFullscreen();
    document.addEventListener("fullscreenchange", browserHandler);

    return () => {
      disposed = true;
      unlisten?.();
      document.removeEventListener("fullscreenchange", browserHandler);
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

  const isDetached = useCallback(
    (panel: JacePanelId) => detached.includes(panel),
    [detached],
  );

  const isHidden = useCallback(
    (panel: JacePanelId) =>
      minimized.includes(panel) || detached.includes(panel),
    [detached, minimized],
  );

  return {
    minimized,
    focused,
    fullscreenPanel,
    detached,
    isMinimized,
    isDetached,
    isHidden,
    minimize,
    restore,
    restoreAll,
    toggleMaximized,
    toggleFullscreen,
    exitFullscreen,
    detach,
    focusDetached,
  };
}

export type JacePanelManager = ReturnType<typeof usePanelManager>;
