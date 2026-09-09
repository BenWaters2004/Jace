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

type PacketColor = "cyan" | "blue" | "violet" | "amber" | "mint";

type CircuitTrace = {
  id: string;
  points: Array<[number, number]>;
  color: PacketColor;
  delay: number;
  speed: number;
  nodeLabel: string;
};

/*
 * IMPORTANT:
 * The central hub occupies exactly:
 *   x = 310..690 in the SVG viewBox
 *   y = 185..335 in the SVG viewBox
 *
 * .neural-hub-shell uses those same percentages in CSS. This keeps the
 * circuit traces physically connected to the processor in normal and
 * fullscreen modes without state-dependent resizing.
 */
const CIRCUIT_TRACES: CircuitTrace[] = [
  { id: "t01", points: [[310, 210], [280, 210], [280, 174], [230, 174], [230, 128], [178, 128], [178, 78], [72, 78]], color: "cyan", delay: 0.15, speed: 3.5, nodeLabel: "MEM" },
  { id: "t02", points: [[310, 232], [258, 232], [258, 254], [204, 254], [204, 224], [118, 224], [118, 176], [32, 176]], color: "blue", delay: 1.0, speed: 4.0, nodeLabel: "NET" },
  { id: "t03", points: [[310, 256], [270, 256], [270, 300], [218, 300], [218, 354], [144, 354], [144, 420], [48, 420]], color: "violet", delay: 0.55, speed: 4.2, nodeLabel: "WEB" },
  { id: "t04", points: [[310, 280], [286, 280], [286, 328], [250, 328], [250, 392], [198, 392], [198, 470], [122, 470]], color: "amber", delay: 1.65, speed: 3.7, nodeLabel: "OPS" },

  { id: "t05", points: [[390, 185], [390, 150], [354, 150], [354, 104], [300, 104], [300, 56], [244, 56], [244, 18]], color: "mint", delay: 0.35, speed: 3.6, nodeLabel: "CTX" },
  { id: "t06", points: [[448, 185], [448, 132], [422, 132], [422, 78], [394, 78], [394, 24]], color: "cyan", delay: 1.05, speed: 4.1, nodeLabel: "SYS" },
  { id: "t07", points: [[552, 185], [552, 138], [586, 138], [586, 92], [640, 92], [640, 42], [718, 42], [718, 12]], color: "blue", delay: 1.8, speed: 3.8, nodeLabel: "LLM" },
  { id: "t08", points: [[610, 185], [610, 158], [664, 158], [664, 102], [738, 102], [738, 66], [836, 66], [836, 24]], color: "violet", delay: 0.55, speed: 4.15, nodeLabel: "RAG" },

  { id: "t09", points: [[690, 210], [724, 210], [724, 176], [776, 176], [776, 124], [852, 124], [852, 80], [970, 80]], color: "amber", delay: 1.35, speed: 3.85, nodeLabel: "MAIL" },
  { id: "t10", points: [[690, 234], [744, 234], [744, 270], [806, 270], [806, 226], [886, 226], [886, 184], [982, 184]], color: "cyan", delay: 0.25, speed: 3.45, nodeLabel: "CAL" },
  { id: "t11", points: [[690, 258], [736, 258], [736, 310], [786, 310], [786, 364], [858, 364], [858, 418], [972, 418]], color: "blue", delay: 1.6, speed: 4.05, nodeLabel: "FILE" },
  { id: "t12", points: [[690, 282], [724, 282], [724, 338], [756, 338], [756, 402], [812, 402], [812, 470], [902, 470]], color: "mint", delay: 0.75, speed: 4.3, nodeLabel: "AGT" },

  { id: "t13", points: [[410, 335], [410, 374], [374, 374], [374, 418], [332, 418], [332, 482], [286, 482]], color: "violet", delay: 1.15, speed: 3.8, nodeLabel: "LOG" },
  { id: "t14", points: [[468, 335], [468, 384], [446, 384], [446, 446], [420, 446], [420, 510]], color: "cyan", delay: 0.4, speed: 4.0, nodeLabel: "AUD" },
  { id: "t15", points: [[532, 335], [532, 378], [562, 378], [562, 430], [608, 430], [608, 482], [668, 482], [668, 516]], color: "amber", delay: 1.45, speed: 3.95, nodeLabel: "SAFE" },
  { id: "t16", points: [[590, 335], [590, 356], [636, 356], [636, 402], [702, 402], [702, 468], [742, 468], [742, 510]], color: "blue", delay: 0.65, speed: 4.2, nodeLabel: "CTRL" },
];

const CHIP_LAYOUT = [
  { x: 88, y: 106, w: 56, h: 36 },
  { x: 192, y: 310, w: 64, h: 42 },
  { x: 96, y: 370, w: 50, h: 32 },
  { x: 778, y: 142, w: 58, h: 40 },
  { x: 846, y: 292, w: 66, h: 42 },
  { x: 724, y: 408, w: 48, h: 32 },
  { x: 864, y: 428, w: 42, h: 28 },
  { x: 272, y: 76, w: 44, h: 30 },
];

const STATIC_BOARD_PATHS = [
  "M0 42 H92 V20 H164 V48 H246",
  "M0 478 H88 V448 H160 V470 H240",
  "M1000 46 H922 V24 H846 V52 H770",
  "M1000 476 H932 V446 H860 V468 H800",
  "M18 104 H54 V136 H94 V156 H150",
  "M982 112 H940 V142 H900 V164 H850",
  "M28 332 H88 V302 H146 V278 H188",
  "M972 344 H916 V314 H864 V286 H824",
  "M56 52 H56 V102 H100 V120",
  "M944 58 V104 H904 V126",
  "M64 246 H108 V270 H154 V248 H188",
  "M936 244 H894 V268 H842 V248 H816",
  "M264 18 V42 H286 V70",
  "M750 16 V44 H730 V72",
  "M252 500 V466 H280 V440",
  "M770 504 V472 H744 V444",
  "M170 188 H206 V164 H246",
  "M830 196 H798 V170 H760",
  "M154 442 H190 V420 H222",
  "M846 448 H812 V426 H782",
];

const DATA_CHARS = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789@$%#&+<>?/";

const PACKET_TAILS = [
  { offset: 0.045, r: 2.45, opacity: 0.58 },
  { offset: 0.085, r: 2.05, opacity: 0.38 },
  { offset: 0.125, r: 1.65, opacity: 0.24 },
  { offset: 0.165, r: 1.25, opacity: 0.13 },
];

function pointPath(points: Array<[number, number]>): string {
  return points.map(([x, y], index) => `${index === 0 ? "M" : "L"}${x} ${y}`).join(" ");
}

function flowDirection(state: JaceRuntimeState, index: number): "in" | "out" | "none" {
  if (state === "listening" || state === "transcribing") return "in";
  if (state === "speaking" || state === "working") return "out";
  if (state === "thinking") return index % 2 === 0 ? "in" : "out";

  // Idle should feel alive without looking busy. Only a few buses carry data.
  if (state === "idle") {
    if (index % 5 === 0) return "in";
    if (index % 7 === 0) return "out";
  }

  return "none";
}

function pulseSpeed(state: JaceRuntimeState, base: number): number {
  if (state === "listening" || state === "speaking") return Math.max(1.1, base * 0.44);
  if (state === "thinking" || state === "working") return Math.max(1.25, base * 0.52);
  if (state === "transcribing") return Math.max(1.4, base * 0.62);
  return base * 1.55;
}

function randomCoreText(): string {
  const groups = [3, 3, 3, 3];
  let result = "";

  for (let groupIndex = 0; groupIndex < groups.length; groupIndex += 1) {
    if (groupIndex > 0) result += ".";

    for (let index = 0; index < groups[groupIndex]; index += 1) {
      result += DATA_CHARS[Math.floor(Math.random() * DATA_CHARS.length)];
    }
  }

  return result;
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
    }, 86);

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
          <button
            className="cc-icon-button"
            onClick={props.onExpand}
            title="Focus Jace core"
            aria-label="Focus Jace core"
          >
            □
          </button>
        </div>
      </div>

      <div
        className={`neural-core-stage mode-${props.state}`}
        style={stageStyle}
        aria-label={`${props.name} ${LABELS[props.state]}`}
      >
        <div className="neural-board-substrate" />
        <div className="neural-board-weave" />
        <div className="neural-board-noise" />
        <div className="neural-board-vignette" />

        <svg
          className="neural-circuit-svg"
          viewBox="0 0 1000 520"
          preserveAspectRatio="none"
          aria-hidden="true"
        >
          <defs>
            <filter id="neuralPacketGlow" x="-120%" y="-120%" width="340%" height="340%">
              <feGaussianBlur stdDeviation="4.5" result="blur" />
              <feMerge>
                <feMergeNode in="blur" />
                <feMergeNode in="SourceGraphic" />
              </feMerge>
            </filter>
            <filter id="neuralPacketTailGlow" x="-100%" y="-100%" width="300%" height="300%">
              <feGaussianBlur stdDeviation="2.7" result="blur" />
              <feMerge>
                <feMergeNode in="blur" />
                <feMergeNode in="SourceGraphic" />
              </feMerge>
            </filter>
          </defs>

          <g className="neural-static-copper">
            {STATIC_BOARD_PATHS.map((path, index) => (
              <path key={`static-${index}`} d={path} />
            ))}
          </g>

          <g className="neural-pcb-components">
            {CHIP_LAYOUT.map((chip, index) => (
              <g key={`chip-${index}`} className="neural-chip">
                <rect x={chip.x} y={chip.y} width={chip.w} height={chip.h} rx="2" />
                <rect
                  className="neural-chip-inner"
                  x={chip.x + 6}
                  y={chip.y + 6}
                  width={Math.max(8, chip.w - 12)}
                  height={Math.max(8, chip.h - 12)}
                  rx="1"
                />
                {Array.from({ length: 5 }, (_, pin) => {
                  const pinX = chip.x + 6 + pin * ((chip.w - 12) / 4);
                  return (
                    <g key={`pins-${index}-${pin}`}>
                      <line x1={pinX} y1={chip.y - 5} x2={pinX} y2={chip.y} />
                      <line x1={pinX} y1={chip.y + chip.h} x2={pinX} y2={chip.y + chip.h + 5} />
                    </g>
                  );
                })}
              </g>
            ))}

            {Array.from({ length: 24 }, (_, index) => {
              const x = 64 + ((index * 151) % 868);
              const y = 48 + ((index * 91) % 424);
              return (
                <g key={`pad-${index}`} className="neural-solder-pad">
                  <rect x={x} y={y} width="10" height="5" rx="1" />
                  <rect x={x + 15} y={y} width="10" height="5" rx="1" />
                </g>
              );
            })}
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
                <g key={trace.id} className={`neural-trace packet-${trace.color} flow-${direction}`}>
                  <path className="neural-trace-shadow" d={outwardPath} />
                  <path className="neural-trace-line" d={outwardPath} />

                  <circle className="neural-end-node-halo" cx={endPoint[0]} cy={endPoint[1]} r="7" />
                  <circle className="neural-end-node" cx={endPoint[0]} cy={endPoint[1]} r="2.4" />
                  <text className="neural-node-label" x={endPoint[0] + 10} y={endPoint[1] - 7}>
                    {trace.nodeLabel}
                  </text>

                  {direction !== "none" && (
                    <>
                      {PACKET_TAILS.map((tail, tailIndex) => (
                        <circle
                          key={`${trace.id}-tail-${tailIndex}`}
                          className="neural-data-tail"
                          r={tail.r}
                          opacity={tail.opacity}
                          filter="url(#neuralPacketTailGlow)"
                        >
                          <animateMotion
                            path={activePath}
                            dur={`${duration}s`}
                            begin={`${trace.delay + tail.offset}s`}
                            repeatCount="indefinite"
                          />
                        </circle>
                      ))}

                      <circle className="neural-data-pulse" r="3.3" filter="url(#neuralPacketGlow)">
                        <animateMotion
                          path={activePath}
                          dur={`${duration}s`}
                          begin={`${trace.delay}s`}
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
            {Array.from({ length: 58 }, (_, index) => {
              const x = 40 + ((index * 137) % 920);
              const y = 24 + ((index * 83) % 468);
              const large = index % 9 === 0;

              return (
                <g key={`point-${index}`}>
                  {large && <circle className="neural-via-ring" cx={x} cy={y} r="4.5" />}
                  <circle className="neural-via" cx={x} cy={y} r={large ? 1.7 : 1.05} />
                </g>
              );
            })}
          </g>
        </svg>

        <div className="neural-corner corner-tl" />
        <div className="neural-corner corner-tr" />
        <div className="neural-corner corner-bl" />
        <div className="neural-corner corner-br" />

        <div className="neural-hud neural-hud-left">
          <span>SIGNAL INTAKE</span>
          {SYSTEM_LINES[props.state].map((line) => (
            <small key={line}>{line}</small>
          ))}
        </div>

        <div className="neural-hud neural-hud-right">
          <span>{STATE_MODE_COPY[props.state]}</span>
          <strong>{LABELS[props.state]}</strong>
          <small>{timeString}</small>
        </div>

        <div className="neural-core-glow" />

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
            {props.state === "listening" || props.state === "speaking" ? (
              <>
                <div className={`neural-waveform wave-${props.state}`} aria-hidden="true">
                  {waveformBars.map((index) => {
                    const centre = (waveformBars.length - 1) / 2;
                    const centreBias = 1 - Math.abs(index - centre) / (centre + 1);
                    const base = 7 + centreBias * 8;
                    const reactive = amplitude * (16 + centreBias * 30);
                    const wobble = ((index * 13) % 9) * 0.55;

                    return (
                      <span
                        key={`wave-${index}`}
                        style={{
                          height: `${Math.max(7, base + reactive + wobble)}px`,
                          animationDelay: `${(index % 7) * 0.045}s`,
                          opacity: 0.46 + amplitude * 0.54,
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
