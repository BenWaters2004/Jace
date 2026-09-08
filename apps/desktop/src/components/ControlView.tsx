import { useMemo, useState } from "react";
import type {
  ControlActionRecord,
  ControlAppPolicy,
  ControlAppPolicyCreateRequest,
  ControlAppPolicyUpdateRequest,
  ControlSessionRecord,
  ControlStatus,
  ControlWindowRecord,
} from "../types";
import { Modal } from "./Modal";

interface ControlViewProps {
  status: ControlStatus | null;
  windows: ControlWindowRecord[];
  policies: ControlAppPolicy[];
  sessions: ControlSessionRecord[];
  actions: ControlActionRecord[];
  activeConversationId: string | null;
  onRefresh: () => Promise<void>;
  onCreatePolicy: (payload: ControlAppPolicyCreateRequest) => Promise<void>;
  onUpdatePolicy: (policy: ControlAppPolicy, payload: ControlAppPolicyUpdateRequest) => Promise<void>;
  onDeletePolicy: (policy: ControlAppPolicy) => Promise<void>;
  onStartSession: (maxSteps: number, storeScreenshots: boolean) => Promise<void>;
  onStopSession: (session: ControlSessionRecord) => Promise<void>;
  onAuthorizeSensitive: (session: ControlSessionRecord) => Promise<void>;
  onEmergencyStop: () => Promise<void>;
}

interface PolicyDraft {
  id: string | null;
  label: string;
  process_pattern: string;
  title_pattern: string;
  observe_enabled: boolean;
  interact_enabled: boolean;
  sensitive_enabled: boolean;
  is_active: boolean;
}

const emptyDraft = (): PolicyDraft => ({
  id: null,
  label: "",
  process_pattern: "",
  title_pattern: "*",
  observe_enabled: true,
  interact_enabled: false,
  sensitive_enabled: false,
  is_active: true,
});

function timeLabel(value: string | null) {
  if (!value) return "—";
  return new Date(value).toLocaleString();
}

function policyFromWindow(window: ControlWindowRecord): PolicyDraft {
  return {
    id: null,
    label: window.process_name.replace(/\.exe$/i, "") || "Application",
    process_pattern: window.process_name,
    title_pattern: "*",
    observe_enabled: true,
    interact_enabled: true,
    sensitive_enabled: false,
    is_active: true,
  };
}

export function ControlView(props: ControlViewProps) {
  const [policyDraft, setPolicyDraft] = useState<PolicyDraft | null>(null);
  const [maxSteps, setMaxSteps] = useState(30);
  const [storeScreenshots, setStoreScreenshots] = useState(false);
  const [saving, setSaving] = useState(false);
  const [windowFilter, setWindowFilter] = useState("");
  const activeSession = props.status?.active_session ?? null;

  const filteredWindows = useMemo(() => {
    const q = windowFilter.trim().toLowerCase();
    if (!q) return props.windows;
    return props.windows.filter((window) =>
      `${window.process_name} ${window.title}`.toLowerCase().includes(q),
    );
  }, [props.windows, windowFilter]);

  async function savePolicy() {
    if (!policyDraft || saving) return;
    setSaving(true);
    try {
      if (policyDraft.id) {
        const existing = props.policies.find((item) => item.id === policyDraft.id);
        if (!existing) return;
        await props.onUpdatePolicy(existing, {
          label: policyDraft.label,
          process_pattern: policyDraft.process_pattern,
          title_pattern: policyDraft.title_pattern,
          observe_enabled: policyDraft.observe_enabled,
          interact_enabled: policyDraft.interact_enabled,
          sensitive_enabled: policyDraft.sensitive_enabled,
          is_active: policyDraft.is_active,
        });
      } else {
        await props.onCreatePolicy({
          label: policyDraft.label,
          process_pattern: policyDraft.process_pattern,
          title_pattern: policyDraft.title_pattern,
          observe_enabled: policyDraft.observe_enabled,
          interact_enabled: policyDraft.interact_enabled,
          sensitive_enabled: policyDraft.sensitive_enabled,
        });
      }
      setPolicyDraft(null);
    } finally {
      setSaving(false);
    }
  }

  return (
    <section className="page control-page">
      <header className="page-header">
        <div>
          <span className="eyebrow">Phase 9</span>
          <h1>Interactive Control</h1>
          <p>Short-lived, audited GUI control with per-application boundaries and an emergency stop.</p>
        </div>
        <div className="page-header-actions">
          <button className="secondary-button" onClick={() => void props.onRefresh()}>Refresh</button>
          <button className="danger-button control-stop-button" onClick={() => void props.onEmergencyStop()}>
            ■ Emergency stop
          </button>
        </div>
      </header>

      {!props.status?.platform_supported && (
        <div className="notice-banner warning">
          Phase 9 interactive control is Windows-first. The API can load here, but mouse/keyboard/window actions require Windows.
        </div>
      )}

      <div className="stat-grid control-stat-grid">
        <div className="stat-card"><span>Status</span><strong>{props.status?.enabled ? "Enabled" : "Disabled"}</strong></div>
        <div className="stat-card"><span>Visible windows</span><strong>{props.status?.visible_window_count ?? 0}</strong></div>
        <div className="stat-card"><span>App policies</span><strong>{props.status?.active_policy_count ?? 0}</strong></div>
        <div className="stat-card"><span>Control</span><strong>{activeSession ? "ACTIVE" : "Idle"}</strong></div>
      </div>

      <div className="control-safety-card">
        <div>
          <span className="eyebrow">Safety boundary</span>
          <h2>Approval is layered</h2>
          <p>
            Starting a session does not grant access to every app. An app must match an active policy before Jace can interact with it.
            Password managers and Windows credential/secure-desktop windows remain blocked. Sensitive screens/actions need a separate one-time authorization.
          </p>
        </div>
        <code>{props.status?.physical_failsafe ?? "Move the mouse to the top-left corner to trigger the physical fail-safe."}</code>
      </div>

      <div className="control-session-card">
        <div className="control-section-heading">
          <div>
            <span className="eyebrow">Live session</span>
            <h2>{activeSession ? "Jace can act within approved apps" : "No active control session"}</h2>
          </div>
          {activeSession && <span className="control-live-pill">LIVE</span>}
        </div>

        {activeSession ? (
          <div className="control-live-grid">
            <div><span>Session</span><code>{activeSession.id}</code></div>
            <div><span>Steps</span><strong>{activeSession.step_count} / {activeSession.max_steps}</strong></div>
            <div><span>Screenshots</span><strong>{activeSession.store_screenshots ? "Persisted" : "Live only"}</strong></div>
            <div><span>Sensitive</span><strong>{activeSession.sensitive_authorized_once ? "Next action authorised" : "Locked"}</strong></div>
            <div className="control-session-actions">
              <button
                className="secondary-button sensitive-button"
                disabled={activeSession.sensitive_authorized_once}
                onClick={() => void props.onAuthorizeSensitive(activeSession)}
              >
                Authorize next sensitive action
              </button>
              <button className="secondary-button danger-soft" onClick={() => void props.onStopSession(activeSession)}>Stop session</button>
            </div>
          </div>
        ) : (
          <div className="control-start-row">
            <label>
              <span>Maximum steps</span>
              <input type="number" min={1} max={80} value={maxSteps} onChange={(event) => setMaxSteps(Number(event.target.value))} />
            </label>
            <label className="toggle-line compact-toggle">
              <input type="checkbox" checked={storeScreenshots} onChange={(event) => setStoreScreenshots(event.target.checked)} />
              <span><strong>Store screenshots</strong><small>Keep action screenshots as conversation attachments for later audit.</small></span>
            </label>
            <button className="primary-button" onClick={() => void props.onStartSession(maxSteps, storeScreenshots)}>
              Start control session
            </button>
          </div>
        )}
      </div>

      <div className="control-two-column">
        <div className="control-panel">
          <div className="control-section-heading">
            <div><span className="eyebrow">Applications</span><h2>Visible windows</h2></div>
            <input className="control-filter" placeholder="Filter windows..." value={windowFilter} onChange={(event) => setWindowFilter(event.target.value)} />
          </div>
          <div className="control-window-list">
            {filteredWindows.length === 0 ? (
              <div className="command-empty">No visible windows found.</div>
            ) : filteredWindows.map((window) => (
              <div key={window.handle} className={`control-window-row ${window.blocked ? "blocked" : window.interact_allowed ? "allowed" : ""}`}>
                <div className="control-window-main">
                  <div className="control-window-title">
                    <strong>{window.process_name}</strong>
                    {window.is_active && <span className="control-mini-pill active">Active</span>}
                    {window.sensitive && <span className="control-mini-pill sensitive">Sensitive</span>}
                    {window.blocked && <span className="control-mini-pill blocked">Blocked</span>}
                  </div>
                  <span>{window.title}</span>
                  <small>{window.width}×{window.height} · HWND {window.handle}</small>
                </div>
                <div className="control-window-permissions">
                  <span className={window.observe_allowed ? "yes" : "no"}>Observe {window.observe_allowed ? "✓" : "×"}</span>
                  <span className={window.interact_allowed ? "yes" : "no"}>Interact {window.interact_allowed ? "✓" : "×"}</span>
                  {!window.blocked && !window.interact_allowed && (
                    <button className="tiny-button" onClick={() => setPolicyDraft(policyFromWindow(window))}>Approve app</button>
                  )}
                </div>
              </div>
            ))}
          </div>
        </div>

        <div className="control-panel">
          <div className="control-section-heading">
            <div><span className="eyebrow">Policy</span><h2>Approved applications</h2></div>
            <button className="secondary-button" onClick={() => setPolicyDraft(emptyDraft())}>＋ Add policy</button>
          </div>
          <div className="control-policy-list">
            {props.policies.length === 0 ? (
              <div className="command-empty">No app policies yet. Approve a visible app before Jace can interact with it.</div>
            ) : props.policies.map((policy) => (
              <div key={policy.id} className={`control-policy-row ${policy.is_active ? "" : "inactive"}`}>
                <div>
                  <strong>{policy.label}</strong>
                  <code>{policy.process_pattern} · {policy.title_pattern}</code>
                  <div className="control-policy-badges">
                    <span className={policy.observe_enabled ? "on" : "off"}>Observe</span>
                    <span className={policy.interact_enabled ? "on" : "off"}>Interact</span>
                    <span className={policy.sensitive_enabled ? "sensitive-on" : "off"}>Sensitive</span>
                  </div>
                </div>
                <div className="row-actions">
                  <button className="tiny-button" onClick={() => setPolicyDraft({ ...policy })}>Edit</button>
                  <button className="tiny-button danger-soft" onClick={() => void props.onDeletePolicy(policy)}>Delete</button>
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>

      <div className="control-panel control-history-panel">
        <div className="control-section-heading">
          <div><span className="eyebrow">Audit trail</span><h2>Recent GUI actions</h2></div>
          <span className="muted-copy">{props.actions.length} shown</span>
        </div>
        <div className="control-action-list">
          {props.actions.length === 0 ? (
            <div className="command-empty">No interactive actions have been recorded yet.</div>
          ) : props.actions.slice(0, 100).map((action) => (
            <div key={action.id} className={`control-action-row ${action.status}`}>
              <div>
                <strong>{action.action_type.replace(/_/g, " ")}</strong>
                <span>{action.process_name ?? "Unknown app"}{action.window_title ? ` · ${action.window_title}` : ""}</span>
              </div>
              <div>
                <span>{action.status}</span>
                <small>{timeLabel(action.created_at)}</small>
              </div>
              {action.result_preview && <p>{action.result_preview}</p>}
            </div>
          ))}
        </div>
      </div>

      {policyDraft && (
        <Modal title={policyDraft.id ? "Edit app policy" : "Add app policy"} onClose={() => setPolicyDraft(null)}>
          <div className="control-policy-editor">
            <label><span>Label</span><input value={policyDraft.label} onChange={(event) => setPolicyDraft({ ...policyDraft, label: event.target.value })} /></label>
            <label><span>Process pattern</span><input value={policyDraft.process_pattern} onChange={(event) => setPolicyDraft({ ...policyDraft, process_pattern: event.target.value })} placeholder="msedge.exe" /></label>
            <label><span>Window title pattern</span><input value={policyDraft.title_pattern} onChange={(event) => setPolicyDraft({ ...policyDraft, title_pattern: event.target.value })} placeholder="*" /></label>
            <p className="section-note">Patterns use wildcards. For example <code>Code.exe</code> or <code>*Chrome*.exe</code>; title <code>*GitHub*</code>.</p>
            <div className="control-policy-toggle-grid">
              <label className="toggle-line"><input type="checkbox" checked={policyDraft.observe_enabled} onChange={(event) => setPolicyDraft({ ...policyDraft, observe_enabled: event.target.checked })} /><span><strong>Observe</strong><small>Jace may capture this window inside a control session.</small></span></label>
              <label className="toggle-line"><input type="checkbox" checked={policyDraft.interact_enabled} onChange={(event) => setPolicyDraft({ ...policyDraft, interact_enabled: event.target.checked, sensitive_enabled: event.target.checked ? policyDraft.sensitive_enabled : false })} /><span><strong>Interact</strong><small>Jace may focus/click/scroll/type after the session has been approved.</small></span></label>
              <label className={`toggle-line sensitive-policy ${policyDraft.interact_enabled ? "" : "disabled"}`}><input type="checkbox" disabled={!policyDraft.interact_enabled} checked={policyDraft.sensitive_enabled} onChange={(event) => setPolicyDraft({ ...policyDraft, sensitive_enabled: event.target.checked })} /><span><strong>Sensitive screens</strong><small>Still requires a separate one-time authorization for each detected sensitive action.</small></span></label>
              {policyDraft.id && <label className="toggle-line"><input type="checkbox" checked={policyDraft.is_active} onChange={(event) => setPolicyDraft({ ...policyDraft, is_active: event.target.checked })} /><span><strong>Policy active</strong><small>Disable without deleting the policy.</small></span></label>}
            </div>
          </div>
          <div className="modal-actions">
            <button className="secondary-button" onClick={() => setPolicyDraft(null)}>Cancel</button>
            <button className="primary-button" disabled={saving || !policyDraft.label.trim() || !policyDraft.process_pattern.trim()} onClick={() => void savePolicy()}>{saving ? "Saving..." : "Save policy"}</button>
          </div>
        </Modal>
      )}
    </section>
  );
}
