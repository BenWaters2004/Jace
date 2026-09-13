import type { Screen } from "../types";
import type { JacePanelId } from "./usePanelManager";

export const DETACHED_WORKSPACE_SCREEN_KEY =
  "jace.desktop.detached-workspace-screen.v1";

const SCREEN_VALUES: Screen[] = [
  "chat",
  "output",
  "computer",
  "web",
  "automations",
  "memory",
  "control",
  "tools",
  "settings",
];

export type JaceWindowEntry = {
  panel: JacePanelId | null;
  screen: Screen | null;
  conversationId: string | null;
};

export function isScreenValue(value: unknown): value is Screen {
  return typeof value === "string" && SCREEN_VALUES.includes(value as Screen);
}

export function readWindowEntry(): JaceWindowEntry {
  if (typeof window === "undefined") {
    return { panel: null, screen: null, conversationId: null };
  }

  const params = new URLSearchParams(window.location.search);
  const rawPanel = params.get("jaceDetached");
  const panel: JacePanelId | null =
    rawPanel === "core" || rawPanel === "office" || rawPanel === "workspace"
      ? rawPanel
      : null;

  const rawScreen = params.get("screen");

  return {
    panel,
    screen: isScreenValue(rawScreen) ? rawScreen : null,
    conversationId: params.get("conversation"),
  };
}
