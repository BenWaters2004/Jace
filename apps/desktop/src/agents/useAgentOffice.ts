import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import {
  cancelAgentTask,
  createAgentTask,
  getAgentDefinitions,
  getAgentStatus,
  getAgentTask,
  getAgentTaskEvents,
  getAgentTasks,
  retryAgentTask,
} from "./api";
import {
  ACTIVE_AGENT_TASK_STATUSES,
  TERMINAL_AGENT_TASK_STATUSES,
  isAgentTaskActive,
  taskTimestamp,
} from "./activity";
import type {
  AgentDefinition,
  AgentStatus,
  AgentTask,
  AgentTaskCreateRequest,
  AgentTaskEvent,
} from "./types";
import {
  runtimeTransportConnected,
  subscribeRuntimeEvents,
  type RuntimeEvent,
} from "../shell/runtime";

const RECENT_TERMINAL_RETENTION_MS = 2 * 60 * 1000;

export const AGENT_TERMINAL_BROWSER_EVENT =
  "jace:agent-task-terminal";

export interface OfficeWorker {
  id: string;
  definition: AgentDefinition;
  task: AgentTask | null;
  overflowIndex: number;
  latestEvent: AgentTaskEvent | null;
}

export interface AgentOfficeNotice {
  task: AgentTask;
  kind: "completed" | "failed";
}

export type AgentAssignmentRequest = Omit<
  AgentTaskCreateRequest,
  "agent_id"
>;

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
  const [tasks, setTasks] = useState<AgentTask[]>([]);
  const [status, setStatus] = useState<AgentStatus | null>(null);
  const [error, setError] = useState<string | null>(null);

  const [selectedAgentId, setSelectedAgentId] =
    useState<string | null>(null);
  const [selectedWorkerId, setSelectedWorkerId] =
    useState<string | null>(null);
  const [selectedTaskId, setSelectedTaskId] =
    useState<string | null>(null);
  const [selectedTaskEvents, setSelectedTaskEvents] =
    useState<AgentTaskEvent[]>([]);
  const [selectedTaskEventsLoading, setSelectedTaskEventsLoading] =
    useState(false);
  const [selectedTaskEventsError, setSelectedTaskEventsError] =
    useState<string | null>(null);
  const [latestTaskEventsById, setLatestTaskEventsById] =
    useState<Record<string, AgentTaskEvent>>({});

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

  const refreshLatestTaskEvent = useCallback(async (taskId: string) => {
    try {
      const response = await getAgentTaskEvents(taskId, 24);
      if (!mountedRef.current) return;

      const latestEvent = [...response.events]
        .sort(
          (a, b) =>
            new Date(b.created_at).getTime() -
            new Date(a.created_at).getTime(),
        )
        .find((event) => event.event_type === "tool_started") ?? null;

      if (latestEvent) {
        setLatestTaskEventsById((current) => ({
          ...current,
          [taskId]: latestEvent,
        }));
      }
    } catch {
      // Bubble detail is optional. Task/event inspection still works normally.
    }
  }, []);

  const publishTerminalTransition = useCallback(
    (task: AgentTask, previousStatus?: string) => {
      if (
        !TERMINAL_AGENT_TASK_STATUSES.has(task.status) ||
        previousStatus === task.status
      ) {
        return;
      }

      const directorManaged =
        task.metadata?.director_managed === true ||
        task.metadata?.suppress_chat_handoff === true;

      // Director child tasks still animate and remain inspectable in Pixel
      // Office, but only the Director's combined result should appear in chat.
      if (directorManaged) {
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
        kind: task.status === "failed" ? "failed" : "completed",
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
      const [definitionResponse, taskResponse, statusResponse] =
        await Promise.all([
          getAgentDefinitions(),
          getAgentTasks(100),
          getAgentStatus(),
        ]);

      if (!mountedRef.current) return;

      setDefinitions(definitionResponse.agents);
      replaceSnapshot(taskResponse.tasks);
      setStatus(statusResponse);
      setError(null);

      for (const task of taskResponse.tasks) {
        if (task.status === "using_tool") {
          void refreshLatestTaskEvent(task.id);
        }
      }
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
  }, [refreshLatestTaskEvent, replaceSnapshot]);

  const refreshTask = useCallback(
    async (taskId: string, eventSequence: number) => {
      const previousRequested =
        taskRequestSequenceRef.current.get(taskId) ?? -1;

      if (eventSequence < previousRequested) return;

      taskRequestSequenceRef.current.set(taskId, eventSequence);

      try {
        const task = await getAgentTask(taskId);
        if (!mountedRef.current) return;

        const latestRequested =
          taskRequestSequenceRef.current.get(taskId) ?? eventSequence;
        if (eventSequence < latestRequested) return;

        setTasks((current) => {
          const previousTask =
            current.find((item) => item.id === task.id) ?? null;
          const previousStatus =
            previousTask?.status ??
            statusSnapshotRef.current.get(task.id);

          statusSnapshotRef.current.set(task.id, task.status);
          publishTerminalTransition(task, previousStatus);

          return sortNewestFirst([
            task,
            ...current.filter((item) => item.id !== task.id),
          ]);
        });

        if (task.status === "using_tool") {
          void refreshLatestTaskEvent(task.id);
        }

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
    [publishTerminalTransition, refreshLatestTaskEvent],
  );

  useEffect(() => {
    mountedRef.current = true;
    void hydrate();

    const unsubscribe = subscribeRuntimeEvents((event) => {
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
          typeof event.sequence === "number" ? event.sequence : null;
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
    });

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
        ACTIVE_AGENT_TASK_STATUSES.has(task.status),
      ),
    [tasks],
  );

  const recentTerminalTasks = useMemo(
    () =>
      tasks.filter((task) => {
        if (!TERMINAL_AGENT_TASK_STATUSES.has(task.status)) {
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
        latestEvent:
          latestTaskEventsById[
            (matchingActive[0] ?? matchingRecent[0])?.id ?? ""
          ] ?? null,
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
          latestEvent:
            latestTaskEventsById[matchingActive[index].id] ?? null,
        });
      }
    }

    return output;
  }, [activeTasks, definitions, latestTaskEventsById, recentTerminalTasks]);

  const selectedWorker = useMemo(
    () =>
      selectedWorkerId
        ? workers.find((worker) => worker.id === selectedWorkerId) ?? null
        : null,
    [selectedWorkerId, workers],
  );

  const selectedAgentDefinition = useMemo(
    () =>
      selectedAgentId
        ? definitions.find(
            (definition) => definition.id === selectedAgentId,
          ) ?? null
        : null,
    [definitions, selectedAgentId],
  );

  const selectedAgentTasks = useMemo(
    () =>
      selectedAgentId
        ? sortNewestFirst(
            tasks.filter((task) => task.agent_id === selectedAgentId),
          )
        : [],
    [selectedAgentId, tasks],
  );

  const selectedTask = useMemo(
    () =>
      selectedTaskId
        ? tasks.find((task) => task.id === selectedTaskId) ?? null
        : null,
    [selectedTaskId, tasks],
  );

  const selectedCurrentTask = useMemo(() => {
    if (selectedWorker?.task && isAgentTaskActive(selectedWorker.task)) {
      return selectedWorker.task;
    }

    if (!selectedAgentId) return null;

    return (
      activeTasks.find((task) => task.agent_id === selectedAgentId) ?? null
    );
  }, [activeTasks, selectedAgentId, selectedWorker]);

  useEffect(() => {
    if (!selectedWorkerId || selectedWorker) return;

    const fallbackWorker = selectedAgentId
      ? workers.find(
          (worker) =>
            worker.definition.id === selectedAgentId &&
            worker.overflowIndex === 0,
        ) ?? null
      : null;

    setSelectedWorkerId(fallbackWorker?.id ?? null);
  }, [selectedAgentId, selectedWorker, selectedWorkerId, workers]);

  const selectWorker = useCallback(
    (workerId: string | null) => {
      if (!workerId) {
        setSelectedWorkerId(null);
        setSelectedAgentId(null);
        setSelectedTaskId(null);
        return;
      }

      const worker = workers.find((candidate) => candidate.id === workerId);
      if (!worker) return;

      setSelectedWorkerId(worker.id);
      setSelectedAgentId(worker.definition.id);
      setSelectedTaskId(worker.task?.id ?? null);
    },
    [workers],
  );

  useEffect(() => {
    if (!selectedTaskId) {
      setSelectedTaskEvents([]);
      setSelectedTaskEventsLoading(false);
      setSelectedTaskEventsError(null);
      return;
    }

    let cancelled = false;
    setSelectedTaskEventsLoading(true);
    setSelectedTaskEventsError(null);

    void getAgentTaskEvents(selectedTaskId, 200)
      .then((response) => {
        if (cancelled || !mountedRef.current) return;
        setSelectedTaskEvents(response.events);
      })
      .catch((nextError) => {
        if (cancelled || !mountedRef.current) return;
        setSelectedTaskEvents([]);
        setSelectedTaskEventsError(
          nextError instanceof Error
            ? nextError.message
            : "Could not load the task activity history.",
        );
      })
      .finally(() => {
        if (cancelled || !mountedRef.current) return;
        setSelectedTaskEventsLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [selectedTask?.updated_at, selectedTaskId]);

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

  const assign = useCallback(
    async (
      agentId: string,
      request: AgentAssignmentRequest,
    ): Promise<AgentTask> => {
      try {
        const task = await createAgentTask({
          agent_id: agentId,
          ...request,
        });

        statusSnapshotRef.current.set(task.id, task.status);
        setTasks((current) =>
          sortNewestFirst([
            task,
            ...current.filter((item) => item.id !== task.id),
          ]),
        );

        setSelectedAgentId(agentId);
        setSelectedWorkerId(agentId);
        setSelectedTaskId(task.id);
        setError(null);

        return task;
      } catch (nextError) {
        const message =
          nextError instanceof Error
            ? nextError.message
            : "Could not assign work to the agent.";
        setError(message);
        throw nextError instanceof Error
          ? nextError
          : new Error(message);
      }
    },
    [],
  );

  const cancel = useCallback(async (taskId: string) => {
    try {
      const task = await cancelAgentTask(taskId);
      statusSnapshotRef.current.set(task.id, task.status);

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
  }, []);

  const retry = useCallback(async (taskId: string) => {
    try {
      const task = await retryAgentTask(taskId);

      setTasks((current) =>
        sortNewestFirst([
          task,
          ...current.filter((item) => item.id !== task.id),
        ]),
      );

      statusSnapshotRef.current.set(task.id, task.status);
      setSelectedTaskId(task.id);
      setError(null);
    } catch (nextError) {
      setError(
        nextError instanceof Error
          ? nextError.message
          : "Could not retry the task.",
      );
    }
  }, []);

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

    selectedAgentId,
    selectedAgentDefinition,
    selectedAgentTasks,
    selectedWorker,
    selectedWorkerId,
    selectedCurrentTask,
    selectedTask,
    selectedTaskId,
    selectedTaskEvents,
    selectedTaskEventsLoading,
    selectedTaskEventsError,

    selectWorker,
    setSelectedTaskId,
    refresh: hydrate,
    assign,
    cancel,
    retry,
  };
}
