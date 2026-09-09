import { useEffect, useMemo, useRef, useState, type CSSProperties } from "react";
import type { JaceRuntimeState } from "./runtime";
import type { ToolActivity } from "../types";
import "./JaceCore.css";

const LABELS: Record<JaceRuntimeState, string> = {
  offline: "Offline",
  idle: "Ready",
  listening: "Listening",
  transcribing: "Transcribing",
  thinking: "Thinking",
  speaking: "Speaking",
  working: "Working",
  waiting_permission: "Needs approval",
  warning: "Attention",
};

const STATUS_COPY: Record<JaceRuntimeState, string> = {
  offline: "Core link unavailable",
  idle: "Standing by for your next request",
  listening: "Drawing your voice inward",
  transcribing: "Decoding speech into text",
  thinking: "Branching through context and intent",
  speaking: "Projecting a response outward",
  working: "Dispatching tools and sub-agents",
  waiting_permission: "Holding for your confirmation",
  warning: "Something needs your attention",
};

/* Fragments assembled into fast-changing pseudo-telemetry while the core thinks. */
const DATA_HEAD = ["JACE", "CTX", "TOK", "VEC", "MEM", "PLAN", "TOOL", "NODE", "SYN", "RTE"];
const HEX = "0123456789ABCDEF";

function randomToken(): string {
  const head = DATA_HEAD[Math.floor(Math.random() * DATA_HEAD.length)];
  const len = 4 + Math.floor(Math.random() * 5);
  let body = "";
  for (let i = 0; i < len; i += 1) body += HEX[Math.floor(Math.random() * 16)];
  return `${head}·${body}`;
}

function coreGlyphFor(state: JaceRuntimeState): string {
  if (state === "waiting_permission") return "HOLD";
  if (state === "warning") return "ALERT";
  if (state === "offline") return "----";
  return "JACE";
}

const SPOKES = Array.from({ length: 16 }, (_, index) => index);
const PARTICLES = Array.from({ length: 44 }, (_, index) => index);
const ORBIT_LAYERS = [
  { cls: "orbit-1", sats: 3 },
  { cls: "orbit-2", sats: 2 },
  { cls: "orbit-3", sats: 4 },
  { cls: "orbit-4", sats: 2 },
  { cls: "orbit-5", sats: 3 },
];
const MESH_NODES = Array.from({ length: 9 }, (_, index) => index);
const DATA_SLOTS = Array.from({ length: 5 }, (_, index) => index);

export function JaceCore(props: {
  name: string;
  state: JaceRuntimeState;
  model: string;
  runtimeConnected: boolean;
  amplitude?: number;
  activities?: ToolActivity[];
  onExpand: () => void;
}) {
  const { state } = props;
  const amplitude = Math.max(0, Math.min(1, props.amplitude ?? 0));
  const showWave = state === "listening" || state === "speaking" || state === "transcribing";
  const isDataState = state === "thinking" || state === "working";

  const [dataStrings, setDataStrings] = useState<string[]>(() => DATA_SLOTS.map(() => randomToken()));
  const [glyph, setGlyph] = useState(() => coreGlyphFor(state));

  /* Fast, randomised JACE telemetry only churns while the core is reasoning. */
  useEffect(() => {
    if (!isDataState) {
      setDataStrings(DATA_SLOTS.map(() => randomToken()));
      return;
    }
    const timer = window.setInterval(() => {
      setDataStrings((prev) => {
        const next = prev.slice();
        const hits = 1 + Math.floor(Math.random() * 2);
        for (let i = 0; i < hits; i += 1) next[Math.floor(Math.random() * next.length)] = randomToken();
        return next;
      });
    }, 90);
    return () => window.clearInterval(timer);
  }, [isDataState]);

  /* Transcribing decodes the centre glyph character by character. */
  const decodeRef = useRef<number | null>(null);
  useEffect(() => {
    if (decodeRef.current) window.clearInterval(decodeRef.current);
    const target = coreGlyphFor(state);
    if (state !== "transcribing") {
      setGlyph(target);
      return;
    }
    decodeRef.current = window.setInterval(() => {
      setGlyph(
        target
          .split("")
          .map((char, i) => (Math.random() > 0.35 + i * 0.14 ? HEX[Math.floor(Math.random() * 16)] : char))
          .join(""),
      );
    }, 70);
    return () => {
      if (decodeRef.current) window.clearInterval(decodeRef.current);
    };
  }, [state]);

  /* Recent tool / sub-agent actions light up individual spokes as they propagate. */
  const activeSpokes = useMemo(() => {
    const recent = (props.activities ?? []).slice(-6);
    return recent.map((activity, index) => ({
      key: activity.callId ?? `act-${index}`,
      spoke: (index * 5 + 2) % SPOKES.length,
      status: activity.status,
      label: activity.label,
    }));
  }, [props.activities]);

  const waveformBars = Array.from({ length: 23 }, (_, index) => index);
  const stageStyle = {
    "--voice-level": amplitude.toFixed(3),
  } as CSSProperties;

  return (
    <section className={`cc-panel jace-core-panel state-${state}`}>
      <div className="cc-panel-topline">
        <div>
          <span className="cc-kicker">Neural core</span>
          <strong>{LABELS[state]}</strong>
        </div>
        <button className="cc-icon-button" onClick={props.onExpand} title="Focus Jace core">
          ⤢
        </button>
      </div>

      <div className={`jace-core-stage mode-${state}`} style={stageStyle} aria-label={`${props.name} ${LABELS[state]}`}>
        <div className="core-vignette" />
        <div className="core-grid" />

        {/* Drifting background particle / node field */}
        <div className="core-particles" aria-hidden="true">
          {PARTICLES.map((index) => {
            const style = {
              left: `${(index * 47) % 100}%`,
              top: `${(index * 73) % 100}%`,
              "--pd": `${(index % 9) * 0.7}s`,
              "--pdur": `${7 + (index % 6) * 1.6}s`,
              "--psize": `${1 + (index % 4)}px`,
            } as CSSProperties;
            return <span key={`particle-${index}`} className={`core-particle p-${index % 6}`} style={style} />;
          })}
        </div>

        {/* Network mesh with travelling pulses */}
        <svg className="core-mesh" viewBox="0 0 400 300" preserveAspectRatio="xMidYMid slice" aria-hidden="true">
          <defs>
            <radialGradient id="jaceMeshGlow" cx="50%" cy="50%" r="50%">
              <stop offset="0%" stopColor="var(--jc-accent)" stopOpacity="0.5" />
              <stop offset="100%" stopColor="var(--jc-accent)" stopOpacity="0" />
            </radialGradient>
          </defs>
          <g className="mesh-links">
            {MESH_NODES.map((node) => {
              const angle = (node / MESH_NODES.length) * Math.PI * 2;
              const x = 200 + Math.cos(angle) * (110 + (node % 3) * 26);
              const y = 150 + Math.sin(angle) * (78 + (node % 4) * 16);
              const nx = 200 + Math.cos(angle + 0.7) * 150;
              const ny = 150 + Math.sin(angle + 0.7) * 104;
              return (
                <g key={`mesh-${node}`}>
                  <line className="mesh-link" x1="200" y1="150" x2={x} y2={y} />
                  <line className="mesh-link faint" x1={x} y1={y} x2={nx} y2={ny} />
                  <circle className="mesh-node" cx={x} cy={y} r={2.2 + (node % 3)} style={{ animationDelay: `${node * 0.32}s` }} />
                  <circle
                    className="mesh-pulse"
                    r="2.6"
                    cx="200"
                    cy="150"
                    style={{ "--mx": `${x - 200}px`, "--my": `${y - 150}px`, animationDelay: `${node * 0.5}s` } as CSSProperties}
                  />
                </g>
              );
            })}
          </g>
        </svg>

        {/* Radial spokes — carry inward/outward energy and tool propagation */}
        <div className="core-spokes" aria-hidden="true">
          {SPOKES.map((index) => {
            const hit = activeSpokes.find((entry) => entry.spoke === index);
            const style = {
              "--a": `${(index / SPOKES.length) * 360}deg`,
              "--sd": `${(index % 8) * 0.28}s`,
              "--slen": `${64 + (index % 5) * 10}%`,
            } as CSSProperties;
            return (
              <div
                key={`spoke-${index}`}
                className={`core-spoke${hit ? ` active status-${hit.status}` : ""}`}
                style={style}
              >
                <span className="spoke-line" />
                <span className="spoke-shuttle" />
                {hit && <span className="spoke-burst" />}
              </div>
            );
          })}
        </div>

        {/* Concentric orbit layers with satellites */}
        <div className="core-orbits" aria-hidden="true">
          {ORBIT_LAYERS.map((layer) => (
            <div key={layer.cls} className={`core-orbit ${layer.cls}`}>
              {Array.from({ length: layer.sats }, (_, sat) => (
                <span key={sat} className="orbit-sat" style={{ "--sat": `${(360 / layer.sats) * sat}deg` } as CSSProperties} />
              ))}
            </div>
          ))}
        </div>

        {/* Emitted concentric shock rings (outward while speaking / working) */}
        <div className="core-emitters" aria-hidden="true">
          <span className="emit-ring e1" />
          <span className="emit-ring e2" />
          <span className="emit-ring e3" />
        </div>

        <div className="core-ring ring-outer" />
        <div className="core-ring ring-mid" />
        <div className="core-ring ring-inner" />
        <div className="core-scanline" />

        {/* Cycling JACE data strings while thinking */}
        <div className={`core-datastream${isDataState ? " on" : ""}`} aria-hidden="true">
          {dataStrings.map((value, index) => (
            <span key={`data-${index}`} className={`data-line dl-${index}`}>
              {value}
            </span>
          ))}
        </div>

        <div className="core-center">
          <div className="core-center-frame">
            {showWave ? (
              <div className={`core-waveform wave-${state}`} aria-hidden="true">
                {waveformBars.map((index) => {
                  const centreBias = 1 - Math.abs(index - (waveformBars.length - 1) / 2) / (waveformBars.length / 2);
                  const liveHeight =
                    state === "speaking" || state === "listening"
                      ? 7 + amplitude * (22 + centreBias * 26)
                      : 9 + centreBias * 13;
                  return (
                    <span
                      key={`wave-${index}`}
                      style={{
                        animationDelay: `${(index % 7) * 0.07}s`,
                        height: `${Math.max(7, liveHeight)}px`,
                        opacity: 0.55 + amplitude * 0.45,
                      }}
                    />
                  );
                })}
              </div>
            ) : (
              <div className={`core-display display-${state}`}>
                <span className="core-glyph">{glyph}</span>
              </div>
            )}
          </div>
          <span className="core-state">{LABELS[state]}</span>
        </div>

        <div className="core-caption-block">
          <span className="core-caption-label">State</span>
          <strong>{LABELS[state]}</strong>
          <small>{STATUS_COPY[state]}</small>
        </div>
      </div>

      <div className="core-footer">
        <span>{props.runtimeConnected ? "● LIVE EVENT LINK" : "○ EVENT FALLBACK"}</span>
        <span>{props.model || "No model"}</span>
      </div>
    </section>
  );
}
