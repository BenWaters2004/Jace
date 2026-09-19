import { useCallback, useEffect, useMemo, useState } from "react";
import {
  createExecutionScope,
  deleteExecutionScope,
  getComputerWorkspaces,
  getDevices,
  getExecutionScopes,
  updateExecutionScope,
} from "../api";
import type {
  ComputerWorkspace,
  DeviceRecord,
  ExecutionScope,
  ExecutionScopeCreateRequest,
  ExecutionScopeUpdateRequest,
} from "../types";

const SHELLS = ["powershell", "cmd", "wsl", "bash"] as const;

type ShellName = (typeof SHELLS)[number];

interface ScopeFormState {
  label: string;
  device_id: string;
  workspace_id: string;
  device_root_path: string;
  allowed_shells: ShellName[];
  process_enabled: boolean;
  terminal_enabled: boolean;
}

const EMPTY_FORM: ScopeFormState = {
  label: "",
  device_id: "",
  workspace_id: "",
  device_root_path: "",
  allowed_shells: ["powershell"],
  process_enabled: true,
  terminal_enabled: true,
};

function shellLabel(shell: ShellName) {
  switch (shell) {
    case "powershell":
      return "PowerShell";
    case "cmd":
      return "Command Prompt";
    case "wsl":
      return "WSL";
    case "bash":
      return "Bash";
    default:
      return shell;
  }
}

function deviceShells(device: DeviceRecord | null): ShellName[] {
  if (!device) return [...SHELLS];

  const explicit = new Set(
    device.capabilities
      .filter((capability) => capability.startsWith("terminal."))
      .map((capability) => capability.replace("terminal.", "")),
  );

  const shells = SHELLS.filter((shell) => explicit.has(shell));

  return shells.length > 0 ? [...shells] : [...SHELLS];
}

function scopeCapabilityLabel(scope: ExecutionScope) {
  if (scope.process_enabled && scope.terminal_enabled) return "Process + terminal";
  if (scope.process_enabled) return "Process";
  if (scope.terminal_enabled) return "Terminal";
  return "No execution";
}

export function ExecutionScopesSettings() {
  const [devices, setDevices] = useState<DeviceRecord[]>([]);
  const [workspaces, setWorkspaces] = useState<ComputerWorkspace[]>([]);
  const [scopes, setScopes] = useState<ExecutionScope[]>([]);
  const [form, setForm] = useState<ScopeFormState>(EMPTY_FORM);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const selectedDevice = useMemo(
    () => devices.find((device) => device.id === form.device_id) ?? null,
    [devices, form.device_id],
  );

  const selectedWorkspace = useMemo(
    () => workspaces.find((workspace) => workspace.id === form.workspace_id) ?? null,
    [workspaces, form.workspace_id],
  );

  const availableShells = useMemo(
    () => deviceShells(selectedDevice),
    [selectedDevice],
  );

  const refresh = useCallback(async () => {
    setLoading(true);
    setError(null);

    try {
      const [deviceResponse, workspaceResponse, scopeResponse] = await Promise.all([
        getDevices(),
        getComputerWorkspaces(),
        getExecutionScopes(false),
      ]);

      setDevices(deviceResponse.devices);
      setWorkspaces(workspaceResponse.workspaces);
      setScopes(scopeResponse.scopes);
    } catch (refreshError) {
      setError(
        refreshError instanceof Error
          ? refreshError.message
          : "Could not load execution scopes.",
      );
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  useEffect(() => {
    if (!selectedDevice) return;

    const supported = new Set(availableShells);
    const current = form.allowed_shells.filter((shell) => supported.has(shell));

    if (current.length === 0 && availableShells.length > 0) {
      setForm((value) => ({
        ...value,
        allowed_shells: [availableShells[0]],
      }));
    } else if (current.length !== form.allowed_shells.length) {
      setForm((value) => ({
        ...value,
        allowed_shells: current,
      }));
    }
  }, [availableShells, form.allowed_shells.length, selectedDevice]);

  function resetForm() {
    setEditingId(null);
    setForm(EMPTY_FORM);
    setError(null);
  }

  function selectWorkspace(workspaceId: string) {
    const workspace = workspaces.find((item) => item.id === workspaceId) ?? null;

    setForm((current) => ({
      ...current,
      workspace_id: workspaceId,
      device_root_path:
        !editingId || !current.device_root_path
          ? workspace?.root_path ?? current.device_root_path
          : current.device_root_path,
      label:
        !editingId && !current.label && workspace
          ? `${workspace.label} execution`
          : current.label,
    }));
  }

  function toggleShell(shell: ShellName) {
    setForm((current) => {
      const exists = current.allowed_shells.includes(shell);

      if (exists && current.allowed_shells.length === 1) {
        return current;
      }

      return {
        ...current,
        allowed_shells: exists
          ? current.allowed_shells.filter((item) => item !== shell)
          : [...current.allowed_shells, shell],
      };
    });
  }

  function editScope(scope: ExecutionScope) {
    setEditingId(scope.id);
    setForm({
      label: scope.label,
      device_id: scope.device_id,
      workspace_id: scope.workspace_id,
      device_root_path: scope.device_root_path,
      allowed_shells: scope.allowed_shells.filter(
        (shell): shell is ShellName => SHELLS.includes(shell as ShellName),
      ),
      process_enabled: scope.process_enabled,
      terminal_enabled: scope.terminal_enabled,
    });
    setError(null);
  }

  async function saveScope() {
    if (
      !form.label.trim()
      || !form.device_id
      || !form.workspace_id
      || !form.device_root_path.trim()
      || form.allowed_shells.length === 0
    ) {
      setError(
        "Label, device, workspace, device root and at least one shell are required.",
      );
      return;
    }

    setSaving(true);
    setError(null);

    try {
      if (editingId) {
        const payload: ExecutionScopeUpdateRequest = {
          label: form.label.trim(),
          device_root_path: form.device_root_path.trim(),
          allowed_shells: form.allowed_shells,
          process_enabled: form.process_enabled,
          terminal_enabled: form.terminal_enabled,
        };

        await updateExecutionScope(editingId, payload);
      } else {
        const payload: ExecutionScopeCreateRequest = {
          label: form.label.trim(),
          device_id: form.device_id,
          workspace_id: form.workspace_id,
          device_root_path: form.device_root_path.trim(),
          allowed_shells: form.allowed_shells,
          process_enabled: form.process_enabled,
          terminal_enabled: form.terminal_enabled,
        };

        await createExecutionScope(payload);
      }

      resetForm();
      await refresh();
    } catch (saveError) {
      setError(
        saveError instanceof Error
          ? saveError.message
          : "Could not save execution scope.",
      );
    } finally {
      setSaving(false);
    }
  }

  async function removeScope(scope: ExecutionScope) {
    if (!window.confirm(`Delete the execution scope "${scope.label}"?`)) return;

    try {
      setError(null);
      await deleteExecutionScope(scope.id);

      if (editingId === scope.id) {
        resetForm();
      }

      await refresh();
    } catch (deleteError) {
      setError(
        deleteError instanceof Error
          ? deleteError.message
          : "Could not delete execution scope.",
      );
    }
  }

  async function toggleScopeActive(scope: ExecutionScope) {
    try {
      setError(null);
      await updateExecutionScope(scope.id, {
        is_active: !scope.is_active,
      });
      await refresh();
    } catch (updateError) {
      setError(
        updateError instanceof Error
          ? updateError.message
          : "Could not change execution scope state.",
      );
    }
  }

  const onlineDeviceCount = devices.filter((device) => device.state === "online").length;
  const activeScopeCount = scopes.filter((scope) => scope.is_active).length;
  const writableWorkspaceCount = workspaces.filter(
    (workspace) => workspace.is_active && workspace.write_enabled,
  ).length;

  return (
    <section className="execution-scopes-settings">
      <header className="execution-scopes-header">
        <div>
          <span className="section-kicker">Execution security</span>
          <h2>Execution scopes</h2>
          <p>
            Bind a paired Device Agent to an approved Computer Workspace before
            Jace can run arbitrary commands or open interactive terminals.
          </p>
        </div>
        <button
          type="button"
          className="secondary-button"
          disabled={loading}
          onClick={() => void refresh()}
        >
          Refresh
        </button>
      </header>

      <div className="execution-scope-summary">
        <article>
          <span>Active scopes</span>
          <strong>{activeScopeCount}</strong>
        </article>
        <article>
          <span>Online devices</span>
          <strong>
            {onlineDeviceCount}/{devices.length}
          </strong>
        </article>
        <article>
          <span>Writable workspaces</span>
          <strong>
            {writableWorkspaceCount}/{workspaces.length}
          </strong>
        </article>
      </div>

      <div className="execution-scope-warning" role="note">
        <strong>Scope boundary, not a sandbox.</strong>
        <span>
          The configured root controls Jace&apos;s launch directory and approval
          context. An approved shell still runs as the Device Agent OS user and
          can explicitly address other host paths. Strong host isolation comes
          later in 4B.4C.
        </span>
      </div>

      {error && <div className="execution-scope-error">{error}</div>}

      <div className="execution-scope-layout">
        <div className="execution-scope-list">
          <div className="execution-scope-subhead">
            <div>
              <strong>Configured scopes</strong>
              <span>{scopes.length} total</span>
            </div>
          </div>

          {loading ? (
            <div className="execution-scope-empty">Loading execution scopes…</div>
          ) : scopes.length === 0 ? (
            <div className="execution-scope-empty">
              No execution scopes are configured yet.
            </div>
          ) : (
            scopes.map((scope) => {
              const device =
                devices.find((item) => item.id === scope.device_id) ?? null;
              const workspace =
                workspaces.find((item) => item.id === scope.workspace_id) ?? null;
              const online = device?.state === "online";
              const processReady =
                scope.process_enabled && device?.capabilities.includes("process.runtime");
              const terminalReady =
                scope.terminal_enabled && device?.capabilities.includes("terminal.runtime");

              return (
                <article
                  key={scope.id}
                  className={`execution-scope-card${scope.is_active ? "" : " inactive"}`}
                >
                  <div className="execution-scope-card-head">
                    <div>
                      <strong>{scope.label}</strong>
                      <span>{scopeCapabilityLabel(scope)}</span>
                    </div>
                    <span
                      className={`execution-scope-state ${
                        scope.is_active && online ? "ready" : "muted"
                      }`}
                    >
                      {scope.is_active
                        ? online
                          ? "ACTIVE · ONLINE"
                          : "ACTIVE · OFFLINE"
                        : "INACTIVE"}
                    </span>
                  </div>

                  <dl className="execution-scope-details">
                    <div>
                      <dt>Device</dt>
                      <dd>
                        {device?.name ?? scope.device_id}
                        {device?.hostname ? ` · ${device.hostname}` : ""}
                      </dd>
                    </div>
                    <div>
                      <dt>Workspace</dt>
                      <dd>{workspace?.label ?? scope.workspace_id}</dd>
                    </div>
                    <div>
                      <dt>Device root</dt>
                      <dd className="execution-scope-path">
                        {scope.device_root_path}
                      </dd>
                    </div>
                    <div>
                      <dt>Shells</dt>
                      <dd>{scope.allowed_shells.map((shell) => shellLabel(shell as ShellName)).join(", ")}</dd>
                    </div>
                  </dl>

                  <div className="execution-scope-capabilities">
                    <span className={processReady ? "ready" : "muted"}>
                      Process {processReady ? "ready" : "unavailable"}
                    </span>
                    <span className={terminalReady ? "ready" : "muted"}>
                      Terminal {terminalReady ? "ready" : "unavailable"}
                    </span>
                    <span className={workspace?.write_enabled ? "ready" : "warning"}>
                      {workspace?.write_enabled ? "Write-enabled" : "Read-only workspace"}
                    </span>
                  </div>

                  <div className="execution-scope-actions">
                    <button
                      type="button"
                      className="secondary-button"
                      onClick={() => editScope(scope)}
                    >
                      Edit
                    </button>
                    <button
                      type="button"
                      className="secondary-button"
                      onClick={() => void toggleScopeActive(scope)}
                    >
                      {scope.is_active ? "Disable" : "Enable"}
                    </button>
                    <button
                      type="button"
                      className="danger-button"
                      onClick={() => void removeScope(scope)}
                    >
                      Delete
                    </button>
                  </div>
                </article>
              );
            })
          )}
        </div>

        <form
          className="execution-scope-form"
          onSubmit={(event) => {
            event.preventDefault();
            void saveScope();
          }}
        >
          <div className="execution-scope-subhead">
            <div>
              <strong>{editingId ? "Edit scope" : "New scope"}</strong>
              <span>
                {editingId
                  ? "Device/workspace identity stays fixed; edit mount and access."
                  : "Create a device-specific mount for an approved workspace."}
              </span>
            </div>
            {editingId && (
              <button
                type="button"
                className="secondary-button"
                onClick={resetForm}
              >
                Cancel
              </button>
            )}
          </div>

          <label>
            <span>Label</span>
            <input
              value={form.label}
              onChange={(event) =>
                setForm((current) => ({
                  ...current,
                  label: event.target.value,
                }))
              }
              placeholder="Jace repo on BEN-DESKTOP"
            />
          </label>

          <label>
            <span>Device Agent</span>
            <select
              value={form.device_id}
              disabled={Boolean(editingId)}
              onChange={(event) =>
                setForm((current) => ({
                  ...current,
                  device_id: event.target.value,
                }))
              }
            >
              <option value="">Select a paired device…</option>
              {devices
                .filter((device) => device.is_active)
                .map((device) => (
                  <option key={device.id} value={device.id}>
                    {device.name} · {device.state}
                  </option>
                ))}
            </select>
          </label>

          {selectedDevice && (
            <div className="execution-scope-device-note">
              <span>
                {selectedDevice.platform} · {selectedDevice.architecture}
              </span>
              <span>
                process.runtime{" "}
                {selectedDevice.capabilities.includes("process.runtime")
                  ? "✓"
                  : "×"}
              </span>
              <span>
                terminal.runtime{" "}
                {selectedDevice.capabilities.includes("terminal.runtime")
                  ? "✓"
                  : "×"}
              </span>
            </div>
          )}

          <label>
            <span>Computer Workspace</span>
            <select
              value={form.workspace_id}
              disabled={Boolean(editingId)}
              onChange={(event) => selectWorkspace(event.target.value)}
            >
              <option value="">Select an approved workspace…</option>
              {workspaces
                .filter((workspace) => workspace.is_active)
                .map((workspace) => (
                  <option key={workspace.id} value={workspace.id}>
                    {workspace.label}
                    {workspace.write_enabled ? " · read/write" : " · read-only"}
                  </option>
                ))}
            </select>
          </label>

          {selectedWorkspace && !selectedWorkspace.write_enabled && (
            <div className="execution-scope-inline-warning">
              This workspace is read-only. Read-only inspection can use the
              scope, but arbitrary process execution and terminals will fail
              closed until workspace write access is enabled.
            </div>
          )}

          <label>
            <span>Device-local root</span>
            <input
              value={form.device_root_path}
              onChange={(event) =>
                setForm((current) => ({
                  ...current,
                  device_root_path: event.target.value,
                }))
              }
              placeholder="C:\Users\Ben\jace"
            />
            <small>
              This path is resolved by the selected Device Agent. It may differ
              from the same logical workspace&apos;s path on another device.
            </small>
          </label>

          <fieldset>
            <legend>Allowed shells</legend>
            <div className="execution-scope-shells">
              {SHELLS.map((shell) => {
                const available = availableShells.includes(shell);
                const checked = form.allowed_shells.includes(shell);

                return (
                  <label
                    key={shell}
                    className={!available ? "unavailable" : ""}
                  >
                    <input
                      type="checkbox"
                      checked={checked}
                      disabled={!available}
                      onChange={() => toggleShell(shell)}
                    />
                    <span>{shellLabel(shell)}</span>
                  </label>
                );
              })}
            </div>
          </fieldset>

          <div className="execution-scope-toggles">
            <label>
              <input
                type="checkbox"
                checked={form.process_enabled}
                onChange={(event) =>
                  setForm((current) => ({
                    ...current,
                    process_enabled: event.target.checked,
                  }))
                }
              />
              <span>
                <strong>Process runtime</strong>
                <small>Allow scoped foreground/background command execution.</small>
              </span>
            </label>
            <label>
              <input
                type="checkbox"
                checked={form.terminal_enabled}
                onChange={(event) =>
                  setForm((current) => ({
                    ...current,
                    terminal_enabled: event.target.checked,
                  }))
                }
              />
              <span>
                <strong>Interactive terminal</strong>
                <small>Allow scoped PTY/ConPTY terminal sessions.</small>
              </span>
            </label>
          </div>

          <button
            type="submit"
            className="primary-button"
            disabled={saving}
          >
            {saving
              ? "Saving…"
              : editingId
                ? "Save scope"
                : "Create execution scope"}
          </button>
        </form>
      </div>
    </section>
  );
}
