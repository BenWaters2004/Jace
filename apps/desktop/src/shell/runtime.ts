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

const listeners = new Set<RuntimeListener>();

let socket: WebSocket | null = null;
let retryTimer: number | null = null;
let transportConnected = false;
let closingBecauseUnused = false;
let latestEvent: RuntimeEvent | null = null;

function websocketUrl(): string {
  const base = new URL(API_BASE_URL);
  const protocol = base.protocol === "https:" ? "wss:" : "ws:";
  return `${protocol}//${base.host}/runtime/events`;
}

function emit(event: RuntimeEvent) {
  latestEvent = event;

  for (const listener of listeners) {
    try {
      listener(event);
    } catch {
      // A presentation subscriber must never break the shared runtime stream.
    }
  }
}

function clearRetryTimer() {
  if (retryTimer !== null) {
    window.clearTimeout(retryTimer);
    retryTimer = null;
  }
}

function scheduleReconnect() {
  if (listeners.size === 0 || retryTimer !== null) return;

  retryTimer = window.setTimeout(() => {
    retryTimer = null;
    ensureRuntimeConnection();
  }, 1500);
}

function ensureRuntimeConnection() {
  if (listeners.size === 0) return;

  if (
    socket &&
    (
      socket.readyState === WebSocket.CONNECTING ||
      socket.readyState === WebSocket.OPEN
    )
  ) {
    return;
  }

  clearRetryTimer();
  closingBecauseUnused = false;

  const nextSocket = new WebSocket(websocketUrl());
  socket = nextSocket;

  nextSocket.onopen = () => {
    if (socket !== nextSocket) return;

    transportConnected = true;

    emit({
      type: "runtime.transport.connected",
      connected: true,
      timestamp: new Date().toISOString(),
    });
  };

  nextSocket.onmessage = (message) => {
    if (socket !== nextSocket) return;

    try {
      const event = JSON.parse(message.data) as RuntimeEvent;
      emit(event);
    } catch {
      // REST state remains authoritative if a presentation message is malformed.
    }
  };

  nextSocket.onerror = () => {
    if (socket === nextSocket) {
      nextSocket.close();
    }
  };

  nextSocket.onclose = () => {
    if (socket === nextSocket) {
      socket = null;
    }

    const wasConnected = transportConnected;
    transportConnected = false;

    if (wasConnected || !closingBecauseUnused) {
      emit({
        type: "runtime.transport.disconnected",
        connected: false,
        timestamp: new Date().toISOString(),
      });
    }

    if (!closingBecauseUnused) {
      scheduleReconnect();
    }
  };
}

function disconnectIfUnused() {
  if (listeners.size > 0) return;

  clearRetryTimer();
  closingBecauseUnused = true;

  const current = socket;
  socket = null;
  transportConnected = false;

  if (current) {
    current.close();
  }
}

export function subscribeRuntimeEvents(
  listener: RuntimeListener,
): () => void {
  listeners.add(listener);
  ensureRuntimeConnection();

  if (latestEvent) {
    queueMicrotask(() => {
      if (listeners.has(listener) && latestEvent) {
        listener(latestEvent);
      }
    });
  }

  return () => {
    listeners.delete(listener);
    disconnectIfUnused();
  };
}

export function runtimeTransportConnected(): boolean {
  return transportConnected;
}

export function useRuntimeEvents(fallback: JaceRuntimeState) {
  const [state, setState] =
    useState<JaceRuntimeState>(fallback);
  const [connected, setConnected] =
    useState(runtimeTransportConnected());
  const [lastEvent, setLastEvent] =
    useState<RuntimeEvent | null>(latestEvent);

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
