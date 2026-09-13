import { useEffect, useState } from "react";
import type {
  AssistantSettings,
  ModelInfo,
  ReasoningMode,
  ResponseStyle,
  VoiceSettings,
  VoiceStatus,
} from "../types";

interface SettingsViewProps {
  settings: AssistantSettings;
  voiceSettings: VoiceSettings;
  voiceStatus: VoiceStatus | null;
  models: ModelInfo[];
  hasActiveConversation: boolean;
  onSave: (settings: AssistantSettings) => Promise<void>;
  onSaveVoice: (settings: VoiceSettings) => Promise<void>;
  onReset: () => Promise<void>;
  onResetVoice: () => Promise<void>;
  onTestVoice: () => void;
  onApplyToCurrentConversation: () => Promise<void>;
}

function VoiceReadyPill(props: { ready: boolean; label: string }) {
  return (
    <span className={`voice-ready-pill ${props.ready ? "ready" : "missing"}`}>
      <i />{props.label}
    </span>
  );
}

export function SettingsView(props: SettingsViewProps) {
  const [draft, setDraft] = useState(props.settings);
  const [voiceDraft, setVoiceDraft] = useState(props.voiceSettings);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState<string | null>(null);

  useEffect(() => setDraft(props.settings), [props.settings]);
  useEffect(() => setVoiceDraft(props.voiceSettings), [props.voiceSettings]);

  async function save() {
    setSaving(true);
    setMessage(null);
    try {
      await Promise.all([
        props.onSave(draft),
        props.onSaveVoice(voiceDraft),
      ]);
      setMessage("Settings saved. New conversations will use this profile and voice configuration.");
    } finally {
      setSaving(false);
    }
  }

  async function reset() {
    if (!window.confirm("Reset Jace's assistant and voice settings to defaults?")) return;
    setSaving(true);
    setMessage(null);
    try {
      await Promise.all([props.onReset(), props.onResetVoice()]);
      setMessage("Settings reset to defaults.");
    } finally {
      setSaving(false);
    }
  }

  function chooseVoice(voiceId: string) {
    const voice = props.voiceStatus?.voices.find((item) => item.id === voiceId);
    setVoiceDraft({
      ...voiceDraft,
      tts_voice: voiceId,
      tts_language: voice?.language ?? voiceDraft.tts_language,
    });
  }

  const sttReady = Boolean(props.voiceStatus?.stt_dependency_available);
  const ttsDependencyReady = Boolean(props.voiceStatus?.tts_dependency_available);
  const ttsModelReady = Boolean(props.voiceStatus?.tts_model_files_available);
  const voiceReady = Boolean(props.voiceStatus?.enabled && sttReady && ttsDependencyReady && ttsModelReady);

  return (
    <section className="content-shell page-shell settings-shell">
      <header className="page-header">
        <div>
          <h1>Settings</h1>
          <p>Configure Jace's identity, model, memory and local voice presence.</p>
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

        <section className="settings-card full-card voice-settings-card">
          <div className="settings-card-heading">
            <div><span className="section-kicker">Voice & presence</span><h2>How Jace sounds and listens</h2></div>
            <span className="settings-icon">◉</span>
          </div>

          <div className="voice-runtime-banner">
            <div>
              <strong>{voiceReady ? "Local voice stack ready" : "Local voice setup needs attention"}</strong>
              <span>Push-to-talk keeps the microphone closed unless you are actively holding the voice control. Speech recognition and speech synthesis stay on this machine.</span>
            </div>
            <div className="voice-ready-row">
              <VoiceReadyPill ready={sttReady} label={`STT · ${props.voiceStatus?.stt_model ?? "not installed"}`} />
              <VoiceReadyPill ready={ttsDependencyReady} label="Kokoro runtime" />
              <VoiceReadyPill ready={ttsModelReady} label="Kokoro model files" />
            </div>
          </div>

          <div className="toggle-grid voice-toggle-grid">
            <label className="toggle-card">
              <div><strong>Local voice</strong><span>Enable push-to-talk, local speech recognition and local speech output.</span></div>
              <input type="checkbox" checked={voiceDraft.enabled} onChange={(event) => setVoiceDraft({ ...voiceDraft, enabled: event.target.checked })} />
            </label>
            <label className={`toggle-card ${!voiceDraft.enabled ? "disabled" : ""}`}>
              <div><strong>Speak typed replies</strong><span>Read Jace's normal typed-chat answers aloud as well as voice-initiated turns.</span></div>
              <input type="checkbox" disabled={!voiceDraft.enabled} checked={voiceDraft.auto_speak} onChange={(event) => setVoiceDraft({ ...voiceDraft, auto_speak: event.target.checked })} />
            </label>
            <label className={`toggle-card ${!voiceDraft.enabled ? "disabled" : ""}`}>
              <div><strong>Verbal approvals</strong><span>When a normal tool permission is waiting, allow a spoken “yes”, “no” or “details” response.</span></div>
              <input type="checkbox" disabled={!voiceDraft.enabled} checked={voiceDraft.verbal_approvals} onChange={(event) => setVoiceDraft({ ...voiceDraft, verbal_approvals: event.target.checked })} />
            </label>
          </div>

          <div className="form-grid voice-form-grid">
            <label>
              <span>Voice</span>
              <select value={voiceDraft.tts_voice} onChange={(event) => chooseVoice(event.target.value)} disabled={!voiceDraft.enabled}>
                {(props.voiceStatus?.voices ?? []).map((voice) => <option key={voice.id} value={voice.id}>{voice.label}</option>)}
              </select>
            </label>
            <label>
              <span>Language</span>
              <select value={voiceDraft.tts_language} onChange={(event) => setVoiceDraft({ ...voiceDraft, tts_language: event.target.value })} disabled={!voiceDraft.enabled}>
                <option value="en-gb">English · United Kingdom</option>
                <option value="en-us">English · United States</option>
              </select>
            </label>
            <label className="full">
              <span>Speaking speed · {voiceDraft.tts_speed.toFixed(2)}×</span>
              <input type="range" min="0.80" max="1.30" step="0.01" value={voiceDraft.tts_speed} onChange={(event) => setVoiceDraft({ ...voiceDraft, tts_speed: Number(event.target.value) })} disabled={!voiceDraft.enabled} />
            </label>
          </div>

          <div className="voice-settings-actions">
            <button className="secondary-button" onClick={props.onTestVoice} disabled={!voiceDraft.enabled || !ttsDependencyReady || !ttsModelReady}>Test current voice</button>
            <span>Default: <strong>bm_lewis</strong> — a calm British male voice. Voice affects sound only; Jace's personality remains controlled by the assistant profile.</span>
          </div>

          {!ttsModelReady && (
            <div className="info-box voice-setup-box">
              <strong>First-time local voice setup</strong>
              <span>Run <code>backend\scripts\install_voice_windows.ps1</code>. It installs the local eSpeak phonemizer dependency, Kokoro model files and the existing local Whisper model. Nothing is downloaded automatically while you are talking to Jace.</span>
            </div>
          )}
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
