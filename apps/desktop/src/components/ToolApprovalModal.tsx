import { useState } from "react";
import type { PendingToolApproval, ToolApprovalDecision } from "../types";
import { Modal } from "./Modal";

interface ToolApprovalModalProps {
  approval: PendingToolApproval | null;
  onDecision: (decision: ToolApprovalDecision) => Promise<void>;
}

function prettyArguments(argumentsValue: Record<string, unknown>) {
  return JSON.stringify(argumentsValue, null, 2);
}

export function ToolApprovalModal({ approval, onDecision }: ToolApprovalModalProps) {
  const [submitting, setSubmitting] = useState(false);

  if (!approval) return null;

  async function decide(decision: ToolApprovalDecision) {
    if (submitting) return;
    setSubmitting(true);
    try {
      await onDecision(decision);
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <Modal title="Tool approval required" onClose={() => void decide("deny_once")}>
      <div className="approval-content">
        <div className={`approval-risk ${approval.risk}`}>{approval.risk === "write" ? "Changes local data" : "Read only"}</div>
        <h3>{approval.label}</h3>
        <p>{approval.description}</p>

        <div className="approval-details">
          <span>Requested action</span>
          <code>{approval.tool_name}</code>
        </div>

        <div className="approval-arguments">
          <span>Arguments</span>
          <pre>{prettyArguments(approval.arguments)}</pre>
        </div>

        <p className="approval-help">
          Allow once applies only to this call. Always allow changes the saved permission for this tool.
        </p>
      </div>

      <div className="approval-actions">
        <button className="secondary-button danger-soft" disabled={submitting} onClick={() => void decide("deny_always")}>Always deny</button>
        <button className="secondary-button" disabled={submitting} onClick={() => void decide("deny_once")}>Deny once</button>
        <button className="secondary-button" disabled={submitting} onClick={() => void decide("allow_always")}>Always allow</button>
        <button className="primary-button" disabled={submitting} onClick={() => void decide("allow_once")}>Allow once</button>
      </div>
    </Modal>
  );
}
