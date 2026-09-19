// JACE_4BS3_AUTH_CLIENT
// Tokens are deliberately memory-only in this foundation phase.
// Persistent secure storage will move to the OS credential boundary later.

export interface AuthUser {
  id: string;
  email: string | null;
  display_name: string;
  is_active: boolean;
  is_admin: boolean;
  local: boolean;
  created_at?: string | null;
  last_login_at?: string | null;
}

export interface AuthStatusResponse {
  mode: "local" | "server" | string;
  auth_required: boolean;
  bootstrap_required: boolean;
  bootstrap_available: boolean;
}

export interface AuthBootstrapRequest {
  email: string;
  display_name: string;
  password: string;
  client_id: string;
  client_name?: string | null;
}

export interface AuthLoginRequest {
  email: string;
  password: string;
  client_id: string;
  client_name?: string | null;
}

export interface AuthTokenResponse {
  access_token: string;
  refresh_token: string;
  token_type: "bearer" | string;
  access_expires_at: string;
  refresh_expires_at: string;
  session_id: string;
  user: AuthUser;
}

let currentSession: AuthTokenResponse | null = null;

export function setAuthSession(session: AuthTokenResponse): void {
  currentSession = session;
}

export function clearAuthSession(): void {
  currentSession = null;
}

export function getAuthAccessToken(): string | null {
  return currentSession?.access_token ?? null;
}

export function getAuthRefreshToken(): string | null {
  return currentSession?.refresh_token ?? null;
}

export function getAuthUser(): AuthUser | null {
  return currentSession?.user ?? null;
}

export function getOrCreateClientId(): string {
  const key = "jace.auth.clientId";

  try {
    const existing = window.localStorage.getItem(key);
    if (existing) return existing;

    const id = crypto.randomUUID();
    window.localStorage.setItem(key, id);
    return id;
  } catch {
    return "jace-desktop";
  }
}
