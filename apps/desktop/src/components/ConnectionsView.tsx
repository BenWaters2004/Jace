// JACE_STEP4A1_CONNECTIONS_FOUNDATION
import { useCallback, useEffect, useMemo, useState } from "react";
import {
  createConnection,
  deleteConnection,
  disconnectConnection,
  getConnections,
  getConnectionProviders,
} from "../api";
import type {
  ConnectionAuthMode,
  ConnectionProvider,
  ConnectionRecord,
} from "../types";

type Draft = {
  label: string;
  baseUrl: string;
  authMode: ConnectionAuthMode;
  headerName: string;
  secret: string;
};

const EMPTY_DRAFT: Draft = {
  label: "",
  baseUrl: "",
  authMode: "bearer",
  headerName: "X-API-Key",
  secret: "",
};

function providerState(provider: ConnectionProvider, count: number): string {
  if (count > 0) return `${count} configured`;
  return provider.setup_state === "available" ? "Available" : "OAuth next";
}

export function ConnectionsView() {
  const [providers, setProviders] = useState<ConnectionProvider[]>([]);
  const [connections, setConnections] = useState<ConnectionRecord[]>([]);
  const [secretStore, setSecretStore] = useState<{ available: boolean; backend: string; reason: string | null } | null>(null);
  const [showCustomForm, setShowCustomForm] = useState(false);
  const [draft, setDraft] = useState<Draft>(EMPTY_DRAFT);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    setError(null);
    try {
      const [providerResponse, connectionResponse] = await Promise.all([
        getConnectionProviders(),
        getConnections(),
      ]);
      setProviders(providerResponse.providers);
      setConnections(connectionResponse.connections);
      setSecretStore(connectionResponse.secret_store);
    } catch (nextError) {
      setError(nextError instanceof Error ? nextError.message : "Could not load connections.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const counts = useMemo(() => {
    const next = new Map<string, number>();
    for (const connection of connections) {
      next.set(connection.provider_id, (next.get(connection.provider_id) ?? 0) + 1);
    }
    return next;
  }, [connections]);

  async function addCustomConnection() {
    if (!draft.label.trim() || !draft.baseUrl.trim()) {
      setError("Name and base URL are required.");
      return;
    }
    if (!secretStore?.available && draft.authMode !== "none") {
      setError(secretStore?.reason || "Secure credential storage is unavailable.");
      return;
    }
    setSaving(true);
    setError(null);
    try {
      await createConnection({
        provider_id: "custom_api",
        label: draft.label.trim(),
        base_url: draft.baseUrl.trim(),
        auth_mode: draft.authMode,
        header_name: draft.authMode === "header" ? draft.headerName.trim() : null,
        secret: draft.authMode === "none" ? null : (draft.secret.trim() || null),
      });
      setDraft(EMPTY_DRAFT);
      setShowCustomForm(false);
      await refresh();
    } catch (nextError) {
      setError(nextError instanceof Error ? nextError.message : "Could not create connection.");
    } finally {
      setSaving(false);
    }
  }

  async function disconnect(connection: ConnectionRecord) {
    if (!window.confirm(`Disconnect ${connection.label}? Its stored credential will be removed.`)) return;
    setError(null);
    try {
      await disconnectConnection(connection.id);
      await refresh();
    } catch (nextError) {
      setError(nextError instanceof Error ? nextError.message : "Could not disconnect connection.");
    }
  }

  async function remove(connection: ConnectionRecord) {
    if (!window.confirm(`Delete ${connection.label}? This removes its Jace metadata and stored credential.`)) return;
    setError(null);
    try {
      await deleteConnection(connection.id);
      await refresh();
    } catch (nextError) {
      setError(nextError instanceof Error ? nextError.message : "Could not delete connection.");
    }
  }

  if (loading) {
    return <div className="connections-loading">Loading connection registry…</div>;
  }

  return (
    <div className="connections-view">
      <div className={`connections-vault-banner ${secretStore?.available ? "ready" : "warning"}`}>
        <div>
          <strong>{secretStore?.available ? "Secure credential vault ready" : "Credential vault unavailable"}</strong>
          <span>
            {secretStore?.available
              ? "API secrets are stored in Windows Credential Manager. SQLite only contains non-secret connection metadata."
              : secretStore?.reason || "Jace will not accept connection secrets until a secure vault is available."}
          </span>
        </div>
        <span className="connections-status-pill">{secretStore?.backend ?? "checking"}</span>
      </div>

      {error && <div className="error-banner connections-error"><div><strong>Connections</strong><span>{error}</span></div></div>}

      <div className="connection-provider-grid">
        {providers.map((provider) => (
          <article className="connection-provider-card" key={provider.id}>
            <div className="connection-provider-head">
              <div>
                <span className="section-kicker">{provider.auth_kind}</span>
                <h3>{provider.name}</h3>
              </div>
              <span className={`connections-status-pill ${provider.setup_state}`}>{providerState(provider, counts.get(provider.id) ?? 0)}</span>
            </div>
            <p>{provider.description}</p>
            <div className="connection-capability-chips">
              {provider.capabilities.slice(0, 6).map((capability) => <span key={capability.id}>{capability.id}</span>)}
            </div>
            {provider.id === "custom_api" ? (
              <button type="button" className="primary-button" onClick={() => setShowCustomForm((value) => !value)}>
                {showCustomForm ? "Cancel" : "Add API connection"}
              </button>
            ) : (
              <button type="button" className="secondary-button" disabled title="OAuth flow is the next 4A step">
                OAuth in 4A.2
              </button>
            )}
          </article>
        ))}
      </div>

      {showCustomForm && (
        <section className="connection-form-card">
          <div className="settings-card-heading">
            <div><span className="section-kicker">Custom API</span><h2>Configure endpoint</h2></div>
            <span className="settings-icon">↗</span>
          </div>
          <div className="form-grid connection-form-grid">
            <label><span>Name</span><input value={draft.label} onChange={(event) => setDraft({ ...draft, label: event.target.value })} placeholder="e.g. Company API" /></label>
            <label><span>Base URL</span><input value={draft.baseUrl} onChange={(event) => setDraft({ ...draft, baseUrl: event.target.value })} placeholder="https://api.example.com" /></label>
            <label>
              <span>Authentication</span>
              <select value={draft.authMode} onChange={(event) => setDraft({ ...draft, authMode: event.target.value as ConnectionAuthMode })}>
                <option value="none">None</option>
                <option value="bearer">Bearer token</option>
                <option value="header">Custom header</option>
              </select>
            </label>
            {draft.authMode === "header" && <label><span>Header name</span><input value={draft.headerName} onChange={(event) => setDraft({ ...draft, headerName: event.target.value })} placeholder="X-API-Key" /></label>}
            {draft.authMode !== "none" && <label className="full"><span>API secret</span><input type="password" autoComplete="new-password" value={draft.secret} onChange={(event) => setDraft({ ...draft, secret: event.target.value })} placeholder="Stored only in Windows Credential Manager" /></label>}
          </div>
          <div className="info-box">
            <strong>Configuration only in 4A.1</strong>
            <span>Saving this connection does not give the model a generic HTTP execution tool. Guarded requests and provider-specific tools are added in later 4A steps.</span>
          </div>
          <div className="connection-form-actions">
            <button type="button" className="primary-button" disabled={saving} onClick={() => void addCustomConnection()}>{saving ? "Saving…" : "Save connection"}</button>
          </div>
        </section>
      )}

      <section className="connections-saved-section">
        <div className="connections-section-heading"><div><span className="section-kicker">Configured</span><h2>Saved connections</h2></div><button type="button" className="secondary-button" onClick={() => void refresh()}>Refresh</button></div>
        {connections.length === 0 ? (
          <div className="settings-hub-empty">No connections have been configured yet.</div>
        ) : (
          <div className="connections-saved-list">
            {connections.map((connection) => (
              <article className="connection-saved-row" key={connection.id}>
                <div className="connection-saved-main">
                  <div><strong>{connection.label}</strong><span>{connection.provider_name} · {connection.account_hint || "local configuration"}</span></div>
                  <span className={`connections-status-pill ${connection.status}`}>{connection.status}</span>
                </div>
                <div className="connection-saved-meta">
                  <span>{connection.auth_type === "none" ? "No authentication" : connection.has_secret ? "Credential stored securely" : "Credential not stored"}</span>
                  <span>{connection.capabilities.join(" · ")}</span>
                </div>
                <div className="connection-saved-actions">
                  {connection.status !== "disconnected" && <button type="button" className="secondary-button" onClick={() => void disconnect(connection)}>Disconnect</button>}
                  <button type="button" className="danger-button" onClick={() => void remove(connection)}>Delete</button>
                </div>
              </article>
            ))}
          </div>
        )}
      </section>
    </div>
  );
}
