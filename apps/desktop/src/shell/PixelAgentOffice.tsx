import type { CSSProperties } from "react";
import type { OfficeWorker } from "../agents/useAgentOffice";
import type { AgentTask } from "../agents/types";

type AgentVisualState =
  | "idle"
  | "queued"
  | "walking"
  | "thinking"
  | "working"
  | "waiting"
  | "complete"
  | "failed";

function visualState(task: AgentTask | null): AgentVisualState {
  if (!task) return "idle";

  switch (task.status) {
    case "queued":
      return "queued";
    case "running":
      return "walking";
    case "thinking":
      return "thinking";
    case "using_tool":
      return "working";
    case "waiting_permission":
      return "waiting";
    case "completed":
      return "complete";
    case "failed":
      return "failed";
    case "cancelled":
      return "idle";
  }
}

function activityLabel(task: AgentTask | null): string {
  if (!task) return "Standing by";

  if (task.progress_message?.trim()) {
    return task.progress_message;
  }

  return task.status.replace(/_/g, " ");
}

function pixelStyle(worker: OfficeWorker): CSSProperties {
  return {
    "--agent-accent": worker.definition.accent,
    "--overflow-offset": `${Math.min(worker.overflowIndex, 3) * 5}px`,
  } as CSSProperties;
}

function DeskStation(props: {
  worker: OfficeWorker;
  index: number;
  selected: boolean;
  onSelect: () => void;
}) {
  const state = visualState(props.worker.task);
  const task = props.worker.task;

  return (
    <button
      type="button"
      className={`pixel-agent-station state-${state} ${
        props.selected ? "selected" : ""
      }`}
      style={pixelStyle(props.worker)}
      onClick={props.onSelect}
      title={task?.title ?? `${props.worker.definition.name} standing by`}
    >
      <div className="pixel-desk-shadow" />

      <div className="pixel-desk">
        <span className="desk-monitor">
          <i />
        </span>
        <span className="desk-keyboard" />
        <span className="desk-leg left" />
        <span className="desk-leg right" />
      </div>

      <div className={`pixel-worker worker-${props.index % 5}`}>
        <span className="worker-hair" />
        <span className="worker-head">
          <i className="worker-eye left" />
          <i className="worker-eye right" />
        </span>
        <span className="worker-body">
          <i className="worker-arm left" />
          <i className="worker-arm right" />
        </span>
        <span className="worker-legs">
          <i />
          <i />
        </span>
      </div>

      {state === "thinking" && (
        <div className="pixel-thought-bubble" aria-hidden="true">
          <i />
          <i />
          <strong>…</strong>
        </div>
      )}

      {state === "waiting" && (
        <div className="pixel-permission-bubble">!</div>
      )}

      {state === "complete" && (
        <div className="pixel-complete-bubble">✓</div>
      )}

      {state === "failed" && (
        <div className="pixel-failed-bubble">×</div>
      )}

      <div className="station-copy">
        <strong>{props.worker.definition.name}</strong>
        <small>{activityLabel(task)}</small>

        {task && (
          <span className="station-progress">
            <i style={{ width: `${Math.round(task.progress * 100)}%` }} />
          </span>
        )}
      </div>
    </button>
  );
}

export function PixelAgentOffice(props: {
  workers: OfficeWorker[];
  selectedTaskId: string | null;
  onSelectTask: (taskId: string | null) => void;
}) {
  return (
    <div className="pixel-office-scene">
      <div className="pixel-office-wall">
        <div className="office-window">
          <i />
          <i />
          <i />
          <i />
        </div>

        <div className="office-clock">
          <i />
        </div>

        <div className="office-status-board">
          <strong>JACE</strong>
          <span>AGENT OPS</span>
          <i />
        </div>
      </div>

      <div className="pixel-office-floor">
        <div className="pixel-server-rack">
          <span />
          <span />
          <span />
          <span />
        </div>

        <div className="pixel-plant">
          <i className="leaf a" />
          <i className="leaf b" />
          <i className="leaf c" />
          <span />
        </div>

        <div className="pixel-office-desks">
          {props.workers.map((worker, index) => (
            <DeskStation
              key={worker.id}
              worker={worker}
              index={index}
              selected={
                Boolean(worker.task) &&
                worker.task?.id === props.selectedTaskId
              }
              onSelect={() =>
                props.onSelectTask(
                  worker.task
                    ? worker.task.id === props.selectedTaskId
                      ? null
                      : worker.task.id
                    : null,
                )
              }
            />
          ))}
        </div>

        <div className="pixel-office-walkway">
          <span>JACE // AGENT FLOOR</span>
        </div>
      </div>
    </div>
  );
}
