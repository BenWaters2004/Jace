// JACE_STEP4A6_FINAL_CONNECTIONS_CAPABILITIES
import type { ComponentProps } from "react";

import { AppearanceSettings } from "./AppearanceSettings";
import { AuditView } from "./AuditView";
import { CapabilityOverview } from "./CapabilityOverview";
import { ConnectionsView } from "./ConnectionsView";
import { ControlView } from "./ControlView";
import { ExecutionScopesSettings } from "./ExecutionScopesSettings";
import { DesktopWindowModeSettings } from "./DesktopWindowModeSettings";
import { SecurityControls } from "./SecurityControls";
import { SettingsView } from "./SettingsView";
import { ToolsView } from "./ToolsView";
import { WindowLayoutSettings } from "./WindowLayoutSettings";


import { ExecutionAuditView } from "./ExecutionAuditView"; // JACE_4B3G_EXECUTION_AUDIT_VIEW
export type SettingsSection =
  | "general"
  | "appearance"
  | "connections"
  | "capabilities"
  | "permissions"
  | "audit";


type GeneralProps = ComponentProps<
  typeof SettingsView
>;

type ToolsProps = ComponentProps<
  typeof ToolsView
>;

type ControlProps = ComponentProps<
  typeof ControlView
>;


export interface SettingsHubProps {
  section: SettingsSection;
  onSectionChange: (
    section: SettingsSection,
  ) => void;
  general: GeneralProps;
  tools: ToolsProps;
  control: ControlProps;
}


const SETTINGS_SECTIONS: Array<{
  id: SettingsSection;
  label: string;
  description: string;
}> = [
  {
    id: "general",
    label: "General",
    description: "Identity, model, memory and voice",
  },
  {
    id: "appearance",
    label: "Appearance",
    description: "Windows, layout and themes",
  },
  {
    id: "connections",
    label: "Connections",
    description: "Accounts, APIs and services",
  },
  {
    id: "capabilities",
    label: "Capabilities",
    description: "Tools Jace can invoke",
  },
  {
    id: "permissions",
    label: "Permissions / Security",
    description: "Runtime safety and computer policy",
  },
  {
    id: "audit",
    label: "Audit Log",
    description: "Review what Jace has done",
  },
];


function SectionHeader(
  props: {
    title: string;
    description: string;
    kicker?: string;
  },
) {
  return (
    <header className="settings-hub-section-header">
      <div>
        <span className="section-kicker">
          {props.kicker ?? "Settings"}
        </span>

        <h1>
          {props.title}
        </h1>

        <p>
          {props.description}
        </p>
      </div>
    </header>
  );
}


function ConnectionsSection() {
  return (
    <section className="settings-hub-section">
      <SectionHeader
        kicker="Connections"
        title="Accounts & APIs"
        description={
          "Authenticate external accounts and API endpoints. "
          + "Credentials remain outside Jace's SQLite database and "
          + "connection alone never grants every provider capability."
        }
      />

      <ConnectionsView />
    </section>
  );
}


function AppearanceSection() {
  return (
    <section className="settings-hub-section">
      <SectionHeader
        kicker="Appearance"
        title="Appearance"
        description={
          "Theme, desktop window behaviour and workspace layout live together here."
        }
      />

      <div className="settings-hub-theme-panel">
        <AppearanceSettings />
      </div>

      <div className="settings-hub-embedded-grid">
        <DesktopWindowModeSettings />
        <WindowLayoutSettings />
      </div>
    </section>
  );
}


function CapabilitiesSection(
  props: {
    tools: ToolsProps;
  },
) {
  return (
    <section
      className={
        "settings-hub-section settings-hub-embedded-section"
      }
    >
      <SectionHeader
        kicker="Capabilities"
        title="Capabilities & tools"
        description={
          "Provider access, account-specific permission and executable "
          + "tools are kept separate. Ready means Jace can actually route "
          + "the capability now."
        }
      />

      <CapabilityOverview />

      <ToolsView
        {...props.tools}
      />
    </section>
  );
}


function PermissionsSection(
  props: {
    control: ControlProps;
    tools: ToolsProps;
  },
) {
  return (
    <section
      className={
        "settings-hub-section settings-hub-embedded-section"
      }
    >
      <SectionHeader
        kicker="Permissions / Security"
        title="Runtime safety"
        description={
          "Use master and provider-level switches to stop external access "
          + "without deleting accounts. Computer-control policy remains "
          + "separately constrained and audited."
        }
      />

      <SecurityControls
        toolsEnabled={
          props.tools.enabled
        }
      />

      <div
        className="settings-security-roadmap"
        role="note"
      >
        <div>
          <strong>
            Files
          </strong>

          <span>
            Workspace / selected folders / full computer
          </span>
        </div>

        <div>
          <strong>
            Applications
          </strong>

          <span>
            Launch, focus, close and automate
          </span>
        </div>

        <div>
          <strong>
            Terminal
          </strong>

          <span>
            Ask / low-risk allow / trusted execution
          </span>
        </div>

        <div>
          <strong>
            Destructive actions
          </strong>

          <span>
            Explicit approval and audit trail
          </span>
        </div>
      </div>

      {/* JACE_4B3E_EXECUTION_SCOPE_SETTINGS */}

      <ExecutionScopesSettings />

      <ControlView
        {...props.control}
      />
    </section>
  );
}


function AuditSection(
  props: {
    tools: ToolsProps;
  },
) {
  return (
    <section className="settings-hub-section">
      <SectionHeader
        kicker="Audit"
        title="Jace activity"
        description="Trace execution policy, scope/device provenance, approvals and outcomes without persisting raw shell commands or terminal keystrokes."
      />

      <ExecutionAuditView
        audit={props.tools.audit}
        tools={props.tools.tools}
        onRefresh={props.tools.onRefresh}
        onClearAudit={props.tools.onClearAudit}
      />
    </section>
  );
}

export function SettingsHub(
  props: SettingsHubProps,
) {
  return (
    <div className="settings-hub">
      <aside
        className="settings-hub-nav"
        aria-label="Settings sections"
      >
        <div className="settings-hub-nav-head">
          <span>
            JACE
          </span>

          <strong>
            Settings
          </strong>
        </div>

        {
          SETTINGS_SECTIONS.map(
            (item) => (
              <button
                type="button"
                key={item.id}
                className={
                  props.section === item.id
                    ? "active"
                    : ""
                }
                onClick={
                  () => props.onSectionChange(
                    item.id,
                  )
                }
              >
                <strong>
                  {item.label}
                </strong>

                <span>
                  {item.description}
                </span>
              </button>
            ),
          )
        }
      </aside>

      <div className="settings-hub-content">
        {
          props.section === "general"
          && (
            <SettingsView
              {...props.general}
            />
          )
        }

        {
          props.section === "appearance"
          && <AppearanceSection />
        }

        {
          props.section === "connections"
          && <ConnectionsSection />
        }

        {
          props.section === "capabilities"
          && (
            <CapabilitiesSection
              tools={props.tools}
            />
          )
        }

        {
          props.section === "permissions"
          && (
            <PermissionsSection
              control={props.control}
              tools={props.tools}
            />
          )
        }

        {
          props.section === "audit"
          && (
            <AuditSection
              tools={props.tools}
              control={props.control}
            />
          )
        }
      </div>
    </div>
  );
}
