import {
  useMemo,
  useState,
} from "react";

import type {
  ControlActionRecord,
  ToolAuditRecord,
} from "../types";


interface AuditViewProps {
  audit: ToolAuditRecord[];
  controlActions: ControlActionRecord[];
  onRefresh: () => void;
  onClearAudit: () => Promise<void>;
}


function providerLabel(
  providerId: string | null,
): string {
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
      return providerId || "Local";
  }
}


function statusClass(
  status: string,
): string {
  if (
    status === "completed"
  ) {
    return "success";
  }

  if (
    [
      "denied",
      "timed_out",
    ].includes(status)
  ) {
    return "warning";
  }

  if (
    status === "failed"
  ) {
    return "danger";
  }

  return "neutral";
}


export function AuditView({
  audit,
  controlActions,
  onRefresh,
  onClearAudit,
}: AuditViewProps) {
  const [
    search,
    setSearch,
  ] = useState("");

  const [
    provider,
    setProvider,
  ] = useState("all");

  const [
    status,
    setStatus,
  ] = useState("all");

  const providers = useMemo(
    () => Array.from(
      new Set(
        audit
          .map(
            (entry) => entry.provider_id,
          )
          .filter(
            (
              value,
            ): value is string => Boolean(value),
          ),
      ),
    ).sort(
      (left, right) => (
        providerLabel(left)
          .localeCompare(
            providerLabel(right),
          )
      ),
    ),
    [audit],
  );

  const statuses = useMemo(
    () => Array.from(
      new Set(
        audit.map(
          (entry) => entry.status,
        ),
      ),
    ).sort(),
    [audit],
  );

  const filtered = useMemo(
    () => {
      const query = search.trim().toLowerCase();

      return audit.filter(
        (entry) => {
          if (
            provider !== "all"
            && entry.provider_id !== provider
          ) {
            return false;
          }

          if (
            status !== "all"
            && entry.status !== status
          ) {
            return false;
          }

          if (!query) {
            return true;
          }

          const haystack = [
            entry.tool_name,
            entry.provider_id,
            entry.account_hint,
            entry.capability_id,
            entry.status,
            entry.permission_mode,
            entry.result_preview,
            entry.error,
          ]
            .filter(Boolean)
            .join(" ")
            .toLowerCase();

          return haystack.includes(query);
        },
      );
    },
    [
      audit,
      provider,
      search,
      status,
    ],
  );

  const externalCount = audit.filter(
    (entry) => Boolean(
      entry.connection_id,
    ),
  ).length;

  const blockedCount = audit.filter(
    (entry) => [
      "denied",
      "failed",
      "timed_out",
    ].includes(entry.status),
  ).length;

  return (
    <>
      <div className="settings-audit-summary settings-audit-summary-wide">
        <article>
          <span>
            Tool events
          </span>

          <strong>
            {audit.length}
          </strong>
        </article>

        <article>
          <span>
            External actions
          </span>

          <strong>
            {externalCount}
          </strong>
        </article>

        <article>
          <span>
            Blocked / failed
          </span>

          <strong>
            {blockedCount}
          </strong>
        </article>

        <article>
          <span>
            Control actions
          </span>

          <strong>
            {controlActions.length}
          </strong>
        </article>
      </div>

      <div className="settings-audit-toolbar">
        <input
          type="search"
          value={search}
          placeholder="Search tool, account or capability"
          onChange={
            (event) => setSearch(
              event.target.value,
            )
          }
        />

        <select
          value={provider}
          onChange={
            (event) => setProvider(
              event.target.value,
            )
          }
        >
          <option value="all">
            All providers
          </option>

          {providers.map(
            (providerId) => (
              <option
                key={providerId}
                value={providerId}
              >
                {
                  providerLabel(
                    providerId,
                  )
                }
              </option>
            ),
          )}
        </select>

        <select
          value={status}
          onChange={
            (event) => setStatus(
              event.target.value,
            )
          }
        >
          <option value="all">
            All statuses
          </option>

          {statuses.map(
            (value) => (
              <option
                key={value}
                value={value}
              >
                {
                  value.replace(
                    /_/g,
                    " ",
                  )
                }
              </option>
            ),
          )}
        </select>

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
                "Clear the tool audit log? Tool and capability permissions will not be changed.",
              )
            ) {
              void onClearAudit();
            }
          }}
        >
          Clear log
        </button>
      </div>

      <div className="settings-audit-list">
        {filtered.length === 0 ? (
          <div className="settings-hub-empty">
            {
              audit.length === 0
                ? "No tool activity has been recorded yet."
                : "No audit entries match the current filters."
            }
          </div>
        ) : (
          filtered.map(
            (entry) => (
              <article
                key={entry.id}
                className="settings-audit-row settings-audit-row-rich"
              >
                <div className="settings-audit-row-head">
                  <div>
                    <strong>
                      {entry.tool_name}
                    </strong>

                    <span
                      className={
                        `audit-status ${
                          statusClass(
                            entry.status,
                          )
                        }`
                      }
                    >
                      {
                        entry.status.replace(
                          /_/g,
                          " ",
                        )
                      }
                    </span>
                  </div>

                  <small>
                    {
                      new Date(
                        entry.created_at,
                      ).toLocaleString()
                    }
                  </small>
                </div>

                <div className="settings-audit-tags">
                  <span>
                    Policy · {
                      entry.permission_mode
                    }
                  </span>

                  {entry.provider_id && (
                    <span>
                      {
                        providerLabel(
                          entry.provider_id,
                        )
                      }
                    </span>
                  )}

                  {entry.account_hint && (
                    <span>
                      {entry.account_hint}
                    </span>
                  )}

                  {entry.capability_id && (
                    <span>
                      {entry.capability_id}
                    </span>
                  )}
                </div>

                <p>
                  {
                    entry.error
                    || entry.result_preview
                    || "No result preview recorded."
                  }
                </p>

                {Object.keys(
                  entry.arguments,
                ).length > 0 && (
                  <details>
                    <summary>
                      Arguments
                    </summary>

                    <pre>
                      {
                        JSON.stringify(
                          entry.arguments,
                          null,
                          2,
                        )
                      }
                    </pre>
                  </details>
                )}
              </article>
            ),
          )
        )}
      </div>
    </>
  );
}
