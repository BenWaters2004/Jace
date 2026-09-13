// JACE_PHASE3G_WORKSPACE_CONSOLIDATION
import { useState, type ComponentProps } from "react";
import { ComputerView } from "./ComputerView";

type ComputerHubProps = ComponentProps<typeof ComputerView>;
type ComputerSection = "files" | "apps" | "terminal" | "processes";

const SECTIONS: Array<{ id: ComputerSection; label: string }> = [
  { id: "files", label: "Files" },
  { id: "apps", label: "Apps" },
  { id: "terminal", label: "Terminal" },
  { id: "processes", label: "Processes" },
];

function FutureComputerSection(props: {
  kicker: string;
  title: string;
  description: string;
  items: string[];
}) {
  return (
    <section className="computer-hub-future content-shell page-shell">
      <header className="page-header">
        <div>
          <span className="section-kicker">{props.kicker}</span>
          <h1>{props.title}</h1>
          <p>{props.description}</p>
        </div>
        <span className="computer-hub-planned">FOUNDATION</span>
      </header>
      <div className="computer-hub-roadmap-grid">
        {props.items.map((item) => (
          <article key={item}>
            <span>○</span>
            <strong>{item}</strong>
          </article>
        ))}
      </div>
      <div className="info-box">
        <strong>3G establishes the workspace, not unrestricted execution.</strong>
        <span>The backend capability and permission layers will be connected here in later phases so every sensitive action can be scoped and audited.</span>
      </div>
    </section>
  );
}

export function ComputerHub(props: ComputerHubProps) {
  const [section, setSection] = useState<ComputerSection>("files");

  return (
    <div className="computer-hub">
      <nav className="computer-hub-tabs" aria-label="Computer sections">
        {SECTIONS.map((item) => (
          <button
            type="button"
            key={item.id}
            className={section === item.id ? "active" : ""}
            onClick={() => setSection(item.id)}
          >
            {item.label}
          </button>
        ))}
      </nav>
      <div className="computer-hub-content">
        {section === "files" && <ComputerView {...props} />}
        {section === "apps" && (
          <FutureComputerSection
            kicker="Computer · Apps"
            title="Application control"
            description="The future home for discovering, launching, focusing, closing and automating desktop applications."
            items={["Installed applications", "Running applications", "Launch / focus / close", "Application permissions"]}
          />
        )}
        {section === "terminal" && (
          <FutureComputerSection
            kicker="Computer · Terminal"
            title="Command runtime"
            description="A dedicated terminal surface for commands Jace runs on your behalf, with working-directory context, output and approval policy."
            items={["Command sessions", "Working directory", "Live stdout / stderr", "Execution history"]}
          />
        )}
        {section === "processes" && (
          <FutureComputerSection
            kicker="Computer · Processes"
            title="Processes & resources"
            description="Inspect running processes and eventually let Jace diagnose or act on resource usage with explicit permissions."
            items={["Running processes", "CPU / RAM usage", "Process details", "Stop / restart controls"]}
          />
        )}
      </div>
    </div>
  );
}
