import { useState } from "react";

import type {
  PendingToolApproval,
  ToolApprovalDecision,
} from "../types";

import { Modal } from "./Modal";


interface ToolApprovalModalProps {
  approval: PendingToolApproval | null;
  onDecision: (
    decision: ToolApprovalDecision,
  ) => Promise<void>;
}


function prettyArguments(
  argumentsValue: Record<string, unknown>,
) {
  return JSON.stringify(
    argumentsValue,
    null,
    2,
  );
}


function providerLabel(
  providerId: string | null | undefined,
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
      return providerId || "External service";
  }
}


export function ToolApprovalModal({
  approval,
  onDecision,
}: ToolApprovalModalProps) {
  const [
    submitting,
    setSubmitting,
  ] = useState(false);

  if (!approval) return null;

  const external = Boolean(
    approval.connection_id
    && approval.capability_id,
  );

  async function decide(
    decision: ToolApprovalDecision,
  ) {
    if (submitting) return;

    setSubmitting(true);

    try {
      await onDecision(decision);
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <Modal
      title="Tool approval required"
      onClose={() => void decide("deny_once")}
    >
      <div className="approval-content">
        <div
          className={`approval-risk ${approval.risk}`}
        >
          {
            approval.risk === "write"
              ? (
                external
                  ? "Changes external data"
                  : "Changes local data"
              )
              : approval.risk === "execute"
                ? "Runs an action"
                : "Read only"
          }
        </div>

        <h3>{approval.label}</h3>

        <p>{approval.description}</p>

        {external && (
          <>
            <div className="approval-details">
              <span>Connected account</span>
              <code>
                {
                  `${providerLabel(approval.provider_id)}${
                    approval.account_hint
                      ? ` · ${approval.account_hint}`
                      : ""
                  }`
                }
              </code>
            </div>

            <div className="approval-details">
              <span>Capability</span>
              <code>{approval.capability_id}</code>
            </div>
          </>
        )}

        <div className="approval-details">
          <span>Requested action</span>
          <code>{approval.tool_name}</code>
        </div>

        {approval.source === "agent" && (
          <div className="approval-details">
            <span>Requested by</span>
            <code>
              {
                `${(approval.agent_id || "background").toUpperCase()} AGENT`
              }
            </code>
          </div>
        )}

        <div className="approval-arguments">
          <span>Arguments</span>
          <pre>
            {prettyArguments(approval.arguments)}
          </pre>
        </div>

        <p className="approval-help">
          {
            external
              ? (
                "Allow once applies only to this call. "
                + "Always allow/deny changes the saved permission for "
                + "this capability on this connected account only."
              )
              : (
                "Allow once applies only to this call. "
                + "Always allow changes the saved permission for this tool."
              )
          }
        </p>
      </div>

      <div className="approval-actions">
        <button
          className="secondary-button danger-soft"
          disabled={submitting}
          onClick={() => void decide("deny_always")}
        >
          Always deny
        </button>

        <button
          className="secondary-button"
          disabled={submitting}
          onClick={() => void decide("deny_once")}
        >
          Deny once
        </button>

        <button
          className="secondary-button"
          disabled={submitting}
          onClick={() => void decide("allow_always")}
        >
          Always allow
        </button>

        <button
          className="primary-button"
          disabled={submitting}
          onClick={() => void decide("allow_once")}
        >
          Allow once
        </button>
      </div>
    </Modal>
  );
}
