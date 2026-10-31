/** C4D.2 Fix1: process-local passive provider counters, not a network test. */
import { useEffect, useState } from "react";
import { authenticatedFetch } from "../api";
import { API_BASE_URL } from "../constants";
import "./LiveProviderActivity.css";

interface RouteObservation {
  route_id: string;
  attempts: number;
  successes: number;
  failures: number;
  active: number;
}
interface ReliabilitySnapshot {
  enabled: boolean;
  scope: string;
  routes: RouteObservation[];
}
interface GatewayStatus { routes: Record<string, { provider?: string; model?: string; error?: string }> }

export function LiveProviderActivity() {
  const [observed, setObserved] = useState<ReliabilitySnapshot | null>(null);
  const [configured, setConfigured] = useState<GatewayStatus | null>(null);
  const [error, setError] = useState(false);
  useEffect(() => {
    let disposed = false;
    async function refresh() {
      try {
        const [reliability, status] = await Promise.all([
          authenticatedFetch(`${API_BASE_URL}/model-gateway/reliability`),
          authenticatedFetch(`${API_BASE_URL}/model-gateway/status`),
        ]);
        if (!reliability.ok || !status.ok) throw new Error("Gateway status unavailable");
        const metrics = await reliability.json() as ReliabilitySnapshot;
        const routeSettings = await status.json() as GatewayStatus;
        if (!Array.isArray(metrics.routes) || typeof metrics.enabled !== "boolean" ||
            !routeSettings.routes || typeof routeSettings.routes !== "object") throw new Error("Invalid response");
        if (!disposed) { setObserved(metrics); setConfigured(routeSettings); setError(false); }
      } catch {
        if (!disposed) { setError(true); setObserved(null); setConfigured(null); }
      }
    }
    void refresh();
    const handle = window.setInterval(() => { void refresh(); }, 20000);
    return () => { disposed = true; window.clearInterval(handle); };
  }, []);
  const cloud = (observed?.routes ?? []).filter(r =>
    /^(openai|anthropic):/.test(r.route_id) && Number.isFinite(r.successes));
  const total = cloud.reduce((count, r) => count + Math.max(0, r.successes), 0);
  const fast = configured?.routes?.["conversation.fast"];
  return <section className="jdi-provider-actual" aria-label="Observed model provider activity">
    <header><strong>Provider activity — this Core process</strong><span>Auto refreshes every 20 seconds</span></header>
    <p>Configured conversation.fast route: <strong>{fast?.provider && fast.model
      ? `${fast.provider}:${fast.model}` : fast?.error ? "Unavailable" : "Not reported"}</strong></p>
    {error ? <p>Could not read local gateway telemetry.</p> :
      !observed ? <p>Checking Jace Core…</p> :
      !observed.enabled ? <p><strong>Cloud request tracking is disabled.</strong> Enable JACE_CLOUD_RELIABILITY_ENABLED=true in Core and restart to observe subsequent cloud calls.</p> :
      <><p><strong>{total} completed cloud provider operation(s)</strong> observed since this Jace Core process started. This includes chat and collaboration, not just this conversation.</p>
        {cloud.length === 0 ? <p>No cloud requests observed in this process.</p> :
          <div className="jdi-provider-observed-list">{cloud.map(r =>
            <div key={r.route_id}><strong>{r.route_id}</strong><span>{r.successes} successful · {r.failures} failed · {r.active} active</span></div>
          )}</div>}
      </>}
    <small>This reports live gateway counters only. A configured route is not proof of use; individual specialist tasks can still use Ollama. Counters reset with Core.</small>
  </section>;
}
