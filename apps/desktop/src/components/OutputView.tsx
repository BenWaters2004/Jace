import type { PerformanceDiagnostics, ToolActivity } from "../types";

export function OutputView(props: { diagnostics: PerformanceDiagnostics | null; activities: ToolActivity[] }) {
  return (
    <section className="content-shell page-shell command-output-view">
      <header className="page-header compact-header">
        <div><span className="section-kicker">Workspace output</span><h1>Output</h1><p>Generated results and live execution context appear here.</p></div>
      </header>
      <div className="output-dashboard-grid">
        <article className="output-card">
          <span className="section-kicker">Latest response</span>
          <h3>Performance</h3>
          {!props.diagnostics ? <p className="muted-copy">Send a message to populate response diagnostics.</p> : (
            <dl className="output-metrics">
              <div><dt>Pre-processing</dt><dd>{props.diagnostics.preprocess_ms.toFixed(0)} ms</dd></div>
              <div><dt>Memory</dt><dd>{props.diagnostics.memory_retrieval_used ? `${props.diagnostics.memory_count} hits` : "Skipped"}</dd></div>
              <div><dt>History</dt><dd>{props.diagnostics.history_messages} msgs</dd></div>
              <div><dt>Tools supplied</dt><dd>{props.diagnostics.tool_names.length}</dd></div>
              <div><dt>Attachments</dt><dd>{props.diagnostics.attachment_count}</dd></div>
            </dl>
          )}
        </article>
        <article className="output-card">
          <span className="section-kicker">Execution</span>
          <h3>Recent tool activity</h3>
          <div className="output-activity-list">
            {props.activities.length === 0 ? <p className="muted-copy">No tool activity in this conversation yet.</p> : props.activities.slice().reverse().slice(0, 8).map((item) => (
              <div key={item.callId}><strong>{item.label}</strong><span>{item.status.replace(/_/g, " ")}</span><small>{item.summary ?? item.toolName}</small></div>
            ))}
          </div>
        </article>
      </div>
    </section>
  );
}
