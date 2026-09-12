// JACE_AGENT_READINESS_PHASE_1E
import { useCallback, useEffect, useMemo, useState } from "react";
import { getAgentReadiness } from "./api";
import type {
  AgentReadiness,
  AgentReadinessSnapshot,
} from "./types";

const READINESS_REFRESH_MS = 15_000;

export function useAgentReadiness() {
  const [snapshot, setSnapshot] = useState<AgentReadinessSnapshot | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      const next = await getAgentReadiness();
      setSnapshot(next);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not check agent readiness.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
    const timer = window.setInterval(() => void refresh(), READINESS_REFRESH_MS);
    return () => window.clearInterval(timer);
  }, [refresh]);

  const byAgentId = useMemo(() => {
    const map = new Map<string, AgentReadiness>();
    for (const item of snapshot?.agents ?? []) {
      map.set(item.agent_id, item);
    }
    return map;
  }, [snapshot]);

  const counts = useMemo(() => {
    const value = { ready: 0, degraded: 0, unavailable: 0 };
    for (const item of snapshot?.agents ?? []) value[item.status] += 1;
    return value;
  }, [snapshot]);

  return {
    snapshot,
    loading,
    error,
    byAgentId,
    counts,
    refresh,
  };
}
