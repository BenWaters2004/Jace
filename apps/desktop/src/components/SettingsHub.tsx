// JACE_PHASE3G_WORKSPACE_CONSOLIDATION
import type { ComponentProps } from "react";
import { ControlView } from "./ControlView";
import { DesktopWindowModeSettings } from "./DesktopWindowModeSettings";
import { SettingsView } from "./SettingsView";
import { ToolsView } from "./ToolsView";
import { WindowLayoutSettings } from "./WindowLayoutSettings";

export type SettingsSection =
  | "general"
  | "appearance"
  | "connections"
  | "capabilities"
  | "permissions"
  | "audit";

type GeneralProps = ComponentProps<typeof SettingsView>;
type ToolsProps = ComponentProps<typeof ToolsView>;
type ControlProps = ComponentProps<typeof ControlView>;

export interface SettingsHubProps {
  section: SettingsSection;
  onSectionChange: (section: SettingsSection) => void;
  general: GeneralProps;
  tools: ToolsProps;
  control: ControlProps;
}

const SETTINGS_SECTIONS: Array<{
  id: SettingsSection;
  label: string;
  description: string;
}> = [
  { id: "general", label: "General", description: "Identity, model, memory and voice" },
  { id: "appearance", label: "Appearance", description: "Windows, layout and themes" },
  { id: "connections", label: "Connections", description: "Accounts, APIs and services" },
  { id: "capabilities", label: "Capabilities", description: "Tools Jace can invoke" },
  { id: "permissions", label: "Permissions / Security", description: "Desktop control and safety policy" },
  { id: "audit", label: "Audit", description: "Review what Jace has done" },
];

function SectionHeader(props: { title: string; description: string; kicker?: string }) {
  return (
    <header className="settings-hub-section-header">
      <div>
        <span className="section-kicker">{props.kicker ?? "Settings"}</span>
        <h1>{props.title}</h1>
        <p>{props.description}</p>
      </div>
    </header>
  );
}

function ConnectionCard(props: { name: string; detail: string; capability: string }) {
  return (
    <article className="settings-hub-placeholder-card">
      <div className="settings-hub-placeholder-head">
        <strong>{props.name}</strong>
        <span className="settings-hub-status planned">PLANNED · 4A</span>
      </div>
      <p>{props.detail}</p>
      <small>{props.capability}</small>
    </article>
  );
}

function ConnectionsSection() {
  return (
    <section className="settings-hub-section">
      <SectionHeader
        kicker="Connections"
        title="Accounts & APIs"
        description="This is the home for provider authentication and API connections. Phase 4A will add the connector runtime without turning providers into workspace tabs."
      />
      <div className="settings-hub-card-grid">
        <ConnectionCard name="Google" detail="Personal Gmail, Google Calendar and future Drive access." capability="email · calendar · files" />
        <ConnectionCard name="Microsoft" detail="Work Outlook / Microsoft 365, calendar and future OneDrive access." capability="email · calendar · files" />
        <ConnectionCard name="GitHub" detail="Repository context, issues, pull requests and development workflows." capability="code · repositories" />
        <ConnectionCard name="Custom API" detail="Register an API connection without adding another permanent workspace tab." capability="custom capabilities" />
      </div>
    </section>
  );
}

function AppearanceSection() {
  return (
    <section className="settings-hub-section">
      <SectionHeader
        kicker="Appearance"
        title="Window & layout"
        description="Desktop window behaviour now lives with visual settings. Colour themes are reserved here for the next appearance pass."
      />
      <div className="settings-hub-embedded-grid">
        <DesktopWindowModeSettings />
        <WindowLayoutSettings />
      </div>
      <article className="settings-hub-placeholder-card full">
        <div className="settings-hub-placeholder-head">
          <strong>Colour themes</strong>
          <span className="settings-hub-status planned">PLACEHOLDER</span>
        </div>
        <p>Semantic theme variables will support Dark, Light, AMOLED, high-contrast and custom Jace themes without rebuilding individual components.</p>
      </article>
    </section>
  );
}

function CapabilitiesSection(props: { tools: ToolsProps }) {
  return (
    <section className="settings-hub-section settings-hub-embedded-section">
      <SectionHeader
        kicker="Capabilities"
        title="Tools"
        description="Configure the capabilities Jace can invoke. This is the existing Tools workspace, moved under Settings rather than removed."
      />
      <ToolsView {...props.tools} />
    </section>
  );
}

function PermissionsSection(props: { control: ControlProps }) {
  return (
    <section className="settings-hub-section settings-hub-embedded-section">
      <SectionHeader
        kicker="Permissions / Security"
        title="Computer control"
        description="Desktop control policy now lives with permissions. Future filesystem, application and terminal scopes will extend this same safety model."
      />
      <div className="settings-security-roadmap" role="note">
        <div><strong>Files</strong><span>Workspace / selected folders / full computer</span></div>
        <div><strong>Applications</strong><span>Launch, focus, close and automate</span></div>
        <div><strong>Terminal</strong><span>Ask / low-risk allow / trusted execution</span></div>
        <div><strong>Destructive actions</strong><span>Explicit approval and audit trail</span></div>
      </div>
      <ControlView {...props.control} />
    </section>
  );
}

function AuditSection(props: { tools: ToolsProps; control: ControlProps }) {
  const entries = props.tools.audit.slice(0, 24);
  return (
    <section className="settings-hub-section">
      <SectionHeader
        kicker="Audit"
        title="Jace activity"
        description="A single place to answer “what did Jace do?”. Tool history is available now; computer-control actions remain preserved in the permissions view while the unified audit model is expanded."
      />
      <div className="settings-audit-summary">
        <article>
          <span>Tool events</span>
          <strong>{props.tools.audit.length}</strong>
        </article>
        <article>
          <span>Control actions</span>
          <strong>{props.control.actions.length}</strong>
        </article>
      </div>
      <div className="settings-audit-list">
        {entries.length === 0 ? (
          <div className="settings-hub-empty">No tool activity has been recorded yet.</div>
        ) : (
          entries.map((entry) => (
            <article key={entry.id} className="settings-audit-row">
              <div>
                <strong>{entry.tool_name}</strong>
                <span>{entry.status.replace(/_/g, " ")}</span>
              </div>
              <small>{new Date(entry.created_at).toLocaleString()}</small>
              <p>{entry.error || entry.result_preview || "No result preview recorded."}</p>
            </article>
          ))
        )}
      </div>
    </section>
  );
}

export function SettingsHub(props: SettingsHubProps) {
  return (
    <div className="settings-hub">
      <aside className="settings-hub-nav" aria-label="Settings sections">
        <div className="settings-hub-nav-head">
          <span>JACE</span>
          <strong>Settings</strong>
        </div>
        {SETTINGS_SECTIONS.map((item) => (
          <button
            type="button"
            key={item.id}
            className={props.section === item.id ? "active" : ""}
            onClick={() => props.onSectionChange(item.id)}
          >
            <strong>{item.label}</strong>
            <span>{item.description}</span>
          </button>
        ))}
      </aside>

      <div className="settings-hub-content">
        {props.section === "general" && <SettingsView {...props.general} />}
        {props.section === "appearance" && <AppearanceSection />}
        {props.section === "connections" && <ConnectionsSection />}
        {props.section === "capabilities" && <CapabilitiesSection tools={props.tools} />}
        {props.section === "permissions" && <PermissionsSection control={props.control} />}
        {props.section === "audit" && <AuditSection tools={props.tools} control={props.control} />}
      </div>
    </div>
  );
}
