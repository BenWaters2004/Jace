import { useEffect, useState } from "react";
import type { AssistantSettings, ModelInfo, ReasoningMode, ResponseStyle } from "../types";

interface SettingsViewProps {
  settings: AssistantSettings;
  models: ModelInfo[];
  hasActiveConversation: boolean;
  onSave: (settings: AssistantSettings) => Promise<void>;
  onReset: () => Promise<void>;
  onApplyToCurrentConversation: () => Promise<void>;
}

export function SettingsView(props: SettingsViewProps) {
  const [draft, setDraft] = useState(props.settings);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState<string | null>(null);

  useEffect(() => setDraft(props.settings), [props.settings]);

  async function save() {
    setSaving(true);
    setMessage(null);
    try {
      await props.onSave(draft);
      setMessage("Settings saved. New conversations will use this profile.");
    } finally {
      setSaving(false);
    }
  }

  async function reset() {
    if (!window.confirm("Reset Jace's Phase 3 assistant settings to defaults?")) return;
    setSaving(true);
    setMessage(null);
    try {
      await props.onReset();
      setMessage("Settings reset to defaults.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <section className="content-shell page-shell settings-shell">
      <header className="page-header">
        <div>
          <h1>Settings</h1>
          <p>Configure Jace's identity, response behaviour, model and memory policy.</p>
        </div>
        <div className="header-actions">
          <button className="secondary-button" onClick={() => void reset()} disabled={saving}>Reset</button>
          <button className="primary-button" onClick={() => void save()} disabled={saving}>{saving ? "Saving..." : "Save settings"}</button>
        </div>
      </header>

      {message && <div className="success-banner">{message}</div>}

      <div className="settings-grid">
        <section className="settings-card">
          <div className="settings-card-heading">
            <div><span className="section-kicker">Identity</span><h2>Who Jace is</h2></div>
            <span className="settings-icon">J</span>
          </div>
          <div className="form-grid">
            <label><span>Assistant name</span><input value={draft.assistant_name} onChange={(event) => setDraft({ ...draft, assistant_name: event.target.value })} /></label>
            <label><span>Your display name</span><input value={draft.user_name} onChange={(event) => setDraft({ ...draft, user_name: event.target.value })} /></label>
            <label className="full"><span>Core system prompt</span><textarea rows={12} value={draft.system_prompt} onChange={(event) => setDraft({ ...draft, system_prompt: event.target.value })} /></label>
          </div>
          <p className="field-help">Each conversation stores its own copy of the system prompt. Changing this profile affects new conversations unless you apply it to the current one.</p>
          {props.hasActiveConversation && <button className="secondary-button" onClick={() => void props.onApplyToCurrentConversation()}>Apply saved identity/model to current chat</button>}
        </section>

        <section className="settings-card">
          <div className="settings-card-heading">
            <div><span className="section-kicker">Model</span><h2>Response behaviour</h2></div>
            <span className="settings-icon">◎</span>
          </div>
          <div className="form-grid">
            <label className="full"><span>Default model</span><select value={draft.default_model} onChange={(event) => setDraft({ ...draft, default_model: event.target.value })}>{props.models.map((model) => <option key={model.name} value={model.name}>{model.name}{model.parameter_size ? ` · ${model.parameter_size}` : ""}</option>)}</select></label>
            <label><span>Reasoning mode</span><select value={draft.reasoning_mode} onChange={(event) => setDraft({ ...draft, reasoning_mode: event.target.value as ReasoningMode })}><option value="fast">Fast</option><option value="balanced">Balanced</option><option value="deep">Deep</option></select></label>
            <label><span>Response style</span><select value={draft.response_style} onChange={(event) => setDraft({ ...draft, response_style: event.target.value as ResponseStyle })}><option value="concise">Concise</option><option value="balanced">Balanced</option><option value="detailed">Detailed</option></select></label>
            <label className="full"><span>Temperature · {draft.temperature.toFixed(2)}</span><input type="range" min="0" max="1.5" step="0.05" value={draft.temperature} onChange={(event) => setDraft({ ...draft, temperature: Number(event.target.value) })} /></label>
          </div>
          <div className="info-box"><strong>Reasoning modes</strong><span>Fast limits generation and disables thinking. Balanced allows longer normal responses. Deep enables the model's thinking mode and a larger output budget, so it can be much slower on your RTX 2060.</span></div>
        </section>

        <section className="settings-card full-card">
          <div className="settings-card-heading">
            <div><span className="section-kicker">Memory</span><h2>Long-term memory policy</h2></div>
            <span className="settings-icon">◇</span>
          </div>
          <div className="toggle-grid">
            <label className="toggle-card">
              <div><strong>Long-term memory</strong><span>Allow Jace to retrieve stored memories and process explicit remember/forget instructions.</span></div>
              <input type="checkbox" checked={draft.memory_enabled} onChange={(event) => setDraft({ ...draft, memory_enabled: event.target.checked })} />
            </label>
            <label className={`toggle-card ${!draft.memory_enabled ? "disabled" : ""}`}>
              <div><strong>Automatic learning</strong><span>After successful conversations, identify durable user information and reconcile it into memory.</span></div>
              <input type="checkbox" disabled={!draft.memory_enabled} checked={draft.memory_auto_extract} onChange={(event) => setDraft({ ...draft, memory_auto_extract: event.target.checked })} />
            </label>
          </div>
          <div className="form-grid memory-policy-grid">
            <label><span>Memories per request · {draft.memory_top_k}</span><input type="range" min="1" max="12" step="1" value={draft.memory_top_k} onChange={(event) => setDraft({ ...draft, memory_top_k: Number(event.target.value) })} /></label>
            <label><span>Minimum similarity · {draft.memory_min_similarity.toFixed(2)}</span><input type="range" min="0.30" max="0.85" step="0.01" value={draft.memory_min_similarity} onChange={(event) => setDraft({ ...draft, memory_min_similarity: Number(event.target.value) })} /></label>
          </div>
          <div className="info-box"><strong>Recommended</strong><span>Keep similarity around 0.50 on the current embedding model. Lower values recall more loosely related memories and can cause unrelated project context to appear.</span></div>
        </section>
      </div>
    </section>
  );
}
