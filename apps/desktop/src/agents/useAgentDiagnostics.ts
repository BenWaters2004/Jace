// JACE_AGENT_DIAGNOSTICS_PHASE_1F
import { useCallback, useEffect, useMemo, useState } from "react";
import {
  getAgentDiagnostics,
  runAgentDiagnostic,
  runAllAgentDiagnostics,
} from "./api";
import type {
  AgentDiagnostic,
  AgentDiagnosticsSnapshot,
} from "./types";

const IDLE_REFRESH_MS = 15_000;
const ACTIVE_REFRESH_MS = 2_500;

export function useAgentDiagnostics() {
  const [snapshot, setSnapshot] = useState<AgentDiagnosticsSnapshot | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState<Set<string>>(new Set());
  const [runningAll, setRunningAll] = useState(false);

  const refresh = useCallback(async () => {
    try {
      const next = await getAgentDiagnostics();
      setSnapshot(next);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not load agent self-tests.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
    const active = (snapshot?.counts.running ?? 0) > 0;
    const timer = window.setTimeout(
      () => void refresh(),
      active ? ACTIVE_REFRESH_MS : IDLE_REFRESH_MS,
    );
    return () => window.clearTimeout(timer);
  }, [refresh, snapshot?.counts.running]);

  const byAgentId = useMemo(() => {
    const map = new Map<string, AgentDiagnostic>();
    for (const item of snapshot?.agents ?? []) map.set(item.agent_id, item);
    return map;
  }, [snapshot]);

  const run = useCallback(async (agentId: string) => {
    setSubmitting((current) => new Set(current).add(agentId));
    try {
      await runAgentDiagnostic(agentId);
      await refresh();
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not run the agent self-test.");
    } finally {
      setSubmitting((current) => {
        const next = new Set(current);
        next.delete(agentId);
        return next;
      });
    }
  }, [refresh]);

  const runAll = useCallback(async () => {
    setRunningAll(true);
    try {
      await runAllAgentDiagnostics();
      await refresh();
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not queue the agent self-tests.");
    } finally {
      setRunningAll(false);
    }
  }, [refresh]);

  return {
    snapshot,
    loading,
    error,
    byAgentId,
    submitting,
    runningAll,
    refresh,
    run,
    runAll,
  };
}
