import { useMemo, useState } from "react";
import type {
  ComputerCommandCreateRequest,
  ComputerCommandPreset,
  ComputerCommandUpdateRequest,
  ComputerStatus,
  ComputerWorkspace,
  ComputerWorkspaceCreateRequest,
  ComputerWorkspaceUpdateRequest,
} from "../types";

interface ComputerViewProps {
  status: ComputerStatus | null;
  workspaces: ComputerWorkspace[];
  onRefresh: () => void;
  onCreateWorkspace: (payload: ComputerWorkspaceCreateRequest) => Promise<void>;
  onUpdateWorkspace: (workspace: ComputerWorkspace, payload: ComputerWorkspaceUpdateRequest) => Promise<void>;
  onDeleteWorkspace: (workspace: ComputerWorkspace) => Promise<void>;
  onCreateCommand: (workspace: ComputerWorkspace, payload: ComputerCommandCreateRequest) => Promise<void>;
  onUpdateCommand: (command: ComputerCommandPreset, payload: ComputerCommandUpdateRequest) => Promise<void>;
  onDeleteCommand: (command: ComputerCommandPreset) => Promise<void>;
}

interface WorkspaceDraft {
  label: string;
  root_path: string;
  read_enabled: boolean;
  write_enabled: boolean;
}

interface CommandDraft {
  label: string;
  executable: string;
  argumentsText: string;
  relative_cwd: string;
  timeout_seconds: number;
}

const EMPTY_WORKSPACE: WorkspaceDraft = {
  label: "",
  root_path: "",
  read_enabled: true,
  write_enabled: false,
};

const EMPTY_COMMAND: CommandDraft = {
  label: "",
  executable: "",
  argumentsText: "",
  relative_cwd: ".",
  timeout_seconds: 120,
};

function parseArguments(value: string): string[] {
  const text = value.trim();
  if (!text) return [];

  const result: string[] = [];
  let current = "";
  let quote: '"' | "'" | null = null;

  for (const char of text) {
    if (quote) {
      if (char === quote) quote = null;
      else current += char;
      continue;
    }
    if (char === '"' || char === "'") {
      quote = char;
      continue;
    }
    if (/\s/.test(char)) {
      if (current) {
        result.push(current);
        current = "";
      }
      continue;
    }
    current += char;
  }

  if (current) result.push(current);
  return result;
}

function commandPreview(command: ComputerCommandPreset) {
  const args = command.arguments.map((item) => (/\s/.test(item) ? `"${item}"` : item)).join(" ");
  return `${command.executable}${args ? ` ${args}` : ""}`;
}

export function ComputerView(props: ComputerViewProps) {
  const [workspaceDraft, setWorkspaceDraft] = useState<WorkspaceDraft>(EMPTY_WORKSPACE);
  const [addingWorkspace, setAddingWorkspace] = useState(false);
  const [commandWorkspaceId, setCommandWorkspaceId] = useState<string | null>(null);
  const [commandDraft, setCommandDraft] = useState<CommandDraft>(EMPTY_COMMAND);
  const [busy, setBusy] = useState(false);

  const commandCount = useMemo(
    () => props.workspaces.reduce((total, workspace) => total + workspace.commands.length, 0),
    [props.workspaces],
  );

  async function submitWorkspace() {
    if (!workspaceDraft.label.trim() || !workspaceDraft.root_path.trim()) return;
    setBusy(true);
    try {
      await props.onCreateWorkspace({
        label: workspaceDraft.label.trim(),
        root_path: workspaceDraft.root_path.trim(),
        read_enabled: workspaceDraft.read_enabled,
        write_enabled: workspaceDraft.write_enabled,
      });
      setWorkspaceDraft(EMPTY_WORKSPACE);
      setAddingWorkspace(false);
    } finally {
      setBusy(false);
    }
  }

  async function submitCommand(workspace: ComputerWorkspace) {
    if (!commandDraft.label.trim() || !commandDraft.executable.trim()) return;
    setBusy(true);
    try {
      await props.onCreateCommand(workspace, {
        label: commandDraft.label.trim(),
        executable: commandDraft.executable.trim(),
        arguments: parseArguments(commandDraft.argumentsText),
        relative_cwd: commandDraft.relative_cwd.trim() || ".",
        timeout_seconds: commandDraft.timeout_seconds,
      });
      setCommandDraft(EMPTY_COMMAND);
      setCommandWorkspaceId(null);
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="content-shell page-shell">
      <header className="page-header">
        <div>
          <h1>Computer</h1>
          <p>Choose exactly which local folders Jace can see and which commands it may request.</p>
        </div>
        <div className="header-actions">
          <button className="secondary-button" onClick={props.onRefresh}>Refresh</button>
          <button className="primary-button" onClick={() => setAddingWorkspace((value) => !value)}>
            {addingWorkspace ? "Cancel" : "Add workspace"}
          </button>
        </div>
      </header>

      {!props.status?.enabled && (
        <div className="notice-banner">Computer access is disabled by backend configuration. Set JACE_COMPUTER_ENABLED=true and restart Jace.</div>
      )}

      <div className="notice-banner computer-safety-banner">
        Jace cannot access arbitrary paths. Every filesystem tool is confined to an active workspace below. Sensitive credential files are blocked by default, existing file changes require a current SHA-256, recursive deletion is unavailable, and commands must be exact presets you create here.
      </div>

      <div className="stat-grid computer-stat-grid">
        <div className="stat-card"><strong>{props.workspaces.length}</strong><span>Configured workspaces</span></div>
        <div className="stat-card"><strong>{props.workspaces.filter((item) => item.is_active).length}</strong><span>Active workspaces</span></div>
        <div className="stat-card"><strong>{props.workspaces.filter((item) => item.write_enabled && item.is_active).length}</strong><span>Write-enabled</span></div>
        <div className="stat-card"><strong>{commandCount}</strong><span>Command presets</span></div>
      </div>

      {addingWorkspace && (
        <section className="computer-editor-card">
          <div className="section-heading-row">
            <div><span className="section-kicker">Trust boundary</span><h2>Add local workspace</h2></div>
          </div>
          <div className="computer-form-grid">
            <label>
              <span>Name</span>
              <input
                value={workspaceDraft.label}
                placeholder="Jace project"
                onChange={(event) => setWorkspaceDraft((current) => ({ ...current, label: event.target.value }))}
              />
            </label>
            <label className="wide-field">
              <span>Absolute folder path</span>
              <input
                value={workspaceDraft.root_path}
                placeholder="C:\\Users\\Ben\\jace"
                onChange={(event) => setWorkspaceDraft((current) => ({ ...current, root_path: event.target.value }))}
              />
            </label>
          </div>
          <div className="computer-toggle-row">
            <label className="toggle-line">
              <input
                type="checkbox"
                checked={workspaceDraft.read_enabled}
                onChange={(event) => setWorkspaceDraft((current) => ({ ...current, read_enabled: event.target.checked }))}
              />
              <span><strong>Read</strong><small>Allow Jace to request listing, reading and searching inside this root.</small></span>
            </label>
            <label className="toggle-line">
              <input
                type="checkbox"
                checked={workspaceDraft.write_enabled}
                onChange={(event) => setWorkspaceDraft((current) => ({ ...current, write_enabled: event.target.checked }))}
              />
              <span><strong>Write</strong><small>Allow approved create/edit/move/delete tools inside this root.</small></span>
            </label>
          </div>
          <div className="computer-editor-actions">
            <button className="primary-button" disabled={busy || !workspaceDraft.label.trim() || !workspaceDraft.root_path.trim()} onClick={() => void submitWorkspace()}>
              Add workspace
            </button>
          </div>
        </section>
      )}

      <div className="computer-workspace-list">
        {props.workspaces.length === 0 ? (
          <div className="large-empty">
            <div>▣</div>
            <h3>No computer workspaces</h3>
            <p>Add a folder before asking Jace to inspect or modify local files.</p>
          </div>
        ) : props.workspaces.map((workspace) => (
          <article className={`computer-workspace-card ${workspace.is_active ? "" : "inactive"}`} key={workspace.id}>
            <div className="computer-workspace-head">
              <div>
                <div className="computer-title-line">
                  <h2>{workspace.label}</h2>
                  <span className={`workspace-state ${workspace.is_active ? "active" : "inactive"}`}>{workspace.is_active ? "Active" : "Inactive"}</span>
                  {workspace.read_enabled && <span className="risk-tag read">Read</span>}
                  {workspace.write_enabled && <span className="risk-tag write">Write</span>}
                </div>
                <code>{workspace.root_path}</code>
              </div>
              <div className="computer-workspace-actions">
                <button
                  className="secondary-button"
                  onClick={() => void props.onUpdateWorkspace(workspace, { is_active: !workspace.is_active })}
                >
                  {workspace.is_active ? "Disable" : "Enable"}
                </button>
                <button
                  className="secondary-button danger-soft"
                  onClick={() => {
                    if (window.confirm(`Remove the workspace configuration "${workspace.label}"?\n\nNo files will be deleted.`)) {
                      void props.onDeleteWorkspace(workspace);
                    }
                  }}
                >
                  Remove
                </button>
              </div>
            </div>

            <div className="workspace-access-grid">
              <label className="toggle-line compact-toggle">
                <input
                  type="checkbox"
                  checked={workspace.read_enabled}
                  onChange={(event) => void props.onUpdateWorkspace(workspace, { read_enabled: event.target.checked })}
                />
                <span><strong>Read access</strong><small>List, inspect, search and read files.</small></span>
              </label>
              <label className="toggle-line compact-toggle">
                <input
                  type="checkbox"
                  checked={workspace.write_enabled}
                  onChange={(event) => void props.onUpdateWorkspace(workspace, { write_enabled: event.target.checked })}
                />
                <span><strong>Write access</strong><small>Create and approved exact edits inside this root.</small></span>
              </label>
            </div>

            <div className="command-section">
              <div className="section-heading-row command-heading">
                <div><span className="section-kicker">Execution boundary</span><h3>Command presets</h3></div>
                <button
                  className="secondary-button"
                  disabled={!workspace.is_active}
                  onClick={() => {
                    setCommandWorkspaceId(commandWorkspaceId === workspace.id ? null : workspace.id);
                    setCommandDraft(EMPTY_COMMAND);
                  }}
                >
                  {commandWorkspaceId === workspace.id ? "Cancel" : "Add preset"}
                </button>
              </div>

              {commandWorkspaceId === workspace.id && (
                <div className="command-editor">
                  <div className="computer-form-grid command-form-grid">
                    <label><span>Name</span><input value={commandDraft.label} placeholder="Run tests" onChange={(event) => setCommandDraft((current) => ({ ...current, label: event.target.value }))} /></label>
                    <label><span>Executable</span><input value={commandDraft.executable} placeholder="python" onChange={(event) => setCommandDraft((current) => ({ ...current, executable: event.target.value }))} /></label>
                    <label className="wide-field"><span>Fixed arguments</span><input value={commandDraft.argumentsText} placeholder="-m pytest" onChange={(event) => setCommandDraft((current) => ({ ...current, argumentsText: event.target.value }))} /></label>
                    <label><span>Working folder</span><input value={commandDraft.relative_cwd} placeholder="." onChange={(event) => setCommandDraft((current) => ({ ...current, relative_cwd: event.target.value }))} /></label>
                    <label><span>Timeout (seconds)</span><input type="number" min={1} max={900} value={commandDraft.timeout_seconds} onChange={(event) => setCommandDraft((current) => ({ ...current, timeout_seconds: Number(event.target.value) || 120 }))} /></label>
                  </div>
                  <p className="command-warning">Shell hosts such as PowerShell, cmd, bash and WSL are blocked. The executable and arguments above are fixed; Jace cannot append its own arguments.</p>
                  <button className="primary-button" disabled={busy || !commandDraft.label.trim() || !commandDraft.executable.trim()} onClick={() => void submitCommand(workspace)}>Save command preset</button>
                </div>
              )}

              {workspace.commands.length === 0 ? (
                <div className="command-empty">No command presets. Jace cannot execute programs in this workspace.</div>
              ) : (
                <div className="command-list">
                  {workspace.commands.map((command) => (
                    <div className={`command-row ${command.is_active ? "" : "inactive"}`} key={command.id}>
                      <div>
                        <strong>{command.label}</strong>
                        <code>{commandPreview(command)}</code>
                        <small>cwd {command.relative_cwd} · timeout {command.timeout_seconds}s · ID {command.id}</small>
                      </div>
                      <div>
                        <button className="secondary-button" onClick={() => void props.onUpdateCommand(command, { is_active: !command.is_active })}>
                          {command.is_active ? "Disable" : "Enable"}
                        </button>
                        <button
                          className="secondary-button danger-soft"
                          onClick={() => {
                            if (window.confirm(`Delete command preset "${command.label}"?`)) void props.onDeleteCommand(command);
                          }}
                        >
                          Delete
                        </button>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </article>
        ))}
      </div>
    </section>
  );
}
