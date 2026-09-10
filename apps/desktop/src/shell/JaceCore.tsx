import { useEffect, useMemo, useState, type CSSProperties } from "react";
import type { JaceRuntimeState } from "./runtime";
import "./JaceCore.css";

/* --------------------------------------------------------------------------
   JACE core — dense PCB board with a lit centre nameplate.

   Geometry notes:
   - The board SVG uses a fixed 1000x560 viewBox with preserveAspectRatio
     "xMidYMid slice". Slice (not "none") is what keeps every 45-degree trace
     at a true 45 degrees whatever the panel aspect ratio is; the board simply
     crops at the edges like a real board extending past the window.
   - Traces run edge to edge and pass *behind* the nameplate rather than
     terminating at it, so no trace has to stay aligned with the HTML plate.
   -------------------------------------------------------------------------- */

const VIEW_W = 1000;
const VIEW_H = 560;
const GRID = 20;

const LABELS: Record<JaceRuntimeState, string> = {
  offline: "Offline",
  idle: "Standby",
  listening: "Listening",
  transcribing: "Transcribing",
  thinking: "Thinking",
  speaking: "Speaking",
  working: "Working",
  waiting_permission: "Approval",
  warning: "Attention",
};

type PacketColour = "cyan" | "blue" | "violet" | "amber" | "mint" | "danger";
type PacketDirection = "forward" | "reverse";

type Route = {
  id: string;
  d: string;
  colour: PacketColour;
  core?: boolean;
  delay?: number;
  speed?: number;
};

type Chip = {
  x: number;
  y: number;
  w: number;
  h: number;
  pins?: boolean;
  inner?: boolean;
};

function seededRandom(seed: number) {
  let value = seed >>> 0;
  return () => {
    value = (value * 1664525 + 1013904223) >>> 0;
    return value / 0xffffffff;
  };
}

const snap = (value: number) => Math.round(value / GRID) * GRID;

/*
 * Ambient copper. Routes favour long orthogonal runs with occasional 45-degree
 * jogs, which is what gives a real board its lattice look. Start points are
 * allowed off-canvas so traces bleed past every edge.
 */
function buildAmbientRoutes() {
  const random = seededRandom(0x4a414345);
  const routes: Array<{ d: string; weight: number }> = [];

  for (let index = 0; index < 104; index += 1) {
    let x = snap(-60 + random() * (VIEW_W + 120));
    let y = snap(-40 + random() * (VIEW_H + 80));
    const points = [`M ${x} ${y}`];
    const segments = 2 + Math.floor(random() * 4);

    for (let segment = 0; segment < segments; segment += 1) {
      const kind = random();

      if (kind < 0.44) {
        const length = GRID * (2 + Math.floor(random() * 8));
        x += random() > 0.5 ? length : -length;
        x = Math.max(-80, Math.min(VIEW_W + 80, x));
        points.push(`H ${x}`);
      } else if (kind < 0.8) {
        const length = GRID * (2 + Math.floor(random() * 6));
        y += random() > 0.5 ? length : -length;
        y = Math.max(-60, Math.min(VIEW_H + 60, y));
        points.push(`V ${y}`);
      } else {
        const length = GRID * (1 + Math.floor(random() * 4));
        x = Math.max(-80, Math.min(VIEW_W + 80, x + (random() > 0.5 ? length : -length)));
        y = Math.max(-60, Math.min(VIEW_H + 60, y + (random() > 0.5 ? length : -length)));
        points.push(`L ${x} ${y}`);
      }
    }

    routes.push({ d: points.join(" "), weight: index % 5 === 0 ? 2 : index % 3 === 0 ? 1 : 0 });
  }

  return routes;
}

/* A few long buses give the board some order behind the noise. */
function buildBusLines() {
  const random = seededRandom(0x0b0512);
  const lines: string[] = [];

  for (let index = 0; index < 10; index += 1) {
    if (random() > 0.5) {
      const y = snap(random() * VIEW_H);
      const x0 = snap(random() * VIEW_W * 0.4);
      lines.push(`M ${x0 - 90} ${y} H ${snap(x0 + 240 + random() * 320)}`);
    } else {
      const x = snap(random() * VIEW_W);
      const y0 = snap(random() * VIEW_H * 0.4);
      lines.push(`M ${x} ${y0 - 60} V ${snap(y0 + 190 + random() * 230)}`);
    }
  }

  return lines;
}

function buildPads() {
  const random = seededRandom(0x50434231);
  const pads: Array<{ x: number; y: number; r: number }> = [];

  for (let index = 0; index < 128; index += 1) {
    pads.push({
      x: 8 + random() * (VIEW_W - 16),
      y: 8 + random() * (VIEW_H - 16),
      r: random() > 0.82 ? 2.6 : 1.7,
    });
  }

  return pads;
}

const CHIPS: Chip[] = [
  { x: 58, y: 96, w: 62, h: 42, pins: true, inner: true },
  { x: 140, y: 300, w: 46, h: 34, inner: true },
  { x: 196, y: 96, w: 40, h: 34 },
  { x: 272, y: 268, w: 56, h: 44, pins: true, inner: true },
  { x: 300, y: 480, w: 62, h: 44, inner: true },
  { x: 424, y: 108, w: 54, h: 40, pins: true, inner: true },
  { x: 436, y: 372, w: 56, h: 34, inner: true },
  { x: 520, y: 356, w: 62, h: 46, pins: true },
  { x: 556, y: 490, w: 58, h: 42, inner: true },
  { x: 596, y: 132, w: 52, h: 40, pins: true, inner: true },
  { x: 620, y: 300, w: 58, h: 42, inner: true },
  { x: 700, y: 424, w: 54, h: 40, pins: true },
  { x: 712, y: 236, w: 48, h: 36, inner: true },
  { x: 724, y: 104, w: 60, h: 44, pins: true, inner: true },
  { x: 786, y: 132, w: 50, h: 38 },
  { x: 830, y: 220, w: 62, h: 46, inner: true },
  { x: 846, y: 350, w: 58, h: 42, pins: true, inner: true },
  { x: 868, y: 470, w: 56, h: 40, inner: true },
  { x: 928, y: 120, w: 54, h: 40, pins: true },
  { x: 940, y: 300, w: 60, h: 44, inner: true },
  { x: 66, y: 430, w: 66, h: 44, pins: true, inner: true },
  { x: 176, y: 420, w: 44, h: 32 },
  { x: 352, y: 40, w: 48, h: 34, inner: true },
  { x: 492, y: 40, w: 44, h: 32, pins: true },
];

const CAPS: Array<{ x: number; y: number; r: number }> = [
  { x: 300, y: 48, r: 8 },
  { x: 484, y: 69, r: 9 },
  { x: 686, y: 201, r: 8 },
  { x: 758, y: 263, r: 7 },
  { x: 870, y: 506, r: 8 },
  { x: 128, y: 214, r: 7 },
];

const PASSIVES: Array<{ x: number; y: number; n: number }> = [
  { x: 368, y: 128, n: 4 },
  { x: 754, y: 42, n: 4 },
  { x: 806, y: 218, n: 5 },
  { x: 766, y: 486, n: 4 },
  { x: 128, y: 246, n: 3 },
  { x: 350, y: 430, n: 4 },
  { x: 900, y: 402, n: 4 },
  { x: 556, y: 60, n: 3 },
];

/* Sparse static colour, exactly like the handful of coloured runs on the
   reference board. Everything else stays monochrome copper. */
const ACCENTS: Array<{ d: string; tone: string }> = [
  { d: "M 581 96 L 579 126", tone: "rose" },
  { d: "M 316 372 L 330 398", tone: "ice" },
  { d: "M 683 358 V 414", tone: "gold" },
  { d: "M 112 448 L 166 472", tone: "ember" },
  { d: "M 320 306 H 352", tone: "mint" },
  { d: "M 524 420 H 622", tone: "gold" },
  { d: "M 786 108 L 824 84", tone: "ice" },
  { d: "M 206 540 L 250 518", tone: "mint" },
  { d: "M 944 196 L 908 220", tone: "ice" },
  { d: "M 60 268 V 320", tone: "gold" },
];

/* Packet-carrying routes. Several cross the plate footprint so packets appear
   to enter and leave the core. */
const SIGNAL_ROUTES: Route[] = [
  { id: "s1", d: "M -20 160 H 120 L 180 220 H 300 V 260 H 520", colour: "cyan", core: true, delay: 0.1, speed: 1 },
  { id: "s2", d: "M -20 420 H 140 L 200 360 H 320 V 300 H 540", colour: "blue", core: true, delay: 0.7, speed: 0.95 },
  { id: "s3", d: "M 480 280 H 660 L 720 220 H 860 V 160 H 1020", colour: "mint", core: true, delay: 0.42, speed: 1.02 },
  { id: "s4", d: "M 500 320 H 680 L 740 380 H 880 V 440 H 1020", colour: "blue", core: true, delay: 1.65, speed: 0.94 },
  { id: "s5", d: "M 420 -20 V 80 L 470 130 V 200 H 560", colour: "cyan", core: true, delay: 0.2, speed: 1.04 },
  { id: "s6", d: "M 600 -20 V 70 L 556 114 V 210 H 470", colour: "violet", core: true, delay: 1.05, speed: 1.1 },
  { id: "s7", d: "M 440 340 V 400 L 396 444 V 580", colour: "amber", core: true, delay: 0.58, speed: 0.98 },
  { id: "s8", d: "M 580 340 V 396 L 626 442 V 580", colour: "mint", core: true, delay: 1.44, speed: 1.06 },
  { id: "s9", d: "M 60 60 H 180 L 232 112 H 340 V 60 H 420", colour: "blue", delay: 0.82, speed: 0.92 },
  { id: "s10", d: "M 700 60 H 820 L 872 112 H 1020", colour: "amber", delay: 1.2, speed: 0.88 },
  { id: "s11", d: "M -20 500 H 120 L 172 448 H 280 V 500 H 380", colour: "mint", delay: 1.95, speed: 1.1 },
  { id: "s12", d: "M 700 500 H 800 L 852 448 H 1020", colour: "violet", delay: 0.35, speed: 1.02 },
  { id: "s13", d: "M 140 200 V 120 L 200 60 H 300", colour: "cyan", delay: 2.35, speed: 0.86 },
  { id: "s14", d: "M 860 300 V 220 L 920 160 H 1020", colour: "blue", delay: 1.72, speed: 1.04 },
];

const AMBIENT_ROUTES = buildAmbientRoutes();
const BUS_LINES = buildBusLines();
const PADS = buildPads();

function makeThinkingText() {
  const alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789";
  return [3, 3, 3, 3]
    .map((length) =>
      Array.from({ length }, () => alphabet[Math.floor(Math.random() * alphabet.length)]).join(""),
    )
    .join(".");
}

function packetDirection(state: JaceRuntimeState, index: number): PacketDirection {
  if (state === "listening" || state === "transcribing") return "reverse";
  if (state === "speaking") return "forward";
  if (state === "thinking") return index % 2 === 0 ? "forward" : "reverse";
  if (state === "working") return index % 4 === 0 ? "reverse" : "forward";
  return index % 2 === 0 ? "forward" : "reverse";
}

function packetIsVisible(state: JaceRuntimeState, index: number, core: boolean) {
  switch (state) {
    case "offline": return false;
    case "idle": return index % 5 === 0;
    case "listening": return core;
    case "transcribing": return core || index % 3 === 0;
    case "thinking": return true;
    case "speaking": return core;
    case "working": return true;
    case "waiting_permission": return index % 4 === 0;
    case "warning": return index % 3 === 0;
    default: return false;
  }
}

function stateDuration(state: JaceRuntimeState, speed = 1, amplitude = 0) {
  const base = (() => {
    switch (state) {
      case "idle": return 9.2;
      case "listening": return 3.6 - amplitude * 1.25;
      case "transcribing": return 2.9;
      case "thinking": return 2.2;
      case "speaking": return 3.2 - amplitude * 0.9;
      case "working": return 2.1;
      case "waiting_permission": return 5.4;
      case "warning": return 2.6;
      default: return 6;
    }
  })();

  return Math.max(1.05, base / speed);
}

function Packet(props: {
  route: Route;
  index: number;
  state: JaceRuntimeState;
  amplitude: number;
}) {
  const { route, index, state, amplitude } = props;
  if (!packetIsVisible(state, index, Boolean(route.core))) return null;

  const reverse = packetDirection(state, index) === "reverse";
  const duration = stateDuration(state, route.speed, amplitude);
  const delay = (route.delay ?? 0) + index * 0.09;
  const colour: PacketColour =
    state === "waiting_permission" ? "amber" : state === "warning" ? "danger" : route.colour;

  return (
    <g className={`jc-packet jc-packet-${colour}`} aria-hidden="true">
      {[4, 3, 2, 1, 0].map((tail) => {
        const head = tail === 0;
        return (
          <circle
            key={`${route.id}-${tail}`}
            className={head ? "jc-packet-head" : "jc-packet-tail"}
            r={head ? 2.4 : 0.85 + (4 - tail) * 0.22}
            opacity={head ? 1 : 0.09 + (4 - tail) * 0.1}
          >
            <animateMotion
              path={route.d}
              dur={`${duration.toFixed(2)}s`}
              begin={`${(delay + (4 - tail) * 0.038).toFixed(2)}s`}
              repeatCount="indefinite"
              calcMode="linear"
              keyPoints={reverse ? "1;0" : "0;1"}
              keyTimes="0;1"
            />
          </circle>
        );
      })}
    </g>
  );
}

function BoardChip({ chip, index }: { chip: Chip; index: number }) {
  const pinCount = Math.max(3, Math.round(chip.w / 9));

  return (
    <g className="jc-chip" aria-hidden="true">
      {chip.pins &&
        Array.from({ length: pinCount }, (_, pin) => {
          const px = chip.x + (chip.w * (pin + 0.5)) / pinCount;
          return (
            <g key={`${index}-p-${pin}`}>
              <line className="jc-chip-pin" x1={px} y1={chip.y - 4} x2={px} y2={chip.y} />
              <line className="jc-chip-pin" x1={px} y1={chip.y + chip.h} x2={px} y2={chip.y + chip.h + 4} />
            </g>
          );
        })}
      <rect className="jc-chip-body" x={chip.x} y={chip.y} width={chip.w} height={chip.h} rx="1.5" />
      {chip.inner && (
        <rect
          className="jc-chip-inner"
          x={chip.x + 5}
          y={chip.y + 5}
          width={chip.w - 10}
          height={chip.h - 10}
          rx="1"
        />
      )}
    </g>
  );
}

function useClock() {
  const [now, setNow] = useState(() => new Date());

  useEffect(() => {
    const timer = window.setInterval(() => setNow(new Date()), 1000);
    return () => window.clearInterval(timer);
  }, []);

  return now.toLocaleTimeString("en-GB", { hour12: false });
}

export function JaceCore(props: {
  name: string;
  state: JaceRuntimeState;
  model: string;
  runtimeConnected: boolean;
  amplitude?: number;
  onExpand: () => void;
}) {
  const amplitude = Math.max(0, Math.min(1, props.amplitude ?? 0));
  const [thinkingText, setThinkingText] = useState(() => makeThinkingText());
  const clock = useClock();

  useEffect(() => {
    if (props.state !== "thinking") return;
    const timer = window.setInterval(() => setThinkingText(makeThinkingText()), 92);
    return () => window.clearInterval(timer);
  }, [props.state]);

  const plateText =
    props.state === "thinking"
      ? thinkingText
      : (props.name || "Jace").trim().toUpperCase().split("").join(".") + ".";

  const stageStyle = { "--voice-level": amplitude.toFixed(3) } as CSSProperties;

  const packets = useMemo(
    () =>
      SIGNAL_ROUTES.map((route, index) => (
        <Packet key={route.id} route={route} index={index} state={props.state} amplitude={amplitude} />
      )),
    [props.state, amplitude],
  );

  return (
    <section className="cc-panel jace-core-panel jc-panel">
      <div
        className={`jc-stage state-${props.state}`}
        style={stageStyle}
        aria-label={`${props.name} core, ${LABELS[props.state]}`}
      >
        <div className="jc-substrate" aria-hidden="true" />
        <div className="jc-weave" aria-hidden="true" />

        <svg
          className="jc-board"
          viewBox={`0 0 ${VIEW_W} ${VIEW_H}`}
          preserveAspectRatio="xMidYMid slice"
          role="presentation"
          aria-hidden="true"
        >
          <defs>
            <filter id="jc-packet-glow" x="-300%" y="-300%" width="700%" height="700%">
              <feGaussianBlur stdDeviation="2.2" result="b" />
              <feMerge>
                <feMergeNode in="b" />
                <feMergeNode in="SourceGraphic" />
              </feMerge>
            </filter>
          </defs>

          <g className="jc-traces">
            {AMBIENT_ROUTES.map((route, index) => (
              <path key={`a-${index}`} className={`jc-trace w-${route.weight}`} d={route.d} />
            ))}
            {BUS_LINES.map((d, index) => (
              <path key={`b-${index}`} className="jc-bus" d={d} />
            ))}
          </g>

          <g className="jc-pads">
            {PADS.map((pad, index) => (
              <circle key={`pad-${index}`} cx={pad.x.toFixed(1)} cy={pad.y.toFixed(1)} r={pad.r} />
            ))}
          </g>

          <g className="jc-passives">
            {PASSIVES.map((group, gi) =>
              Array.from({ length: group.n }, (_, k) => (
                <rect key={`pv-${gi}-${k}`} x={group.x} y={group.y + k * 9} width="13" height="4" rx="0.5" />
              )),
            )}
          </g>

          <g className="jc-caps">
            {CAPS.map((cap, index) => (
              <g key={`cap-${index}`}>
                <circle className="jc-cap-body" cx={cap.x} cy={cap.y} r={cap.r} />
                <path
                  className="jc-cap-gloss"
                  d={`M ${cap.x - cap.r * 0.55} ${cap.y + cap.r * 0.42} A ${cap.r * 0.72} ${cap.r * 0.72} 0 0 1 ${cap.x + cap.r * 0.5} ${cap.y - cap.r * 0.5}`}
                />
              </g>
            ))}
          </g>

          <g className="jc-chips">
            {CHIPS.map((chip, index) => (
              <BoardChip key={`chip-${index}`} chip={chip} index={index} />
            ))}
          </g>

          <g className="jc-signals">
            {SIGNAL_ROUTES.map((route) => (
              <path key={route.id} className="jc-signal" d={route.d} />
            ))}
          </g>

          <g className="jc-accents">
            {ACCENTS.map((accent, index) => (
              <path key={`ac-${index}`} className={`jc-accent tone-${accent.tone}`} d={accent.d} />
            ))}
          </g>

          <g className="jc-packets" filter="url(#jc-packet-glow)">
            {packets}
          </g>
        </svg>

        <div className="jc-glow-warm" aria-hidden="true" />
        <div className="jc-glow-cool" aria-hidden="true" />
        <div className="jc-scan" aria-hidden="true" />

        <div className="jc-plate">
          <span className="jc-plate-stub stub-top" aria-hidden="true" />
          <span className="jc-plate-stub stub-bottom" aria-hidden="true" />
          <span className="jc-plate-stub stub-left" aria-hidden="true" />
          <span className="jc-plate-stub stub-right" aria-hidden="true" />
          <div className="jc-plate-frame">
            <div className="jc-plate-screen">
              <span className={`jc-plate-text ${props.state === "thinking" ? "is-data" : ""}`}>
                {plateText}
              </span>
            </div>
          </div>
        </div>

        <div className="jc-vignette" aria-hidden="true" />

        <div className="jc-hud jc-hud-tl">
          <strong>{(props.name || "Jace").toUpperCase().split("").join(".")}.</strong>
          <em>
            <i className={props.runtimeConnected ? "on" : "off"} />
            Neural link — {props.runtimeConnected ? "connected" : "fallback"}
          </em>
        </div>

        <div className="jc-hud jc-hud-tr">
          <strong>{LABELS[props.state]}</strong>
          <em>{clock}</em>
          <span className="jc-led" aria-hidden="true" />
        </div>

        <div className="jc-hud jc-hud-bl">
          <em>Mic — hold Home to talk</em>
        </div>

        <div className="jc-hud jc-hud-br">
          <em>{props.model || "no model"}</em>
        </div>

        <button className="jc-expand" onClick={props.onExpand} title="Focus core" aria-label="Focus core">
          □
        </button>
      </div>
    </section>
  );
}