import { useSession } from "@/stores/session";

/**
 * API client. The access token lives in memory only (never localStorage). It is obtained from the
 * auth-service refresh endpoint using the httpOnly refresh cookie plus a double-submit CSRF header.
 */
export class ApiError extends Error {
  constructor(public status: number, public code: string, message: string, public detail?: unknown) {
    super(message);
  }
}

function csrf(): string {
  const m = document.cookie.match(/(?:^|; )nsip_csrf=([^;]+)/);
  return m ? decodeURIComponent(m[1]) : "";
}

let refreshing: Promise<boolean> | null = null;

export async function refreshSession(): Promise<boolean> {
  if (refreshing) return refreshing;
  refreshing = (async () => {
    try {
      const r = await fetch("/auth/refresh", { method: "POST", credentials: "include", headers: { "X-CSRF-Token": csrf() } });
      if (!r.ok) {
        useSession.getState().clear();
        return false;
      }
      const body = await r.json();
      useSession.getState().setToken(body.access_token, body.expires_in, body.user);
      return true;
    } catch {
      return false;
    } finally {
      setTimeout(() => (refreshing = null), 0);
    }
  })();
  return refreshing;
}

export function redirectToLogin(): void {
  const next = encodeURIComponent(window.location.pathname + window.location.search);
  window.location.assign(`/login/?next=${next}`);
}

export async function api<T>(path: string, init: RequestInit & { json?: unknown; raw?: boolean } = {}, retry = true): Promise<T> {
  const token = useSession.getState().token;
  const headers = new Headers(init.headers);
  if (token) headers.set("Authorization", `Bearer ${token}`);
  let body = init.body;
  if (init.json !== undefined) {
    headers.set("Content-Type", "application/json");
    body = JSON.stringify(init.json);
  }
  const res = await fetch(path, { ...init, headers, body });
  if (res.status === 401 && retry) {
    if (await refreshSession()) return api<T>(path, init, false);
    redirectToLogin();
    throw new ApiError(401, "unauthenticated", "Session expired");
  }
  if (!res.ok) {
    const data = await res.json().catch(() => ({}));
    const d = data?.detail;
    const message = typeof d === "object" && d?.message ? d.message : typeof d === "string" ? d : `Request failed (${res.status})`;
    throw new ApiError(res.status, d?.code ?? "error", message, d);
  }
  if (init.raw) return res as unknown as T;
  if (res.status === 204) return undefined as T;
  return res.json() as Promise<T>;
}

export async function logout(): Promise<void> {
  await fetch("/auth/logout", { method: "POST", credentials: "include", headers: { "X-CSRF-Token": csrf() } }).catch(() => undefined);
  useSession.getState().clear();
  window.location.assign("/login/");
}

export const authApi = {
  sessions: () => api<Array<{ id: string; created_at: string; last_seen_at: string; ip: string; user_agent: string; current: boolean; mfa_verified: boolean }>>("/auth/sessions"),
  revoke: (id: string) => api(`/auth/sessions/${id}`, { method: "DELETE" }),
  users: () => api<Array<Record<string, unknown>>>("/auth/admin/users"),
  setRoles: (id: string, roles: string[]) => api(`/auth/admin/users/${id}/roles`, { method: "PUT", json: { roles } }),
  unlock: (id: string) => api(`/auth/admin/users/${id}/unlock`, { method: "POST" }),
};
