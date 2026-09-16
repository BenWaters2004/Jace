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


const EMAIL_WRITE_TOOLS = new Set([
  "gmail_create_draft",
  "gmail_send_email",
  "outlook_create_draft",
  "outlook_send_email",
]);


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


function stringList(
  value: unknown,
): string[] {
  if (!Array.isArray(value)) {
    return [];
  }

  return value.filter(
    (
      item,
    ): item is string => (
      typeof item === "string"
      && item.length > 0
    ),
  );
}


function EmailApprovalSummary({
  approval,
}: {
  approval: PendingToolApproval;
}) {
  const args = approval.arguments;
  const draftId = (
    typeof args.draft_id === "string"
      ? args.draft_id
      : ""
  );

  const to = stringList(
    args.to,
  );
  const cc = stringList(
    args.cc,
  );
  const bcc = stringList(
    args.bcc,
  );

  const subject = (
    typeof args.subject === "string"
      ? args.subject
      : ""
  );

  const body = (
    typeof args.body === "string"
      ? args.body
      : ""
  );

  const bodyFormat = (
    args.body_format === "html"
      ? "HTML"
      : "Plain text"
  );

  if (draftId) {
    return (
      <>
        <div className="approval-details">
          <span>
            Existing draft
          </span>

          <code>
            {draftId}
          </code>
        </div>

        <div className="approval-details">
          <span>
            Action
          </span>

          <code>
            Send this existing draft
          </code>
        </div>
      </>
    );
  }

  return (
    <>
      <div className="approval-details">
        <span>
          To
        </span>

        <code>
          {
            to.length > 0
              ? to.join(", ")
              : "(none)"
          }
        </code>
      </div>

      {cc.length > 0 && (
        <div className="approval-details">
          <span>
            Cc
          </span>

          <code>
            {cc.join(", ")}
          </code>
        </div>
      )}

      {bcc.length > 0 && (
        <div className="approval-details">
          <span>
            Bcc
          </span>

          <code>
            {bcc.join(", ")}
          </code>
        </div>
      )}

      <div className="approval-details">
        <span>
          Subject
        </span>

        <code>
          {subject || "(no subject)"}
        </code>
      </div>

      <div className="approval-details">
        <span>
          Body format
        </span>

        <code>
          {bodyFormat}
        </code>
      </div>

      <div className="approval-arguments">
        <span>
          Message body
        </span>

        <pre>
          {body || "(empty message body)"}
        </pre>
      </div>
    </>
  );
}


export function ToolApprovalModal({
  approval,
  onDecision,
}: ToolApprovalModalProps) {
  const [
    submitting,
    setSubmitting,
  ] = useState(false);

  if (!approval) {
    return null;
  }

  const external = Boolean(
    approval.connection_id
    && approval.capability_id,
  );

  const emailWrite = EMAIL_WRITE_TOOLS.has(
    approval.tool_name,
  );

  const isSend = (
    approval.capability_id === "email.send"
  );

  async function decide(
    decision: ToolApprovalDecision,
  ) {
    if (submitting) {
      return;
    }

    setSubmitting(true);

    try {
      await onDecision(
        decision,
      );
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <Modal
      title={
        isSend
          ? "Confirm email send"
          : "Tool approval required"
      }
      onClose={
        () => void decide(
          "deny_once",
        )
      }
    >
      <div className="approval-content">
        <div
          className={
            `approval-risk ${approval.risk}`
          }
        >
          {
            isSend
              ? "Sends external email"
              : approval.risk === "write"
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

        <h3>
          {approval.label}
        </h3>

        <p>
          {approval.description}
        </p>

        {external && (
          <>
            <div className="approval-details">
              <span>
                Connected account
              </span>

              <code>
                {
                  `${providerLabel(
                    approval.provider_id,
                  )}${
                    approval.account_hint
                      ? ` · ${approval.account_hint}`
                      : ""
                  }`
                }
              </code>
            </div>

            <div className="approval-details">
              <span>
                Capability
              </span>

              <code>
                {approval.capability_id}
              </code>
            </div>
          </>
        )}

        <div className="approval-details">
          <span>
            Requested action
          </span>

          <code>
            {approval.tool_name}
          </code>
        </div>

        {approval.source === "agent" && (
          <div className="approval-details">
            <span>
              Requested by
            </span>

            <code>
              {
                `${
                  (
                    approval.agent_id
                    || "background"
                  ).toUpperCase()
                } AGENT`
              }
            </code>
          </div>
        )}

        {
          emailWrite
            ? (
              <EmailApprovalSummary
                approval={approval}
              />
            )
            : (
              <div className="approval-arguments">
                <span>
                  Arguments
                </span>

                <pre>
                  {
                    prettyArguments(
                      approval.arguments,
                    )
                  }
                </pre>
              </div>
            )
        }

        <p className="approval-help">
          {
            isSend
              ? (
                "Send once authorizes only this email. "
                + "Always allow changes the saved send permission for "
                + "this capability on this connected account."
              )
              : external
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
          onClick={
            () => void decide(
              "deny_always",
            )
          }
        >
          Always deny
        </button>

        <button
          className="secondary-button"
          disabled={submitting}
          onClick={
            () => void decide(
              "deny_once",
            )
          }
        >
          {
            isSend
              ? "Cancel"
              : "Deny once"
          }
        </button>

        <button
          className="secondary-button"
          disabled={submitting}
          onClick={
            () => void decide(
              "allow_always",
            )
          }
        >
          {
            isSend
              ? "Always allow sending"
              : "Always allow"
          }
        </button>

        <button
          className="primary-button"
          disabled={submitting}
          onClick={
            () => void decide(
              "allow_once",
            )
          }
        >
          {
            isSend
              ? "Send once"
              : "Allow once"
          }
        </button>
      </div>
    </Modal>
  );
}
