// JACE_STEP4A22_ONE_CLICK_CONNECTIONS
import { openUrl } from "@tauri-apps/plugin-opener";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  createConnection,
  deleteConnection,
  disconnectConnection,
  getConnections,
  getConnectionProviders,
  getOAuthClientConfigs,
  getOAuthSession,
  startOAuthConnection,
  verifyConnection,
} from "../api";
import type {
  ConnectionAuthMode,
  ConnectionProvider,
  ConnectionRecord,
  OAuthClientConfig,
  OAuthSession,
} from "../types";

type Draft = { label: string; baseUrl: string; authMode: ConnectionAuthMode; headerName: string; secret: string };
const EMPTY_DRAFT: Draft = { label: "", baseUrl: "", authMode: "bearer", headerName: "X-API-Key", secret: "" };

function providerState(provider: ConnectionProvider, count: number, configured: boolean): string {
  if (count > 0) return `${count} connected`;
  if (provider.auth_kind === "oauth2") return configured ? "Ready to connect" : "App setup needed";
  return provider.setup_state === "available" ? "Available" : "Unavailable";
}

export function ConnectionsView() {
  const [providers, setProviders] = useState<ConnectionProvider[]>([]);
  const [connections, setConnections] = useState<ConnectionRecord[]>([]);
  const [oauthConfigs, setOAuthConfigs] = useState<OAuthClientConfig[]>([]);
  const [secretStore, setSecretStore] = useState<{
    available: boolean;
    backend: string;
    reason: string | null;
  } | null>(null);

  const [showCustomForm, setShowCustomForm] = useState(false);
  const [oauthFlow, setOAuthFlow] = useState<OAuthSession | null>(null);
  const [draft, setDraft] = useState<Draft>(EMPTY_DRAFT);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const pollTimer = useRef<number | null>(null);

  const refresh = useCallback(async () => {
    setError(null);
    try {
      const [providerResponse, connectionResponse, oauthResponse] = await Promise.all([
        getConnectionProviders(), getConnections(), getOAuthClientConfigs(),
      ]);
      setProviders(providerResponse.providers);
      setConnections(connectionResponse.connections);
      setOAuthConfigs(oauthResponse.configs);
      setSecretStore(connectionResponse.secret_store);
    } catch (nextError) {
      setError(nextError instanceof Error ? nextError.message : "Could not load connections.");
    } finally { setLoading(false); }
  }, []);

  useEffect(() => { void refresh(); }, [refresh]);
  useEffect(() => () => { if (pollTimer.current !== null) window.clearTimeout(pollTimer.current); }, []);

  const counts = useMemo(() => {
    const next = new Map<string, number>();
    for (const connection of connections) next.set(connection.provider_id, (next.get(connection.provider_id) ?? 0) + 1);
    return next;
  }, [connections]);
  const configMap = useMemo(() => new Map(oauthConfigs.map((item) => [item.provider_id, item])), [oauthConfigs]);

  async function addCustomConnection() {
    if (!draft.label.trim() || !draft.baseUrl.trim()) { setError("Name and base URL are required."); return; }
    if (!secretStore?.available && draft.authMode !== "none") { setError(secretStore?.reason || "Secure credential storage is unavailable."); return; }
    setSaving(true); setError(null);
    try {
      await createConnection({ provider_id: "custom_api", label: draft.label.trim(), base_url: draft.baseUrl.trim(), auth_mode: draft.authMode, header_name: draft.authMode === "header" ? draft.headerName.trim() : null, secret: draft.authMode === "none" ? null : (draft.secret.trim() || null) });
      setDraft(EMPTY_DRAFT); setShowCustomForm(false); await refresh();
    } catch (nextError) { setError(nextError instanceof Error ? nextError.message : "Could not create connection."); }
    finally { setSaving(false); }
  }

  async function pollOAuth(sessionId: string, delaySeconds: number) {
    if (pollTimer.current !== null) window.clearTimeout(pollTimer.current);
    pollTimer.current = window.setTimeout(async () => {
      try {
        const status = await getOAuthSession(sessionId);
        setOAuthFlow(status);
        if (status.status === "pending") { void pollOAuth(sessionId, Math.max(2, status.poll_interval_seconds)); return; }
        if (status.status === "completed") await refresh();
      } catch (nextError) { setError(nextError instanceof Error ? nextError.message : "Could not check authorization status."); }
    }, Math.max(2, delaySeconds) * 1000);
  }

  async function connectOAuth(providerId: string) {
    const oauthConfig = configMap.get(providerId);
    if (!oauthConfig?.configured) { setError("This Jace installation is missing the provider OAuth client ID. Configure it once in backend/.env and restart Jace."); return; }
    if (!secretStore?.available) { setError(secretStore?.reason || "Secure credential storage is unavailable."); return; }
    setError(null);
    try {
      const flow = await startOAuthConnection(providerId);
      setOAuthFlow(flow);
      const target = flow.authorization_url || flow.verification_uri;
      if (target) await openUrl(target);
      void pollOAuth(flow.session_id, flow.poll_interval_seconds);
    } catch (nextError) { setError(nextError instanceof Error ? nextError.message : "Could not start OAuth authorization."); }
  }

  async function disconnect(connection: ConnectionRecord) {
    if (!window.confirm(`Disconnect ${connection.label}? Its stored credential/token will be removed.`)) return;
    try { await disconnectConnection(connection.id); await refresh(); } catch (nextError) { setError(nextError instanceof Error ? nextError.message : "Could not disconnect account."); }
  }
  async function remove(connection: ConnectionRecord) {
    if (!window.confirm(`Delete ${connection.label}? This removes its Jace metadata and stored credential/token.`)) return;
    try { await deleteConnection(connection.id); await refresh(); } catch (nextError) { setError(nextError instanceof Error ? nextError.message : "Could not delete connection."); }
  }
  async function verify(connection: ConnectionRecord) {
    try { await verifyConnection(connection.id); await refresh(); } catch (nextError) { setError(nextError instanceof Error ? nextError.message : "Could not verify account."); }
  }

  if (loading) return <div className="connections-loading">Loading connection registry…</div>;

  return <div className="connections-view">
    <div className={`connections-vault-banner ${secretStore?.available ? "ready" : "warning"}`}><div><strong>{secretStore?.available ? "Secure credential vault ready" : "Credential vault unavailable"}</strong><span>{secretStore?.available ? "OAuth tokens, refresh tokens and API secrets stay in Windows Credential Manager. SQLite stores account metadata only." : secretStore?.reason || "Jace will not accept connection secrets until a secure vault is available."}</span></div><span className="connections-status-pill">{secretStore?.backend ?? "checking"}</span></div>
    {error && <div className="error-banner connections-error"><div><strong>Connections</strong><span>{error}</span></div></div>}

    {oauthFlow && <div className="connection-modal-backdrop"><section className="connection-modal" role="dialog" aria-modal="true"><div className={`connection-modal-pulse ${oauthFlow.status}`}>{oauthFlow.status === "completed" ? "✓" : oauthFlow.status === "pending" ? "↗" : "!"}</div><span className="section-kicker">Secure authentication</span><h2>{oauthFlow.status === "pending" ? "Connecting account" : oauthFlow.status === "completed" ? "Account connected" : "Authorization did not complete"}</h2><p>{oauthFlow.status === "pending" ? "Jace opened the provider sign-in in your system browser. Complete authentication there; this window will update automatically." : oauthFlow.account_hint || oauthFlow.error || "Authorization finished."}</p>{oauthFlow.user_code && <div className="connection-device-code"><span>Verification code</span><code>{oauthFlow.user_code}</code></div>}<button type="button" className="secondary-button" onClick={() => setOAuthFlow(null)}>{oauthFlow.status === "pending" ? "Cancel" : "Close"}</button></section></div>}

    <div className="connection-provider-grid">{providers.map((provider) => {
      const oauthConfig = configMap.get(provider.id); const count = counts.get(provider.id) ?? 0;
      return <article className="connection-provider-card" key={provider.id}>
        <div className="connection-provider-head"><div><span className="section-kicker">{provider.auth_kind}</span><h3>{provider.name}</h3></div><span className={`connections-status-pill ${count ? "configured" : oauthConfig?.configured ? "ready" : provider.setup_state}`}>{providerState(provider, count, Boolean(oauthConfig?.configured))}</span></div>
        <p>{provider.description}</p><div className="connection-capability-chips">{provider.capabilities.slice(0,6).map((capability)=><span key={capability.id}>{capability.id}</span>)}</div>
        {provider.id === "custom_api" ? <button type="button" className="primary-button" onClick={() => setShowCustomForm((value)=>!value)}>{showCustomForm ? "Cancel" : "Add API connection"}</button> : <div className="oauth-provider-actions"><button type="button" className="primary-button" disabled={!oauthConfig?.configured || !secretStore?.available} onClick={() => void connectOAuth(provider.id)}>{count > 0 ? "Connect another account" : "Connect"}</button>{!oauthConfig?.configured && <span className="connection-developer-note">Developer setup required once in backend/.env.</span>}</div>}
      </article>;
    })}</div>



    {showCustomForm && <section className="connection-form-card"><div className="settings-card-heading"><div><span className="section-kicker">Custom API</span><h2>Configure endpoint</h2></div><span className="settings-icon">↗</span></div><div className="form-grid connection-form-grid"><label><span>Name</span><input value={draft.label} onChange={(event)=>setDraft({...draft,label:event.target.value})} placeholder="e.g. Company API" /></label><label><span>Base URL</span><input value={draft.baseUrl} onChange={(event)=>setDraft({...draft,baseUrl:event.target.value})} placeholder="https://api.example.com" /></label><label><span>Authentication</span><select value={draft.authMode} onChange={(event)=>setDraft({...draft,authMode:event.target.value as ConnectionAuthMode})}><option value="none">None</option><option value="bearer">Bearer token</option><option value="header">Custom header</option></select></label>{draft.authMode === "header" && <label><span>Header name</span><input value={draft.headerName} onChange={(event)=>setDraft({...draft,headerName:event.target.value})} /></label>}{draft.authMode !== "none" && <label className="full"><span>API secret</span><input type="password" autoComplete="new-password" value={draft.secret} onChange={(event)=>setDraft({...draft,secret:event.target.value})} /></label>}</div><div className="info-box"><strong>Configuration only</strong><span>Custom endpoints are not exposed as arbitrary model HTTP tools yet.</span></div><div className="connection-form-actions"><button type="button" className="primary-button" disabled={saving} onClick={()=>void addCustomConnection()}>{saving?"Saving…":"Save connection"}</button></div></section>}

    <section className="connections-saved-section"><div className="connections-section-heading"><div><span className="section-kicker">Connected</span><h2>Accounts & APIs</h2></div><button type="button" className="secondary-button" onClick={()=>void refresh()}>Refresh</button></div>{connections.length===0?<div className="settings-hub-empty">No accounts or APIs are connected yet.</div>:<div className="connections-saved-list">{connections.map((connection)=><article className="connection-saved-row" key={connection.id}><div className="connection-saved-main"><div><strong>{connection.label}</strong><span>{connection.provider_name} · {connection.account_hint || "local configuration"}</span></div><span className={`connections-status-pill ${connection.status}`}>{connection.status}</span></div><div className="connection-saved-meta"><span>{connection.auth_type === "oauth2" ? "OAuth token stored securely" : connection.auth_type === "none" ? "No authentication" : connection.has_secret ? "Credential stored securely" : "Credential not stored"}</span><span>{connection.last_verified_at ? `Verified ${new Date(connection.last_verified_at).toLocaleString()}` : "Not verified yet"}</span></div>{connection.last_error && <div className="connection-inline-error">{connection.last_error}</div>}<div className="connection-saved-actions">{connection.auth_type === "oauth2" && connection.status !== "disconnected" && <button type="button" className="secondary-button" onClick={()=>void verify(connection)}>Verify</button>}{connection.auth_type === "oauth2" && connection.status === "disconnected" && <button type="button" className="secondary-button" onClick={()=>void connectOAuth(connection.provider_id)}>Reconnect</button>}{connection.status !== "disconnected" && <button type="button" className="secondary-button" onClick={()=>void disconnect(connection)}>Disconnect</button>}<button type="button" className="danger-button" onClick={()=>void remove(connection)}>Delete</button></div></article>)}</div>}</section>
  </div>;
}
