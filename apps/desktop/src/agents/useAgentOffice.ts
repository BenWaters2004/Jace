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

const TERMINAL_STATUSES = new Set([
  "completed",
  "failed",
]);

const RECENT_TERMINAL_RETENTION_MS = 2 * 60 * 1000;
const POLL_MS = 1000;

export const AGENT_TERMINAL_BROWSER_EVENT =
  "jace:agent-task-terminal";

export interface OfficeWorker {
  id: string;
  definition: AgentDefinition;
  task: AgentTask | null;
  overflowIndex: number;
}

function taskTimestamp(task: AgentTask): number {
  const value =
    task.completed_at ??
    task.updated_at ??
    task.started_at ??
    task.created_at;

  const timestamp = Date.parse(value);
  return Number.isFinite(timestamp) ? timestamp : 0;
}

export function useAgentOffice() {
  const [definitions, setDefinitions] = useState<AgentDefinition[]>([]);
  const [tasks, setTasks] = useState<AgentTask[]>([]);
  const [status, setStatus] = useState<AgentStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [selectedTaskId, setSelectedTaskId] = useState<string | null>(null);

  const mountedRef = useRef(true);
  const requestRunningRef = useRef(false);
  const statusSnapshotRef = useRef<Map<string, string>>(new Map());
  const officePrimedRef = useRef(false);

  const publishTerminalTransitions = useCallback(
    (nextTasks: AgentTask[]) => {
      if (!officePrimedRef.current) {
        statusSnapshotRef.current = new Map(
          nextTasks.map((task) => [task.id, task.status]),
        );
        officePrimedRef.current = true;
        return;
      }

      const nextSnapshot = new Map<string, string>();

      for (const task of nextTasks) {
        const previousStatus = statusSnapshotRef.current.get(task.id);
        nextSnapshot.set(task.id, task.status);

        if (
          TERMINAL_STATUSES.has(task.status) &&
          previousStatus !== task.status
        ) {
          window.dispatchEvent(
            new CustomEvent<AgentTask>(
              AGENT_TERMINAL_BROWSER_EVENT,
              { detail: task },
            ),
          );
        }
      }

      statusSnapshotRef.current = nextSnapshot;
    },
    [],
  );

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

      publishTerminalTransitions(taskResponse.tasks);

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
  }, [publishTerminalTransitions]);

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

  const recentTerminalTasks = useMemo(() => {
    const now = Date.now();

    return tasks.filter((task) => {
      if (!TERMINAL_STATUSES.has(task.status)) return false;

      const timestamp = taskTimestamp(task);
      return (
        timestamp > 0 &&
        now - timestamp <= RECENT_TERMINAL_RETENTION_MS
      );
    });
  }, [tasks]);

  const workers = useMemo<OfficeWorker[]>(() => {
    const output: OfficeWorker[] = [];

    for (const definition of definitions) {
      const matchingActive = activeTasks
        .filter((task) => task.agent_id === definition.id)
        .sort((a, b) => {
          if (a.priority !== b.priority) return b.priority - a.priority;
          return a.created_at.localeCompare(b.created_at);
        });

      const matchingRecent = recentTerminalTasks
        .filter((task) => task.agent_id === definition.id)
        .sort((a, b) => taskTimestamp(b) - taskTimestamp(a));

      const primaryTask =
        matchingActive[0] ??
        matchingRecent[0] ??
        null;

      output.push({
        id: definition.id,
        definition,
        task: primaryTask,
        overflowIndex: 0,
      });

      for (let index = 1; index < matchingActive.length; index += 1) {
        output.push({
          id: `${definition.id}-overflow-${matchingActive[index].id}`,
          definition: {
            ...definition,
            name: `${definition.name} ${index + 1}`,
          },
          task: matchingActive[index],
          overflowIndex: index,
        });
      }
    }

    return output;
  }, [activeTasks, definitions, recentTerminalTasks]);

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
    recentTerminalTasks,
    workers,
    selectedTask,
    selectedTaskId,
    setSelectedTaskId,
    refresh,
    cancel,
    retry,
  };
}
