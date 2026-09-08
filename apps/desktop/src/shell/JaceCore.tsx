import type { JaceRuntimeState } from "./runtime";

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

const THINKING_GLYPHS = ["ZWT@+TG$Q5<S", "SYNCING CONTEXT", "ROUTING TOOLS", "CHECKING MEMORY"];

function coreDisplayFor(state: JaceRuntimeState) {
  if (state === "thinking" || state === "working") {
    return THINKING_GLYPHS;
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
  const displayLines = coreDisplayFor(props.state);
  const showWave = props.state === "listening" || props.state === "speaking" || props.state === "transcribing";
  const waveformBars = Array.from({ length: 19 }, (_, index) => index);
  const traceIndexes = Array.from({ length: 8 }, (_, index) => index + 1);
  const ambientIndexes = Array.from({ length: 6 }, (_, index) => index + 1);

  return (
    <section className={`cc-panel jace-core-panel state-${props.state}`}>
      <div className="cc-panel-topline">
        <div>
          <span className="cc-kicker">Neural core</span>
          <strong>{LABELS[props.state]}</strong>
        </div>
        <button className="cc-icon-button" onClick={props.onExpand} title="Focus Jace core">□</button>
      </div>

      <div className={`jace-core-stage mode-${props.state}`} aria-label={`${props.name} ${LABELS[props.state]}`}>
        <div className="core-grid" />
        <div className="core-board-layer">
          {traceIndexes.map((index) => (
            <span key={`trace-${index}`} className={`board-trace trace-${index}`} />
          ))}
          {ambientIndexes.map((index) => (
            <span key={`ambient-${index}`} className={`board-ambient ambient-${index}`} />
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

        <div className="core-orbit orbit-a"><i /><i /><i /></div>
        <div className="core-orbit orbit-b"><i /><i /><i /></div>
        <div className="core-ring ring-outer" />
        <div className="core-ring ring-mid" />
        <div className="core-ring ring-inner" />
        <div className="core-pulse pulse-one" />
        <div className="core-pulse pulse-two" />
        <div className="core-scanline" />

        <div className="core-center">
          <div className="core-center-frame">
            {showWave ? (
              <div className={`core-waveform wave-${props.state}`} aria-hidden="true">
                {waveformBars.map((index) => (
                  <span key={`wave-${index}`} style={{ animationDelay: `${(index % 6) * 0.08}s` }} />
                ))}
              </div>
            ) : (
              <div className={`core-display display-${props.state}`}>
                {displayLines.map((line, index) => (
                  <span key={`${line}-${index}`}>{line}</span>
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
        <span>{props.runtimeConnected ? "● LIVE EVENT LINK" : "○ EVENT FALLBACK"}</span>
        <span>{props.model || "No model"}</span>
      </div>
    </section>
  );
}
