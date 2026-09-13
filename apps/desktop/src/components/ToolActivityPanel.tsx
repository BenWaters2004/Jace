import type { ToolActivity } from "../types";

interface ToolActivityPanelProps {
  activities: ToolActivity[];
}

function statusLabel(status: ToolActivity["status"]) {
  switch (status) {
    case "requested":
      return "Working";
    case "awaiting_approval":
      return "Waiting for approval";
    case "completed":
      return "Completed";
    case "denied":
      return "Denied";
    case "failed":
      return "Failed";
  }
}

function statusGlyph(status: ToolActivity["status"]) {
  switch (status) {
    case "requested":
      return "↻";
    case "awaiting_approval":
      return "!";
    case "completed":
      return "✓";
    case "denied":
      return "–";
    case "failed":
      return "×";
  }
}

function formatArguments(argumentsValue: Record<string, unknown>) {
  const keys = Object.keys(argumentsValue);
  if (keys.length === 0) return null;

  try {
    return JSON.stringify(argumentsValue, null, 2);
  } catch {
    return String(argumentsValue);
  }
}

export function ToolActivityPanel({
  activities,
}: ToolActivityPanelProps) {
  if (activities.length === 0) return null;

  const activeCount = activities.filter(
    (activity) =>
      activity.status === "requested" ||
      activity.status === "awaiting_approval",
  ).length;

  return (
    <section
      className="rich-tool-activity-panel"
      aria-label="Tool activity"
    >
      <div className="rich-tool-activity-heading">
        <div>
          <span className="rich-tool-activity-kicker">
            Tool activity
          </span>
          <strong>
            {activeCount > 0
              ? `${activeCount} active`
              : `${activities.length} completed`}
          </strong>
        </div>
        <span className="rich-tool-activity-count">
          {activities.length}
        </span>
      </div>

      <div className="rich-tool-activity-list">
        {activities.map((activity) => {
          const formattedArguments = formatArguments(activity.arguments);
          const isActive =
            activity.status === "requested" ||
            activity.status === "awaiting_approval";

          return (
            <details
              className={`rich-tool-card status-${activity.status}`}
              key={activity.callId}
              open={isActive || undefined}
            >
              <summary className="rich-tool-card-summary">
                <span
                  className={`rich-tool-status-icon status-${activity.status}`}
                  aria-hidden="true"
                >
                  {statusGlyph(activity.status)}
                </span>

                <span className="rich-tool-card-title">
                  <strong>{activity.label}</strong>
                  <small>{activity.toolName}</small>
                </span>

                <span
                  className={`rich-tool-status-badge status-${activity.status}`}
                >
                  {statusLabel(activity.status)}
                </span>

                <span
                  className="rich-tool-disclosure"
                  aria-hidden="true"
                >
                  ▾
                </span>
              </summary>

              <div className="rich-tool-card-body">
                {activity.description && (
                  <p className="rich-tool-description">
                    {activity.description}
                  </p>
                )}

                {(activity.risk || activity.permission) && (
                  <div className="rich-tool-meta-row">
                    {activity.risk && (
                      <span className={`rich-tool-meta risk-${activity.risk}`}>
                        {activity.risk} risk
                      </span>
                    )}
                    {activity.permission && (
                      <span className="rich-tool-meta">
                        permission: {activity.permission}
                      </span>
                    )}
                  </div>
                )}

                {activity.summary && (
                  <div className="rich-tool-result">
                    <span>Result</span>
                    <p>{activity.summary}</p>
                  </div>
                )}

                {formattedArguments && (
                  <details className="rich-tool-arguments">
                    <summary>Arguments</summary>
                    <pre>
                      <code>{formattedArguments}</code>
                    </pre>
                  </details>
                )}
              </div>
            </details>
          );
        })}
      </div>
    </section>
  );
}
