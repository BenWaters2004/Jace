import {
  useMemo,
  useState,
} from "react";

import {
  clearConversationToolGrants,
} from "../api";
import type {
  ToolAuditRecord,
  ToolRecord,
} from "../types";

import "../executionAudit.css";


interface PolicyContext {
  version?: number;
  configured_permission?: string | null;
  dynamic_floor?: string | null;
  effective_permission?: string | null;
  classification?: string | null;
  session_grant_used?: boolean | null;
  session_grant_available?: boolean | null;
  grantable?: boolean | null;
  scope_id?: string | null;
  scope_label?: string | null;
  device_id?: string | null;
  workspace_id?: string | null;
  shell?: string | null;
  relative_cwd?: string | null;
  mode?: string | null;
  command_sha256?: string | null;
  command_length?: number | null;
  provenance?: string | null;
}


interface ExecutionAuditViewProps {
  audit: ToolAuditRecord[];
  tools: ToolRecord[];
  onRefresh: () => void;
  onClearAudit: () => Promise<void>;
}


const EXECUTION_TOOL_NAMES = new Set([
  "run_device_command",
  "stop_device_process",
  "open_device_terminal",
  "send_device_terminal_input",
  "resize_device_terminal",
  "close_device_terminal",
  "inspect_device_command",
  "ui_run_device_command",
  "ui_stop_device_process",
  "ui_open_device_terminal",
  "ui_close_device_terminal",
]);


function objectValue(
  value: unknown,
): Record<string, unknown> | null {
  if (
    value
    && typeof value === "object"
    && !Array.isArray(value)
  ) {
    return value as Record<string, unknown>;
  }

  return null;
}


function stringValue(
  value: unknown,
): string | null {
  return typeof value === "string"
    && value.trim()
    ? value
    : null;
}


function booleanValue(
  value: unknown,
): boolean | null {
  return typeof value === "boolean"
    ? value
    : null;
}


function numberValue(
  value: unknown,
): number | null {
  return typeof value === "number"
    && Number.isFinite(value)
    ? value
    : null;
}


function policyContext(
  entry: ToolAuditRecord,
): PolicyContext | null {
  const value = objectValue(
    entry.arguments._jace_policy,
  );

  if (!value) return null;

  return {
    version: numberValue(value.version) ?? undefined,
    configured_permission: stringValue(
      value.configured_permission,
    ),
    dynamic_floor: stringValue(
      value.dynamic_floor,
    ),
    effective_permission: stringValue(
      value.effective_permission,
    ),
    classification: stringValue(
      value.classification,
    ),
    session_grant_used: booleanValue(
      value.session_grant_used,
    ),
    session_grant_available: booleanValue(
      value.session_grant_available,
    ),
    grantable: booleanValue(
      value.grantable,
    ),
    scope_id: stringValue(value.scope_id),
    scope_label: stringValue(value.scope_label),
    device_id: stringValue(value.device_id),
    workspace_id: stringValue(value.workspace_id),
    shell: stringValue(value.shell),
    relative_cwd: stringValue(value.relative_cwd),
    mode: stringValue(value.mode),
    command_sha256: stringValue(
      value.command_sha256,
    ),
    command_length: numberValue(
      value.command_length,
    ),
    provenance: stringValue(value.provenance),
  };
}


function visibleArguments(
  entry: ToolAuditRecord,
) {
  const {
    _jace_policy: _ignored,
    ...argumentsWithoutPolicy
  } = entry.arguments;

  return argumentsWithoutPolicy;
}


function dateTime(
  value: string,
) {
  return new Date(value).toLocaleString();
}


function statusClass(
  status: string,
) {
  if (status === "completed") return "success";

  if (
    status === "denied"
    || status === "timed_out"
  ) {
    return "warning";
  }

  if (status === "failed") return "danger";

  return "neutral";
}


function shortId(
  value: string | null | undefined,
) {
  if (!value) return "—";

  return value.length > 18
    ? `${value.slice(0, 8)}…${value.slice(-6)}`
    : value;
}


function permissionLabel(
  value: string | null | undefined,
) {
  if (!value) return "Not recorded";

  if (value === "explicit_user_action") {
    return "Explicit UI action";
  }

  return value.replace(/_/g, " ");
}


export function ExecutionAuditView({
  audit,
  tools,
  onRefresh,
  onClearAudit,
}: ExecutionAuditViewProps) {
  const [query, setQuery] = useState("");
  const [status, setStatus] = useState("all");
  const [scope, setScope] = useState("all");
  const [executionOnly, setExecutionOnly] = useState(true);
  const [busyConversation, setBusyConversation] =
    useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const toolLabels = useMemo(
    () =>
      new Map(
        tools.map((tool) => [
          tool.name,
          tool.label,
        ]),
      ),
    [tools],
  );

  const scopeOptions = useMemo(() => {
    const values = new Map<string, string>();

    for (const entry of audit) {
      const policy = policyContext(entry);

      if (!policy?.scope_id) continue;

      values.set(
        policy.scope_id,
        policy.scope_label
          || shortId(policy.scope_id),
      );
    }

    return Array.from(values.entries())
      .sort((left, right) =>
        left[1].localeCompare(right[1]),
      );
  }, [audit]);

  const filtered = useMemo(() => {
    const normalizedQuery = query.trim().toLowerCase();

    return audit.filter((entry) => {
      const policy = policyContext(entry);
      const executionEvent = (
        EXECUTION_TOOL_NAMES.has(entry.tool_name)
        || Boolean(policy)
      );

      if (
        executionOnly
        && !executionEvent
      ) {
        return false;
      }

      if (
        status !== "all"
        && entry.status !== status
      ) {
        return false;
      }

      if (
        scope !== "all"
        && policy?.scope_id !== scope
      ) {
        return false;
      }

      if (!normalizedQuery) return true;

      const haystack = [
        entry.tool_name,
        toolLabels.get(entry.tool_name) || "",
        entry.status,
        entry.permission_mode,
        entry.conversation_id || "",
        entry.error || "",
        entry.result_preview || "",
        policy?.scope_id || "",
        policy?.scope_label || "",
        policy?.device_id || "",
        policy?.workspace_id || "",
        policy?.classification || "",
        policy?.command_sha256 || "",
      ]
        .join(" ")
        .toLowerCase();

      return haystack.includes(normalizedQuery);
    });
  }, [
    audit,
    executionOnly,
    query,
    scope,
    status,
    toolLabels,
  ]);

  const executionEntries = audit.filter((entry) => (
    EXECUTION_TOOL_NAMES.has(entry.tool_name)
    || policyContext(entry) !== null
  ));

  const grantEntries = executionEntries.filter(
    (entry) =>
      policyContext(entry)?.session_grant_used
      === true,
  );

  const problemEntries = executionEntries.filter(
    (entry) =>
      entry.status === "failed"
      || entry.status === "denied"
      || entry.status === "timed_out",
  );

  async function clearConversationGrants(
    conversationId: string,
  ) {
    setBusyConversation(conversationId);
    setNotice(null);

    try {
      const result = await clearConversationToolGrants(
        conversationId,
      );

      setNotice(
        result.cleared > 0
          ? `Cleared ${result.cleared} remembered chat approval${result.cleared === 1 ? "" : "s"}.`
          : "No remembered chat approvals were active for that conversation.",
      );

      onRefresh();
    } catch (error) {
      setNotice(
        error instanceof Error
          ? error.message
          : "Could not clear remembered chat approvals.",
      );
    } finally {
      setBusyConversation(null);
    }
  }

  return (
    <section className="execution-audit">
      <header className="execution-audit-header">
        <div>
          <span className="section-kicker">
            4B.3G · Policy provenance
          </span>
          <h2>Execution audit</h2>
          <p>
            See what executed, which policy allowed or blocked it,
            and which device/workspace scope was involved. Raw shell
            commands and terminal keystrokes are not persisted here.
          </p>
        </div>

        <div className="execution-audit-header-actions">
          <button
            type="button"
            className="secondary-button"
            onClick={onRefresh}
          >
            Refresh
          </button>

          <button
            type="button"
            className="secondary-button"
            disabled={audit.length === 0}
            onClick={() => {
              if (
                window.confirm(
                  "Clear the tool audit log? Tool permissions and active chat grants will not be changed.",
                )
              ) {
                void onClearAudit();
              }
            }}
          >
            Clear audit
          </button>
        </div>
      </header>

      <div className="execution-audit-summary">
        <article>
          <span>Execution events</span>
          <strong>{executionEntries.length}</strong>
        </article>
        <article>
          <span>Exact chat grants used</span>
          <strong>{grantEntries.length}</strong>
        </article>
        <article>
          <span>Denied / failed</span>
          <strong>{problemEntries.length}</strong>
        </article>
        <article>
          <span>Total tool events</span>
          <strong>{audit.length}</strong>
        </article>
      </div>

      <div className="execution-audit-note">
        <strong>Historical compatibility</strong>
        <span>
          Events created before 4B.3G may not contain policy
          provenance. Their original audit status is still shown.
        </span>
      </div>

      {notice && (
        <div className="execution-audit-notice">
          {notice}
        </div>
      )}

      <div className="execution-audit-filters">
        <input
          value={query}
          onChange={(event) =>
            setQuery(event.target.value)
          }
          placeholder="Search tool, conversation, scope, device or hash…"
        />

        <select
          value={status}
          onChange={(event) =>
            setStatus(event.target.value)
          }
        >
          <option value="all">All statuses</option>
          <option value="requested">Requested</option>
          <option value="awaiting_approval">
            Awaiting approval
          </option>
          <option value="approved">Approved</option>
          <option value="completed">Completed</option>
          <option value="denied">Denied</option>
          <option value="failed">Failed</option>
          <option value="timed_out">Timed out</option>
        </select>

        <select
          value={scope}
          onChange={(event) =>
            setScope(event.target.value)
          }
        >
          <option value="all">All execution scopes</option>
          {scopeOptions.map(([id, label]) => (
            <option key={id} value={id}>
              {label}
            </option>
          ))}
        </select>

        <label className="execution-audit-toggle">
          <input
            type="checkbox"
            checked={executionOnly}
            onChange={(event) =>
              setExecutionOnly(event.target.checked)
            }
          />
          <span>Execution only</span>
        </label>
      </div>

      <div className="execution-audit-list">
        {filtered.length === 0 ? (
          <div className="settings-hub-empty">
            No audit events match these filters.
          </div>
        ) : (
          filtered.map((entry) => {
            const policy = policyContext(entry);
            const args = visibleArguments(entry);
            const toolLabel = (
              toolLabels.get(entry.tool_name)
              || entry.tool_name
            );

            return (
              <article
                key={entry.id}
                className="execution-audit-row"
              >
                <div className="execution-audit-row-head">
                  <div>
                    <strong>{toolLabel}</strong>
                    <code>{entry.tool_name}</code>
                  </div>
                  <span
                    className={`audit-status ${statusClass(entry.status)}`}
                  >
                    {entry.status.replace(/_/g, " ")}
                  </span>
                </div>

                <div className="execution-audit-time">
                  <span>{dateTime(entry.created_at)}</span>
                  {entry.completed_at && (
                    <span>
                      Completed {dateTime(entry.completed_at)}
                    </span>
                  )}
                  {entry.conversation_id && (
                    <span>
                      Conversation {shortId(entry.conversation_id)}
                    </span>
                  )}
                </div>

                {policy ? (
                  <div className="execution-policy-grid">
                    <div>
                      <span>Configured</span>
                      <strong>
                        {permissionLabel(
                          policy.configured_permission,
                        )}
                      </strong>
                    </div>
                    <div>
                      <span>Dynamic floor</span>
                      <strong>
                        {permissionLabel(
                          policy.dynamic_floor,
                        )}
                      </strong>
                    </div>
                    <div>
                      <span>Effective</span>
                      <strong>
                        {permissionLabel(
                          policy.effective_permission
                          || entry.permission_mode,
                        )}
                      </strong>
                    </div>
                    <div>
                      <span>Classification</span>
                      <strong>
                        {policy.classification
                          ?.replace(/_/g, " ")
                          || "Not recorded"}
                      </strong>
                    </div>
                    <div>
                      <span>Chat grant</span>
                      <strong>
                        {policy.session_grant_used === true
                          ? "Exact grant used"
                          : policy.session_grant_used === false
                            ? "Not used"
                            : "Not recorded"}
                      </strong>
                    </div>
                    <div>
                      <span>Grantable</span>
                      <strong>
                        {policy.grantable === true
                          ? "Yes"
                          : policy.grantable === false
                            ? "No"
                            : "Not recorded"}
                      </strong>
                    </div>
                  </div>
                ) : (
                  <div className="execution-policy-legacy">
                    Recorded policy:{" "}
                    <strong>
                      {permissionLabel(entry.permission_mode)}
                    </strong>
                  </div>
                )}

                {policy && (
                  <div className="execution-provenance">
                    <div>
                      <span>Scope</span>
                      <code>
                        {policy.scope_label
                          || shortId(policy.scope_id)}
                      </code>
                    </div>
                    <div>
                      <span>Device</span>
                      <code>{shortId(policy.device_id)}</code>
                    </div>
                    <div>
                      <span>Workspace</span>
                      <code>{shortId(policy.workspace_id)}</code>
                    </div>
                    <div>
                      <span>Shell</span>
                      <code>{policy.shell || "—"}</code>
                    </div>
                    <div>
                      <span>Relative CWD</span>
                      <code>{policy.relative_cwd || "—"}</code>
                    </div>
                    <div>
                      <span>Mode</span>
                      <code>{policy.mode || "—"}</code>
                    </div>
                  </div>
                )}

                {policy?.command_sha256 && (
                  <div className="execution-command-hash">
                    <span>Command SHA-256</span>
                    <code>{policy.command_sha256}</code>
                    {policy.command_length !== null
                      && policy.command_length !== undefined
                      && (
                        <small>
                          {policy.command_length} characters
                        </small>
                      )}
                  </div>
                )}

                {Object.keys(args).length > 0 && (
                  <details>
                    <summary>Redacted arguments</summary>
                    <pre>
                      {JSON.stringify(args, null, 2)}
                    </pre>
                  </details>
                )}

                {entry.result_preview && (
                  <p className="execution-audit-result">
                    {entry.result_preview}
                  </p>
                )}

                {entry.error && (
                  <p className="execution-audit-error">
                    {entry.error}
                  </p>
                )}

                {entry.conversation_id && (
                  <div className="execution-audit-row-actions">
                    <button
                      type="button"
                      className="secondary-button"
                      disabled={
                        busyConversation
                        === entry.conversation_id
                      }
                      onClick={() =>
                        void clearConversationGrants(
                          entry.conversation_id!,
                        )
                      }
                    >
                      Clear chat approvals
                    </button>
                  </div>
                )}
              </article>
            );
          })
        )}
      </div>
    </section>
  );
}
