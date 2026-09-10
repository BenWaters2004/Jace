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
  getAgentTask,
  getAgentTasks,
  retryAgentTask,
} from "./api";
import type {
  AgentDefinition,
  AgentStatus,
  AgentTask,
} from "./types";
import {
  runtimeTransportConnected,
  subscribeRuntimeEvents,
  type RuntimeEvent,
} from "../shell/runtime";

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

export const AGENT_TERMINAL_BROWSER_EVENT =
  "jace:agent-task-terminal";

export interface OfficeWorker {
  id: string;
  definition: AgentDefinition;
  task: AgentTask | null;
  overflowIndex: number;
}

export interface AgentOfficeNotice {
  task: AgentTask;
  kind: "completed" | "failed";
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

function sortNewestFirst(tasks: AgentTask[]): AgentTask[] {
  return [...tasks].sort(
    (a, b) => taskTimestamp(b) - taskTimestamp(a),
  );
}

function isAgentTaskEvent(event: RuntimeEvent): boolean {
  return (
    event.type === "agent.task.queued" ||
    event.type === "agent.task.changed" ||
    event.type === "agent.task.completed" ||
    event.type === "agent.task.failed"
  );
}

export function useAgentOffice() {
  const [definitions, setDefinitions] =
    useState<AgentDefinition[]>([]);
  const [tasks, setTasks] =
    useState<AgentTask[]>([]);
  const [status, setStatus] =
    useState<AgentStatus | null>(null);
  const [error, setError] =
    useState<string | null>(null);
  const [selectedTaskId, setSelectedTaskId] =
    useState<string | null>(null);
  const [realtimeConnected, setRealtimeConnected] =
    useState(runtimeTransportConnected());
  const [notice, setNotice] =
    useState<AgentOfficeNotice | null>(null);
  const [clock, setClock] =
    useState<number>(() => Date.now());

  const mountedRef = useRef(true);
  const hydrateRunningRef = useRef(false);
  const hydrateAgainRef = useRef(false);
  const statusSnapshotRef =
    useRef<Map<string, string>>(new Map());
  const primedRef = useRef(false);
  const latestSequenceRef = useRef<number | null>(null);
  const taskRequestSequenceRef =
    useRef<Map<string, number>>(new Map());
  const noticeTimerRef = useRef<number | null>(null);

  const publishTerminalTransition = useCallback(
    (task: AgentTask, previousStatus?: string) => {
      if (
        !TERMINAL_STATUSES.has(task.status) ||
        previousStatus === task.status
      ) {
        return;
      }

      window.dispatchEvent(
        new CustomEvent<AgentTask>(
          AGENT_TERMINAL_BROWSER_EVENT,
          { detail: task },
        ),
      );

      setNotice({
        task,
        kind:
          task.status === "failed"
            ? "failed"
            : "completed",
      });

      if (noticeTimerRef.current !== null) {
        window.clearTimeout(noticeTimerRef.current);
      }

      noticeTimerRef.current = window.setTimeout(() => {
        setNotice(null);
        noticeTimerRef.current = null;
      }, 6500);
    },
    [],
  );

  const replaceSnapshot = useCallback(
    (nextTasks: AgentTask[]) => {
      const ordered = sortNewestFirst(nextTasks);

      if (!primedRef.current) {
        statusSnapshotRef.current = new Map(
          ordered.map((task) => [task.id, task.status]),
        );
        primedRef.current = true;
        setTasks(ordered);
        return;
      }

      const previous = statusSnapshotRef.current;
      const nextStatuses = new Map<string, string>();

      for (const task of ordered) {
        const previousStatus = previous.get(task.id);
        nextStatuses.set(task.id, task.status);
        publishTerminalTransition(task, previousStatus);
      }

      statusSnapshotRef.current = nextStatuses;
      setTasks(ordered);
    },
    [publishTerminalTransition],
  );

  const hydrate = useCallback(async () => {
    if (hydrateRunningRef.current) {
      hydrateAgainRef.current = true;
      return;
    }

    hydrateRunningRef.current = true;

    try {
      const [
        definitionResponse,
        taskResponse,
        statusResponse,
      ] = await Promise.all([
        getAgentDefinitions(),
        getAgentTasks(100),
        getAgentStatus(),
      ]);

      if (!mountedRef.current) return;

      setDefinitions(definitionResponse.agents);
      replaceSnapshot(taskResponse.tasks);
      setStatus(statusResponse);
      setError(null);
    } catch (nextError) {
      if (!mountedRef.current) return;

      setError(
        nextError instanceof Error
          ? nextError.message
          : "Could not synchronise the Jace agent office.",
      );
    } finally {
      hydrateRunningRef.current = false;

      if (hydrateAgainRef.current) {
        hydrateAgainRef.current = false;
        void hydrate();
      }
    }
  }, [replaceSnapshot]);

  const refreshTask = useCallback(
    async (
      taskId: string,
      eventSequence: number,
    ) => {
      const previousRequested =
        taskRequestSequenceRef.current.get(taskId) ?? -1;

      if (eventSequence < previousRequested) {
        return;
      }

      taskRequestSequenceRef.current.set(
        taskId,
        eventSequence,
      );

      try {
        const task = await getAgentTask(taskId);

        if (!mountedRef.current) return;

        const latestRequested =
          taskRequestSequenceRef.current.get(taskId) ?? eventSequence;

        if (eventSequence < latestRequested) {
          return;
        }

        setTasks((current) => {
          const previousTask =
            current.find((item) => item.id === task.id) ?? null;
          const previousStatus =
            previousTask?.status ??
            statusSnapshotRef.current.get(task.id);

          statusSnapshotRef.current.set(
            task.id,
            task.status,
          );

          publishTerminalTransition(
            task,
            previousStatus,
          );

          return sortNewestFirst([
            task,
            ...current.filter(
              (item) => item.id !== task.id,
            ),
          ]);
        });

        setError(null);
      } catch (nextError) {
        if (!mountedRef.current) return;

        setError(
          nextError instanceof Error
            ? nextError.message
            : "Could not refresh an agent task.",
        );
      }
    },
    [publishTerminalTransition],
  );

  useEffect(() => {
    mountedRef.current = true;
    void hydrate();

    const unsubscribe = subscribeRuntimeEvents(
      (event) => {
        if (event.type === "runtime.transport.connected") {
          setRealtimeConnected(true);
          return;
        }

        if (event.type === "runtime.transport.disconnected") {
          setRealtimeConnected(false);
          return;
        }

        if (event.type === "runtime.snapshot") {
          setRealtimeConnected(true);
          latestSequenceRef.current =
            typeof event.sequence === "number"
              ? event.sequence
              : null;
          void hydrate();
          return;
        }

        if (typeof event.sequence === "number") {
          const previous = latestSequenceRef.current;

          if (
            previous !== null &&
            event.sequence > previous + 1
          ) {
            void hydrate();
          }

          latestSequenceRef.current = event.sequence;
        }

        if (
          isAgentTaskEvent(event) &&
          typeof event.task_id === "string"
        ) {
          void refreshTask(
            event.task_id,
            event.sequence ?? Date.now(),
          );
        }
      },
    );

    return () => {
      mountedRef.current = false;
      unsubscribe();

      if (noticeTimerRef.current !== null) {
        window.clearTimeout(noticeTimerRef.current);
      }
    };
  }, [hydrate, refreshTask]);

  useEffect(() => {
    const timer = window.setInterval(
      () => setClock(Date.now()),
      10_000,
    );

    return () => window.clearInterval(timer);
  }, []);

  const activeTasks = useMemo(
    () =>
      tasks.filter((task) =>
        ACTIVE_STATUSES.has(task.status),
      ),
    [tasks],
  );

  const recentTerminalTasks = useMemo(
    () =>
      tasks.filter((task) => {
        if (!TERMINAL_STATUSES.has(task.status)) {
          return false;
        }

        const timestamp = taskTimestamp(task);

        return (
          timestamp > 0 &&
          clock - timestamp <= RECENT_TERMINAL_RETENTION_MS
        );
      }),
    [clock, tasks],
  );

  const workers = useMemo<OfficeWorker[]>(() => {
    const output: OfficeWorker[] = [];

    for (const definition of definitions) {
      const matchingActive = activeTasks
        .filter((task) => task.agent_id === definition.id)
        .sort((a, b) => {
          if (a.priority !== b.priority) {
            return b.priority - a.priority;
          }

          return a.created_at.localeCompare(b.created_at);
        });

      const matchingRecent = recentTerminalTasks
        .filter((task) => task.agent_id === definition.id)
        .sort((a, b) => taskTimestamp(b) - taskTimestamp(a));

      output.push({
        id: definition.id,
        definition,
        task:
          matchingActive[0] ??
          matchingRecent[0] ??
          null,
        overflowIndex: 0,
      });

      for (
        let index = 1;
        index < matchingActive.length;
        index += 1
      ) {
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
  }, [
    activeTasks,
    definitions,
    recentTerminalTasks,
  ]);

  const selectedTask = useMemo(
    () =>
      selectedTaskId
        ? tasks.find((task) => task.id === selectedTaskId) ?? null
        : null,
    [selectedTaskId, tasks],
  );

  const derivedStatus = useMemo<AgentStatus | null>(() => {
    if (!status) return null;

    return {
      ...status,
      active_tasks: activeTasks.filter(
        (task) => task.status !== "queued",
      ).length,
      queued_tasks: activeTasks.filter(
        (task) => task.status === "queued",
      ).length,
    };
  }, [activeTasks, status]);

  const cancel = useCallback(
    async (taskId: string) => {
      try {
        const task = await cancelAgentTask(taskId);

        setTasks((current) =>
          sortNewestFirst([
            task,
            ...current.filter((item) => item.id !== task.id),
          ]),
        );

        setError(null);
      } catch (nextError) {
        setError(
          nextError instanceof Error
            ? nextError.message
            : "Could not cancel the task.",
        );
      }
    },
    [],
  );

  const retry = useCallback(
    async (taskId: string) => {
      try {
        const task = await retryAgentTask(taskId);

        setTasks((current) =>
          sortNewestFirst([
            task,
            ...current.filter((item) => item.id !== task.id),
          ]),
        );

        statusSnapshotRef.current.set(
          task.id,
          task.status,
        );

        setError(null);
      } catch (nextError) {
        setError(
          nextError instanceof Error
            ? nextError.message
            : "Could not retry the task.",
        );
      }
    },
    [],
  );

  return {
    definitions,
    tasks,
    status: derivedStatus,
    error,
    realtimeConnected,
    notice,
    activeTasks,
    recentTerminalTasks,
    workers,
    selectedTask,
    selectedTaskId,
    setSelectedTaskId,
    refresh: hydrate,
    cancel,
    retry,
  };
}
