import { API_BASE_URL } from "../constants";
import type {
  AgentDefinitionListResponse,
  AgentStatus,
  AgentTask,
  AgentTaskCreateRequest,
  AgentTaskEventsResponse,
  AgentTaskListResponse,
} from "./types";

async function agentRequest<T>(
  path: string,
  options?: RequestInit,
): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...(options?.headers ?? {}),
    },
  });

  if (!response.ok) {
    let detail = `${response.status} ${response.statusText}`;

    try {
      const body = (await response.json()) as {
        detail?: unknown;
        message?: unknown;
      };

      if (typeof body.detail === "string") detail = body.detail;
      else if (typeof body.message === "string") detail = body.message;
    } catch {
      // Keep the HTTP fallback.
    }

    throw new Error(detail);
  }

  return response.json() as Promise<T>;
}

export const getAgentDefinitions = () =>
  agentRequest<AgentDefinitionListResponse>("/agents");

export const getAgentStatus = () =>
  agentRequest<AgentStatus>("/agents/status");

export const getAgentTasks = (limit = 100) =>
  agentRequest<AgentTaskListResponse>(
    `/agents/tasks?limit=${encodeURIComponent(String(limit))}`,
  );

export const createAgentTask = (payload: AgentTaskCreateRequest) =>
  agentRequest<AgentTask>("/agents/tasks", {
    method: "POST",
    body: JSON.stringify(payload),
  });

export const getAgentTask = (taskId: string) =>
  agentRequest<AgentTask>(
    `/agents/tasks/${encodeURIComponent(taskId)}`,
  );

export const getAgentTaskEvents = (taskId: string, limit = 200) =>
  agentRequest<AgentTaskEventsResponse>(
    `/agents/tasks/${encodeURIComponent(taskId)}/events?limit=${encodeURIComponent(
      String(limit),
    )}`,
  );

export const cancelAgentTask = (taskId: string) =>
  agentRequest<AgentTask>(
    `/agents/tasks/${encodeURIComponent(taskId)}/cancel`,
    { method: "POST" },
  );

export const retryAgentTask = (taskId: string) =>
  agentRequest<AgentTask>(
    `/agents/tasks/${encodeURIComponent(taskId)}/retry`,
    { method: "POST" },
  );
