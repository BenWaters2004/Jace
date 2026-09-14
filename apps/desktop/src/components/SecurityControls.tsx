import {
  useCallback,
  useEffect,
  useMemo,
  useState,
} from "react";

import {
  emergencyStopExternalAccess,
  getExternalAccessPolicy,
  updateExternalAccessPolicy,
} from "../api";

import type {
  ExternalAccessPolicy,
} from "../types";


interface SecurityControlsProps {
  toolsEnabled: boolean;
}


function providerLabel(
  policy: ExternalAccessPolicy,
  providerId: string,
): string {
  return (
    policy.provider_names[providerId]
    || providerId
  );
}


export function SecurityControls({
  toolsEnabled,
}: SecurityControlsProps) {
  const [
    policy,
    setPolicy,
  ] = useState<ExternalAccessPolicy | null>(
    null,
  );

  const [
    loading,
    setLoading,
  ] = useState(true);

  const [
    savingKey,
    setSavingKey,
  ] = useState<string | null>(
    null,
  );

  const [
    error,
    setError,
  ] = useState<string | null>(
    null,
  );

  const refresh = useCallback(
    async () => {
      setError(null);

      try {
        setPolicy(
          await getExternalAccessPolicy(),
        );
      } catch (nextError) {
        setError(
          nextError instanceof Error
            ? nextError.message
            : "Could not load external access policy.",
        );
      } finally {
        setLoading(false);
      }
    },
    [],
  );

  useEffect(
    () => {
      void refresh();
    },
    [refresh],
  );

  const providerIds = useMemo(
    () => Object.keys(
      policy?.providers ?? {},
    ).sort(
      (left, right) => (
        providerLabel(
          policy as ExternalAccessPolicy,
          left,
        ).localeCompare(
          providerLabel(
            policy as ExternalAccessPolicy,
            right,
          ),
        )
      ),
    ),
    [policy],
  );

  async function setMaster(
    enabled: boolean,
  ) {
    setSavingKey("master");
    setError(null);

    try {
      setPolicy(
        await updateExternalAccessPolicy({
          external_services_enabled: enabled,
        }),
      );
    } catch (nextError) {
      setError(
        nextError instanceof Error
          ? nextError.message
          : "Could not update external access policy.",
      );
    } finally {
      setSavingKey(null);
    }
  }

  async function setProvider(
    providerId: string,
    enabled: boolean,
  ) {
    setSavingKey(
      `provider:${providerId}`,
    );
    setError(null);

    try {
      setPolicy(
        await updateExternalAccessPolicy({
          providers: {
            [providerId]: enabled,
          },
        }),
      );
    } catch (nextError) {
      setError(
        nextError instanceof Error
          ? nextError.message
          : "Could not update provider access.",
      );
    } finally {
      setSavingKey(null);
    }
  }

  async function emergencyStop() {
    if (
      !window.confirm(
        "Disable all external service access immediately? "
        + "Connected accounts and stored credentials will remain configured, "
        + "but Jace will not be allowed to use them until you re-enable access.",
      )
    ) {
      return;
    }

    setSavingKey("emergency");
    setError(null);

    try {
      setPolicy(
        await emergencyStopExternalAccess(),
      );
    } catch (nextError) {
      setError(
        nextError instanceof Error
          ? nextError.message
          : "Could not disable external access.",
      );
    } finally {
      setSavingKey(null);
    }
  }

  if (
    loading
    && !policy
  ) {
    return (
      <section className="security-control-panel">
        <div className="settings-hub-empty">
          Loading security policy…
        </div>
      </section>
    );
  }

  return (
    <section className="security-control-panel">
      <div className="security-control-heading">
        <div>
          <span className="section-kicker">
            Runtime safety
          </span>

          <h2>
            Access switches
          </h2>

          <p>
            These switches are enforced by the capability registry and
            revalidated immediately before external execution.
          </p>
        </div>

        <button
          type="button"
          className="danger-button"
          disabled={
            savingKey !== null
            || !policy?.external_services_enabled
          }
          onClick={() => void emergencyStop()}
        >
          Disable all external access
        </button>
      </div>

      {error && (
        <div className="error-banner">
          <div>
            <strong>
              Security policy
            </strong>

            <span>
              {error}
            </span>
          </div>
        </div>
      )}

      <div className="security-master-grid">
        <article
          className={
            `security-switch-card ${
              toolsEnabled
                ? "enabled"
                : "disabled"
            }`
          }
        >
          <div>
            <strong>
              Tool execution
            </strong>

            <span>
              Backend master switch
            </span>

            <p>
              {
                toolsEnabled
                  ? (
                    "Enabled by JACE_TOOLS_ENABLED. "
                    + "Individual tools and capabilities still apply their own policy."
                  )
                  : (
                    "Disabled by backend configuration. "
                    + "No Jace tool can execute until the backend setting is enabled."
                  )
              }
            </p>
          </div>

          <span className="security-switch-state">
            {toolsEnabled ? "Enabled" : "Disabled"}
          </span>
        </article>

        <article
          className={
            `security-switch-card ${
              policy?.external_services_enabled
                ? "enabled"
                : "disabled"
            }`
          }
        >
          <div>
            <strong>
              External services
            </strong>

            <span>
              Runtime master switch
            </span>

            <p>
              Disable every connected Google, Microsoft, GitHub and Custom API
              capability without removing accounts or credentials.
            </p>
          </div>

          <label className="security-toggle">
            <input
              type="checkbox"
              checked={
                policy?.external_services_enabled
                ?? false
              }
              disabled={savingKey !== null}
              onChange={(event) => {
                void setMaster(
                  event.target.checked,
                );
              }}
            />

            <span>
              {
                policy?.external_services_enabled
                  ? "Enabled"
                  : "Disabled"
              }
            </span>
          </label>
        </article>
      </div>

      <div className="security-provider-grid">
        {policy && providerIds.map(
          (providerId) => {
            const providerEnabled = (
              policy.providers[providerId]
              ?? true
            );

            const effective = (
              policy.external_services_enabled
              && providerEnabled
            );

            return (
              <article
                key={providerId}
                className={
                  `security-provider-row ${
                    effective
                      ? "enabled"
                      : "disabled"
                  }`
                }
              >
                <div>
                  <strong>
                    {
                      providerLabel(
                        policy,
                        providerId,
                      )
                    }
                  </strong>

                  <span>
                    {
                      policy.external_services_enabled
                        ? (
                          providerEnabled
                            ? "External capabilities available subject to scope and permission."
                            : "Provider blocked by Jace security policy."
                        )
                        : "Blocked by the external-services master switch."
                    }
                  </span>
                </div>

                <label className="security-toggle">
                  <input
                    type="checkbox"
                    checked={providerEnabled}
                    disabled={savingKey !== null}
                    onChange={(event) => {
                      void setProvider(
                        providerId,
                        event.target.checked,
                      );
                    }}
                  />

                  <span>
                    {
                      providerEnabled
                        ? "Allow"
                        : "Block"
                    }
                  </span>
                </label>
              </article>
            );
          },
        )}
      </div>

      <div className="info-box">
        <strong>
          Connections are preserved
        </strong>

        <span>
          Turning access off does not delete OAuth tokens or account metadata.
          It only makes matching capabilities unavailable to Jace until access
          is restored.
        </span>
      </div>
    </section>
  );
}
