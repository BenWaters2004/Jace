import { useEffect, useMemo, useRef, useState, type KeyboardEvent as ReactKeyboardEvent } from "react";
import type { JaceRuntimeState } from "./runtime";
import { JaceBoardEngine, type BoardVisualState, type JaceBoardSnapshot } from "./JaceBoardEngine";
import "./JaceCore.css";

const STATE_LABELS: Record<JaceRuntimeState, string> = {
  offline: "OFFLINE",
  idle: "IDLE",
  listening: "LISTENING",
  transcribing: "THINKING",
  thinking: "THINKING",
  speaking: "SPEAKING",
  working: "THINKING",
  waiting_permission: "THINKING",
  warning: "ATTENTION",
};

function toBoardState(state: JaceRuntimeState): BoardVisualState {
  if (state === "listening") return "listening";
  if (state === "speaking") return "speaking";
  if (state === "thinking" || state === "transcribing" || state === "working" || state === "waiting_permission") return "thinking";
  return "idle";
}

function dottedName(name: string) {
  const cleaned = (name || "JACE").replace(/[^a-z0-9]/gi, "").toUpperCase();
  if (/^[A-Z0-9]{2,10}$/.test(cleaned)) return `${cleaned.split("").join(".")}.`;
  return "J.A.C.E.";
}

function formatClock(date: Date) {
  return [date.getHours(), date.getMinutes(), date.getSeconds()].map((value) => String(value).padStart(2, "0")).join(":");
}

export function JaceCore(props: {
  name: string;
  state: JaceRuntimeState;
  model: string;
  runtimeConnected: boolean;
  amplitude?: number;
  onExpand: () => void;
}) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const engineRef = useRef<JaceBoardEngine | null>(null);
  const snapshotRef = useRef<JaceBoardSnapshot>({
    state: "idle",
    displayState: "IDLE",
    level: 0,
    alert: false,
    connected: props.runtimeConnected,
    label: dottedName(props.name),
  });
  const [clock, setClock] = useState(() => formatClock(new Date()));

  const snapshot = useMemo<JaceBoardSnapshot>(() => ({
    state: toBoardState(props.state),
    displayState: STATE_LABELS[props.state],
    level: Math.max(0, Math.min(1, props.amplitude ?? 0)),
    alert: props.state === "warning" || props.state === "offline",
    connected: props.runtimeConnected,
    label: dottedName(props.name),
  }), [props.state, props.amplitude, props.runtimeConnected, props.name]);

  snapshotRef.current = snapshot;

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const engine = new JaceBoardEngine({ canvas, getSnapshot: () => snapshotRef.current, seed: 7 });
    engineRef.current = engine;
    engine.start();
    return () => {
      engine.destroy();
      engineRef.current = null;
    };
  }, []);

  useEffect(() => {
    const timer = window.setInterval(() => setClock(formatClock(new Date())), 1000);
    return () => window.clearInterval(timer);
  }, []);

  return (
    <section
      className={`cc-panel jace-core-panel jace-ai-visualizer state-${props.state}`}
      aria-label={`${props.name} neural link ${STATE_LABELS[props.state]}`}
      onDoubleClick={props.onExpand}
      onKeyDown={(event: ReactKeyboardEvent<HTMLElement>) => {
        if (event.key === " " || event.key === "c" || event.key === "C") {
          event.preventDefault();
          engineRef.current?.toggleCinematic();
        }
        if (event.key === "f" || event.key === "F") {
          event.preventDefault();
          props.onExpand();
        }
      }}
      tabIndex={0}
    >
      <canvas ref={canvasRef} className="jace-av-stage" />
      <div className="jace-av-vignette" />

      <div className="jace-av-hud" aria-hidden="true">
        <span className="jace-av-corner tl" />
        <span className="jace-av-corner tr" />
        <span className="jace-av-corner bl" />
        <span className="jace-av-corner br" />
        <span className="jace-av-square tl" />
        <span className="jace-av-square tr" />

        <div className="jace-av-brand">
          <div className="jace-av-brand-title">{dottedName(props.name)}</div>
          <div className="jace-av-brand-sub">NEURAL LINK - <b>{props.runtimeConnected ? "CONNECTED" : "FALLBACK"}</b></div>
        </div>

        <div className="jace-av-status">
          <div className="jace-av-state">
            {STATE_LABELS[props.state]}
            {(props.state === "thinking" || props.state === "working" || props.state === "transcribing" || props.state === "waiting_permission") && <span className="jace-av-spinner" />}
          </div>
          <div className="jace-av-clock">{clock}</div>
          <div className={`jace-av-orb ${props.state === "warning" || props.state === "offline" ? "alert" : ""}`} />
        </div>

        <div className="jace-av-bus">SIGNAL BUS - <span>{props.runtimeConnected ? "ONLINE" : "LOCAL"}</span></div>
        <div className="jace-av-hint">
          {props.state === "thinking" || props.state === "working" || props.state === "transcribing" || props.state === "waiting_permission"
            ? "PROCESSING..."
            : "SPACE - CINEMATIC FLYTHROUGH"}
        </div>
      </div>

      <button className="jace-av-focus-button" onClick={props.onExpand} title="Focus Jace visualizer" aria-label="Focus Jace visualizer">□</button>
    </section>
  );
}
