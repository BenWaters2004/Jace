import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import {
  cancelAgentTask,
  getAgentDefinitions,
  getAgentStatus,
  getAgentTasks,
  retryAgentTask,
} from "./api";
import type {
  AgentDefinition,
  AgentStatus,
  AgentTask,
} from "./types";

const ACTIVE_STATUSES = new Set([
  "queued",
  "running",
  "thinking",
  "using_tool",
  "waiting_permission",
]);

const POLL_MS = 1000;

export interface OfficeWorker {
  id: string;
  definition: AgentDefinition;
  task: AgentTask | null;
  overflowIndex: number;
}

export function useAgentOffice() {
  const [definitions, setDefinitions] = useState<AgentDefinition[]>([]);
  const [tasks, setTasks] = useState<AgentTask[]>([]);
  const [status, setStatus] = useState<AgentStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [selectedTaskId, setSelectedTaskId] = useState<string | null>(null);
  const mountedRef = useRef(true);
  const requestRunningRef = useRef(false);

  const refresh = useCallback(async () => {
    if (requestRunningRef.current) return;

    requestRunningRef.current = true;

    try {
      const [definitionResponse, taskResponse, statusResponse] =
        await Promise.all([
          getAgentDefinitions(),
          getAgentTasks(100),
          getAgentStatus(),
        ]);

      if (!mountedRef.current) return;

      setDefinitions(definitionResponse.agents);
      setTasks(taskResponse.tasks);
      setStatus(statusResponse);
      setError(null);
    } catch (nextError) {
      if (!mountedRef.current) return;

      setError(
        nextError instanceof Error
          ? nextError.message
          : "Could not read the Jace agent office.",
      );
    } finally {
      requestRunningRef.current = false;
    }
  }, []);

  useEffect(() => {
    mountedRef.current = true;
    void refresh();

    const timer = window.setInterval(() => {
      void refresh();
    }, POLL_MS);

    return () => {
      mountedRef.current = false;
      window.clearInterval(timer);
    };
  }, [refresh]);

  const activeTasks = useMemo(
    () => tasks.filter((task) => ACTIVE_STATUSES.has(task.status)),
    [tasks],
  );

  const workers = useMemo<OfficeWorker[]>(() => {
    const output: OfficeWorker[] = [];

    for (const definition of definitions) {
      const matching = activeTasks
        .filter((task) => task.agent_id === definition.id)
        .sort((a, b) => {
          if (a.priority !== b.priority) return b.priority - a.priority;
          return a.created_at.localeCompare(b.created_at);
        });

      output.push({
        id: definition.id,
        definition,
        task: matching[0] ?? null,
        overflowIndex: 0,
      });

      for (let index = 1; index < matching.length; index += 1) {
        output.push({
          id: `${definition.id}-overflow-${matching[index].id}`,
          definition: {
            ...definition,
            name: `${definition.name} ${index + 1}`,
          },
          task: matching[index],
          overflowIndex: index,
        });
      }
    }

    return output;
  }, [activeTasks, definitions]);

  const selectedTask = useMemo(
    () =>
      selectedTaskId
        ? tasks.find((task) => task.id === selectedTaskId) ?? null
        : null,
    [selectedTaskId, tasks],
  );

  const cancel = useCallback(
    async (taskId: string) => {
      try {
        await cancelAgentTask(taskId);
        await refresh();
      } catch (nextError) {
        setError(
          nextError instanceof Error
            ? nextError.message
            : "Could not cancel the task.",
        );
      }
    },
    [refresh],
  );

  const retry = useCallback(
    async (taskId: string) => {
      try {
        await retryAgentTask(taskId);
        await refresh();
      } catch (nextError) {
        setError(
          nextError instanceof Error
            ? nextError.message
            : "Could not retry the task.",
        );
      }
    },
    [refresh],
  );

  return {
    definitions,
    tasks,
    status,
    error,
    activeTasks,
    workers,
    selectedTask,
    selectedTaskId,
    setSelectedTaskId,
    refresh,
    cancel,
    retry,
  };
}
