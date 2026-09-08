import type { ToolAuditRecord } from "../types";

export function WebWorkspaceView(props: { audit: ToolAuditRecord[] }) {
  const webEntries = props.audit.filter((entry) => /web|browser/i.test(entry.tool_name)).slice(0, 30);
  return (
    <section className="content-shell page-shell command-web-view">
      <header className="page-header compact-header"><div><span className="section-kicker">Research surface</span><h1>Web</h1><p>Recent browsing and research activity from Jace.</p></div></header>
      <div className="web-research-list">
        {webEntries.length === 0 ? (
          <div className="large-empty"><div>⌕</div><h3>No web research yet</h3><p>Ask Jace to search or read a webpage. Research actions will appear here.</p></div>
        ) : webEntries.map((entry) => (
          <article className="web-research-card" key={entry.id}>
            <div><span className={`web-status ${entry.status}`} /> <strong>{entry.tool_name}</strong></div>
            <small>{new Date(entry.created_at).toLocaleString()}</small>
            {entry.result_preview && <pre>{entry.result_preview}</pre>}
            {entry.error && <p className="web-error">{entry.error}</p>}
          </article>
        ))}
      </div>
    </section>
  );
}
