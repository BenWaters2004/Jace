// JACE_STEP4A1_CONNECTIONS_FOUNDATION
import { useCallback, useEffect, useMemo, useState } from "react";
import { getCapabilities } from "../api";
import type { CapabilityRecord, CapabilitySnapshotResponse } from "../types";

const STATE_ORDER: CapabilityRecord["state"][] = ["ready", "configured", "blocked", "disconnected", "planned"];

export function CapabilityOverview() {
  const [snapshot, setSnapshot] = useState<CapabilitySnapshotResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    setError(null);
    try {
      setSnapshot(await getCapabilities());
    } catch (nextError) {
      setError(nextError instanceof Error ? nextError.message : "Could not load capabilities.");
    }
  }, []);

  useEffect(() => { void refresh(); }, [refresh]);

  const providerCapabilities = useMemo(
    () => (snapshot?.capabilities ?? []).filter((capability) => capability.source === "connection")
      .sort((left, right) => STATE_ORDER.indexOf(left.state) - STATE_ORDER.indexOf(right.state) || left.label.localeCompare(right.label)),
    [snapshot],
  );

  return (
    <div className="capability-overview">
      {error && <div className="error-banner"><div><strong>Capability registry</strong><span>{error}</span></div></div>}
      <div className="capability-summary-grid">
        <article><span>Ready local tools</span><strong>{snapshot?.counts.ready ?? "—"}</strong></article>
        <article><span>Configured providers</span><strong>{snapshot?.counts.configured ?? "—"}</strong></article>
        <article><span>Blocked</span><strong>{snapshot?.counts.blocked ?? "—"}</strong></article>
        <article><span>Connections</span><strong>{snapshot?.connection_count ?? "—"}</strong></article>
      </div>
      <div className="capability-registry-heading">
        <div><span className="section-kicker">Bindings</span><h3>External capability roadmap</h3></div>
        <button type="button" className="secondary-button" onClick={() => void refresh()}>Refresh</button>
      </div>
      <div className="capability-provider-list">
        {providerCapabilities.length === 0 ? (
          <div className="settings-hub-empty">Capability registry is loading…</div>
        ) : providerCapabilities.map((capability) => (
          <article key={capability.id}>
            <div><strong>{capability.label}</strong><span>{capability.provider_id} · {capability.category}</span></div>
            <p>{capability.description}</p>
            <span className={`connections-status-pill ${capability.state}`}>{capability.state}</span>
          </article>
        ))}
      </div>
      <div className="info-box capability-boundary-note">
        <strong>Configured does not mean executable.</strong>
        <span>Existing local tools remain the only model-callable capabilities in 4A.1. External provider capabilities become ready only when their guarded connector implementation is registered.</span>
      </div>
    </div>
  );
}
