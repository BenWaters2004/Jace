// JACE_STEP4A3_PROVIDER_CAPABILITY_PERMISSIONS
import { useCallback, useEffect, useMemo, useState } from "react";
import { getCapabilities, updateConnectionCapabilityPermission } from "../api";
import type { CapabilityPermissionMode, CapabilityRecord, CapabilitySnapshotResponse } from "../types";

const STATE_ORDER: CapabilityRecord["state"][] = ["ready", "configured", "blocked", "disconnected", "planned"];

export function CapabilityOverview() {
  const [snapshot, setSnapshot] = useState<CapabilitySnapshotResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [savingKey, setSavingKey] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    setError(null);
    try { setSnapshot(await getCapabilities()); }
    catch (nextError) { setError(nextError instanceof Error ? nextError.message : "Could not load capabilities."); }
  }, []);

  useEffect(() => { void refresh(); }, [refresh]);

  const providerCapabilities = useMemo(
    () => (snapshot?.capabilities ?? []).filter((capability) => capability.source === "connection")
      .sort((left, right) => STATE_ORDER.indexOf(left.state) - STATE_ORDER.indexOf(right.state) || left.label.localeCompare(right.label)),
    [snapshot],
  );

  async function setPermission(capability: CapabilityRecord, permission: CapabilityPermissionMode) {
    if (!capability.connection_id) return;
    const key = `${capability.connection_id}:${capability.id}`;
    setSavingKey(key); setError(null);
    try {
      setSnapshot(await updateConnectionCapabilityPermission(capability.connection_id, capability.provider_capability_id || capability.id.split(".").slice(1).join("."), permission));
    } catch (nextError) {
      setError(nextError instanceof Error ? nextError.message : "Could not update capability permission.");
    } finally { setSavingKey(null); }
  }

  return <div className="capability-overview">
    {error && <div className="error-banner"><div><strong>Capability registry</strong><span>{error}</span></div></div>}
    <div className="capability-summary-grid">
      <article><span>Ready local tools</span><strong>{snapshot?.counts.ready ?? "—"}</strong></article>
      <article><span>Provider bindings</span><strong>{snapshot?.counts.configured ?? "—"}</strong></article>
      <article><span>Blocked</span><strong>{snapshot?.counts.blocked ?? "—"}</strong></article>
      <article><span>Connections</span><strong>{snapshot?.connection_count ?? "—"}</strong></article>
    </div>
    <div className="capability-registry-heading"><div><span className="section-kicker">Bindings</span><h3>Provider capabilities</h3></div><button type="button" className="secondary-button" onClick={() => void refresh()}>Refresh</button></div>
    <div className="capability-provider-list">
      {providerCapabilities.length === 0 ? <div className="settings-hub-empty">Capability registry is loading…</div> : providerCapabilities.map((capability) => {
        const key = `${capability.connection_id}:${capability.id}`;
        return <article key={capability.id} className={`capability-binding-card risk-${capability.risk}`}>
          <div className="capability-binding-copy"><div><strong>{capability.label}</strong><span>{capability.provider_id} · {capability.category} · {capability.risk}</span></div><p>{capability.description}</p></div>
          <div className="capability-binding-controls"><span className={`connections-status-pill ${capability.state}`}>{capability.state}</span>{capability.connection_id ? <label><span>Permission</span><select value={(capability.permission || "ask") as CapabilityPermissionMode} disabled={savingKey === key} onChange={(event) => void setPermission(capability, event.target.value as CapabilityPermissionMode)}><option value="allow">Allow</option><option value="ask">Ask</option><option value="deny">Deny</option></select></label> : <span className="settings-muted">Connect an account first</span>}</div>
        </article>;
      })}
    </div>
    <div className="info-box capability-boundary-note"><strong>Permission binding is not execution.</strong><span>4A.3 records what Jace may do with each connected account. Provider API implementations arrive next; connecting an account never silently grants email, calendar or repository writes.</span></div>
  </div>;
}
