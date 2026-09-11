import { useEffect, useMemo, useState } from "react";
import { API_BASE_URL } from "../constants";

export type JaceRuntimeState =
  | "offline"
  | "idle"
  | "listening"
  | "transcribing"
  | "thinking"
  | "speaking"
  | "working"
  | "waiting_permission"
  | "warning";

export interface RuntimeEvent {
  type: string;
  sequence?: number;
  timestamp?: string;

  state?: JaceRuntimeState;
  reason?: string;
  tool_name?: string;
  label?: string;
  status?: string;
  summary?: string;
  risk?: string;

  task_id?: string;
  agent_id?: string;
  conversation_id?: string | null;
  progress?: number;
  progress_message?: string | null;
  error?: string;
  result_preview?: string;
  handoff_message_id?: string | null;

  connected?: boolean;

  [key: string]: unknown;
}

type RuntimeListener = (event: RuntimeEvent) => void;

interface RuntimeHub {
  listeners: Set<RuntimeListener>;
  socket: WebSocket | null;
  retryTimer: number | null;
  disconnectTimer: number | null;
  transportConnected: boolean;
  latestEvent: RuntimeEvent | null;
  socketGeneration: number;
  intentionallyClosing: WeakSet<WebSocket>;
}

type JaceRuntimeGlobal = typeof globalThis & {
  __JACE_RUNTIME_HUB__?: RuntimeHub;
};

/*
 * Keep the transport outside React's component lifecycle.
 *
 * React.StrictMode deliberately mounts, unmounts and remounts effects in
 * development. Vite can also replace this module while the desktop window is
 * still alive. A module-local WebSocket can therefore briefly exist twice.
 *
 * globalThis gives the renderer exactly one runtime hub for the lifetime of
 * the webview, including StrictMode effect replay and Vite HMR.
 */
const runtimeGlobal = globalThis as JaceRuntimeGlobal;
const hub: RuntimeHub =
  runtimeGlobal.__JACE_RUNTIME_HUB__ ?? {
    listeners: new Set<RuntimeListener>(),
    socket: null,
    retryTimer: null,
    disconnectTimer: null,
    transportConnected: false,
    latestEvent: null,
    socketGeneration: 0,
    intentionallyClosing: new WeakSet<WebSocket>(),
  };

runtimeGlobal.__JACE_RUNTIME_HUB__ = hub;

const RECONNECT_DELAY_MS = 1500;
const UNUSED_DISCONNECT_GRACE_MS = 500;

function websocketUrl(): string {
  const base = new URL(API_BASE_URL);
  const protocol = base.protocol === "https:" ? "wss:" : "ws:";
  return `${protocol}//${base.host}/runtime/events`;
}

function emit(event: RuntimeEvent) {
  hub.latestEvent = event;

  for (const listener of hub.listeners) {
    try {
      listener(event);
    } catch {
      // A presentation subscriber must never break the shared runtime stream.
    }
  }
}

function clearRetryTimer() {
  if (hub.retryTimer !== null) {
    window.clearTimeout(hub.retryTimer);
    hub.retryTimer = null;
  }
}

function clearDisconnectTimer() {
  if (hub.disconnectTimer !== null) {
    window.clearTimeout(hub.disconnectTimer);
    hub.disconnectTimer = null;
  }
}

function scheduleReconnect() {
  if (hub.listeners.size === 0 || hub.retryTimer !== null) return;

  hub.retryTimer = window.setTimeout(() => {
    hub.retryTimer = null;

    if (hub.listeners.size === 0) return;
    ensureRuntimeConnection();
  }, RECONNECT_DELAY_MS);
}

function ensureRuntimeConnection() {
  clearDisconnectTimer();

  if (hub.listeners.size === 0) return;

  if (
    hub.socket &&
    (hub.socket.readyState === WebSocket.CONNECTING ||
      hub.socket.readyState === WebSocket.OPEN)
  ) {
    return;
  }

  clearRetryTimer();

  const generation = ++hub.socketGeneration;
  const nextSocket = new WebSocket(websocketUrl());
  hub.socket = nextSocket;

  nextSocket.onopen = () => {
    if (
      hub.socket !== nextSocket ||
      generation !== hub.socketGeneration
    ) {
      return;
    }

    hub.transportConnected = true;
    emit({
      type: "runtime.transport.connected",
      connected: true,
      timestamp: new Date().toISOString(),
    });
  };

  nextSocket.onmessage = (message) => {
    if (
      hub.socket !== nextSocket ||
      generation !== hub.socketGeneration
    ) {
      return;
    }

    try {
      const event = JSON.parse(message.data) as RuntimeEvent;
      emit(event);
    } catch {
      // REST state remains authoritative if a presentation event is malformed.
    }
  };

  nextSocket.onerror = () => {
    if (hub.socket === nextSocket) {
      try {
        nextSocket.close();
      } catch {
        // onclose/reconnect is best-effort; REST remains authoritative.
      }
    }
  };

  nextSocket.onclose = () => {
    const isCurrent =
      hub.socket === nextSocket &&
      generation === hub.socketGeneration;
    const intentional = hub.intentionallyClosing.has(nextSocket);

    if (!isCurrent) {
      return;
    }

    hub.socket = null;
    const wasConnected = hub.transportConnected;
    hub.transportConnected = false;

    if (!intentional && (wasConnected || hub.listeners.size > 0)) {
      emit({
        type: "runtime.transport.disconnected",
        connected: false,
        timestamp: new Date().toISOString(),
      });
    }

    if (!intentional) {
      scheduleReconnect();
    }
  };
}

function closeRuntimeConnectionIfStillUnused() {
  hub.disconnectTimer = null;

  if (hub.listeners.size > 0) return;

  clearRetryTimer();

  const current = hub.socket;
  hub.socket = null;
  hub.transportConnected = false;

  if (!current) return;

  hub.intentionallyClosing.add(current);

  try {
    current.close();
  } catch {
    // The renderer is shutting down; nothing else needs to happen.
  }
}

function scheduleDisconnectIfUnused() {
  if (hub.listeners.size > 0 || hub.disconnectTimer !== null) return;

  /*
   * Do not close immediately. React.StrictMode removes every effect and then
   * re-subscribes moments later in development. The grace period lets that
   * replay reuse the same socket instead of opening a second one.
   */
  hub.disconnectTimer = window.setTimeout(
    closeRuntimeConnectionIfStillUnused,
    UNUSED_DISCONNECT_GRACE_MS,
  );
}

export function subscribeRuntimeEvents(
  listener: RuntimeListener,
): () => void {
  clearDisconnectTimer();
  hub.listeners.add(listener);
  ensureRuntimeConnection();

  if (hub.latestEvent) {
    queueMicrotask(() => {
      if (hub.listeners.has(listener) && hub.latestEvent) {
        listener(hub.latestEvent);
      }
    });
  }

  return () => {
    hub.listeners.delete(listener);
    scheduleDisconnectIfUnused();
  };
}

export function runtimeTransportConnected(): boolean {
  return hub.transportConnected;
}

export function useRuntimeEvents(fallback: JaceRuntimeState) {
  const [state, setState] = useState<JaceRuntimeState>(fallback);
  const [connected, setConnected] = useState(runtimeTransportConnected());
  const [lastEvent, setLastEvent] = useState<RuntimeEvent | null>(
    hub.latestEvent,
  );

  useEffect(() => {
    return subscribeRuntimeEvents((event) => {
      setLastEvent(event);

      if (event.type === "runtime.transport.connected") {
        setConnected(true);
        return;
      }

      if (event.type === "runtime.transport.disconnected") {
        setConnected(false);
        return;
      }

      if (
        event.type === "jace.state.changed" &&
        event.state
      ) {
        setState(event.state);
      }

      if (
        event.type === "runtime.snapshot" &&
        event.state
      ) {
        setState(event.state);
        setConnected(true);
      }
    });
  }, []);

  useEffect(() => {
    if (!connected) {
      setState(fallback);
    }
  }, [fallback, connected]);

  return useMemo(
    () => ({ state, connected, lastEvent }),
    [state, connected, lastEvent],
  );
}
