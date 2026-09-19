export interface RuntimeStreamTicket {
  ticket: string;
  expires_at: string;
}

export interface RuntimeReplayEvent {
  type: string;
  event_id?: string;
  sequence?: number;
  timestamp?: string;
  durable?: boolean;
  replayed?: boolean;
  [key: string]: unknown;
}

export interface RuntimeReplayResponse {
  events: RuntimeReplayEvent[];
  count: number;
  after_sequence: number;
  latest_sequence: number;
}
