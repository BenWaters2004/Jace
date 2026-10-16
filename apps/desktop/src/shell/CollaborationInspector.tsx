/** C4D.2: read-only detail from a persisted, ownership-checked workflow endpoint. */
import { useEffect, useState } from "react";
import { authenticatedFetch } from "../api";
import { API_BASE_URL } from "../constants";
import "./CollaborationInspector.css";

interface SourceObservation {
  kind: "public_web" | "workspace_file";
  tool: string;
  sha256: string;
  digest_scope: "web_excerpt" | "workspace_full_file";
  task_id: string;
}
interface SpecialistObservation {
  task_id: string;
  specialist: string;
  status: string;
  recorded_model: string | null;
  manual_review: boolean;
}
interface Inspection {
  workflow_id: string;
  checkpoint_stage: string | null;
  handoff_status: string | null;
  handoff_recorded: boolean;
  review_status: string;
  source_count_reported_by_review: number | null;
  model_calls_reported_by_review: number | null;
  excerpt_supported_claims: number | null;
  unresolved_claims: number | null;
  external_fact_verification: boolean;
  recorded_synthesis_model: string | null;
  specialists: SpecialistObservation[];
  available_source_observations: SourceObservation[];
  source_observation_limit_reached: boolean;
  provenance_notice: string;
}

const shown = (value: number | null): string => value === null ? "Not recorded" : String(value);

export function CollaborationInspector({ workflowId }: { workflowId: string }) {
  const [data, setData] = useState<Inspection | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  useEffect(() => {
    const controller = new AbortController();
    setData(null);
    setError(null);
    setLoading(true);
    void (async () => {
      try {
        const url = `${API_BASE_URL}/collaboration/workflows/${encodeURIComponent(workflowId)}/inspection`;
        const response = await authenticatedFetch(url, { signal: controller.signal });
        if (!response.ok) {
          throw new Error(response.status === 404
            ? "No accessible persisted inspection is available for this workflow."
            : "The workflow inspection could not be loaded.");
        }
        const body = await response.json() as Inspection;
        if (body.workflow_id !== workflowId || !Array.isArray(body.specialists)) {
          throw new Error("The workflow inspection response is invalid.");
        }
        if (!controller.signal.aborted) setData(body);
      } catch (cause) {
        if (!controller.signal.aborted) setError(cause instanceof Error ? cause.message : "Inspection unavailable");
      } finally {
        if (!controller.signal.aborted) setLoading(false);
      }
    })();
    return () => controller.abort();
  }, [workflowId]);

  return <section className="c4d2-inspector" aria-label="Persisted collaboration inspection">
    <header><strong>Collaboration inspector</strong><small>Read-only · persisted records</small></header>
    {loading && <p role="status">Loading saved workflow evidence…</p>}
    {error && <p className="c4d2-unavailable" role="status">{error}</p>}
    {data && <>
      <div className="c4d2-values">
        <div><span>Checkpoint stage</span><strong>{data.checkpoint_stage ?? "Not recorded"}</strong></div>
        <div><span>Review outcome</span><strong>{data.review_status}</strong></div>
        <div><span>Review model calls</span><strong>{shown(data.model_calls_reported_by_review)}</strong></div>
        <div><span>Sources reported by review</span><strong>{shown(data.source_count_reported_by_review)}</strong></div>
        <div><span>Excerpt-supported claims</span><strong>{shown(data.excerpt_supported_claims)}</strong></div>
        <div><span>Unresolved claims</span><strong>{shown(data.unresolved_claims)}</strong></div>
      </div>
      <p>Handoff: {data.handoff_recorded ? "Saved" : "No saved chat message"}. Synthesis model recorded in checkpoint: {data.recorded_synthesis_model ?? "Not recorded"}.</p>
      <h4>Specialists and recorded models</h4>
      {data.specialists.length === 0 ? <p>No specialist task records available.</p> :
        <div className="c4d2-list">{data.specialists.map(task =>
          <div key={task.task_id}>
            <strong>{task.specialist}</strong><span>{task.status}{task.manual_review ? " · manual review required" : ""}</span>
            <small>{task.recorded_model ? `Recorded task model: ${task.recorded_model}` : "Task model not recorded"}</small>
          </div>)}</div>}
      <h4>Available source-tool receipts</h4>
      {data.available_source_observations.length === 0 ? <p>No successful source-tool receipts were located in the saved task events.</p> :
        <div className="c4d2-list">{data.available_source_observations.map((source, index) =>
          <div key={`${source.task_id}-${source.sha256}-${index}`}>
            <strong>{source.kind === "public_web" ? "Public webpage read" : "Workspace file read"}</strong>
            <span>{source.digest_scope === "web_excerpt" ? "Excerpt SHA-256" : "Full-file SHA-256"}: <code title={source.sha256}>{source.sha256.slice(0, 16)}…</code></span>
          </div>)}</div>}
      {data.source_observation_limit_reached && <p>More source records may exist beyond the inspection limit.</p>}
      <p className="c4d2-disclaimer">{data.provenance_notice}</p>
    </>}
  </section>;
}
