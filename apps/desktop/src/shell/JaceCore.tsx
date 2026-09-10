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

type PacketColour = "cyan" | "blue" | "violet" | "amber" | "mint" | "danger";
type PacketDirection = "forward" | "reverse";

type Route = {
  id: string;
  d: string;
  colour: PacketColour;
  hubLinked?: boolean;
  delay?: number;
  speed?: number;
};

type Chip = {
  x: number;
  y: number;
  width: number;
  height: number;
  rotate?: number;
};

const HUB = {
  left: 315,
  right: 685,
  top: 240,
  bottom: 360,
};

/*
 * These are the signal routes that can carry visible data packets.
 * Only some of them touch the central processor. The rest behave like local
 * buses on the board so the scene does not look like a starburst.
 */
const SIGNAL_ROUTES: Route[] = [
  {
    id: "sig-west-a",
    d: `M 18 102 H 95 L 135 142 H 218 L 250 174 H 278 V 258 H ${HUB.left}`,
    colour: "cyan",
    hubLinked: true,
    delay: 0.1,
    speed: 1,
  },
  {
    id: "sig-west-b",
    d: `M 22 492 H 118 L 154 456 H 214 L 270 400 V 330 H ${HUB.left}`,
    colour: "blue",
    hubLinked: true,
    delay: 0.7,
    speed: 0.95,
  },
  {
    id: "sig-west-c",
    d: `M 58 316 H 142 L 168 290 H 234 L 267 323 H ${HUB.left}`,
    colour: "violet",
    hubLinked: true,
    delay: 1.25,
    speed: 1.12,
  },
  {
    id: "sig-east-a",
    d: `M ${HUB.right} 272 H 728 L 760 240 H 824 L 855 209 H 982`,
    colour: "mint",
    hubLinked: true,
    delay: 0.42,
    speed: 1.02,
  },
  {
    id: "sig-east-b",
    d: `M ${HUB.right} 334 H 744 L 782 372 H 846 L 884 410 H 976`,
    colour: "blue",
    hubLinked: true,
    delay: 1.65,
    speed: 0.94,
  },
  {
    id: "sig-east-c",
    d: `M ${HUB.right} 304 H 722 L 747 329 H 820 L 854 295 H 934 V 258 H 984`,
    colour: "amber",
    hubLinked: true,
    delay: 2.05,
    speed: 1.08,
  },
  {
    id: "sig-north-a",
    d: `M 374 18 V 82 L 411 119 V 180 L 445 214 V ${HUB.top}`,
    colour: "cyan",
    hubLinked: true,
    delay: 0.2,
    speed: 1.04,
  },
  {
    id: "sig-north-b",
    d: `M 585 14 V 74 L 553 106 V 150 L 526 177 V ${HUB.top}`,
    colour: "violet",
    hubLinked: true,
    delay: 1.05,
    speed: 1.1,
  },
  {
    id: "sig-south-a",
    d: `M 444 ${HUB.bottom} V 397 L 412 429 V 488 L 381 519 V 586`,
    colour: "amber",
    hubLinked: true,
    delay: 0.58,
    speed: 0.98,
  },
  {
    id: "sig-south-b",
    d: `M 566 ${HUB.bottom} V 403 L 597 434 V 474 L 630 507 V 586`,
    colour: "mint",
    hubLinked: true,
    delay: 1.44,
    speed: 1.06,
  },
  {
    id: "sig-local-a",
    d: "M 82 210 H 152 L 184 178 H 245 L 278 145 H 338",
    colour: "blue",
    delay: 0.82,
    speed: 0.92,
  },
  {
    id: "sig-local-b",
    d: "M 720 94 H 788 L 821 127 H 898 L 931 160 H 984",
    colour: "amber",
    delay: 1.2,
    speed: 0.88,
  },
  {
    id: "sig-local-c",
    d: "M 40 424 H 112 L 147 389 H 216 L 247 420 H 293",
    colour: "mint",
    delay: 1.95,
    speed: 1.1,
  },
  {
    id: "sig-local-d",
    d: "M 724 475 H 786 L 817 444 H 875 L 907 476 H 980",
    colour: "violet",
    delay: 0.35,
    speed: 1.02,
  },
  {
    id: "sig-local-e",
    d: "M 166 64 H 224 L 254 94 H 302 L 332 124 H 365",
    colour: "cyan",
    delay: 2.35,
    speed: 0.86,
  },
  {
    id: "sig-local-f",
    d: "M 634 526 H 696 L 726 496 H 781 L 816 531 H 914",
    colour: "blue",
    delay: 1.72,
    speed: 1.04,
  },
];

const CHIPS: Chip[] = [
  { x: 78, y: 154, width: 78, height: 52 },
  { x: 188, y: 372, width: 58, height: 42 },
  { x: 246, y: 72, width: 52, height: 44 },
  { x: 732, y: 132, width: 68, height: 48 },
  { x: 820, y: 364, width: 72, height: 52 },
  { x: 700, y: 456, width: 52, height: 40 },
  { x: 89, y: 468, width: 68, height: 46 },
  { x: 868, y: 74, width: 54, height: 42 },
];

const PACKET_COLOURS: PacketColour[] = ["cyan", "blue", "violet", "amber", "mint"];

function seededRandom(seed: number) {
  let value = seed >>> 0;
  return () => {
    value = (value * 1664525 + 1013904223) >>> 0;
    return value / 0xffffffff;
  };
}

function buildAmbientRoutes() {
  const random = seededRandom(0x4a414345);
  const routes: string[] = [];

  for (let index = 0; index < 42; index += 1) {
    const leftSide = index % 2 === 0;
    const topSide = index % 3 === 0;
    let x = leftSide ? 8 + random() * 255 : 738 + random() * 250;
    let y = topSide ? 12 + random() * 250 : 342 + random() * 242;
    const points = [`M ${x.toFixed(1)} ${y.toFixed(1)}`];
    const segmentCount = 3 + Math.floor(random() * 4);

    for (let segment = 0; segment < segmentCount; segment += 1) {
      const horizontal = segment % 2 === 0;
      const direction = random() > 0.48 ? 1 : -1;
      const length = 34 + random() * 92;

      if (horizontal) {
        x = Math.max(12, Math.min(988, x + direction * length));
        points.push(`H ${x.toFixed(1)}`);
      } else {
        const diagonal = random() > 0.55;
        if (diagonal) {
          const nextX = Math.max(12, Math.min(988, x + direction * Math.min(38, length * 0.42)));
          y = Math.max(12, Math.min(588, y + (random() > 0.5 ? 1 : -1) * Math.min(38, length * 0.42)));
          x = nextX;
          points.push(`L ${x.toFixed(1)} ${y.toFixed(1)}`);
        } else {
          y = Math.max(12, Math.min(588, y + direction * length));
          points.push(`V ${y.toFixed(1)}`);
        }
      }
    }

    routes.push(points.join(" "));
  }

  return routes;
}

function buildVias() {
  const random = seededRandom(0x50434231);
  const points: Array<{ x: number; y: number; r: number }> = [];

  while (points.length < 74) {
    const x = 16 + random() * 968;
    const y = 16 + random() * 568;
    const insideHub = x > HUB.left - 30 && x < HUB.right + 30 && y > HUB.top - 25 && y < HUB.bottom + 25;
    if (insideHub) continue;
    points.push({ x, y, r: random() > 0.84 ? 3.2 : 2.1 });
  }

  return points;
}

const AMBIENT_ROUTES = buildAmbientRoutes();
const VIA_POINTS = buildVias();

function makeThinkingText() {
  const alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789@#$%";
  const groups = [3, 3, 3, 3];
  return groups
    .map((length) =>
      Array.from({ length }, () => alphabet[Math.floor(Math.random() * alphabet.length)]).join(""),
    )
    .join(".");
}

function packetDirection(state: JaceRuntimeState, routeIndex: number): PacketDirection {
  if (state === "listening" || state === "transcribing") return "reverse";
  if (state === "speaking") return "forward";
  if (state === "thinking") return routeIndex % 2 === 0 ? "forward" : "reverse";
  if (state === "working") return routeIndex % 4 === 0 ? "reverse" : "forward";
  return routeIndex % 2 === 0 ? "forward" : "reverse";
}

function packetIsVisible(state: JaceRuntimeState, routeIndex: number, hubLinked: boolean) {
  switch (state) {
    case "offline":
      return false;
    case "idle":
      return routeIndex % 5 === 0;
    case "listening":
      return hubLinked;
    case "transcribing":
      return hubLinked || routeIndex % 3 === 0;
    case "thinking":
      return true;
    case "speaking":
      return hubLinked;
    case "working":
      return true;
    case "waiting_permission":
      return routeIndex % 4 === 0;
    case "warning":
      return routeIndex % 3 === 0;
    default:
      return false;
  }
}

function stateDuration(state: JaceRuntimeState, speed = 1, amplitude = 0) {
  const base = (() => {
    switch (state) {
      case "idle":
        return 8.8;
      case "listening":
        return 3.6 - amplitude * 1.25;
      case "transcribing":
        return 2.8;
      case "thinking":
        return 2.15;
      case "speaking":
        return 3.15 - amplitude * 0.85;
      case "working":
        return 2.0;
      case "waiting_permission":
        return 5.4;
      case "warning":
        return 2.6;
      default:
        return 6;
    }
  })();

  return Math.max(1.05, base / speed);
}

function Packet(props: {
  route: Route;
  routeIndex: number;
  state: JaceRuntimeState;
  amplitude: number;
}) {
  const { route, routeIndex, state, amplitude } = props;
  if (!packetIsVisible(state, routeIndex, Boolean(route.hubLinked))) return null;

  const direction = packetDirection(state, routeIndex);
  const duration = stateDuration(state, route.speed, amplitude);
  const delay = (route.delay ?? 0) + routeIndex * 0.09;
  const colour: PacketColour =
    state === "waiting_permission" ? "amber" : state === "warning" ? "danger" : route.colour;
  const reverse = direction === "reverse";

  return (
    <g className={`pcb-packet packet-${colour} packet-state-${state}`} aria-hidden="true">
      {[4, 3, 2, 1, 0].map((tailIndex) => {
        const isHead = tailIndex === 0;
        const radius = isHead ? 2.55 : 0.9 + (4 - tailIndex) * 0.24;
        const opacity = isHead ? 1 : 0.1 + (4 - tailIndex) * 0.11;
        const extraDelay = (4 - tailIndex) * 0.038;

        return (
          <circle
            key={`${route.id}-tail-${tailIndex}`}
            className={isHead ? "pcb-packet-head" : "pcb-packet-tail"}
            r={radius}
            opacity={opacity}
          >
            <animateMotion
              path={route.d}
              dur={`${duration.toFixed(2)}s`}
              begin={`${(delay + extraDelay).toFixed(2)}s`}
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
  const pinCount = 7;
  const centerX = chip.x + chip.width / 2;
  const centerY = chip.y + chip.height / 2;

  return (
    <g
      className={`pcb-chip pcb-chip-${index + 1}`}
      transform={`rotate(${chip.rotate ?? 0} ${centerX} ${centerY})`}
      aria-hidden="true"
    >
      <rect className="pcb-chip-shadow" x={chip.x - 3} y={chip.y - 3} width={chip.width + 6} height={chip.height + 6} rx="2" />
      <rect className="pcb-chip-body" x={chip.x} y={chip.y} width={chip.width} height={chip.height} rx="2" />
      <rect
        className="pcb-chip-die"
        x={chip.x + chip.width * 0.16}
        y={chip.y + chip.height * 0.18}
        width={chip.width * 0.68}
        height={chip.height * 0.64}
        rx="1"
      />
      {Array.from({ length: pinCount }, (_, pinIndex) => {
        const t = (pinIndex + 1) / (pinCount + 1);
        const px = chip.x + chip.width * t;
        const py = chip.y + chip.height * t;
        return (
          <g key={`${index}-${pinIndex}`}>
            <line className="pcb-chip-pin" x1={px} y1={chip.y - 7} x2={px} y2={chip.y} />
            <line className="pcb-chip-pin" x1={px} y1={chip.y + chip.height} x2={px} y2={chip.y + chip.height + 7} />
            <line className="pcb-chip-pin" x1={chip.x - 7} y1={py} x2={chip.x} y2={py} />
            <line className="pcb-chip-pin" x1={chip.x + chip.width} y1={py} x2={chip.x + chip.width + 7} y2={py} />
          </g>
        );
      })}
    </g>
  );
}

function HubPins() {
  const horizontalPins = Array.from({ length: 26 }, (_, index) => index);
  const verticalPins = Array.from({ length: 9 }, (_, index) => index);

  return (
    <>
      <div className="pcb-hub-pins pcb-hub-pins-top" aria-hidden="true">
        {horizontalPins.map((pin) => <i key={`top-${pin}`} style={{ "--pin-index": pin } as CSSProperties} />)}
      </div>
      <div className="pcb-hub-pins pcb-hub-pins-bottom" aria-hidden="true">
        {horizontalPins.map((pin) => <i key={`bottom-${pin}`} style={{ "--pin-index": pin } as CSSProperties} />)}
      </div>
      <div className="pcb-hub-pins pcb-hub-pins-left" aria-hidden="true">
        {verticalPins.map((pin) => <i key={`left-${pin}`} style={{ "--pin-index": pin } as CSSProperties} />)}
      </div>
      <div className="pcb-hub-pins pcb-hub-pins-right" aria-hidden="true">
        {verticalPins.map((pin) => <i key={`right-${pin}`} style={{ "--pin-index": pin } as CSSProperties} />)}
      </div>
    </>
  );
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

  useEffect(() => {
    if (props.state !== "thinking") return;
    const timer = window.setInterval(() => setThinkingText(makeThinkingText()), 92);
    return () => window.clearInterval(timer);
  }, [props.state]);

  const displayText = props.state === "thinking" ? thinkingText : "J.A.C.E.";
  const stageStyle = {
    "--voice-level": amplitude.toFixed(3),
  } as CSSProperties;

  const packets = useMemo(
    () => SIGNAL_ROUTES.map((route, routeIndex) => (
      <Packet
        key={route.id}
        route={route}
        routeIndex={routeIndex}
        state={props.state}
        amplitude={amplitude}
      />
    )),
    [props.state, amplitude],
  );

  return (
    <section className={`cc-panel jace-core-panel pcb-core-panel state-${props.state}`}>
      <div className="cc-panel-topline pcb-core-topline">
        <div>
          <span className="cc-kicker">Neural core</span>
          <strong>{LABELS[props.state]}</strong>
        </div>
        <div className="pcb-core-actions">
          <span className={`pcb-link-light ${props.runtimeConnected ? "online" : "fallback"}`}>
            {props.runtimeConnected ? "● LINK" : "○ FALLBACK"}
          </span>
          <button className="cc-icon-button" onClick={props.onExpand} title="Focus Jace core">□</button>
        </div>
      </div>

      <div
        className={`pcb-core-stage state-${props.state}`}
        style={stageStyle}
        aria-label={`${props.name} neural core, ${LABELS[props.state]}`}
      >
        <div className="pcb-substrate" />
        <div className="pcb-fibreglass" />
        <div className="pcb-grain" />

        <svg
          className="pcb-board-svg"
          viewBox="0 0 1000 600"
          preserveAspectRatio="none"
          role="presentation"
          aria-hidden="true"
        >
          <defs>
            <filter id="pcb-packet-glow" x="-300%" y="-300%" width="700%" height="700%">
              <feGaussianBlur stdDeviation="2.4" result="blur" />
              <feMerge>
                <feMergeNode in="blur" />
                <feMergeNode in="SourceGraphic" />
              </feMerge>
            </filter>
            <filter id="pcb-hot-glow" x="-200%" y="-200%" width="500%" height="500%">
              <feGaussianBlur stdDeviation="1.45" result="blur" />
              <feMerge>
                <feMergeNode in="blur" />
                <feMergeNode in="SourceGraphic" />
              </feMerge>
            </filter>
          </defs>

          <g className="pcb-ambient-traces">
            {AMBIENT_ROUTES.map((d, index) => (
              <path key={`ambient-${index}`} d={d} />
            ))}
          </g>

          <g className="pcb-signal-traces">
            {SIGNAL_ROUTES.map((route) => (
              <g className={`pcb-signal-route ${route.hubLinked ? "hub-linked" : "local-bus"}`} key={route.id}>
                <path className="pcb-trace-underlay" d={route.d} />
                <path className="pcb-trace" d={route.d} />
              </g>
            ))}
          </g>

          <g className="pcb-vias">
            {VIA_POINTS.map((point, index) => (
              <g key={`via-${index}`} transform={`translate(${point.x.toFixed(1)} ${point.y.toFixed(1)})`}>
                <circle className="pcb-via-ring" r={point.r + 1.55} />
                <circle className="pcb-via-hole" r={point.r} />
              </g>
            ))}
          </g>

          <g className="pcb-chips">
            {CHIPS.map((chip, index) => <BoardChip key={`chip-${index}`} chip={chip} index={index} />)}
          </g>

          <g className="pcb-passives" aria-hidden="true">
            {[
              [35, 258], [48, 258], [61, 258], [934, 310], [947, 310], [960, 310],
              [176, 118], [176, 131], [176, 144], [806, 516], [819, 516], [832, 516],
              [522, 58], [535, 58], [548, 58], [453, 528], [466, 528], [479, 528],
            ].map(([x, y], index) => (
              <rect key={`passive-${index}`} x={x} y={y} width="6" height="12" rx="1" />
            ))}
          </g>

          <g className="pcb-board-marks" aria-hidden="true">
            <path d="M 18 26 H 48 M 18 26 V 54" />
            <path d="M 982 26 H 952 M 982 26 V 54" />
            <path d="M 18 574 H 48 M 18 574 V 546" />
            <path d="M 982 574 H 952 M 982 574 V 546" />
          </g>

          <g className="pcb-packets" filter="url(#pcb-packet-glow)">
            {packets}
          </g>
        </svg>

        <div className="pcb-hub-aura" />
        <div className="pcb-state-scan" />

        <div className="pcb-core-hub">
          <HubPins />
          <div className="pcb-core-hub-inner">
            <span className={`pcb-core-title ${props.state === "thinking" ? "thinking-data" : ""}`}>
              {displayText}
            </span>
          </div>
          <span className="pcb-hub-sheen" aria-hidden="true" />
        </div>

        <div className="pcb-board-vignette" />
      </div>

      <div className="core-footer pcb-core-footer">
        <span>{props.runtimeConnected ? "● LIVE EVENT LINK" : "○ EVENT FALLBACK"}</span>
        <span>{props.model || "No model"}</span>
        <span>{props.state.toUpperCase().replace("_", " ")}</span>
      </div>
    </section>
  );
}
