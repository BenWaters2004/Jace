// JACE_STEP4A3_SCOPE_AWARE_CAPABILITY_REGISTRY

import {
  useCallback,
  useEffect,
  useMemo,
  useState,
} from "react";

import {
  getCapabilities,
  updateConnectionCapabilityPermission,
} from "../api";

import type {
  CapabilityPermissionMode,
  CapabilityRecord,
  CapabilitySnapshotResponse,
} from "../types";

const STATE_ORDER: CapabilityRecord["state"][] = [
  "ready",
  "configured",
  "blocked",
  "disconnected",
  "planned",
];

function stateRank(state: CapabilityRecord["state"]): number {
  const index = STATE_ORDER.indexOf(state);
  return index < 0 ? STATE_ORDER.length : index;
}

function providerLabel(providerId: string | null): string {
  switch (providerId) {
    case "google":
      return "Google";
    case "microsoft":
      return "Microsoft";
    case "github":
      return "GitHub";
    case "custom_api":
      return "Custom API";
    default:
      return providerId || "Provider";
  }
}

function statusLabel(capability: CapabilityRecord): string {
  if (
    capability.state === "blocked"
    && capability.availability_reason === "external_services_disabled"
  ) {
    return "External access off";
  }

  if (
    capability.state === "blocked"
    && capability.availability_reason === "provider_disabled"
  ) {
    return "Provider disabled";
  }

  if (
    capability.state === "blocked"
    && capability.availability_reason === "missing_scopes"
  ) {
    return "Needs access";
  }

  if (
    capability.state === "blocked"
    && capability.availability_reason === "permission_denied"
  ) {
    return "Denied";
  }

  if (
    capability.state === "blocked"
    && capability.availability_reason === "connection_error"
  ) {
    return "Connection error";
  }

  switch (capability.state) {
    case "ready":
      return "Ready";
    case "configured":
      return "Bound";
    case "disconnected":
      return "Disconnected";
    case "planned":
      return "Needs connection";
    default:
      return "Blocked";
  }
}

function availabilityText(capability: CapabilityRecord): string | null {
  switch (capability.availability_reason) {
    case "external_services_disabled":
      return (
        "External service access is disabled by the runtime master switch "
        + "in Permissions / Security."
      );

    case "provider_disabled":
      return (
        "This provider is disabled by Jace's runtime security policy."
      );

    case "missing_scopes":
      return (
        "The account is connected, but this capability needs additional "
        + "provider access before Jace can use it."
      );

    case "implementation_pending":
      return (
        "The account and provider access are ready. The executable Jace tool "
        + "will be attached in the next implementation step."
      );

    case "permission_denied":
      return "Jace permission is set to Deny for this account capability.";

    case "connection_error":
      return "The connected account currently has an error and must be verified or reconnected.";

    case "connection_disconnected":
      return "This account has been disconnected.";

    case "connection_required":
      return "Connect an account for this provider to create a capability binding.";

    case "ready":
      return "This capability has a live tool implementation and can be routed by Jace.";

    default:
      return null;
  }
}

export function CapabilityOverview() {
  const [
    snapshot,
    setSnapshot,
  ] = useState<CapabilitySnapshotResponse | null>(
    null,
  );

  const [
    error,
    setError,
  ] = useState<string | null>(
    null,
  );

  const [
    savingKey,
    setSavingKey,
  ] = useState<string | null>(
    null,
  );

  const refresh = useCallback(async () => {
    setError(null);

    try {
      setSnapshot(
        await getCapabilities(),
      );
    } catch (nextError) {
      setError(
        nextError instanceof Error
          ? nextError.message
          : "Could not load capabilities.",
      );
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const providerCapabilities = useMemo(
    () => (snapshot?.capabilities ?? [])
      .filter(
        (capability) => capability.source === "connection",
      )
      .sort((left, right) => {
        const providerCompare = providerLabel(
          left.provider_id,
        ).localeCompare(
          providerLabel(right.provider_id),
        );

        if (providerCompare !== 0) {
          return providerCompare;
        }

        const accountCompare = (
          left.account_hint ?? ""
        ).localeCompare(
          right.account_hint ?? "",
        );

        if (accountCompare !== 0) {
          return accountCompare;
        }

        const stateCompare = (
          stateRank(left.state)
          - stateRank(right.state)
        );

        if (stateCompare !== 0) {
          return stateCompare;
        }

        const categoryCompare = left.category.localeCompare(
          right.category,
        );

        if (categoryCompare !== 0) {
          return categoryCompare;
        }

        return left.label.localeCompare(
          right.label,
        );
      }),
    [snapshot],
  );

  async function setPermission(
    capability: CapabilityRecord,
    permission: CapabilityPermissionMode,
  ) {
    if (
      !capability.connection_id
      || !capability.provider_capability_id
    ) {
      return;
    }

    const key = (
      `${capability.connection_id}:${capability.provider_capability_id}`
    );

    setSavingKey(key);
    setError(null);

    try {
      setSnapshot(
        await updateConnectionCapabilityPermission(
          capability.connection_id,
          capability.provider_capability_id,
          permission,
        ),
      );
    } catch (nextError) {
      setError(
        nextError instanceof Error
          ? nextError.message
          : "Could not update capability permission.",
      );
    } finally {
      setSavingKey(null);
    }
  }

  return (
    <div className="capability-overview">
      {error && (
        <div className="error-banner">
          <div>
            <strong>Capability registry</strong>
            <span>{error}</span>
          </div>
        </div>
      )}

      <div className="capability-summary-grid">
        <article>
          <span>Ready local tools</span>
          <strong>
            {snapshot?.counts.ready ?? "—"}
          </strong>
        </article>

        <article>
          <span>Provider bindings</span>
          <strong>
            {snapshot?.counts.configured ?? "—"}
          </strong>
        </article>

        <article>
          <span>Needs provider access</span>
          <strong>
            {snapshot?.counts.needs_access ?? "—"}
          </strong>
        </article>

        <article>
          <span>Connections</span>
          <strong>
            {snapshot?.connection_count ?? "—"}
          </strong>
        </article>
      </div>

      <div className="capability-registry-heading">
        <div>
          <span className="section-kicker">
            Bindings
          </span>
          <h3>
            Provider capabilities
          </h3>
        </div>

        <button
          type="button"
          className="secondary-button"
          onClick={() => void refresh()}
        >
          Refresh
        </button>
      </div>

      <div className="capability-provider-list">
        {providerCapabilities.length === 0 ? (
          <div className="settings-hub-empty">
            Capability registry is loading…
          </div>
        ) : (
          providerCapabilities.map(
            (capability) => {
              const key = (
                capability.connection_id
                  ? `${capability.connection_id}:${capability.provider_capability_id}`
                  : capability.id
              );

              const explanation = availabilityText(
                capability,
              );

              return (
                <article
                  key={capability.id}
                  className={
                    `capability-binding-card risk-${capability.risk}`
                  }
                >
                  <div className="capability-binding-copy">
                    <div>
                      <strong>
                        {capability.label}
                      </strong>

                      <span>
                        {providerLabel(
                          capability.provider_id,
                        )}
                        {capability.account_hint
                          ? ` · ${capability.account_hint}`
                          : ""}
                        {` · ${capability.category} · ${capability.risk}`}
                      </span>
                    </div>

                    <p>
                      {capability.description}
                    </p>

                    {explanation && (
                      <small className="settings-muted">
                        {explanation}
                      </small>
                    )}

                    {capability.missing_scopes.length > 0 && (
                      <div className="capability-scope-note">
                        <strong>
                          Additional provider access:
                        </strong>

                        <span>
                          {capability.missing_scopes.join(
                            ", ",
                          )}
                        </span>
                      </div>
                    )}
                  </div>

                  <div className="capability-binding-controls">
                    <span
                      className={
                        `connections-status-pill ${capability.state}`
                      }
                    >
                      {statusLabel(capability)}
                    </span>

                    {capability.connection_id ? (
                      <label>
                        <span>
                          Jace permission
                        </span>

                        <select
                          value={
                            (
                              capability.permission
                              || "ask"
                            ) as CapabilityPermissionMode
                          }
                          disabled={savingKey === key}
                          onChange={(event) => {
                            void setPermission(
                              capability,
                              event.target.value as CapabilityPermissionMode,
                            );
                          }}
                        >
                          <option value="allow">
                            Allow
                          </option>

                          <option value="ask">
                            Ask
                          </option>

                          <option value="deny">
                            Deny
                          </option>
                        </select>
                      </label>
                    ) : (
                      <span className="settings-muted">
                        Connect an account first
                      </span>
                    )}
                  </div>
                </article>
              );
            }
          )
        )}
      </div>

      <div
        className="info-box capability-boundary-note"
      >
        <strong>
          Two separate gates protect external actions.
        </strong>

        <span>
          Provider access decides whether the connected account has granted
          the required OAuth scope. Jace permission decides whether the
          assistant may use that capability. A connection alone does not make
          Gmail, Outlook, Drive, OneDrive or repository actions executable.
        </span>
      </div>
    </div>
  );
}
