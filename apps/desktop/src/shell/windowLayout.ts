import {
  useCallback,
  useEffect,
  useState,
} from "react";
import {
  availableMonitors,
  currentMonitor,
  getAllWindows,
  getCurrentWindow,
  primaryMonitor,
} from "@tauri-apps/api/window";
import {
  PhysicalPosition,
  PhysicalSize,
} from "@tauri-apps/api/dpi";

export type JaceNativeWindowLabel =
  | "main"
  | "jace-core"
  | "jace-office"
  | "jace-workspace";

export type DetachedRestorePanel =
  | "core"
  | "office"
  | "workspace";

export type DetachedRestoreContext = {
  screen?: string | null;
  conversationId?: string | null;
};

export type WindowLayoutPreferences = {
  rememberWindowGeometry: boolean;
  restoreDetachedWindows: boolean;
  restoreMaximizedState: boolean;
};

type SavedWindowGeometry = {
  x: number;
  y: number;
  width: number;
  height: number;
  maximized: boolean;
  monitorName: string | null;
  updatedAt: string;
};

type SavedGeometryMap = Partial<
  Record<JaceNativeWindowLabel, SavedWindowGeometry>
>;

type DetachedRestorePlan = Partial<
  Record<DetachedRestorePanel, DetachedRestoreContext>
>;

type TauriWindowHandle = ReturnType<typeof getCurrentWindow>;
type MonitorInfo = Awaited<
  ReturnType<typeof availableMonitors>
>[number];

const PREFERENCES_KEY =
  "jace.desktop.window-layout.preferences.v1";
const GEOMETRY_KEY =
  "jace.desktop.window-layout.geometry.v1";
const DETACHED_RESTORE_KEY =
  "jace.desktop.window-layout.detached.v1";
const PREFERENCES_EVENT =
  "jace:desktop-window-layout-preferences";
const LAYOUT_EVENT =
  "jace:desktop-window-layout-changed";
const CHANNEL_NAME =
  "jace-desktop-window-layout";

const JACE_WINDOW_LABELS: JaceNativeWindowLabel[] = [
  "main",
  "jace-core",
  "jace-office",
  "jace-workspace",
];

const DETACHED_PANELS: DetachedRestorePanel[] = [
  "core",
  "office",
  "workspace",
];

const MINIMUM_SIZE: Record<
  JaceNativeWindowLabel,
  { width: number; height: number }
> = {
  main: { width: 1100, height: 700 },
  "jace-core": { width: 640, height: 480 },
  "jace-office": { width: 640, height: 480 },
  "jace-workspace": { width: 760, height: 520 },
};

const DEFAULT_PREFERENCES: WindowLayoutPreferences = {
  rememberWindowGeometry: true,
  restoreDetachedWindows: true,
  restoreMaximizedState: true,
};

function isFiniteNumber(value: unknown): value is number {
  return (
    typeof value === "number" &&
    Number.isFinite(value)
  );
}

function isJaceWindowLabel(
  value: unknown,
): value is JaceNativeWindowLabel {
  return (
    typeof value === "string" &&
    JACE_WINDOW_LABELS.includes(
      value as JaceNativeWindowLabel,
    )
  );
}

function isDetachedPanel(
  value: unknown,
): value is DetachedRestorePanel {
  return (
    typeof value === "string" &&
    DETACHED_PANELS.includes(
      value as DetachedRestorePanel,
    )
  );
}

function safeBoolean(
  value: unknown,
  fallback: boolean,
): boolean {
  return typeof value === "boolean"
    ? value
    : fallback;
}

function readJson(
  key: string,
): unknown {
  if (typeof window === "undefined") return null;

  try {
    const raw = window.localStorage.getItem(key);
    return raw ? JSON.parse(raw) : null;
  } catch {
    return null;
  }
}

function writeJson(
  key: string,
  value: unknown,
): void {
  if (typeof window === "undefined") return;

  try {
    window.localStorage.setItem(
      key,
      JSON.stringify(value),
    );
  } catch {
    // Layout persistence is convenience only.
  }
}

function emitLayoutEvent(
  eventName: string,
  detail?: unknown,
): void {
  if (typeof window === "undefined") return;

  window.dispatchEvent(
    new CustomEvent(eventName, { detail }),
  );

  try {
    const channel = new BroadcastChannel(
      CHANNEL_NAME,
    );
    channel.postMessage({
      eventName,
      detail,
    });
    channel.close();
  } catch {
    // BroadcastChannel is optional.
  }
}

export function readWindowLayoutPreferences():
  WindowLayoutPreferences {
  const raw = readJson(PREFERENCES_KEY);

  if (!raw || typeof raw !== "object") {
    return { ...DEFAULT_PREFERENCES };
  }

  const value = raw as Record<string, unknown>;

  return {
    rememberWindowGeometry: safeBoolean(
      value.rememberWindowGeometry,
      DEFAULT_PREFERENCES.rememberWindowGeometry,
    ),
    restoreDetachedWindows: safeBoolean(
      value.restoreDetachedWindows,
      DEFAULT_PREFERENCES.restoreDetachedWindows,
    ),
    restoreMaximizedState: safeBoolean(
      value.restoreMaximizedState,
      DEFAULT_PREFERENCES.restoreMaximizedState,
    ),
  };
}

export function updateWindowLayoutPreferences(
  patch: Partial<WindowLayoutPreferences>,
): WindowLayoutPreferences {
  const next = {
    ...readWindowLayoutPreferences(),
    ...patch,
  };

  writeJson(PREFERENCES_KEY, next);
  emitLayoutEvent(PREFERENCES_EVENT, next);
  return next;
}

export function useWindowLayoutPreferences() {
  const [preferences, setPreferences] =
    useState<WindowLayoutPreferences>(
      () => readWindowLayoutPreferences(),
    );

  useEffect(() => {
    let channel: BroadcastChannel | null = null;

    const apply = (value: unknown) => {
      if (!value || typeof value !== "object") {
        setPreferences(
          readWindowLayoutPreferences(),
        );
        return;
      }

      const raw = value as Record<string, unknown>;
      setPreferences({
        rememberWindowGeometry: safeBoolean(
          raw.rememberWindowGeometry,
          true,
        ),
        restoreDetachedWindows: safeBoolean(
          raw.restoreDetachedWindows,
          true,
        ),
        restoreMaximizedState: safeBoolean(
          raw.restoreMaximizedState,
          true,
        ),
      });
    };

    const onCustom = (event: Event) => {
      apply(
        (
          event as CustomEvent<
            WindowLayoutPreferences
          >
        ).detail,
      );
    };

    const onStorage = (event: StorageEvent) => {
      if (event.key !== PREFERENCES_KEY) return;
      setPreferences(
        readWindowLayoutPreferences(),
      );
    };

    window.addEventListener(
      PREFERENCES_EVENT,
      onCustom,
    );
    window.addEventListener(
      "storage",
      onStorage,
    );

    try {
      channel = new BroadcastChannel(
        CHANNEL_NAME,
      );
      channel.onmessage = (event) => {
        if (
          event.data?.eventName ===
          PREFERENCES_EVENT
        ) {
          apply(event.data?.detail);
        }
      };
    } catch {
      channel = null;
    }

    return () => {
      window.removeEventListener(
        PREFERENCES_EVENT,
        onCustom,
      );
      window.removeEventListener(
        "storage",
        onStorage,
      );
      channel?.close();
    };
  }, []);

  const update = useCallback(
    (
      patch: Partial<WindowLayoutPreferences>,
    ) => {
      setPreferences(
        updateWindowLayoutPreferences(patch),
      );
    },
    [],
  );

  return {
    preferences,
    update,
  };
}

function readGeometryMap(): SavedGeometryMap {
  const raw = readJson(GEOMETRY_KEY);
  if (!raw || typeof raw !== "object") {
    return {};
  }

  const source = raw as Record<string, unknown>;
  const result: SavedGeometryMap = {};

  for (const label of JACE_WINDOW_LABELS) {
    const value = source[label];

    if (
      !value ||
      typeof value !== "object"
    ) {
      continue;
    }

    const candidate =
      value as Record<string, unknown>;

    if (
      !isFiniteNumber(candidate.x) ||
      !isFiniteNumber(candidate.y) ||
      !isFiniteNumber(candidate.width) ||
      !isFiniteNumber(candidate.height)
    ) {
      continue;
    }

    result[label] = {
      x: candidate.x,
      y: candidate.y,
      width: candidate.width,
      height: candidate.height,
      maximized: safeBoolean(
        candidate.maximized,
        false,
      ),
      monitorName:
        typeof candidate.monitorName === "string"
          ? candidate.monitorName
          : null,
      updatedAt:
        typeof candidate.updatedAt === "string"
          ? candidate.updatedAt
          : new Date(0).toISOString(),
    };
  }

  return result;
}

function writeGeometryMap(
  value: SavedGeometryMap,
): void {
  writeJson(GEOMETRY_KEY, value);
  emitLayoutEvent(LAYOUT_EVENT);
}

function monitorContainsPoint(
  monitor: MonitorInfo,
  x: number,
  y: number,
): boolean {
  const area = monitor.workArea;
  const right =
    area.position.x + area.size.width;
  const bottom =
    area.position.y + area.size.height;

  return (
    x >= area.position.x &&
    x < right &&
    y >= area.position.y &&
    y < bottom
  );
}

function monitorForGeometry(
  monitors: MonitorInfo[],
  geometry: SavedWindowGeometry,
): MonitorInfo | null {
  const centerX =
    geometry.x + geometry.width / 2;
  const centerY =
    geometry.y + geometry.height / 2;

  return (
    monitors.find((monitor) =>
      monitorContainsPoint(
        monitor,
        centerX,
        centerY,
      ),
    ) ??
    monitors.find(
      (monitor) =>
        monitor.name === geometry.monitorName,
    ) ??
    null
  );
}

function monitorForRectangle(
  monitors: MonitorInfo[],
  x: number,
  y: number,
  width: number,
  height: number,
): MonitorInfo | null {
  const centerX = x + width / 2;
  const centerY = y + height / 2;

  return (
    monitors.find((monitor) =>
      monitorContainsPoint(
        monitor,
        centerX,
        centerY,
      ),
    ) ?? null
  );
}

function clamp(
  value: number,
  minimum: number,
  maximum: number,
): number {
  if (maximum < minimum) return minimum;
  return Math.min(
    maximum,
    Math.max(minimum, value),
  );
}

function fitGeometryToMonitor(
  label: JaceNativeWindowLabel,
  geometry: SavedWindowGeometry,
  monitor: MonitorInfo,
): SavedWindowGeometry {
  const area = monitor.workArea;
  const minimum = MINIMUM_SIZE[label];
  const margin = 12;

  const maxWidth = Math.max(
    minimum.width,
    area.size.width - margin * 2,
  );
  const maxHeight = Math.max(
    minimum.height,
    area.size.height - margin * 2,
  );

  const width = clamp(
    geometry.width,
    minimum.width,
    maxWidth,
  );
  const height = clamp(
    geometry.height,
    minimum.height,
    maxHeight,
  );

  const minX = area.position.x + margin;
  const minY = area.position.y + margin;
  const maxX =
    area.position.x +
    area.size.width -
    width -
    margin;
  const maxY =
    area.position.y +
    area.size.height -
    height -
    margin;

  return {
    ...geometry,
    x: clamp(geometry.x, minX, maxX),
    y: clamp(geometry.y, minY, maxY),
    width,
    height,
    monitorName: monitor.name,
  };
}

async function fallbackMonitor():
  Promise<MonitorInfo | null> {
  try {
    return (
      (await primaryMonitor()) ??
      (await currentMonitor()) ??
      (await availableMonitors())[0] ??
      null
    );
  } catch {
    return null;
  }
}

async function safeGeometryForRestore(
  label: JaceNativeWindowLabel,
  geometry: SavedWindowGeometry,
): Promise<SavedWindowGeometry> {
  try {
    const monitors = await availableMonitors();
    if (monitors.length === 0) {
      return geometry;
    }

    const monitor =
      monitorForGeometry(monitors, geometry) ??
      (await fallbackMonitor()) ??
      monitors[0];

    return fitGeometryToMonitor(
      label,
      geometry,
      monitor,
    );
  } catch {
    return geometry;
  }
}

function monitorNameForBounds(
  monitors: MonitorInfo[],
  x: number,
  y: number,
  width: number,
  height: number,
): string | null {
  return (
    monitorForRectangle(
      monitors,
      x,
      y,
      width,
      height,
    )?.name ?? null
  );
}

async function captureWindowGeometry(
  target: TauriWindowHandle,
): Promise<boolean> {
  const preferences =
    readWindowLayoutPreferences();

  if (!preferences.rememberWindowGeometry) {
    return false;
  }

  const label = target.label;
  if (!isJaceWindowLabel(label)) {
    return false;
  }

  try {
    const maximized =
      await target.isMaximized();
    const current = readGeometryMap();
    const existing = current[label];

    if (maximized && existing) {
      current[label] = {
        ...existing,
        maximized: true,
        updatedAt: new Date().toISOString(),
      };
      writeGeometryMap(current);
      return true;
    }

    const [position, size, monitors] =
      await Promise.all([
        target.outerPosition(),
        target.outerSize(),
        availableMonitors().catch(
          () => [] as MonitorInfo[],
        ),
      ]);

    current[label] = {
      x: position.x,
      y: position.y,
      width: size.width,
      height: size.height,
      maximized,
      monitorName: monitorNameForBounds(
        monitors,
        position.x,
        position.y,
        size.width,
        size.height,
      ),
      updatedAt: new Date().toISOString(),
    };

    writeGeometryMap(current);
    return true;
  } catch {
    return false;
  }
}

export async function restoreCurrentWindowGeometry():
  Promise<void> {
  const preferences =
    readWindowLayoutPreferences();

  if (!preferences.rememberWindowGeometry) {
    return;
  }

  const target = getCurrentWindow();
  const label = target.label;

  if (!isJaceWindowLabel(label)) {
    return;
  }

  const saved = readGeometryMap()[label];
  if (!saved) return;

  const geometry =
    await safeGeometryForRestore(
      label,
      saved,
    );

  try {
    if (await target.isMaximized()) {
      await target.unmaximize();
    }

    await target.setSize(
      new PhysicalSize(
        geometry.width,
        geometry.height,
      ),
    );
    await target.setPosition(
      new PhysicalPosition(
        geometry.x,
        geometry.y,
      ),
    );

    if (
      preferences.restoreMaximizedState &&
      saved.maximized
    ) {
      await target.maximize();
    }
  } catch (error) {
    console.warn(
      "Could not restore Jace window geometry.",
      error,
    );
  }
}

export async function startCurrentWindowGeometryTracking():
  Promise<() => void> {
  const target = getCurrentWindow();
  let timer: number | null = null;
  let disposed = false;

  const save = () => {
    if (disposed) return;

    if (timer !== null) {
      window.clearTimeout(timer);
    }

    timer = window.setTimeout(() => {
      timer = null;
      void captureWindowGeometry(target);
    }, 220);
  };

  const [unlistenMoved, unlistenResized] =
    await Promise.all([
      target.onMoved(save),
      target.onResized(save),
    ]);

  // Capture the default/non-maximized bounds once so later
  // maximize events never become the only geometry we know.
  void captureWindowGeometry(target);

  return () => {
    disposed = true;

    if (timer !== null) {
      window.clearTimeout(timer);
      timer = null;
    }

    unlistenMoved();
    unlistenResized();
  };
}

export function readDetachedRestorePlan():
  DetachedRestorePlan {
  const raw = readJson(DETACHED_RESTORE_KEY);
  if (!raw || typeof raw !== "object") {
    return {};
  }

  const source = raw as Record<string, unknown>;
  const result: DetachedRestorePlan = {};

  for (const panel of DETACHED_PANELS) {
    const value = source[panel];
    if (!value || typeof value !== "object") {
      continue;
    }

    const rawContext =
      value as Record<string, unknown>;

    result[panel] = {
      screen:
        typeof rawContext.screen === "string"
          ? rawContext.screen
          : null,
      conversationId:
        typeof rawContext.conversationId ===
        "string"
          ? rawContext.conversationId
          : null,
    };
  }

  return result;
}

export function rememberDetachedPanelRestore(
  panel: DetachedRestorePanel,
  context?: DetachedRestoreContext,
): void {
  if (!isDetachedPanel(panel)) return;

  const current = readDetachedRestorePlan();
  current[panel] = {
    screen: context?.screen ?? null,
    conversationId:
      context?.conversationId ?? null,
  };

  writeJson(DETACHED_RESTORE_KEY, current);
  emitLayoutEvent(LAYOUT_EVENT);
}

export function forgetDetachedPanelRestore(
  panel: DetachedRestorePanel,
): void {
  const current = readDetachedRestorePlan();

  if (!(panel in current)) return;

  delete current[panel];
  writeJson(DETACHED_RESTORE_KEY, current);
  emitLayoutEvent(LAYOUT_EVENT);
}

export function getSavedWindowCount(): number {
  return Object.keys(readGeometryMap()).length;
}

export function getDetachedRestoreCount(): number {
  return Object.keys(
    readDetachedRestorePlan(),
  ).length;
}

export async function saveOpenWindowLayoutNow():
  Promise<number> {
  try {
    const windows = await getAllWindows();
    const relevant = windows.filter((item) =>
      isJaceWindowLabel(item.label),
    );

    const results = await Promise.all(
      relevant.map((item) =>
        captureWindowGeometry(item),
      ),
    );

    return results.filter(Boolean).length;
  } catch {
    return 0;
  }
}

export async function bringAllJaceWindowsToCurrentMonitor():
  Promise<number> {
  const monitor =
    (await currentMonitor().catch(
      () => null,
    )) ??
    (await fallbackMonitor());

  if (!monitor) return 0;

  let windows: TauriWindowHandle[] = [];

  try {
    windows = (
      await getAllWindows()
    ).filter((item) =>
      isJaceWindowLabel(item.label),
    );
  } catch {
    return 0;
  }

  const area = monitor.workArea;
  let moved = 0;

  for (
    let index = 0;
    index < windows.length;
    index += 1
  ) {
    const target = windows[index];
    const label = target.label;

    if (!isJaceWindowLabel(label)) continue;

    try {
      await target.unminimize();

      const wasMaximized =
        await target.isMaximized();

      if (wasMaximized) {
        await target.unmaximize();
      }

      const size = await target.outerSize();
      const minimum = MINIMUM_SIZE[label];
      const margin = 20;
      const cascade = index * 34;

      const width = clamp(
        size.width,
        minimum.width,
        Math.max(
          minimum.width,
          area.size.width - margin * 2,
        ),
      );
      const height = clamp(
        size.height,
        minimum.height,
        Math.max(
          minimum.height,
          area.size.height - margin * 2,
        ),
      );

      const maxX =
        area.position.x +
        area.size.width -
        width -
        margin;
      const maxY =
        area.position.y +
        area.size.height -
        height -
        margin;

      const x = clamp(
        area.position.x + margin + cascade,
        area.position.x + margin,
        maxX,
      );
      const y = clamp(
        area.position.y + margin + cascade,
        area.position.y + margin,
        maxY,
      );

      await target.setSize(
        new PhysicalSize(width, height),
      );
      await target.setPosition(
        new PhysicalPosition(x, y),
      );

      if (wasMaximized) {
        await target.maximize();
      }

      await captureWindowGeometry(target);
      moved += 1;
    } catch {
      // Continue recovering the remaining Jace windows.
    }
  }

  return moved;
}

export function clearSavedWindowLayout(): void {
  if (typeof window === "undefined") return;

  try {
    window.localStorage.removeItem(
      GEOMETRY_KEY,
    );
    window.localStorage.removeItem(
      DETACHED_RESTORE_KEY,
    );
  } catch {
    // Best effort.
  }

  emitLayoutEvent(LAYOUT_EVENT);
}

export function subscribeWindowLayoutChanges(
  callback: () => void,
): () => void {
  const onCustom = () => callback();
  let channel: BroadcastChannel | null = null;

  window.addEventListener(
    LAYOUT_EVENT,
    onCustom,
  );

  try {
    channel = new BroadcastChannel(
      CHANNEL_NAME,
    );
    channel.onmessage = (event) => {
      if (
        event.data?.eventName ===
        LAYOUT_EVENT
      ) {
        callback();
      }
    };
  } catch {
    channel = null;
  }

  return () => {
    window.removeEventListener(
      LAYOUT_EVENT,
      onCustom,
    );
    channel?.close();
  };
}
