export type DeviceCapabilityRequestStatus =
  | "pending"
  | "running"
  | "completed"
  | "failed"
  | "timed_out"
  | "cancelled";

export interface DeviceCapabilityExecuteRequest {
  device_id: string;
  capability: string;
  parameters?: Record<string, unknown>;
  timeout_seconds?: number;
  project_id?: string | null;
  task_id?: string | null;
  agent_id?: string | null;
  idempotency_key?: string | null;
}

export interface DeviceCapabilityRequestRecord {
  request_id: string;
  device_id: string;
  capability: string;
  parameters: Record<string, unknown>;
  status: DeviceCapabilityRequestStatus;
  result: unknown;
  error: string | null;
  evidence: Record<string, unknown> | null;
  project_id: string | null;
  task_id: string | null;
  agent_id: string | null;
  idempotency_key: string | null;
  timeout_seconds: number;
  requested_at: string;
  started_at: string | null;
  completed_at: string | null;
  cancelled_at: string | null;
}

export interface DeviceCapabilityCatalogResponse {
  capabilities: Array<{
    id: string;
    title: string;
    description: string;
    risk: "low" | "medium" | "high";
    enabled: boolean;
    read_only: boolean;
  }>;
}
