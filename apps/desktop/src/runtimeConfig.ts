export type JaceDeploymentMode = "local" | "server";

const DEFAULT_API_BASE_URL = "http://127.0.0.1:8000";

const STORAGE_KEYS = {
  deploymentMode: "jace.runtime.deploymentMode",
  apiBaseUrl: "jace.runtime.apiBaseUrl",
  wsBaseUrl: "jace.runtime.wsBaseUrl",
} as const;

function browserStorageAvailable(): boolean {
  try {
    return typeof window !== "undefined" && window.localStorage != null;
  } catch {
    return false;
  }
}

function readStoredValue(key: string): string | null {
  if (!browserStorageAvailable()) {
    return null;
  }

  try {
    const value = window.localStorage.getItem(key);
    return value?.trim() || null;
  } catch {
    return null;
  }
}

function writeStoredValue(key: string, value: string | null): void {
  if (!browserStorageAvailable()) {
    return;
  }

  try {
    if (value === null) {
      window.localStorage.removeItem(key);
      return;
    }

    window.localStorage.setItem(key, value);
  } catch {
    // Runtime configuration must never prevent Jace from starting.
  }
}

function trimTrailingSlash(value: string): string {
  return value.replace(/\/+$/, "");
}

function normaliseHttpUrl(value: string): string {
  const trimmed = trimTrailingSlash(value.trim());

  if (!trimmed) {
    throw new Error("Jace API URL cannot be empty.");
  }

  let parsed: URL;

  try {
    parsed = new URL(trimmed);
  } catch {
    throw new Error(`Invalid Jace API URL: ${value}`);
  }

  if (parsed.protocol !== "http:" && parsed.protocol !== "https:") {
    throw new Error("Jace API URL must use http:// or https://.");
  }

  return trimTrailingSlash(parsed.toString());
}

function normaliseWebSocketUrl(value: string): string {
  const trimmed = trimTrailingSlash(value.trim());

  if (!trimmed) {
    throw new Error("Jace WebSocket URL cannot be empty.");
  }

  let parsed: URL;

  try {
    parsed = new URL(trimmed);
  } catch {
    throw new Error(`Invalid Jace WebSocket URL: ${value}`);
  }

  if (parsed.protocol !== "ws:" && parsed.protocol !== "wss:") {
    throw new Error("Jace WebSocket URL must use ws:// or wss://.");
  }

  return trimTrailingSlash(parsed.toString());
}

function httpToWebSocketUrl(httpUrl: string): string {
  const parsed = new URL(httpUrl);

  if (parsed.protocol === "https:") {
    parsed.protocol = "wss:";
  } else {
    parsed.protocol = "ws:";
  }

  return trimTrailingSlash(parsed.toString());
}

function readEnvironmentValue(name: string): string | null {
  const env = import.meta.env as Record<string, unknown>;
  const value = env[name];

  return typeof value === "string" && value.trim()
    ? value.trim()
    : null;
}

function readDeploymentMode(): JaceDeploymentMode {
  const stored = readStoredValue(STORAGE_KEYS.deploymentMode);

  if (stored === "server" || stored === "local") {
    return stored;
  }

  const envValue = readEnvironmentValue("VITE_JACE_MODE");

  return envValue === "server" ? "server" : "local";
}

function readApiBaseUrl(): string {
  const stored = readStoredValue(STORAGE_KEYS.apiBaseUrl);

  if (stored) {
    try {
      return normaliseHttpUrl(stored);
    } catch {
      // Ignore invalid saved configuration and fall through.
    }
  }

  const envValue = readEnvironmentValue("VITE_JACE_API_URL");

  if (envValue) {
    try {
      return normaliseHttpUrl(envValue);
    } catch {
      // Fall back to the local development endpoint.
    }
  }

  return DEFAULT_API_BASE_URL;
}

function readWsBaseUrl(apiBaseUrl: string): string {
  const stored = readStoredValue(STORAGE_KEYS.wsBaseUrl);

  if (stored) {
    try {
      return normaliseWebSocketUrl(stored);
    } catch {
      // Ignore invalid saved configuration and fall through.
    }
  }

  const envValue = readEnvironmentValue("VITE_JACE_WS_URL");

  if (envValue) {
    try {
      return normaliseWebSocketUrl(envValue);
    } catch {
      // Derive it from the HTTP endpoint instead.
    }
  }

  return httpToWebSocketUrl(apiBaseUrl);
}

export interface JaceRuntimeConfig {
  deploymentMode: JaceDeploymentMode;
  apiBaseUrl: string;
  wsBaseUrl: string;
  isRemote: boolean;
}

export function getRuntimeConfig(): JaceRuntimeConfig {
  const deploymentMode = readDeploymentMode();
  const apiBaseUrl = readApiBaseUrl();
  const wsBaseUrl = readWsBaseUrl(apiBaseUrl);

  return {
    deploymentMode,
    apiBaseUrl,
    wsBaseUrl,
    isRemote: deploymentMode === "server",
  };
}

export interface JaceRuntimeConfigUpdate {
  deploymentMode?: JaceDeploymentMode;
  apiBaseUrl?: string;
  wsBaseUrl?: string | null;
}

export function updateRuntimeConfig(
  update: JaceRuntimeConfigUpdate,
): JaceRuntimeConfig {
  if (update.deploymentMode !== undefined) {
    writeStoredValue(
      STORAGE_KEYS.deploymentMode,
      update.deploymentMode,
    );
  }

  if (update.apiBaseUrl !== undefined) {
    writeStoredValue(
      STORAGE_KEYS.apiBaseUrl,
      normaliseHttpUrl(update.apiBaseUrl),
    );
  }

  if (update.wsBaseUrl !== undefined) {
    writeStoredValue(
      STORAGE_KEYS.wsBaseUrl,
      update.wsBaseUrl === null
        ? null
        : normaliseWebSocketUrl(update.wsBaseUrl),
    );
  }

  return getRuntimeConfig();
}

export function resetRuntimeConfig(): JaceRuntimeConfig {
  writeStoredValue(STORAGE_KEYS.deploymentMode, null);
  writeStoredValue(STORAGE_KEYS.apiBaseUrl, null);
  writeStoredValue(STORAGE_KEYS.wsBaseUrl, null);

  return getRuntimeConfig();
}

export function buildApiUrl(path: string): string {
  const { apiBaseUrl } = getRuntimeConfig();

  if (!path) {
    return apiBaseUrl;
  }

  return `${apiBaseUrl}${path.startsWith("/") ? path : `/${path}`}`;
}

export function buildWebSocketUrl(path: string): string {
  const { wsBaseUrl } = getRuntimeConfig();

  if (!path) {
    return wsBaseUrl;
  }

  return `${wsBaseUrl}${path.startsWith("/") ? path : `/${path}`}`;
}

/*
 * Compatibility exports.
 *
 * Existing Jace code currently imports API_BASE_URL directly. Keeping this
 * export lets us migrate incrementally rather than forcing every call site to
 * change during the distributed-foundation work.
 *
 * New code should prefer buildApiUrl() / buildWebSocketUrl().
 */
const initialRuntimeConfig = getRuntimeConfig();

export const API_BASE_URL = initialRuntimeConfig.apiBaseUrl;
export const WS_BASE_URL = initialRuntimeConfig.wsBaseUrl;
export const JACE_DEPLOYMENT_MODE =
  initialRuntimeConfig.deploymentMode;