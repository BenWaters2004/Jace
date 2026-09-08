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
}

function websocketUrl(): string {
  const base = new URL(API_BASE_URL);
  const protocol = base.protocol === "https:" ? "wss:" : "ws:";
  return `${protocol}//${base.host}/runtime/events`;
}

export function useRuntimeEvents(fallback: JaceRuntimeState) {
  const [state, setState] = useState<JaceRuntimeState>(fallback);
  const [connected, setConnected] = useState(false);
  const [lastEvent, setLastEvent] = useState<RuntimeEvent | null>(null);

  useEffect(() => {
    let socket: WebSocket | null = null;
    let retryTimer: number | null = null;
    let closed = false;

    const connect = () => {
      if (closed) return;
      socket = new WebSocket(websocketUrl());
      socket.onopen = () => setConnected(true);
      socket.onmessage = (message) => {
        try {
          const event = JSON.parse(message.data) as RuntimeEvent;
          setLastEvent(event);
          if (event.type === "jace.state.changed" && event.state) setState(event.state);
          if (event.type === "runtime.snapshot" && event.state) setState(event.state);
        } catch {
          // Presentation events are best-effort. REST/chat state remains authoritative.
        }
      };
      socket.onerror = () => socket?.close();
      socket.onclose = () => {
        setConnected(false);
        if (!closed) retryTimer = window.setTimeout(connect, 2500);
      };
    };

    connect();
    return () => {
      closed = true;
      if (retryTimer !== null) window.clearTimeout(retryTimer);
      socket?.close();
    };
  }, []);

  useEffect(() => {
    if (!connected) setState(fallback);
  }, [fallback, connected]);

  return useMemo(() => ({ state, connected, lastEvent }), [state, connected, lastEvent]);
}
