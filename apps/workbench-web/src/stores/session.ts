import { create } from "zustand";

export type SessionUser = { id: string; email: string; full_name: string; region: string; roles: string[]; mfa_enabled?: boolean };

type SessionState = {
  token: string | null;
  expiresAt: number;
  user: SessionUser | null;
  setToken: (token: string, expiresIn: number, user: SessionUser) => void;
  clear: () => void;
  has: (...roles: string[]) => boolean;
};

export const useSession = create<SessionState>((set, get) => ({
  token: null,
  expiresAt: 0,
  user: null,
  setToken: (token, expiresIn, user) => set({ token, user, expiresAt: Date.now() + expiresIn * 1000 }),
  clear: () => set({ token: null, user: null, expiresAt: 0 }),
  has: (...roles) => !!get().user?.roles.some((r) => roles.includes(r)),
}));

export const ROLE_LABEL: Record<string, string> = {
  data_entry: "Data entry",
  underwriter: "Underwriter",
  senior_underwriter: "Senior underwriter",
  risk_engineer: "Risk engineer",
  cuo: "CUO",
  distribution: "Distribution",
  admin: "Admin",
};
