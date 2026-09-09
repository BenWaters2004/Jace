import { useEffect, useMemo, useState, type CSSProperties } from "react";
import type { JaceRuntimeState } from "./runtime";
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
  listening: "Receiving voice input",
  transcribing: "Decoding local speech",
  thinking: "Processing context and intent",
  speaking: "Delivering a response",
  working: "Coordinating tools and agents",
  waiting_permission: "Awaiting your confirmation",
  warning: "A subsystem needs attention",
};

const STATE_MODE_COPY: Record<JaceRuntimeState, string> = {
  offline: "LINK LOST",
  idle: "STANDBY",
  listening: "SIGNAL IN",
  transcribing: "VOICE DECODE",
  thinking: "REASONING",
  speaking: "SIGNAL OUT",
  working: "EXECUTION",
  waiting_permission: "AUTH GATE",
  warning: "ALERT",
};

const SYSTEM_LINES: Record<JaceRuntimeState, string[]> = {
  offline: ["LOCAL CORE", "RUNTIME", "TOOLS", "MEMORY"],
  idle: ["MEMORY", "TOOLS", "AGENTS", "NETWORK"],
  listening: ["MICROPHONE", "VOICE LEVEL", "LOCAL STT", "CONTEXT"],
  transcribing: ["WHISPER", "LANGUAGE", "TIMING", "TRANSCRIPT"],
  thinking: ["CONTEXT", "MEMORY", "REASONING", "ROUTING"],
  speaking: ["RESPONSE", "KOKORO", "AUDIO", "PLAYBACK"],
  working: ["TOOLS", "AGENTS", "POLICIES", "AUDIT"],
  waiting_permission: ["ACTION", "RISK", "SCOPE", "APPROVAL"],
  warning: ["EVENT", "RUNTIME", "POLICY", "RECOVERY"],
};

type CircuitTrace = {
  id: string;
  points: Array<[number, number]>;
  color: "cyan" | "blue" | "violet" | "amber" | "mint";
  delay: number;
  speed: number;
  nodeLabel: string;
};

const CIRCUIT_TRACES: CircuitTrace[] = [
  { id: "t01", points: [[346, 220], [310, 220], [310, 188], [258, 188], [258, 126], [198, 126], [198, 78], [88, 78]], color: "cyan", delay: 0.2, speed: 3.6, nodeLabel: "MEM" },
  { id: "t02", points: [[346, 245], [286, 245], [286, 270], [218, 270], [218, 236], [126, 236], [126, 180], [38, 180]], color: "blue", delay: 1.3, speed: 4.1, nodeLabel: "NET" },
  { id: "t03", points: [[346, 274], [304, 274], [304, 316], [242, 316], [242, 382], [156, 382], [156, 446], [62, 446]], color: "violet", delay: 0.8, speed: 4.5, nodeLabel: "WEB" },
  { id: "t04", points: [[346, 302], [320, 302], [320, 356], [282, 356], [282, 430], [228, 430], [228, 492], [160, 492]], color: "amber", delay: 1.9, speed: 3.9, nodeLabel: "OPS" },
  { id: "t05", points: [[402, 195], [402, 154], [368, 154], [368, 108], [316, 108], [316, 58], [262, 58], [262, 22]], color: "mint", delay: 0.5, speed: 3.7, nodeLabel: "CTX" },
  { id: "t06", points: [[454, 195], [454, 132], [430, 132], [430, 76], [402, 76], [402, 26]], color: "cyan", delay: 1.1, speed: 4.4, nodeLabel: "SYS" },
  { id: "t07", points: [[510, 195], [510, 144], [548, 144], [548, 98], [604, 98], [604, 42], [690, 42], [690, 12]], color: "blue", delay: 2.0, speed: 3.8, nodeLabel: "LLM" },
  { id: "t08", points: [[570, 195], [570, 164], [628, 164], [628, 104], [710, 104], [710, 68], [814, 68], [814, 26]], color: "violet", delay: 0.6, speed: 4.3, nodeLabel: "RAG" },
  { id: "t09", points: [[654, 220], [702, 220], [702, 180], [758, 180], [758, 126], [846, 126], [846, 82], [960, 82]], color: "amber", delay: 1.5, speed: 4.0, nodeLabel: "MAIL" },
  { id: "t10", points: [[654, 248], [718, 248], [718, 282], [786, 282], [786, 234], [870, 234], [870, 190], [980, 190]], color: "cyan", delay: 0.3, speed: 3.6, nodeLabel: "CAL" },
  { id: "t11", points: [[654, 276], [706, 276], [706, 330], [758, 330], [758, 386], [842, 386], [842, 438], [964, 438]], color: "blue", delay: 1.8, speed: 4.2, nodeLabel: "FILE" },
  { id: "t12", points: [[654, 304], [692, 304], [692, 360], [724, 360], [724, 426], [784, 426], [784, 494], [876, 494]], color: "mint", delay: 0.9, speed: 4.5, nodeLabel: "AGT" },
  { id: "t13", points: [[430, 325], [430, 372], [396, 372], [396, 420], [352, 420], [352, 486], [310, 486]], color: "violet", delay: 1.4, speed: 3.9, nodeLabel: "LOG" },
  { id: "t14", points: [[486, 325], [486, 382], [462, 382], [462, 446], [438, 446], [438, 510]], color: "cyan", delay: 0.4, speed: 4.1, nodeLabel: "AUD" },
  { id: "t15", points: [[542, 325], [542, 376], [574, 376], [574, 430], [620, 430], [620, 482], [680, 482], [680, 516]], color: "amber", delay: 1.7, speed: 4.0, nodeLabel: "SAFE" },
  { id: "t16", points: [[596, 325], [596, 352], [646, 352], [646, 400], [714, 400], [714, 468], [752, 468], [752, 510]], color: "blue", delay: 0.7, speed: 4.4, nodeLabel: "CTRL" },
];

const CHIP_LAYOUT = [
  { x: 105, y: 112, w: 52, h: 34 },
  { x: 205, y: 322, w: 64, h: 42 },
  { x: 116, y: 388, w: 48, h: 30 },
  { x: 760, y: 152, w: 56, h: 38 },
  { x: 838, y: 306, w: 66, h: 42 },
  { x: 730, y: 418, w: 48, h: 32 },
  { x: 850, y: 430, w: 40, h: 26 },
  { x: 280, y: 82, w: 42, h: 28 },
];

const DATA_CHARS = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789@$%#&+<>?/";

function pointPath(points: Array<[number, number]>): string {
  return points.map(([x, y], index) => `${index === 0 ? "M" : "L"}${x} ${y}`).join(" ");
}

function flowDirection(state: JaceRuntimeState, index: number): "in" | "out" | "none" {
  if (state === "listening" || state === "transcribing") return "in";
  if (state === "speaking" || state === "working") return "out";
  if (state === "thinking") return index % 2 === 0 ? "in" : "out";
  if (state === "idle") return index % 3 === 0 ? "out" : "in";
  return "none";
}

function pulseSpeed(state: JaceRuntimeState, base: number): number {
  if (state === "listening" || state === "speaking") return Math.max(1.15, base * 0.45);
  if (state === "thinking" || state === "working") return Math.max(1.35, base * 0.55);
  if (state === "transcribing") return Math.max(1.5, base * 0.68);
  return base * 1.45;
}

function randomCoreText(length = 13): string {
  const groups = [3, 3, 3, 3];
  let result = "";
  for (let groupIndex = 0; groupIndex < groups.length; groupIndex += 1) {
    if (groupIndex > 0) result += ".";
    for (let index = 0; index < groups[groupIndex]; index += 1) {
      result += DATA_CHARS[Math.floor(Math.random() * DATA_CHARS.length)];
    }
  }
  return result.slice(0, length + 3);
}

function displayForState(state: JaceRuntimeState, changingText: string): string {
  switch (state) {
    case "thinking":
      return changingText;
    case "transcribing":
      return "DECODING";
    case "working":
      return "EXECUTING";
    case "waiting_permission":
      return "AUTH REQUIRED";
    case "warning":
      return "ATTENTION";
    case "offline":
      return "OFFLINE";
    default:
      return "J.A.C.E.";
  }
}

export function JaceCore(props: {
  name: string;
  state: JaceRuntimeState;
  model: string;
  runtimeConnected: boolean;
  amplitude?: number;
  onExpand: () => void;
}) {
  const [changingText, setChangingText] = useState(() => randomCoreText());
  const [clock, setClock] = useState(() => new Date());

  const amplitude = Math.max(0, Math.min(1, props.amplitude ?? 0));
  const waveformBars = useMemo(() => Array.from({ length: 25 }, (_, index) => index), []);
  const visibleDisplay = displayForState(props.state, changingText);

  useEffect(() => {
    if (props.state !== "thinking") return;

    const timer = window.setInterval(() => {
      setChangingText(randomCoreText());
    }, 92);

    return () => window.clearInterval(timer);
  }, [props.state]);

  useEffect(() => {
    const timer = window.setInterval(() => setClock(new Date()), 1000);
    return () => window.clearInterval(timer);
  }, []);

  const stageStyle = {
    "--voice-level": amplitude.toFixed(3),
  } as CSSProperties;

  const timeString = clock.toLocaleTimeString([], {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });

  return (
    <section className={`cc-panel jace-core-panel neural-core-panel state-${props.state}`}>
      <div className="cc-panel-topline neural-core-topline">
        <div>
          <span className="cc-kicker">Neural core</span>
          <strong>{LABELS[props.state]}</strong>
        </div>
        <div className="neural-core-top-actions">
          <span className={`neural-link-badge ${props.runtimeConnected ? "online" : "fallback"}`}>
            {props.runtimeConnected ? "● EVENT LINK" : "○ FALLBACK"}
          </span>
          <button className="cc-icon-button" onClick={props.onExpand} title="Focus Jace core" aria-label="Focus Jace core">
            □
          </button>
        </div>
      </div>

      <div
        className={`neural-core-stage mode-${props.state}`}
        style={stageStyle}
        aria-label={`${props.name} ${LABELS[props.state]}`}
      >
        <div className="neural-board-noise" />
        <div className="neural-board-grid" />
        <div className="neural-board-vignette" />

        <svg
          className="neural-circuit-svg"
          viewBox="0 0 1000 520"
          preserveAspectRatio="none"
          aria-hidden="true"
        >
          <defs>
            <filter id="neuralGlowCyan" x="-70%" y="-70%" width="240%" height="240%">
              <feGaussianBlur stdDeviation="3.5" result="blur" />
              <feMerge>
                <feMergeNode in="blur" />
                <feMergeNode in="SourceGraphic" />
              </feMerge>
            </filter>
            <filter id="neuralGlowHot" x="-100%" y="-100%" width="300%" height="300%">
              <feGaussianBlur stdDeviation="5.5" result="blur" />
              <feMerge>
                <feMergeNode in="blur" />
                <feMergeNode in="SourceGraphic" />
              </feMerge>
            </filter>
            <linearGradient id="coreFrameGradient" x1="0" y1="0" x2="1" y2="1">
              <stop offset="0" stopColor="rgba(126,238,255,.86)" />
              <stop offset="0.48" stopColor="rgba(63,194,255,.64)" />
              <stop offset="1" stopColor="rgba(118,111,255,.46)" />
            </linearGradient>
          </defs>

          <g className="neural-static-copper">
            <path d="M0 44 H92 V22 H174 V52 H250" />
            <path d="M0 472 H104 V438 H178 V456 H250" />
            <path d="M1000 54 H924 V30 H846 V58 H770" />
            <path d="M1000 472 H930 V444 H864 V466 H806" />
            <path d="M18 110 H54 V142 H96" />
            <path d="M982 118 H940 V146 H900" />
            <path d="M34 338 H92 V306 H152" />
            <path d="M966 350 H910 V318 H864" />
          </g>

          <g className="neural-chip-layer">
            {CHIP_LAYOUT.map((chip, index) => (
              <g key={`chip-${index}`} className="neural-chip">
                <rect x={chip.x} y={chip.y} width={chip.w} height={chip.h} rx="2" />
                {Array.from({ length: 5 }, (_, pin) => (
                  <g key={`pins-${index}-${pin}`}>
                    <line x1={chip.x + 6 + pin * ((chip.w - 12) / 4)} y1={chip.y - 5} x2={chip.x + 6 + pin * ((chip.w - 12) / 4)} y2={chip.y} />
                    <line x1={chip.x + 6 + pin * ((chip.w - 12) / 4)} y1={chip.y + chip.h} x2={chip.x + 6 + pin * ((chip.w - 12) / 4)} y2={chip.y + chip.h + 5} />
                  </g>
                ))}
              </g>
            ))}
          </g>

          <g className="neural-traces">
            {CIRCUIT_TRACES.map((trace, index) => {
              const outwardPath = pointPath(trace.points);
              const inwardPath = pointPath([...trace.points].reverse());
              const direction = flowDirection(props.state, index);
              const activePath = direction === "in" ? inwardPath : outwardPath;
              const endPoint = trace.points[trace.points.length - 1];
              const duration = pulseSpeed(props.state, trace.speed);

              return (
                <g key={trace.id} className={`neural-trace trace-${trace.color} flow-${direction}`}>
                  <path className="neural-trace-shadow" d={outwardPath} />
                  <path className="neural-trace-line" d={outwardPath} />
                  <circle className="neural-end-node-halo" cx={endPoint[0]} cy={endPoint[1]} r="7" />
                  <circle className="neural-end-node" cx={endPoint[0]} cy={endPoint[1]} r="2.4" />
                  <text className="neural-node-label" x={endPoint[0] + 10} y={endPoint[1] - 7}>{trace.nodeLabel}</text>

                  {direction !== "none" && (
                    <>
                      <circle className="neural-data-pulse pulse-primary" r="3.2" filter="url(#neuralGlowHot)">
                        <animateMotion
                          path={activePath}
                          dur={`${duration}s`}
                          begin={`${trace.delay}s`}
                          repeatCount="indefinite"
                        />
                      </circle>
                      <circle className="neural-data-pulse pulse-secondary" r="1.8" filter="url(#neuralGlowCyan)">
                        <animateMotion
                          path={activePath}
                          dur={`${duration * 1.18}s`}
                          begin={`${trace.delay + duration * 0.48}s`}
                          repeatCount="indefinite"
                        />
                      </circle>
                    </>
                  )}
                </g>
              );
            })}
          </g>

          <g className="neural-board-points">
            {Array.from({ length: 44 }, (_, index) => {
              const x = 44 + ((index * 137) % 910);
              const y = 24 + ((index * 83) % 468);
              return <circle key={`point-${index}`} cx={x} cy={y} r={index % 7 === 0 ? 2.2 : 1.2} />;
            })}
          </g>
        </svg>

        <div className="neural-corner corner-tl" />
        <div className="neural-corner corner-tr" />
        <div className="neural-corner corner-bl" />
        <div className="neural-corner corner-br" />

        <div className="neural-hud neural-hud-left">
          <span>SIGNAL INTAKE</span>
          {SYSTEM_LINES[props.state].map((line) => <small key={line}>{line}</small>)}
        </div>

        <div className="neural-hud neural-hud-right">
          <span>{STATE_MODE_COPY[props.state]}</span>
          <strong>{LABELS[props.state]}</strong>
          <small>{timeString}</small>
        </div>

        <div className="neural-core-glow" />
        <div className="neural-core-halo halo-one" />
        <div className="neural-core-halo halo-two" />

        <div className="neural-hub-shell">
          <span className="neural-hub-pin pin-top" />
          <span className="neural-hub-pin pin-bottom" />
          <span className="neural-hub-pin pin-left" />
          <span className="neural-hub-pin pin-right" />

          <div className="neural-hub-header">
            <span>J.A.C.E. // CORE</span>
            <span>{props.runtimeConnected ? "LIVE" : "LOCAL"}</span>
          </div>

          <div className="neural-hub-content">
            {(props.state === "listening" || props.state === "speaking") ? (
              <>
                <div className={`neural-waveform wave-${props.state}`} aria-hidden="true">
                  {waveformBars.map((index) => {
                    const centre = (waveformBars.length - 1) / 2;
                    const centreBias = 1 - Math.abs(index - centre) / (centre + 1);
                    const base = 7 + centreBias * 8;
                    const reactive = amplitude * (18 + centreBias * 34);
                    const wobble = ((index * 13) % 9) * 0.65;
                    return (
                      <span
                        key={`wave-${index}`}
                        style={{
                          height: `${Math.max(7, base + reactive + wobble)}px`,
                          animationDelay: `${(index % 7) * 0.045}s`,
                          opacity: 0.48 + amplitude * 0.52,
                        }}
                      />
                    );
                  })}
                </div>
                <div className="neural-main-word audio-word">{visibleDisplay}</div>
              </>
            ) : (
              <div className={`neural-main-word state-word-${props.state}`}>{visibleDisplay}</div>
            )}

            <div className="neural-state-line">
              <span>{LABELS[props.state]}</span>
              <i />
              <small>{STATUS_COPY[props.state]}</small>
            </div>
          </div>

          <div className="neural-hub-footer">
            <span>{props.model || "NO MODEL"}</span>
            <span>{STATE_MODE_COPY[props.state]}</span>
          </div>
        </div>

        <div className="neural-scan-line" />
        <div className="neural-state-burst burst-a" />
        <div className="neural-state-burst burst-b" />
      </div>

      <div className="core-footer neural-core-footer">
        <span>{props.runtimeConnected ? "● LIVE EVENT LINK" : "○ EVENT FALLBACK"}</span>
        <span>{STATUS_COPY[props.state]}</span>
        <span>{props.model || "No model"}</span>
      </div>
    </section>
  );
}
