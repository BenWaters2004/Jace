import { useEffect, useState } from "react";
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
  listening: "Taking in your request",
  transcribing: "Converting speech into text",
  thinking: "Processing context and intent",
  speaking: "Delivering a response",
  working: "Using tools and coordinating work",
  waiting_permission: "Waiting for your confirmation",
  warning: "Something needs your attention",
};

const THINKING_CHARACTERS =
  "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789<>[]{}@#$%&*+-=/\\";

const THINKING_LABELS = [
  "SYNCING CONTEXT",
  "CHECKING MEMORY",
  "EVALUATING INTENT",
  "ROUTING CONTEXT",
];

const WORKING_LABELS = [
  "ROUTING TOOLS",
  "EXECUTING TASK",
  "READING RESULT",
  "COORDINATING",
];

const NETWORK_PATHS = [
  "M 42 185 H 165 V 145 H 320 V 205 H 410",
  "M 42 230 H 235 V 230 H 410",
  "M 42 270 H 190 V 330 H 340 V 270 H 410",
  "M 42 315 H 145 V 390 H 315 V 305 H 410",
  "M 958 185 H 835 V 145 H 680 V 205 H 590",
  "M 958 230 H 765 V 230 H 590",
  "M 958 270 H 810 V 330 H 660 V 270 H 590",
  "M 958 315 H 855 V 390 H 685 V 305 H 590",
  "M 140 145 V 82 H 350 V 198 H 420",
  "M 860 145 V 82 H 650 V 198 H 580",
  "M 315 390 V 438 H 470 V 307",
  "M 685 390 V 438 H 530 V 307",
];

const NETWORK_JUNCTIONS = [
  [42, 185],
  [42, 230],
  [42, 270],
  [42, 315],
  [958, 185],
  [958, 230],
  [958, 270],
  [958, 315],
  [140, 145],
  [860, 145],
  [315, 390],
  [685, 390],
];

function randomGlyphString(length = 13) {
  let result = "";

  for (let index = 0; index < length; index += 1) {
    result +=
      THINKING_CHARACTERS[
        Math.floor(Math.random() * THINKING_CHARACTERS.length)
      ];
  }

  return result;
}

function coreDisplayFor(
  state: JaceRuntimeState,
  glyphs: string,
  activityLabel: string,
) {
  if (state === "thinking" || state === "working") {
    return [glyphs, activityLabel];
  }

  if (state === "waiting_permission") {
    return ["APPROVAL REQUIRED"];
  }

  if (state === "offline") {
    return ["OFFLINE"];
  }

  return ["JACE"];
}

export function JaceCore(props: {
  name: string;
  state: JaceRuntimeState;
  model: string;
  runtimeConnected: boolean;
  onExpand: () => void;
}) {
  const [thinkingGlyphs, setThinkingGlyphs] = useState(() =>
    randomGlyphString(),
  );
  const [activityLabel, setActivityLabel] = useState(THINKING_LABELS[0]);

  useEffect(() => {
    if (props.state !== "thinking" && props.state !== "working") {
      return;
    }

    const labels =
      props.state === "working" ? WORKING_LABELS : THINKING_LABELS;
    let labelIndex = 0;

    setThinkingGlyphs(randomGlyphString());
    setActivityLabel(labels[0]);

    const glyphTimer = window.setInterval(() => {
      setThinkingGlyphs(randomGlyphString());
    }, 85);

    const labelTimer = window.setInterval(() => {
      labelIndex = (labelIndex + 1) % labels.length;
      setActivityLabel(labels[labelIndex]);
    }, 850);

    return () => {
      window.clearInterval(glyphTimer);
      window.clearInterval(labelTimer);
    };
  }, [props.state]);

  const displayLines = coreDisplayFor(
    props.state,
    thinkingGlyphs,
    activityLabel,
  );

  const showWave =
    props.state === "listening" ||
    props.state === "speaking" ||
    props.state === "transcribing";

  const waveformBars = Array.from({ length: 19 }, (_, index) => index);
  const ambientIndexes = Array.from({ length: 6 }, (_, index) => index + 1);

  return (
    <section className={`cc-panel jace-core-panel state-${props.state}`}>
      <div className="cc-panel-topline">
        <div>
          <span className="cc-kicker">Neural core</span>
          <strong>{LABELS[props.state]}</strong>
        </div>

        <button
          className="cc-icon-button"
          onClick={props.onExpand}
          title="Focus Jace core"
        >
          □
        </button>
      </div>

      <div
        className={`jace-core-stage mode-${props.state}`}
        aria-label={`${props.name} ${LABELS[props.state]}`}
      >
        <div className="core-grid" />

        <svg
          className="core-network"
          viewBox="0 0 1000 500"
          preserveAspectRatio="none"
          aria-hidden="true"
        >
          <g className="network-wires">
            {NETWORK_PATHS.map((path, index) => (
              <path
                key={`wire-${index}`}
                className="network-wire"
                d={path}
                pathLength={100}
              />
            ))}
          </g>

          <g className="network-energy">
            {NETWORK_PATHS.map((path, index) => (
              <path
                key={`flow-${index}`}
                className="network-flow"
                d={path}
                pathLength={100}
                style={{ animationDelay: `-${index * 0.23}s` }}
              />
            ))}
          </g>

          <g className="network-junctions">
            {NETWORK_JUNCTIONS.map(([cx, cy], index) => (
              <circle key={`junction-${index}`} cx={cx} cy={cy} r="5" />
            ))}
          </g>
        </svg>

        <div className="core-board-layer">
          {ambientIndexes.map((index) => (
            <span
              key={`ambient-${index}`}
              className={`board-ambient ambient-${index}`}
            />
          ))}

          <span className="board-chip chip-a" />
          <span className="board-chip chip-b" />
          <span className="board-chip chip-c" />
          <span className="board-chip chip-d" />
        </div>

        <div className="core-node-stack left">
          <span />
          <span />
          <span />
          <span />
        </div>

        <div className="core-node-stack right">
          <span />
          <span />
          <span />
          <span />
        </div>

        <div className="core-orbit orbit-a">
          <i />
          <i />
          <i />
        </div>

        <div className="core-orbit orbit-b">
          <i />
          <i />
          <i />
        </div>

        <div className="core-ring ring-outer" />
        <div className="core-ring ring-mid" />
        <div className="core-ring ring-inner" />

        <div className="core-pulse pulse-one" />
        <div className="core-pulse pulse-two" />
        <div className="core-scanline" />

        <div className="core-center">
          <div className="core-center-frame">
            {showWave ? (
              <div
                className={`core-waveform wave-${props.state}`}
                aria-hidden="true"
              >
                {waveformBars.map((index) => (
                  <span
                    key={`wave-${index}`}
                    style={{ animationDelay: `${(index % 6) * 0.08}s` }}
                  />
                ))}
              </div>
            ) : (
              <div className={`core-display display-${props.state}`}>
                {displayLines.map((line, index) => (
                  <span key={`${index}-${line}`}>{line}</span>
                ))}
              </div>
            )}
          </div>

          <span className="core-state">{LABELS[props.state]}</span>
        </div>

        <div className="core-caption-block">
          <span className="core-caption-label">State</span>
          <strong>{LABELS[props.state]}</strong>
          <small>{STATUS_COPY[props.state]}</small>
        </div>
      </div>

      <div className="core-footer">
        <span>
          {props.runtimeConnected ? "● LIVE EVENT LINK" : "○ EVENT FALLBACK"}
        </span>
        <span>{props.model || "No model"}</span>
      </div>
    </section>
  );
}
