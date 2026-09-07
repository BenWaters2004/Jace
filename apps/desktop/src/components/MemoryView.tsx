import { useMemo, useState } from "react";
import { MEMORY_TYPES } from "../constants";
import type { MemoryCreateRequest, MemoryRecord, MemoryType } from "../types";
import { Modal } from "./Modal";

interface MemoryViewProps {
  memories: MemoryRecord[];
  enabled: boolean;
  onRefresh: () => void;
  onCreate: (payload: MemoryCreateRequest) => Promise<void>;
  onUpdate: (id: string, payload: Partial<MemoryCreateRequest> & { is_active?: boolean }) => Promise<void>;
  onDelete: (memory: MemoryRecord) => Promise<void>;
  onOpenSource: (conversationId: string) => void;
}

const emptyForm: MemoryCreateRequest = {
  memory_type: "fact",
  subject: "",
  content: "",
  importance: 0.7,
  confidence: 1,
  is_pinned: false,
};

export function MemoryView(props: MemoryViewProps) {
  const [query, setQuery] = useState("");
  const [type, setType] = useState<MemoryType | "all">("all");
  const [status, setStatus] = useState<"active" | "inactive" | "all">("active");
  const [editing, setEditing] = useState<MemoryRecord | null>(null);
  const [creating, setCreating] = useState(false);
  const [form, setForm] = useState<MemoryCreateRequest>(emptyForm);
  const [saving, setSaving] = useState(false);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    return props.memories.filter((memory) => {
      if (type !== "all" && memory.memory_type !== type) return false;
      if (status === "active" && !memory.is_active) return false;
      if (status === "inactive" && memory.is_active) return false;
      if (q && !`${memory.subject} ${memory.content}`.toLowerCase().includes(q)) return false;
      return true;
    });
  }, [props.memories, query, type, status]);

  const activeCount = props.memories.filter((memory) => memory.is_active).length;
  const inferredCount = props.memories.filter((memory) => memory.is_active && memory.source_type === "inferred").length;
  const pinnedCount = props.memories.filter((memory) => memory.is_active && memory.is_pinned).length;

  function openCreate() {
    setForm({ ...emptyForm });
    setCreating(true);
  }

  function openEdit(memory: MemoryRecord) {
    setEditing(memory);
    setForm({
      memory_type: memory.memory_type,
      subject: memory.subject,
      content: memory.content,
      importance: memory.importance,
      confidence: memory.confidence,
      is_pinned: memory.is_pinned,
    });
  }

  async function save() {
    if (!form.subject.trim() || !form.content.trim()) return;
    setSaving(true);
    try {
      if (editing) await props.onUpdate(editing.id, form);
      else await props.onCreate(form);
      setEditing(null);
      setCreating(false);
    } finally {
      setSaving(false);
    }
  }

  const modalOpen = creating || editing !== null;

  return (
    <section className="content-shell page-shell">
      <header className="page-header">
        <div>
          <h1>Memory</h1>
          <p>Inspect and control what Jace carries across conversations.</p>
        </div>
        <div className="header-actions">
          <button className="secondary-button" onClick={props.onRefresh}>Refresh</button>
          <button className="primary-button" onClick={openCreate}>＋ Add memory</button>
        </div>
      </header>

      {!props.enabled && <div className="notice-banner">Long-term memory is currently disabled in Settings. Existing memories remain stored and editable.</div>}

      <div className="stat-grid">
        <div className="stat-card"><strong>{activeCount}</strong><span>Active memories</span></div>
        <div className="stat-card"><strong>{inferredCount}</strong><span>Automatically learned</span></div>
        <div className="stat-card"><strong>{pinnedCount}</strong><span>Pinned</span></div>
        <div className="stat-card"><strong>{props.memories.length - activeCount}</strong><span>Inactive / superseded</span></div>
      </div>

      <div className="memory-toolbar">
        <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search memory..." />
        <select value={type} onChange={(event) => setType(event.target.value as MemoryType | "all")}>
          <option value="all">All types</option>
          {MEMORY_TYPES.map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}
        </select>
        <select value={status} onChange={(event) => setStatus(event.target.value as "active" | "inactive" | "all")}>
          <option value="active">Active</option>
          <option value="inactive">Inactive</option>
          <option value="all">All status</option>
        </select>
      </div>

      <div className="memory-list">
        {filtered.length === 0 ? (
          <div className="large-empty"><div>◇</div><h3>No matching memories</h3><p>Add a memory manually or allow Jace to learn durable information from conversations.</p></div>
        ) : filtered.map((memory) => (
          <article className={`memory-card ${!memory.is_active ? "inactive" : ""}`} key={memory.id}>
            <div className="memory-card-top">
              <div className="memory-tags">
                <span className={`memory-type type-${memory.memory_type}`}>{memory.memory_type}</span>
                <span className={`source-tag ${memory.source_type}`}>{memory.source_type}</span>
                {!memory.is_active && <span className="inactive-tag">inactive</span>}
              </div>
              <button className={`pin-button ${memory.is_pinned ? "active" : ""}`} title="Pin memory" onClick={() => props.onUpdate(memory.id, { is_pinned: !memory.is_pinned })}>◆</button>
            </div>
            <h3>{memory.subject}</h3>
            <p>{memory.content}</p>
            <div className="memory-meter-row">
              <span>Importance <strong>{Math.round(memory.importance * 100)}%</strong></span>
              <span>Confidence <strong>{Math.round(memory.confidence * 100)}%</strong></span>
              <span>Used <strong>{memory.access_count}</strong> times</span>
            </div>
            <div className="memory-card-footer">
              <span>{new Date(memory.updated_at).toLocaleString()}</span>
              <div>
                {memory.source_conversation_id && <button onClick={() => props.onOpenSource(memory.source_conversation_id!)}>Source</button>}
                <button onClick={() => props.onUpdate(memory.id, { is_active: !memory.is_active })}>{memory.is_active ? "Deactivate" : "Restore"}</button>
                <button onClick={() => openEdit(memory)}>Edit</button>
                <button className="danger-link" onClick={() => props.onDelete(memory)}>Delete</button>
              </div>
            </div>
          </article>
        ))}
      </div>

      {modalOpen && (
        <Modal
          title={editing ? "Edit memory" : "Add memory"}
          onClose={() => { setEditing(null); setCreating(false); }}
          footer={<><button className="secondary-button" onClick={() => { setEditing(null); setCreating(false); }}>Cancel</button><button className="primary-button" onClick={() => void save()} disabled={saving || !form.subject.trim() || !form.content.trim()}>{saving ? "Saving..." : "Save memory"}</button></>}
        >
          <div className="form-grid">
            <label><span>Type</span><select value={form.memory_type} onChange={(event) => setForm({ ...form, memory_type: event.target.value as MemoryType })}>{MEMORY_TYPES.map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}</select></label>
            <label><span>Subject</span><input value={form.subject} onChange={(event) => setForm({ ...form, subject: event.target.value })} placeholder="Project Jace" /></label>
            <label className="full"><span>Memory</span><textarea rows={5} value={form.content} onChange={(event) => setForm({ ...form, content: event.target.value })} placeholder="A concise durable fact..." /></label>
            <label><span>Importance · {Math.round(form.importance * 100)}%</span><input type="range" min="0" max="1" step="0.05" value={form.importance} onChange={(event) => setForm({ ...form, importance: Number(event.target.value) })} /></label>
            <label><span>Confidence · {Math.round(form.confidence * 100)}%</span><input type="range" min="0" max="1" step="0.05" value={form.confidence} onChange={(event) => setForm({ ...form, confidence: Number(event.target.value) })} /></label>
            <label className="check-row full"><input type="checkbox" checked={form.is_pinned} onChange={(event) => setForm({ ...form, is_pinned: event.target.checked })} /><span>Pin this memory</span></label>
          </div>
        </Modal>
      )}
    </section>
  );
}
