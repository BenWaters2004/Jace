import type { ToolAuditRecord, ToolPermissionMode, ToolRecord } from "../types";

interface ToolsViewProps {
  enabled: boolean;
  tools: ToolRecord[];
  audit: ToolAuditRecord[];
  onRefresh: () => void;
  onPermissionChange: (tool: ToolRecord, permission: ToolPermissionMode) => Promise<void>;
  onClearAudit: () => Promise<void>;
}

function dateTime(value: string) {
  return new Date(value).toLocaleString();
}

function permissionLabel(permission: ToolPermissionMode) {
  if (permission === "allow") return "Allow automatically";
  if (permission === "ask") return "Ask every time";
  return "Disabled";
}

function statusClass(status: string) {
  if (status === "completed") return "success";
  if (["denied", "timed_out"].includes(status)) return "warning";
  if (status === "failed") return "danger";
  return "neutral";
}

export function ToolsView(props: ToolsViewProps) {
  const allowed = props.tools.filter((tool) => tool.permission === "allow").length;
  const asking = props.tools.filter((tool) => tool.permission === "ask").length;
  const denied = props.tools.filter((tool) => tool.permission === "deny").length;

  return (
    <section className="content-shell page-shell">
      <header className="page-header">
        <div>
          <h1>Tools</h1>
          <p>Control what Jace can do and review every tool action.</p>
        </div>
        <div className="header-actions">
          <button className="secondary-button" onClick={props.onRefresh}>Refresh</button>
        </div>
      </header>

      {!props.enabled && (
        <div className="notice-banner">Tools are disabled by the backend configuration. Set JACE_TOOLS_ENABLED=true and restart Jace.</div>
      )}

      {props.enabled && props.tools.some((tool) => tool.category === "Web") && (
        <div className="notice-banner">
          Phase 5 web tools send search queries and requested public URLs outside this computer. They start in <strong>Ask</strong> mode; review the arguments before choosing Always allow. Browser read executes third-party page JavaScript in a restricted read-only Chromium session.
        </div>
      )}

      <div className="stat-grid tool-stat-grid">
        <div className="stat-card"><strong>{props.tools.length}</strong><span>Registered tools</span></div>
        <div className="stat-card"><strong>{allowed}</strong><span>Automatic</span></div>
        <div className="stat-card"><strong>{asking}</strong><span>Require approval</span></div>
        <div className="stat-card"><strong>{denied}</strong><span>Disabled</span></div>
      </div>

      <div className="tools-layout">
        <section className="tools-panel">
          <div className="section-heading-row">
            <div><span className="section-kicker">Agent capabilities</span><h2>Available tools</h2></div>
            <span className="tool-help">Local read tools can run automatically. Internet and write tools start behind approval so you can choose what to trust.</span>
          </div>

          <div className="tool-list">
            {props.tools.map((tool) => (
              <article className="tool-card" key={tool.name}>
                <div className="tool-card-main">
                  <div className="tool-title-row">
                    <h3>{tool.label}</h3>
                    <span className={`risk-tag ${tool.risk}`}>{tool.risk === "write" ? "Write" : "Read"}</span>
                    <span className="category-tag">{tool.category}</span>
                  </div>
                  <p>{tool.description}</p>
                  <code className="tool-name">{tool.name}</code>
                </div>
                <label className="tool-permission">
                  <span>Permission</span>
                  <select
                    value={tool.permission}
                    disabled={!props.enabled}
                    onChange={(event) => void props.onPermissionChange(tool, event.target.value as ToolPermissionMode)}
                  >
                    <option value="allow">Allow automatically</option>
                    <option value="ask">Ask every time</option>
                    <option value="deny">Disable</option>
                  </select>
                  <small>Default: {permissionLabel(tool.default_permission)}</small>
                </label>
              </article>
            ))}
          </div>
        </section>

        <section className="tools-panel audit-panel">
          <div className="section-heading-row">
            <div><span className="section-kicker">Accountability</span><h2>Audit log</h2></div>
            <button
              className="secondary-button"
              disabled={props.audit.length === 0}
              onClick={() => {
                if (window.confirm("Clear the tool audit log? Tool permissions will not be changed.")) {
                  void props.onClearAudit();
                }
              }}
            >
              Clear log
            </button>
          </div>

          {props.audit.length === 0 ? (
            <div className="large-empty compact-empty">
              <div>⌁</div><h3>No tool activity yet</h3><p>Actions taken by the agent will appear here.</p>
            </div>
          ) : (
            <div className="audit-list">
              {props.audit.map((entry) => (
                <article className="audit-entry" key={entry.id}>
                  <div className="audit-entry-top">
                    <strong>{entry.tool_name}</strong>
                    <span className={`audit-status ${statusClass(entry.status)}`}>{entry.status.replaceAll("_", " ")}</span>
                  </div>
                  <div className="audit-meta">{dateTime(entry.created_at)} · policy {entry.permission_mode}</div>
                  {Object.keys(entry.arguments).length > 0 && (
                    <details>
                      <summary>Arguments</summary>
                      <pre>{JSON.stringify(entry.arguments, null, 2)}</pre>
                    </details>
                  )}
                  {entry.result_preview && <p className="audit-result">{entry.result_preview}</p>}
                  {entry.error && <p className="audit-error">{entry.error}</p>}
                </article>
              ))}
            </div>
          )}
        </section>
      </div>
    </section>
  );
}
