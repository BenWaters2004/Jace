import type { ToolActivity } from "../types";

type AgentState = "idle" | "working" | "waiting" | "complete" | "failed";

function classify(tool: string) {
  if (/web|browser|search/i.test(tool)) return { role: "Research", icon: "⌕" };
  if (/file|workspace|computer|command/i.test(tool)) return { role: "Ops", icon: "⌘" };
  if (/memory/i.test(tool)) return { role: "Memory", icon: "◇" };
  if (/automation|schedule/i.test(tool)) return { role: "Automation", icon: "◷" };
  if (/control|window|pointer|click|type/i.test(tool)) return { role: "Control", icon: "◎" };
  return { role: "General", icon: "◆" };
}

function stateFor(status: ToolActivity["status"]): AgentState {
  if (status === "awaiting_approval") return "waiting";
  if (status === "completed") return "complete";
  if (status === "failed" || status === "denied") return "failed";
  return "working";
}

export function AgentOffice(props: { activities: ToolActivity[]; onExpand: () => void }) {
  const active = props.activities.slice(-6).map((activity) => ({ ...classify(activity.toolName), activity }));
  const fallback = [
    { role: "Research", icon: "⌕" },
    { role: "Coding", icon: "</>" },
    { role: "Memory", icon: "◇" },
    { role: "Automation", icon: "◷" },
  ];

  return (
    <section className="cc-panel agent-office-panel">
      <div className="cc-panel-topline">
        <div><span className="cc-kicker">Jace office</span><strong>{active.length ? `${active.length} recent agent actions` : "Agents standing by"}</strong></div>
        <button className="cc-icon-button" onClick={props.onExpand} title="Focus agent office">□</button>
      </div>
      <div className="office-room">
        <div className="office-wall-lines" />
        <div className="office-grid-floor" />
        <div className="office-agents">
          {(active.length ? active : fallback.map((item) => ({ ...item, activity: null }))).map((item, index) => {
            const status = item.activity ? stateFor(item.activity.status) : "idle";
            return (
              <div className={`office-agent ${status}`} key={`${item.role}-${index}`}>
                <div className="agent-desk"><span>{item.icon}</span></div>
                <div className="agent-avatar"><span>{item.role.slice(0, 1)}</span></div>
                <strong>{item.role}</strong>
                <small>{item.activity?.label ?? (status === "idle" ? "Standing by" : status)}</small>
              </div>
            );
          })}
        </div>
      </div>
    </section>
  );
}
