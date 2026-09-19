export type PrivacyClassification =
  | "public"
  | "internal"
  | "confidential"
  | "personal"
  | "secret";

export type PrivacyMode =
  | "cloud_allowed"
  | "protected_cloud"
  | "local_only";

export interface PrivacyStatus {
  enabled: boolean;
  cloud_egress_enabled: boolean;
  default_classification: PrivacyClassification;
  classification_policy: Record<
    PrivacyClassification,
    PrivacyMode
  >;
}

export interface PrivacyInspectRequest {
  payload: unknown;
  classification_hint?: PrivacyClassification | null;
  requested_mode?: PrivacyMode | null;
}

export interface PrivacyInspectResponse {
  classification: PrivacyClassification;
  mode: PrivacyMode;
  require_local: boolean;
  content_sha256: string;
  detections: Array<{
    kind: string;
    classification: PrivacyClassification;
    count: number;
  }>;
}
