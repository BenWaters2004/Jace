// JACE_4BS4_DEVICE_TYPES

export type DeviceState = "online" | "offline" | "revoked";

export interface DeviceRecord {
  id: string;
  owner_user_id: string | null;
  name: string;
  hostname: string;
  platform: string;
  os_version: string | null;
  architecture: string | null;
  agent_version: string | null;
  capabilities: string[];
  metadata: Record<string, unknown>;
  state: DeviceState;
  is_active: boolean;
  paired_at: string;
  created_at: string;
  updated_at: string;
  last_seen_at: string | null;
  revoked_at: string | null;
}

export interface DeviceListResponse {
  devices: DeviceRecord[];
  counts: {
    total: number;
    online: number;
    offline: number;
    revoked: number;
  };
}

export interface DevicePairingCreateRequest {
  requested_name?: string | null;
  requested_by_client_id?: string | null;
}

export interface DevicePairingResponse {
  pairing_id: string;
  pairing_code: string;
  expires_at: string;
  requested_name: string | null;
}

export interface DeviceUpdateRequest {
  name?: string | null;
}
