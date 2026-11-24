export type LoginResult =
  | { status: "authenticated" }
  | { status: "mfa_required"; mfa_token: string }
  | { status: "mfa_enroll_required"; mfa_token: string; otpauth_uri: string; secret: string };

export class AuthApiError extends Error {
  constructor(public code: string, message: string, public status: number, public retryAfter?: number) {
    super(message);
  }
}

async function post<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(path, {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    const d = (data as { detail?: { code?: string; message?: string; retry_after?: number } }).detail ?? {};
    const msg = typeof d === "object" && d.message ? d.message : res.status === 422 ? "Please check the details entered." : "Something went wrong. Please try again.";
    throw new AuthApiError(d.code ?? "error", msg, res.status, d.retry_after ?? undefined);
  }
  return data as T;
}

export const authApi = {
  login: (email: string, password: string) => post<LoginResult>("/auth/login", { email, password }),
  verifyMfa: (mfa_token: string, code: string) => post<{ status: string }>("/auth/mfa/verify", { mfa_token, code }),
  forgot: (email: string) => post<{ status: string }>("/auth/password/forgot", { email }),
  reset: (token: string, new_password: string) => post<{ status: string }>("/auth/password/reset", { token, new_password }),
  config: async (): Promise<{ sso_enabled: boolean }> => {
    try {
      const r = await fetch("/auth/config", { credentials: "include" });
      return r.ok ? r.json() : { sso_enabled: false };
    } catch {
      return { sso_enabled: false };
    }
  },
};

export function workbenchUrl(): string {
  const params = new URLSearchParams(window.location.search);
  const next = params.get("next");
  // Only allow same-origin relative redirects to prevent open-redirects.
  return next && next.startsWith("/") && !next.startsWith("//") ? next : "/";
}

export function passwordProblems(pw: string): string[] {
  const p: string[] = [];
  if (pw.length < 12) p.push("At least 12 characters");
  const classes = [/[a-z]/, /[A-Z]/, /\d/, /[^A-Za-z0-9]/].filter((r) => r.test(pw)).length;
  if (classes < 3) p.push("Three of: lowercase, uppercase, digit, symbol");
  return p;
}
